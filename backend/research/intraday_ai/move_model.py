"""Phase 5, pre-registered tests P5_move_model and P5_big_mover.

1. Stock-day samples built as scanner_board._samples does (features at 09:45, target the
   |09:45 -> 15:00| move in bp), for the point-in-time top 200; walk-forward by month, OLS on
   the scanner's BASE features vs a fixed-setting LightGBM on BASE + 10 more. Verdict per
   prereg/P5_move_model.json. Predictions -> DATA/runs/move_model/preds.jsonl.gz.
2. The big-mover filter on the six rules' signals (dataset y2) with the chosen model's
   walk-forward ranks. Verdict per prereg/P5_big_mover.json.

Run with the research venv:  D:/intraday_ai_data/venv/Scripts/python.exe move_model.py
"""
from __future__ import annotations

import gzip
import json
import math
import pathlib
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from prereg import load  # noqa: E402
from stubpkg import DATA, activate, build  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
R_MODEL, R_FILTER = load("P5_move_model"), load("P5_big_mover")
BASE = ["log_rvol30", "atr_pct", "abs_gap", "abs_first30", "prev_range_atr", "results"]
EXTRA = ["gap_signed", "first30_signed", "dow", "log_turnover", "vix", "vix_chg", "nifty_abs_gap",
         "nifty_abs_first30", "prev_abs_ret", "range5_atr"]
NOT_STOCKS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "INDIAVIX"}
FIRST_DAY, HOLDOUT_FROM, DEV_FROM = "2024-11-26", "2026-05-04", "2025-05-01"
GBM = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200, subsample=0.8,
           subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=7, objective="l2", verbose=-1)


def dk_of(t: int) -> int:
    return (t + 19800) // 86400


def minute(t: int) -> int:
    return ((t + 19800) % 86400) // 60


def iso(dk: int) -> str:
    return (date(1970, 1, 1) + timedelta(days=int(dk))).isoformat()


def pit_universe() -> tuple[dict[int, set[str]], dict[tuple[str, int], float]]:
    """day -> top-200 symbols by 20-session average traded value before the day; and turnover."""
    tv: dict[str, tuple[list[int], list[float]]] = defaultdict(lambda: ([], []))
    rows = []
    with open(DATA / "exports" / "bars1d.tsv", encoding="utf-8") as f:
        for line in f:
            s, t, c, v = line.rstrip("\n").split("\t")
            rows.append((s, dk_of(int(t)), float(c) * float(v)))
    rows.sort()
    for s, dk, x in rows:
        tv[s][0].append(dk)
        tv[s][1].append(x)
    days = sorted({dk for _s, dk, _x in rows if iso(dk) >= FIRST_DAY})
    uni, turn = {}, {}
    for d in days:
        cand = []
        for s, (ks, vs) in tv.items():
            if s in NOT_STOCKS:
                continue
            i = bisect_left(ks, d)
            if i < 15:
                continue
            w = vs[max(0, i - 20):i]
            a = sum(w) / len(w)
            cand.append((a, s))
            turn[(s, d)] = a / 1e7
        cand.sort(reverse=True)
        uni[d] = {s for _a, s in cand[:200]}
    return uni, turn


def day_bars(b) -> dict[int, list[int]]:
    days: dict[int, list[int]] = {}
    for i in range(len(b)):
        days.setdefault(dk_of(b.t[i]), []).append(i)
    return days


def market_series(read_file, sym: str) -> dict[int, dict]:
    """Per day: open, 09:45 close, previous close — for NIFTY and India VIX."""
    b = read_file(sym)
    days = day_bars(b)
    keys = sorted(days)
    out, prev_c = {}, None
    for k in keys:
        ix = days[k]
        p0945 = next((b.c[i] for i in ix if minute(b.t[i]) == 570), None)
        out[k] = {"o": b.o[ix[0]], "p0945": p0945, "pc": prev_c}
        prev_c = b.c[ix[-1]]
    return out


