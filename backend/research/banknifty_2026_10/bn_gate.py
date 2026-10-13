"""Score every trial against PROTOCOL.md and choose the ten for the NIFTY BANK paper desk.

Reads results/lib, results/fam, results/swing; writes bn_research.json (shipped to the app as
app/data/banknifty_research.json) and prints the ranking.
"""

import glob
import json
import math
import os
import statistics
import sys
from datetime import date

import bn_common as C

TRIALS_DECLARED = 297
FAMILY_CAP = None          # was 3 in PROTOCOL.md; dropped by its dated amendment
SPREAD_STRESS = 0.005


def load_all() -> list[dict]:
    out = []
    for kind, sub in (("library_intraday", "lib"), ("custom_intraday", "fam"), ("daily", "swing")):
        for f in sorted(glob.glob(os.path.join(C.DATA, "results", sub, "*.json"))):
            d = json.load(open(f))
            d["source"] = kind
            out.append(d)
    return out


def stressed_net(row, cols, daily: bool) -> float:
    """The same trade at a 0.50% half spread."""
    saved = C.HALF_SPREAD
    C.HALF_SPREAD = SPREAD_STRESS
    try:
        if daily:
            return sum(C.net_pnl(p_in, p_out) for _, p_in, p_out in row[cols.index("legs")])
        return C.net_pnl(row[cols.index("p0")], row[cols.index("p1")])
    finally:
        C.HALF_SPREAD = saved


def stats_for(rows: list, cols: list, daily: bool) -> dict:
    ki, ni = cols.index("k"), cols.index("net")
    out = {}
    for name, flt in (("explore", lambda k: C.kdate(k) <= C.EXPLORE_END), ("holdout", lambda k: C.kdate(k) > C.EXPLORE_END),
                      ("all", lambda k: True)):
        rs = [r for r in rows if flt(r[ki])]
        xs = [r[ni] for r in rs]
        if daily:
            t = C.tstat(xs)
        else:
            t, _ = C.day_clustered([(r[ki], r[ni]) for r in rs])
        stressed = [stressed_net(r, cols, daily) for r in rs]
        wins = [x for x in xs if x > 0]
        losses = [-x for x in xs if x < 0]
        eq, peak, mdd = 0.0, 0.0, 0.0
        for x in xs:
            eq += x
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        fav = [r[cols.index("fav_bp")] for r in rs]
        out[name] = {"trades": len(xs), "net": round(sum(xs), 0), "mean": round(statistics.mean(xs), 2) if xs else None,
                     "t": round(t, 2) if t is not None else None,
                     "win_rate": round(len(wins) / len(xs), 3) if xs else None,
                     "profit_factor": round(sum(wins) / sum(losses), 2) if losses else None,
                     "max_drawdown": round(mdd, 0), "mean_stressed": round(statistics.mean(stressed), 2) if stressed else None,
                     "fav_bp": round(statistics.mean(fav), 2) if fav else None,
                     "direction_hit": round(sum(1 for x in fav if x > 0) / len(fav), 3) if fav else None}
    years: dict[int, list] = {}
    for r in rows:
        years.setdefault(C.kdate(r[ki]).year, []).append(r[ni])
    out["years"] = {y: {"trades": len(v), "net": round(sum(v), 0)} for y, v in sorted(years.items())}
    return out


def sharpe_parts(rows, cols):
    xs = [r[cols.index("net")] for r in rows]
    if len(xs) < 30:
        return None
    m, sd = statistics.mean(xs), statistics.pstdev(xs)
    if sd == 0:
        return None
    n = len(xs)
    skew = sum((x - m) ** 3 for x in xs) / n / sd ** 3
    kurt = sum((x - m) ** 4 for x in xs) / n / sd ** 4
    return m / sd, n, skew, kurt


