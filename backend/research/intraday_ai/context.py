"""Phase 6: point-in-time market and sector context for the six rules' signals, and the
pre-registered context tests (prereg/P6_context.json).

Adds to each row of DATA/runs/y2/features.jsonl.gz (written to features_ctx.jsonl.gz, which is
also the Phase 7 scorer's input):
  sector_ret / stock_vs_sector / sector_vs_nifty   since the open, at the signal close (signed)
  vix, vix_med60, vix_high                          India VIX at the close vs its 60-session median
  breadth                                           share of the point-in-time universe above its open
  expiry_day, fii_idx_net, deliv_pct_prev           from the PREVIOUS session's NSE archives
  results_day, em_pred, em_rank                     results reaction day; expected-move OLS at 09:45

Run with the research venv:  D:/intraday_ai_data/venv/Scripts/python.exe context.py
"""
from __future__ import annotations

import glob
import gzip
import json
import math
import os
import pathlib
import statistics
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from move_model import NOT_STOCKS, clustered, dk_of, iso, pit_universe  # noqa: E402
from prereg import load  # noqa: E402
from stubpkg import DATA, activate, build  # noqa: E402

RULE = load("P6_context")
TB = RULE["groups"]["TB (trend and breakout)"]
RV = RULE["groups"]["R (reversion)"]
HOLDOUT_FROM = "2026-05-04"


def index_closes(read_file, sym: str) -> tuple[dict, dict]:
    """(day -> open, (day, bar end epoch) -> close) from 15-minute bars."""
    b = read_file(sym)
    opens, closes = {}, {}
    for i in range(len(b)):
        dk = dk_of(b.t[i])
        opens.setdefault(dk, b.o[i])
        closes[(dk, b.t[i] + 900)] = b.c[i]
    return opens, closes


def archive(kind: str) -> tuple[list[str], dict]:
    files = sorted(glob.glob(str(DATA / "intraday" / "nse" / kind / "*.json")))
    days = [os.path.basename(f)[:10] for f in files]
    return days, {d: f for d, f in zip(days, files)}


def prev_doc(days: list[str], files: dict, day: str, cache: dict):
    i = bisect_left(days, day) - 1
    if i < 0:
        return None
    d = days[i]
    if d not in cache:
        cache[d] = json.load(open(files[d], encoding="utf-8"))
    return cache[d]


def main() -> None:
    activate(build("HEAD"))
    from app.services.intraday_store import read_file

    rows = [json.loads(x) for x in gzip.open(DATA / "runs" / "y2" / "features.jsonl.gz", "rt", encoding="utf-8")]
    rows = [r for r in rows if r.get("filled") and r["side"] in (1, -1)]
    sectors = json.load(open(DATA / "exports" / "sectors.json", encoding="utf-8"))
    sec_index = {k: v for k, v in RULE["sector_index"].items() if k != "other"}
    need = sorted(set(sec_index.values()) | {"INDIAVIX", "NIFTY"})
    idx = {s: index_closes(read_file, s) for s in need}
    uni, _turn = pit_universe()

    # breadth: share of the day's universe above its own open at each bar close
    up = defaultdict(lambda: [0, 0])
    for p in sorted((DATA / "intraday" / "15m").glob("*.ibar")):
        s = p.stem
        if s in NOT_STOCKS or s.startswith("NIFTY"):
            continue
        b = read_file(s)
        day_open = {}
        for i in range(len(b)):
            dk = dk_of(b.t[i])
            if s not in uni.get(dk, ()):
                continue
            o = day_open.setdefault(dk, b.o[i])
            c = up[(dk, b.t[i] + 900)]
            c[0] += b.c[i] > o
            c[1] += 1

    # VIX: 60-session median of daily closes before each day
    vo, vc = idx["INDIAVIX"]
    vix_daily = {}
    for (dk, t), c in vc.items():
        if dk not in vix_daily or t > vix_daily[dk][0]:
            vix_daily[dk] = (t, c)
    vdays = sorted(vix_daily)
    reaction = {s: {(date.fromisoformat(x) - date(1970, 1, 1)).days for x in v}
                for s, v in json.load(open(DATA / "exports" / "results_reactions.json", encoding="utf-8")).items()}
    em = defaultdict(list)
    for line in gzip.open(DATA / "runs" / "move_model" / "preds.jsonl.gz", "rt", encoding="utf-8"):
        p = json.loads(line)
        em[p["day"]].append((p["ols"], p["sym"]))
    em_rank = {}
    for d, lst in em.items():
        lst.sort(reverse=True)
        for k, (pred, s) in enumerate(lst, 1):
            em_rank[(d, s)] = (pred, k)
    fo_days, fo_files = archive("fo")
    part_days, part_files = archive("part")
    cm_days, cm_files = archive("cm")
    cache_fo, cache_part, cache_cm = {}, {}, {}

    out = gzip.open(DATA / "runs" / "y2" / "features_ctx.jsonl.gz", "wt", encoding="utf-8")
    for r in rows:
        dk, t, side = dk_of(r["t"]), r["t"], r["side"]
        stock_ret = (r["day_ret"] / side) if r.get("day_ret") is not None else None
        ix = sec_index.get(sectors.get(r["sym"]) or "")
        sec_ret = None
        if ix:
            o, c = idx[ix][0].get(dk), idx[ix][1].get((dk, t))
            sec_ret = (c / o - 1) if o and c else None
        no, nc = idx["NIFTY"][0].get(dk), idx["NIFTY"][1].get((dk, t))
        nifty_ret = (nc / no - 1) if no and nc else None
        vix = vc.get((dk, t))
        j = bisect_left(vdays, dk)
        past = [vix_daily[x][1] for x in vdays[max(0, j - 60):j]]
        med = statistics.median(past) if len(past) >= 20 else None
        u = up.get((dk, t))
        fo = prev_doc(fo_days, fo_files, r["day"], cache_fo)
        expiry = None
        if fo:
            exps = [v[6] for v in fo["x"].values() if isinstance(v, list) and len(v) > 6 and v[6]]
            expiry = max(set(exps), key=exps.count) if exps else None
        part = prev_doc(part_days, part_files, r["day"], cache_part)
        fii = ((part or {}).get("x") or {}).get("FII") or {}
        fl, fs = fii.get("Future Index Long"), fii.get("Future Index Short")
        cm = prev_doc(cm_days, cm_files, r["day"], cache_cm)
        dv = ((cm or {}).get("x") or {}).get(r["sym"])
        emp = em_rank.get((r["day"], r["sym"]))
        r.update({
            "sector_ix": ix, "sector_ret": None if sec_ret is None else round(side * sec_ret, 6),
            "stock_vs_sector": None if sec_ret is None or stock_ret is None else round(side * (stock_ret - sec_ret), 6),
            "sector_vs_nifty": None if sec_ret is None or nifty_ret is None else round(side * (sec_ret - nifty_ret), 6),
            "vix": vix, "vix_med60": med, "vix_high": None if vix is None or med is None else int(vix > med),
            "breadth": round(u[0] / u[1], 4) if u and u[1] >= 30 else None,
            "expiry_day": None if expiry is None else int(r["day"] == expiry),
            "fii_idx_net": round((fl - fs) / (fl + fs), 4) if fl and fs else None,
            "deliv_pct_prev": dv[2] if isinstance(dv, list) and len(dv) > 2 else None,
            "results_day": int(dk in reaction.get(r["sym"], ())),
            "em_pred": emp[0] if emp else None, "em_rank": emp[1] if emp else None})
        out.write(json.dumps(r) + "\n")
    out.close()
    test(rows)


