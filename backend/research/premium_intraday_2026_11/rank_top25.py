"""Rank the 60 replayable imported strategies on the common harness, de-duplicate, keep up to 25 distinct ones.

Ranking (weights fixed before the run): net expectancy 35% (rule view, mean net R), drawdown 20% (book view, lower
is better), consistency 20% (book view, share of months up), sample size 10% (log rule trades), contribution 15%
(1 - correlation of the strategy's daily book P&L with the average of all the others). Each factor is a percentile.

De-duplication:
  equivalent rules   the same tournament family on 15m/45m/1h is ONE strategy in three parameterisations: the best
                     ranked timeframe represents the family, the others are listed as its variants
  same trades        Jaccard overlap of (stock, day, 30-minute bucket, side) between representatives; >= 0.5 means
                     the two repeatedly trade the same stocks at the same times: the lower ranked one is dropped and
                     flagged; 0.25-0.5 is flagged only
Membership never authorises trading: every one is judged on the promotion criteria like the new strategies.
"""
import json
import math
import pickle
import re
import subprocess
from collections import defaultdict
from statistics import mean, pstdev

from common import HERE, ROOT, RUNS
from pis.stats import summarize
from pis.timeutil import day_of

W = {"expectancy": 0.35, "drawdown": 0.20, "consistency": 0.20, "sample": 0.10, "contribution": 0.15}
FAMILY_NAMES = {
    "donchian": "Donchian 20 Breakout", "ema_pullback": "EMA Trend Pullback", "macd_trend": "MACD Trend Turn",
    "keltner": "Keltner Breakout", "supertrend": "Supertrend Flip", "adx_dmi": "ADX Trend Start",
    "rsi_momentum": "RSI Momentum 60/40", "vwap_trend": "VWAP Reclaim", "pdh_pdl": "Prior-Day High/Low Break",
    "or_close_break": "Opening-Range Close Break", "vwap_reversion": "VWAP Reversion", "rsi2": "RSI(2) Extreme",
    "bollinger_snap": "Bollinger Snap-Back", "zscore": "Z-Score Fade in Range", "stoch_range": "Stochastic Range Turn",
    "cci_extreme": "CCI ±200 Return", "orb_inplay_10": "ORB Stocks-in-Play (stop 10% ATR)",
    "orb_inplay_25": "ORB Stocks-in-Play (stop 25% ATR)", "gap_go": "Gap and Go", "gap_fade": "Gap Fade",
}
TF_NAME = {"15m": "15 min", "45m": "45 min", "1h": "1 hour"}
SM_NAMES = {"orb15": "15-minute opening-range break", "orb30": "30-minute opening-range break",
            "vwap": "VWAP trend break", "relative": "Relative strength break", "pullback": "Opening-momentum pullback",
            "gap_go": "Gap and go", "gap_fade": "Gap fade", "volume": "Volume breakout"}


def audit_rules() -> dict:
    """Rule text per tournament family from INTRADAY_STOCKS_54_STRATEGY_AUDIT.md (as committed)."""
    txt = subprocess.run(["git", "-C", str(ROOT), "show", "origin/main:INTRADAY_STOCKS_54_STRATEGY_AUDIT.md"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    out, fam = {}, None
    for line in txt.splitlines():
        m = re.match(r"^### .*`iv2_([a-z_]+?)(?:_\*|_15m)", line)
        if m:
            fam = m.group(1)
        r = re.match(r"^(?:- )?\*\*Rule\.\*\*\s*(.+)$", line)
        if r and fam:
            out.setdefault(fam, r.group(1).strip())
            fam = None
    day = [l for l in txt.splitlines() if l.startswith("- **Rule.**")]
    keys = ["orb_inplay", "gap_go", "gap_fade", "orb_sel"]
    for k, l in zip(keys, day):
        out[k] = l.replace("- **Rule.**", "").strip()
    return out


def family(sid: str) -> tuple[str, str | None]:
    if sid.startswith("SM:"):
        return sid, None
    base = sid[4:]
    for tf in ("_15m", "_45m", "_1h"):
        if base.endswith(tf):
            return base[: -len(tf)], tf[1:]
    return base, None


def name_of(sid: str) -> str:
    if sid.startswith("SM:"):
        return f"Stock Momentum · {SM_NAMES[sid[3:]]}"
    fam, tf = family(sid)
    return FAMILY_NAMES.get(fam, fam) + (f" · {TF_NAME[tf]}" if tf else "")


def pct_rank(vals: dict, higher=True) -> dict:
    items = sorted(vals.items(), key=lambda kv: (kv[1] if kv[1] is not None else (-1e18 if higher else 1e18)))
    n = len(items)
    out = {}
    for i, (k, v) in enumerate(items):
        p = i / (n - 1) if n > 1 else 0.5
        out[k] = p if higher else 1 - p
    return out


def daily(trades):
    d = defaultdict(float)
    for p in trades:
        d[str(day_of(p["t_entry"]))] += p["net"]
    return d


def corr(a, b, days):
    xs = [a.get(d, 0.0) for d in days]
    ys = [b.get(d, 0.0) for d in days]
    if len(xs) < 3 or pstdev(xs) == 0 or pstdev(ys) == 0:
        return 0.0
    mx, my = mean(xs), mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) * pstdev(xs) * pstdev(ys))