def tier(s: dict, daily: bool, dsr_v) -> str:
    ex, ho = s["explore"], s["holdout"]
    nmin_ex, nmin_ho = (25, 15) if daily else (60, 40)
    if ex["trades"] < nmin_ex or ho["trades"] < nmin_ho or ex["mean"] is None or ho["mean"] is None:
        return "INSUFFICIENT"
    pos = ex["mean"] > 0 and ho["mean"] > 0
    stressed_ok = (ex["mean_stressed"] or 0) > 0 and (ho["mean_stressed"] or 0) > 0
    yrs = [v for v in s["years"].values() if v["trades"] >= 5]
    yr_ok = yrs and sum(1 for v in yrs if v["net"] > 0) / len(yrs) >= 0.6
    if pos and (ex["t"] or 0) >= 2 and (ho["t"] or 0) >= 2 and (dsr_v or 0) >= 0.95 and stressed_ok and yr_ok:
        return "A"
    if pos and (ex["t"] or 0) >= 2 and (ho["t"] or 0) >= 1 and stressed_ok:
        return "B"
    if pos:
        return "C"
    return "FAIL"


def daily_pnl(rows, cols):
    by = {}
    for r in rows:
        by[r[cols.index("k")]] = by.get(r[cols.index("k")], 0.0) + r[cols.index("net")]
    return by


def corr(a: dict, b: dict) -> float | None:
    ks = sorted(set(a) | set(b))
    if len(ks) < 30:
        return None
    xa = [a.get(k, 0.0) for k in ks]
    xb = [b.get(k, 0.0) for k in ks]
    ma, mb = statistics.mean(xa), statistics.mean(xb)
    va = sum((x - ma) ** 2 for x in xa)
    vb = sum((x - mb) ** 2 for x in xb)
    if not va or not vb:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(xa, xb)) / math.sqrt(va * vb)


def main():
    import bn_common
    bn = C.Sessions("NIFTYBANK", start=date(2015, 6, 1))
    C.set_trading_days(bn.all_days)
    res = load_all()
    print(f"{len(res)} trials loaded (protocol declared {TRIALS_DECLARED})")
    parts = {}
    for d in res:
        p = sharpe_parts(d["trades"], d["cols"])
        if p:
            parts[d["sid"] + "@" + d["tf"]] = p
    sr_var = statistics.pvariance([p[0] for p in parts.values()]) if len(parts) > 1 else 0.0
    n_trials = max(TRIALS_DECLARED, len(res))
    rows = []
    for d in res:
        key = d["sid"] + "@" + d["tf"]
        daily = d["source"] == "daily"
        s = stats_for(d["trades"], d["cols"], daily)
        p = parts.get(key)
        dsr_v = C.dsr(p[0], p[1], sr_var, n_trials, p[2], p[3]) if p else None
        rows.append({"key": key, "sid": d["sid"], "tf": d["tf"], "source": d["source"],
                     "family": d.get("family") or d.get("category") or "library", "label": d.get("label") or d["sid"],
                     "params": d.get("params") or {}, "stats": s, "dsr": round(dsr_v, 3) if dsr_v is not None else None,
                     "tier": tier(s, daily, dsr_v), "_daily": daily_pnl(d["trades"], d["cols"]), "_trades": d["trades"],
                     "_cols": d["cols"]})
    order = {"A": 0, "B": 1, "C": 2}
    ranked = sorted([r for r in rows if r["tier"] in order],
                    key=lambda r: (order[r["tier"]], -(r["stats"]["holdout"]["t"] or -9), -(r["dsr"] or 0)))
    chosen, fam_count = [], {}
    for r in ranked:
        fam = r["family"] if r["source"] != "library_intraday" else f"library:{r['sid'].split('_')[0]}"
        # PROTOCOL.md amendment (2026-10-12, after results): the "three per family" cap is not
        # applied - it lumped 48 unrelated library swing strategies into one family. The
        # near-duplicate filter below still applies.
        if FAMILY_CAP is not None and fam_count.get(fam, 0) >= FAMILY_CAP:
            r["skipped"] = f"family {fam} already has {FAMILY_CAP}"
            continue
        clash = [(c["key"], cc) for c in chosen if (cc := corr(r["_daily"], c["_daily"])) is not None and cc > 0.7]
        if clash:
            r["skipped"] = f"daily P&L correlates {clash[0][1]:.2f} with {clash[0][0]}"
            continue
        chosen.append(r)
        fam_count[fam] = fam_count.get(fam, 0) + 1
        if len(chosen) == 10:
            break
    counts = {t: sum(1 for r in rows if r["tier"] == t) for t in ("A", "B", "C", "FAIL", "INSUFFICIENT")}
    eligible = sum(1 for r in rows if r["tier"] != "INSUFFICIENT")
    luck = {"trials": len(rows), "eligible": eligible,
            "expected_C_or_better_by_luck": round(0.25 * eligible, 1),
            "expected_B_or_better_by_luck": round(eligible * 0.0228 * 0.1587, 1),
            "expected_A_by_luck": round(eligible * 0.0228 ** 2, 2),
            "observed": counts}
    print("tiers:", counts, "| luck:", luck)
    for i, r in enumerate(chosen, 1):
        ex, ho = r["stats"]["explore"], r["stats"]["holdout"]
        print(f"{i:2d}. [{r['tier']}] {r['key']:<40} explore {ex['trades']:>4} tr {ex['mean']:>8.0f}/tr t {ex['t']}"
              f" | holdout {ho['trades']:>4} tr {ho['mean']:>8.0f}/tr t {ho['t']} | dsr {r['dsr']}")
    return rows, chosen, luck