def test(rows: list[dict]) -> None:
    def filt(name):
        if name == "H6_sector":
            return lambda r: r["sid"] in TB and r.get("sector_ret") is not None and r["sector_ret"] > 0
        if name == "H6_relative":
            return lambda r: r["sid"] in TB and r.get("stock_vs_sector") is not None and r["stock_vs_sector"] > 0
        if name == "H6_vix_TB":
            return lambda r: r["sid"] in TB and r.get("vix_high") == 1
        if name == "H6_vix_R":
            return lambda r: r["sid"] in RV and r.get("vix_high") == 0
        if name == "H6_breadth":
            return lambda r: r["sid"] in TB and r.get("breadth") is not None and (
                (r["side"] > 0 and r["breadth"] > 0.5) or (r["side"] < 0 and r["breadth"] < 0.5))
        if name == "H6_expiry":
            return lambda r: r.get("expiry_day") == 0
    group = {"H6_sector": TB, "H6_relative": TB, "H6_vix_TB": TB, "H6_vix_R": RV, "H6_breadth": TB,
             "H6_expiry": TB + RV}
    res = {}
    print(f"{'hypothesis':<12} {'period':<11} {'filtered':>9} {'t':>6} {'n':>6} | {'group':>8} {'t':>6} {'n':>6}  verdict")
    for h, members in group.items():
        f = filt(h)
        for name, lo, hi in (("development", "0000", HOLDOUT_FROM), ("holdout", HOLDOUT_FROM, "9999")):
            per = [r for r in rows if r["sid"] in members and lo <= r["day"] < hi]
            fm, ft, fn = clustered([(r["day"], r["net_bp"]) for r in per if f(r)])
            gm, gt, gn = clustered([(r["day"], r["net_bp"]) for r in per])
            v = ("GO" if fm > 0 and ft >= 2 else "NO-GO") if name == "holdout" else ""
            res[f"{h}:{name}"] = {"filtered_net_bp": round(fm, 3), "filtered_t": round(ft, 2), "filtered_n": fn,
                                  "group_net_bp": round(gm, 3), "group_t": round(gt, 2), "group_n": gn, "verdict": v or None}
            print(f"{h:<12} {name:<11} {fm:>9.2f} {ft:>6.2f} {fn:>6} | {gm:>8.2f} {gt:>6.2f} {gn:>6}  {v}")
    json.dump(res, open(DATA / "runs" / "y2" / "context_tests.json", "w"), indent=1)


if __name__ == "__main__":
    main()