def r_at_2x(trades):
    out = []
    for p in trades:
        slip = abs(p["entry"] - p["ref"]) * p["qty"] + abs((p["exit"] or 0) - (p["exit_ref"] or 0)) * p["qty"]
        risk = p["net"] / p["r_net"] if p.get("r_net") else None
        if risk:
            out.append((p["net"] - slip) / risk)
    return mean(out) if out else None


def main():
    r = pickle.load(open(RUNS / "imported" / "imported.pkl", "rb"))
    sessions = r["sessions"]
    rules_txt = audit_rules()
    sids = sorted(r["rule"])
    stats = {}
    for sid in sids:
        rt, bt = r["rule"][sid], r["book"].get(sid, [])
        stats[sid] = {"rule": summarize(rt, sessions=sessions), "book": summarize(bt, sessions=sessions),
                      "rule_R_2x": r_at_2x(rt), "book_R_2x": r_at_2x(bt)}
    days = sorted({str(day_of(p["t_entry"])) for sid in sids for p in r["book"].get(sid, [])})
    dly = {sid: daily(r["book"].get(sid, [])) for sid in sids}
    contrib = {}
    for sid in sids:
        others = defaultdict(float)
        for o in sids:
            if o != sid:
                for d, v in dly[o].items():
                    others[d] += v / (len(sids) - 1)
        contrib[sid] = 1 - corr(dly[sid], others, days)
    f_exp = pct_rank({s: stats[s]["rule"].get("mean_R") for s in sids})
    f_dd = pct_rank({s: stats[s]["book"].get("max_dd_pct") for s in sids}, higher=False)
    f_con = pct_rank({s: (stats[s]["book"].get("months_up", 0) / stats[s]["book"]["months"]) if stats[s]["book"].get("months") else 0 for s in sids})
    f_n = pct_rank({s: math.log(1 + stats[s]["rule"].get("trades", 0)) for s in sids})
    f_c = pct_rank(contrib)
    score = {s: W["expectancy"] * f_exp[s] + W["drawdown"] * f_dd[s] + W["consistency"] * f_con[s]
             + W["sample"] * f_n[s] + W["contribution"] * f_c[s] for s in sids}
    order = sorted(sids, key=lambda s: -score[s])
    # equivalent rules: one representative per family
    reps, variants = [], defaultdict(list)
    seen = {}
    for s in order:
        fam, _ = family(s)
        if fam in seen:
            variants[seen[fam]].append(s)
        else:
            seen[fam] = s
            reps.append(s)
    # same trades: overlap between representatives
    keys = {s: set(map(tuple, r["keys"].get(s, []))) for s in sids}

    def jac(a, b):
        A, B = keys[a], keys[b]
        return len(A & B) / len(A | B) if A and B else 0.0

    kept, dropped, flags = [], {}, defaultdict(list)
    for s in reps:
        dup = None
        for k in kept:
            j = jac(s, k)
            if j >= 0.5:
                dup = (k, j)
                break
            if j >= 0.25:
                flags[s].append({"with": k, "overlap": round(j, 3)})
                flags[k].append({"with": s, "overlap": round(j, 3)})
        if dup:
            dropped[s] = {"duplicate_of": dup[0], "overlap": round(dup[1], 3)}
        else:
            kept.append(s)
    top = kept[:25]
    C = {"n": 60, "mean_R": 0.0, "pf": 1.10, "t": 2.0, "months_up": 0.5}
    rows = []
    for rank, s in enumerate(top, 1):
        st = stats[s]
        b, rr = st["book"], st["rule"]
        fam, tf = family(s)
        fails = []
        if (b.get("trades") or 0) < C["n"]:
            fails.append(f"book trades {b.get('trades', 0)} < {C['n']}")
        if (b.get("mean_R") or -1) <= 0:
            fails.append(f"book mean net R {b.get('mean_R', 0):+.3f} <= 0")
        if (rr.get("mean_R") or -1) <= 0:
            fails.append(f"every-signal mean net R {rr.get('mean_R', 0):+.3f} <= 0")
        if (b.get("profit_factor") or 0) < C["pf"]:
            fails.append(f"profit factor {b.get('profit_factor') or 0:.2f} < {C['pf']}")
        if (b.get("t_day") or -9) < C["t"]:
            fails.append(f"day-clustered t {b.get('t_day') or 0:.2f} < {C['t']}")
        if st["book_R_2x"] is not None and st["book_R_2x"] < 0:
            fails.append("negative at 2x slippage")
        src = "Stock Momentum Trading" if s.startswith("SM:") else "Intraday Stocks (tournament)"
        rule_text = (rules_txt.get(fam if not fam.startswith("orb_inplay") else "orb_inplay", "") if not s.startswith("SM:")
                     else SM_NAMES[s[3:]])
        rows.append({
            "rank": rank, "id": s, "name": name_of(s), "source": src,
            "version": ("intraday_v2_strategies.py @ c64c7b7 (md5 010bc509…, = box)" if not s.startswith("SM:")
                        else "screener/morning.py @ origin 2252267e (md5 7be4ff8b…)"),
            "evidence_date": "2026-11-22 (this harness); source studies 2026-11-04 audit / 2026-11-21 morning_replay",
            "rule": rule_text, "variants": [{"id": v, "name": name_of(v), "score": round(score[v], 4)} for v in variants.get(s, [])],
            "overlaps": flags.get(s, []), "score": round(score[s], 4),
            "factors": {"expectancy": round(f_exp[s], 3), "drawdown": round(f_dd[s], 3), "consistency": round(f_con[s], 3),
                        "sample": round(f_n[s], 3), "contribution": round(f_c[s], 3)},
            "contribution_1_minus_corr": round(contrib[s], 3),
            "rule_view": rr, "book_view": b, "book_R_2x": st["book_R_2x"], "rule_R_2x": st["rule_R_2x"],
            "allocated": 1_000_000, "status": "Rejected" if fails else "Backtest Qualified (needs forward confirmation)",
            "reason": "; ".join(fails) if fails else "passed the common-harness criteria",
        })
    out = {"window": ["2025-05-01", "2026-11-03"], "sessions": sessions, "weights": W, "criteria": C,
           "candidates": 62, "replayable": len(sids),
           "not_replayable": [{"id": "iv2_orb_sel15", "name": "Selected ORB 15-min (top-5 expected move)",
                               "why": "needs the Scanner Board's expected-move model, which this harness does not rebuild; "
                                      "its own pre-registered forward test (intraday_v2_registry) decides it"},
                              {"id": "iv2_orb_sel30", "name": "Selected ORB 30-min (top-5 expected move)",
                               "why": "same as Selected ORB 15"}],
           "top25": rows, "dropped_duplicates": dropped,
           "all": [{"id": s, "name": name_of(s), "score": round(score[s], 4), "rule_mean_R": stats[s]["rule"].get("mean_R"),
                    "rule_trades": stats[s]["rule"].get("trades"), "book_mean_R": stats[s]["book"].get("mean_R"),
                    "book_return_pct": stats[s]["book"].get("return_pct"), "book_max_dd_pct": stats[s]["book"].get("max_dd_pct")}
                   for s in order]}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "imported_top25.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"{'#':>2} {'id':26} {'score':>6} {'ruleR':>7} {'n':>6} {'bookR':>7} {'ret%':>7} {'DD%':>5} {'mUp':>5}  status")
    for x in rows:
        b = x["book_view"]
        print(f"{x['rank']:2} {x['id']:26} {x['score']:6.3f} {x['rule_view']['mean_R']:7.3f} {x['rule_view']['trades']:6} "
              f"{(b.get('mean_R') or 0):7.3f} {(b.get('return_pct') or 0):7.2f} {(b.get('max_dd_pct') or 0):5.1f} "
              f"{b.get('months_up', 0)}/{b.get('months', 0)}  {x['status'][:9]}")
    print("dropped as duplicates:", dropped)
    print("qualified:", [x["id"] for x in rows if not x["status"].startswith("Rejected")])


if __name__ == "__main__":
    main()