VERDICT = (
    "Of 297 BANKNIFTY option-buying strategies tested on 2016-2026 (daily ones at REAL NSE option prices, intraday ones "
    "with a premium model checked against real prices), none is statistically proven: 0 passed, 0 confirmed. Intraday "
    "option buying showed no edge at all - over 233 intraday strategies the index moved the bought option's way 49% of "
    "the time, a coin flip, and the typical one lost Rs245-322 a trade after costs. The ten below are the only distinct "
    "strategies that made money after every cost in BOTH 2016-2021 and 2022-2026. Nine are swing strategies held 1-7 "
    "sessions; most of their profit came from calls and from a handful of large winners. Simply holding calls LOST money "
    "in 2022-2026, so their timing did add something - but with 297 tried, part of this is luck. They run here on paper "
    "only, filled at the real order book, so a forward record can decide."
)
SELECTION_NOTE = (
    "Chosen by the pre-registered protocol (backend/research/banknifty_2026_10/PROTOCOL.md) with one amendment made after "
    "the results and disclosed there: the 'three per family' rule counted all 48 library swing strategies as one family "
    "and would have stopped at six, so it was dropped; near-duplicates (daily P&L correlation above 0.7) are still "
    "removed, which took out mr_btst_finnifty (0.76 with wt_btst). Ranked by their 2022-2026 t-statistic. Tier C means "
    "positive in both periods but not statistically significant - the last four are barely positive after 2022. "
    "Click a row for its curve, its years and what it does at double spreads."
)
CATEGORY_NAMES = {"options_scalp": "Library scalp", "options_intraday": "Library intraday",
                  "options_breakout": "Library breakout", "options_swing": "Library swing"}
SOURCE_ORDER = ("library_intraday", "custom_intraday", "daily")


def _library_meta() -> dict:
    import strategy_service.strategies.options_buying  # noqa: F401
    from tradingai_shared.contracts import STRATEGY_REGISTRY
    return {sid: (cls.metadata.name, cls.metadata.category, cls.metadata.description)
            for sid, cls in STRATEGY_REGISTRY.items() if "options_buying" in (getattr(cls, "__module__", "") or "")}