def samples(read_file, symbols, uni, turn, reaction, nifty, vix) -> list[dict]:
    out = []
    for sym in symbols:
        b = read_file(sym)
        if len(b) < 1000:
            continue
        days = day_bars(b)
        keys = sorted(days)
        summ = {k: {"h": max(b.h[i] for i in days[k]), "l": min(b.l[i] for i in days[k]),
                    "c": b.c[days[k][-1]], "v30": sum(b.v[i] for i in days[k][:2])} for k in keys}
        for n in range(16, len(keys)):
            k = keys[n]
            if iso(k) < FIRST_DAY or sym not in uni.get(k, ()):
                continue
            ix = days[k]
            if len(ix) < 22 or minute(b.t[ix[0]]) != 555 or minute(b.t[ix[1]]) != 570:
                continue
            p1500 = next((b.o[i] for i in ix if minute(b.t[i]) == 900), None)
            if p1500 is None:
                continue
            prev = [summ[keys[j]] for j in range(n - 15, n)]
            pc = prev[-1]["c"]
            trs = [max(d["h"] - d["l"], abs(d["h"] - p["c"]), abs(d["l"] - p["c"])) for p, d in zip(prev[:-1], prev[1:])]
            atr = sum(trs) / len(trs)
            base = sum(p["v30"] for p in prev[-14:]) / 14
            if not atr or not base or not pc or not summ[k]["v30"]:
                continue
            o, p0945 = b.o[ix[0]], b.c[ix[1]]
            nf, vx = nifty.get(k, {}), vix.get(k, {})
            x = {"log_rvol30": math.log(max(summ[k]["v30"] / base, 0.05)), "atr_pct": atr / pc * 100,
                 "abs_gap": abs(o / pc - 1) * 100, "abs_first30": abs(p0945 / o - 1) * 100,
                 "prev_range_atr": (prev[-1]["h"] - prev[-1]["l"]) / atr, "results": 1.0 if k in reaction.get(sym, ()) else 0.0,
                 "gap_signed": (o / pc - 1) * 100, "first30_signed": (p0945 / o - 1) * 100,
                 "dow": float(datetime.fromisoformat(iso(k)).weekday()),
                 "log_turnover": math.log10(max(turn.get((sym, k), 1.0), 1.0)),
                 "vix": vx.get("p0945") or np.nan,
                 "vix_chg": (vx["p0945"] / vx["pc"] - 1) * 100 if vx.get("p0945") and vx.get("pc") else np.nan,
                 "nifty_abs_gap": abs(nf["o"] / nf["pc"] - 1) * 100 if nf.get("o") and nf.get("pc") else np.nan,
                 "nifty_abs_first30": abs(nf["p0945"] / nf["o"] - 1) * 100 if nf.get("p0945") and nf.get("o") else np.nan,
                 "prev_abs_ret": abs(prev[-1]["c"] / prev[-2]["c"] - 1) * 100,
                 "range5_atr": sum((d["h"] - d["l"]) for d in prev[-5:]) / 5 / atr}
            out.append({"dk": k, "sym": sym, "y": abs(p1500 / p0945 - 1) * 1e4, **x})
    return out


def rank_ic(days, pred, y) -> tuple[float, float, float, int]:
    ics, tops, alls = [], [], []
    for d in np.unique(days):
        m = days == d
        if m.sum() < 30:
            continue
        p, a = pred[m], y[m]
        ics.append(float(np.corrcoef(np.argsort(np.argsort(p)), np.argsort(np.argsort(a)))[0, 1]))
        tops.append(float(a[np.argsort(-p)[:20]].mean()))
        alls.append(float(a.mean()))
    return (float(np.mean(ics)) if ics else float("nan"), float(np.mean(tops)) if tops else float("nan"),
            float(np.mean(alls)) if alls else float("nan"), len(ics))


def clustered(rows: list[tuple[str, float]]) -> tuple[float, float, int]:
    by = defaultdict(lambda: [0.0, 0])
    for d, v in rows:
        by[d][0] += v
        by[d][1] += 1
    n = sum(c for _s, c in by.values())
    if n == 0 or len(by) < 3:
        return float("nan"), 0.0, n
    mean = sum(s for s, _c in by.values()) / n
    D = len(by)
    var = sum((s - mean * c) ** 2 for s, c in by.values()) / (n * n) * D / (D - 1)
    return mean, mean / math.sqrt(var) if var > 0 else 0.0, n