def _equity(trades, cols) -> list:
    by: dict[str, float] = {}
    for r in trades:
        m = C.kdate(r[cols.index("k")]).strftime("%Y-%m")
        by[m] = by.get(m, 0.0) + r[cols.index("net")]
    out, cum = [], 0.0
    for m in sorted(by):
        cum += by[m]
        out.append([m, round(cum, 0)])
    return out


def _detail(r: dict) -> dict:
    cols, trades = r["_cols"], r["_trades"]
    why = cols.index("why")
    exits: dict[str, int] = {}
    for t in trades:
        exits[t[why]] = exits.get(t[why], 0) + 1
    if "hold_min" in cols:
        hold = round(statistics.mean(t[cols.index("hold_min")] for t in trades)) if trades else None
        kinds = {"CE": sum(1 for t in trades if t[cols.index("side")] > 0), "PE": sum(1 for t in trades if t[cols.index("side")] < 0)}
    else:
        hold = round(statistics.mean(t[cols.index("held")] for t in trades), 1) if trades else None
        kinds = {}
        for t in trades:
            kinds[t[cols.index("kind")]] = kinds.get(t[cols.index("kind")], 0) + 1
    return {**{k: r["stats"][k] for k in ("explore", "holdout", "all")}, "dsr": r["dsr"],
            "years": {str(y): v for y, v in r["stats"]["years"].items()}, "equity": _equity(trades, cols),
            "exits": exits, "avg_hold_min": hold, "kinds": kinds}


def write_app_json(rows, chosen, luck, out_path):
    lib = _library_meta()
    for r in rows:
        if r["source"] in ("library_intraday", "daily") and r["sid"] in lib:
            name, cat, desc = lib[r["sid"]]
            r["label"] = name
            r["family"] = CATEGORY_NAMES.get(cat, cat)
            r["description"] = desc
    calib = json.load(open(os.path.join(C.DATA, "calibration.json"))) if os.path.exists(os.path.join(C.DATA, "calibration.json")) else {}
    intra = json.load(open(os.path.join(C.DATA, "intraday_check.json"))) if os.path.exists(os.path.join(C.DATA, "intraday_check.json")) else {}
    model = {}
    ch = calib.get("chosen")
    if ch:
        model["premium_model"] = (f"Black-76 off the previous session's real smile (NSE closes), India VIX pass-through "
                                  f"beta {ch['beta']}, smile {ch['smile']}-sticky, variance clock")
        model["daily_check_holdout"] = (f"one-day premium change vs real NSE closes 2022-26: bias {ch['holdout']['bias'] * 100:+.2f}% "
                                        f"of premium, rms {ch['holdout']['rmse'] * 100:.1f}% ({ch['holdout']['n']} option-days)")
    real = json.load(open(os.path.join(C.DATA, "real_check.json"))) if os.path.exists(os.path.join(C.DATA, "real_check.json")) else {}
    bench = json.load(open(os.path.join(C.DATA, "benchmarks.json"))) if os.path.exists(os.path.join(C.DATA, "benchmarks.json")) else {}
    if real.get("trades"):
        model["intraday_trades_at_real_prices"] = (f"{real['trades']} of the replays' own intraday trades (Aug-Oct 2026) re-priced with real "
                                                   f"option candles: Rs{real['real_mean']:+,.0f} a trade real vs Rs{real['model_mean']:+,.0f} modelled")
    if bench.get("CE_1"):
        model["benchmark_always_calls"] = ("no signal, buy the ATM call at every close: 2016-21 "
                                           f"Rs{bench['CE_1']['explore'][1]:+,.0f} / 2022-26 Rs{bench['CE_1']['holdout'][1]:+,.0f} a trade "
                                           f"(held 1 session); held 5: Rs{bench['CE_5']['explore'][1]:+,.0f} / Rs{bench['CE_5']['holdout'][1]:+,.0f}")
        model["benchmark_always_straddle"] = (f"daily straddle, held 1 session: Rs{bench['STRADDLE_1']['explore'][1]:+,.0f} / "
                                              f"Rs{bench['STRADDLE_1']['holdout'][1]:+,.0f} a trade - buying volatility loses")
    if intra.get("60"):
        model["intraday_check"] = ("vs real 5-minute option prices, Aug-Oct 2026: 60-minute hold bias "
                                   f"{intra['60']['mean'] * 100:+.2f}% (sd {intra['60']['sd'] * 100:.1f}%), to 15:15 bias "
                                   f"{intra.get('eod', {}).get('mean', 0) * 100:+.2f}% of premium")
    by_source = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    tiers = luck["observed"]
    sel = []
    for i, r in enumerate(chosen, 1):
        d = json.load(open(os.path.join(C.DATA, "results", {"library_intraday": "lib", "custom_intraday": "fam", "daily": "swing"}[r["source"]],
                                        f"{r['sid']}@{r['tf']}.json" if r["source"] == "library_intraday" else f"{r['sid']}.json")))
        sel.append({"rank": i, "key": r["key"], "sid": r["sid"], "tf": r["tf"], "source": r["source"], "tier": r["tier"],
                    "family": r["family"], "label": r["label"], "params": r["params"],
                    "description": r.get("description"), "stop": d.get("stop"), "target": d.get("target"),
                    "research": _detail(r)})
    meta = {
        "generated_at": date.today().isoformat(),
        "window": {"from": "2016-01-01", "to": C.DATA_END.isoformat(),
                   "sessions": len([k for k in C._TRADING if C.RESEARCH_START <= C.kdate(k) <= C.DATA_END])},
        "periods": {"explore": "2016-01-01 .. 2021-12-31", "holdout": "2022-01-01 .. 2026-10-09"},
        "trials": len(rows), "trials_by_source": by_source, "tiers": tiers,
        "luck": {k: luck[k] for k in ("eligible", "expected_C_or_better_by_luck", "expected_B_or_better_by_luck", "expected_A_by_luck")},
        "model": model,
        "costs": "Angel One rate card at today's rates (Rs20/order, STT 0.15% of premium sold, exchange 0.0355%, SEBI, stamp, GST) + 0.25% half spread each side; every result rechecked at 0.50%",
        "contract": "BANKNIFTY monthly options (the only expiry since Nov 2024), lot 30, ATM; intraday: nearest monthly with >= 7 sessions left, daily: >= 15, rolled at <= 3",
        "data": "NIFTY BANK, NIFTY and India VIX 5-minute bars from Angel One, 2015-2026; every BANKNIFTY option's daily close from NSE's F&O bhavcopy, 2015-2026",
        "verdict": VERDICT,
        "selection_note": SELECTION_NOTE,
    }
    trials = []
    chosen_keys = {r["key"] for r in chosen}
    for r in sorted(rows, key=lambda x: ({"A": 0, "B": 1, "C": 2, "FAIL": 3, "INSUFFICIENT": 4}[x["tier"]], -(x["stats"]["holdout"]["t"] or -9))):
        trials.append({"key": r["key"], "source": r["source"], "family": r["family"], "label": r["label"], "tf": r["tf"], "tier": r["tier"],
                       "explore": {k: r["stats"]["explore"][k] for k in ("trades", "mean", "t")},
                       "holdout": {k: r["stats"]["holdout"][k] for k in ("trades", "mean", "t")},
                       "dsr": r["dsr"], "chosen": r["key"] in chosen_keys, "skipped": r.get("skipped")})
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "selected": sel, "trials": trials}, f, separators=(",", ":"))
    print("wrote", out_path, os.path.getsize(out_path) // 1024, "KB")


if __name__ == "__main__":
    rows, chosen, luck = main()
    if len(sys.argv) > 1:
        write_app_json(rows, chosen, luck, sys.argv[1])