def main() -> None:
    activate(build("HEAD"))
    from app.services.intraday_store import read_file
    import lightgbm as lgb

    uni, turn = pit_universe()
    reaction = {s: {(date.fromisoformat(x) - date(1970, 1, 1)).days for x in v}
                for s, v in json.load(open(DATA / "exports" / "results_reactions.json", encoding="utf-8")).items()}
    syms = sorted(p.stem for p in (DATA / "intraday" / "15m").glob("*.ibar")
                  if p.stem not in NOT_STOCKS and not p.stem.startswith("NIFTY"))
    S = samples(read_file, syms, uni, turn, reaction, market_series(read_file, "NIFTY"), market_series(read_file, "INDIAVIX"))
    print(f"samples {len(S)} from {len(syms)} stocks, {len({s['dk'] for s in S})} sessions")
    dks = np.array([s["dk"] for s in S])
    y = np.array([s["y"] for s in S])
    Xo = np.array([[s[f] for f in BASE] + [1.0] for s in S])
    Xg = np.array([[s[f] for f in BASE + EXTRA] for s in S], dtype=float)
    months = sorted({iso(d)[:7] for d in dks if iso(d) >= DEV_FROM})
    p_ols, p_gbm = np.full(len(y), np.nan), np.full(len(y), np.nan)
    for m in months:
        start = (date.fromisoformat(m + "-01") - date(1970, 1, 1)).days
        nxt = (date.fromisoformat(m + "-01") + timedelta(days=32)).replace(day=1)
        end = (nxt - date(1970, 1, 1)).days
        tr, te = dks < start, (dks >= start) & (dks < end)
        if not te.any():
            continue
        w = np.linalg.lstsq(Xo[tr], y[tr], rcond=None)[0]
        p_ols[te] = Xo[te] @ w
        g = lgb.LGBMRegressor(**GBM).fit(Xg[tr], y[tr])
        p_gbm[te] = g.predict(Xg[te])
        print(f"  {m}: trained on {tr.sum()}, predicted {te.sum()}")
    res = {}
    for name, lo, hi in (("development", DEV_FROM, HOLDOUT_FROM), ("holdout", HOLDOUT_FROM, "9999")):
        sel = np.array([lo <= iso(d) < hi for d in dks]) & ~np.isnan(p_ols)
        io, to, ao, nd = rank_ic(dks[sel], p_ols[sel], y[sel])
        ig, tg, _ag, _ = rank_ic(dks[sel], p_gbm[sel], y[sel])
        res[name] = {"days": nd, "ic_ols": round(io, 4), "ic_gbm": round(ig, 4), "ic_gain": round(ig - io, 4),
                     "top20_move_ols_bp": round(to, 1), "top20_move_gbm_bp": round(tg, 1), "all_move_bp": round(ao, 1)}
    adopt = res["holdout"]["ic_gain"] >= 0.03 and res["development"]["ic_gain"] > 0
    res["decision"] = "ADOPT GBM" if adopt else "KEEP OLS"
    print(json.dumps(res, indent=1))
    out = DATA / "runs" / "move_model"
    out.mkdir(parents=True, exist_ok=True)
    chosen = p_gbm if adopt else p_ols
    with gzip.open(out / "preds.jsonl.gz", "wt", encoding="utf-8") as f:
        for i, s in enumerate(S):
            if not np.isnan(p_ols[i]):
                f.write(json.dumps({"day": iso(s["dk"]), "sym": s["sym"], "ols": round(float(p_ols[i]), 2),
                                    "gbm": round(float(p_gbm[i]), 2), "y": round(s["y"], 1)}) + "\n")

    # ── P5_big_mover: the six rules on the day's top 40 expected movers ──
    top40: dict[str, set[str]] = defaultdict(set)
    by_day: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for i, s in enumerate(S):
        if not np.isnan(chosen[i]):
            by_day[iso(s["dk"])].append((float(chosen[i]), s["sym"]))
    for d, lst in by_day.items():
        lst.sort(reverse=True)
        top40[d] = {sym for _p, sym in lst[:40]}
    sig = defaultdict(list)
    for line in gzip.open(DATA / "runs" / "y2" / "features.jsonl.gz", "rt", encoding="utf-8"):
        r = json.loads(line)
        if r.get("filled") and r["day"] >= DEV_FROM and r["day"] in top40:
            sig[r["sid"]].append(r)
    filt = {}
    rules = R_FILTER.get("rules") or sorted(sig)
    for sid in list(sig) + ["POOLED"]:
        rows = [r for k in (sig if sid == "POOLED" else [sid]) for r in sig[k]]
        for name, lo, hi in (("development", DEV_FROM, HOLDOUT_FROM), ("holdout", HOLDOUT_FROM, "9999")):
            per = [r for r in rows if lo <= r["day"] < hi]
            fm, ft, fn = clustered([(r["day"], r["net_bp"]) for r in per if r["sym"] in top40[r["day"]]])
            um, ut, un = clustered([(r["day"], r["net_bp"]) for r in per])
            filt[f"{sid}:{name}"] = {"filtered_net_bp": round(fm, 3), "filtered_t": round(ft, 2), "filtered_n": fn,
                                     "all_net_bp": round(um, 3), "all_t": round(ut, 2), "all_n": un}
        h = filt[f"{sid}:holdout"]
        filt[f"{sid}:holdout"]["verdict"] = "GO" if h["filtered_net_bp"] > 0 and h["filtered_t"] >= 2 else "NO-GO"
    print(f"\nbig-mover filter (top 40 by {'GBM' if adopt else 'OLS'}), net bp per signal:")
    print(f"{'rule':<24} {'period':<11} {'filtered':>9} {'t':>6} {'n':>6} | {'all':>8} {'t':>6} {'n':>6}  verdict")
    for k, v in filt.items():
        sid, per = k.split(":")
        print(f"{sid:<24} {per:<11} {v['filtered_net_bp']:>9.2f} {v['filtered_t']:>6.2f} {v['filtered_n']:>6} | "
              f"{v['all_net_bp']:>8.2f} {v['all_t']:>6.2f} {v['all_n']:>6}  {v.get('verdict', '')}")
    json.dump({"move_model": res, "big_mover": filt, "model_used": "gbm" if adopt else "ols"},
              open(out / "result.json", "w"), indent=1)


if __name__ == "__main__":
    main()
