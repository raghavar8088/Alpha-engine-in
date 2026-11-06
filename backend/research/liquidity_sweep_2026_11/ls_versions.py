"""Round 2: score every version of the liquidity sweep (PREREGISTRATION_VERSIONS.md).

Each version is run by its own registered class over every session on disk, each entry is filled on
1-minute candles (stop first in a minute touching both; v13's stop moves to entry from the candle after
the one that reached +1R; v15 has no target), costed as one futures lot with Angel One charges plus 1 point
of slippage per fill, and scored in S (2016-2022), V (2023 - 23 Sep 2025) and P (24 Sep 2025 - last day).
Writes results/versions/{summary.json, scoreboard.csv, trades.csv.gz}."""

import csv
import gzip
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I leaves the script's folder off sys.path
from ls_common import (HERE, IST, OPEN_MIN, SLIP_PTS, SQUARE_OFF, STRATEGY_REGISTRY, Market, SignalAction,  # noqa: E402
                       StrategyContext, futures_fees, load_minutes, load_minutes_named)

sys.stdout.reconfigure(encoding="utf-8")
OUT = HERE / "results" / "versions"
OUT.mkdir(parents=True, exist_ok=True)
ENTRY = (SignalAction.BUY, SignalAction.SELL)
PERIODS = {"S": (date(2016, 1, 1), date(2022, 12, 31)),
           "V": (date(2023, 1, 1), date(2025, 9, 23)),
           "P": (date(2025, 9, 24), date(2026, 12, 31))}
LOTS = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20}

# (id, strategy id, params, market, candle minutes, label)
VERSIONS = [
    ("v00", "bb_liquidity_sweep", {}, "NIFTY", 5, "Original (D9)"),
    ("v01", "bb_ls_v01_pdh_pdl", {}, "NIFTY", 5, "Levels: PDH/PDL only"),
    ("v02", "bb_ls_v02_pdc_only", {}, "NIFTY", 5, "Levels: PDC only"),
    ("v03", "bb_ls_v03_equal_hl", {}, "NIFTY", 5, "Levels: equal highs/lows only"),
    ("v04", "bb_ls_v04_1h_swings", {}, "NIFTY", 5, "Levels: 1-hour swings only"),
    ("v05", "bb_ls_v05_round_numbers", {}, "NIFTY", 5, "Levels: + round numbers"),
    ("v06", "bb_ls_v06_wick_only", {}, "NIFTY", 5, "Wick sweeps only"),
    ("v07", "bb_ls_v07_strong_reject", {}, "NIFTY", 5, "Strong rejection candle"),
    ("v08", "bb_ls_v08_next_candle", {}, "NIFTY", 5, "Next-candle confirmation"),
    ("v09", "bb_ls_v09_retest_entry", {}, "NIFTY", 5, "Retest-and-reject entry"),
    ("v10", "bb_ls_v10_mss", {}, "NIFTY", 5, "Market-structure shift entry"),
    ("v11", "bb_ls_v11_target_1r", {}, "NIFTY", 5, "Target 1:1"),
    ("v12", "bb_ls_v12_target_3r", {}, "NIFTY", 5, "Target 1:3"),
    ("v13", "bb_ls_v13_breakeven", {}, "NIFTY", 5, "Breakeven at +1R"),
    ("v14", "bb_ls_v14_opposite_liq", {}, "NIFTY", 5, "Target = opposite liquidity"),
    ("v15", "bb_ls_v15_no_target", {}, "NIFTY", 5, "No target (stop or 15:15)"),
    ("v16", "bb_ls_v16_ema200", {}, "NIFTY", 5, "200-EMA side filter"),
    ("v17", "bb_ls_v17_big_sweeps", {}, "NIFTY", 5, "Big sweeps only (risk >= 0.15%)"),
    ("v18", "bb_ls_v18_morning", {}, "NIFTY", 5, "Morning only (to 11:15)"),
    ("v19", "bb_ls_v19_afternoon", {}, "NIFTY", 5, "Afternoon only (from 12:00)"),
    ("v20", "bb_ls_v20_one_a_day", {}, "NIFTY", 5, "One trade a day"),
    ("v21", "bb_ls_v21_break_retest", {}, "NIFTY", 5, "Breakout-and-retest (video's other entry)"),
    ("v22", "bb_ls_v22_full_video", {}, "NIFTY", 5, "Full video: sweeps + break-retests"),
    ("r1", "bb_liquidity_sweep", {"bar_minutes": 15}, "NIFTY", 15, "Original on 15-minute candles"),
    ("r2", "bb_liquidity_sweep", {"bar_minutes": 3}, "NIFTY", 3, "Original on 3-minute candles"),
    ("r3", "bb_liquidity_sweep", {}, "BANKNIFTY", 5, "Original on BANK NIFTY"),
    ("r4", "bb_liquidity_sweep", {}, "SENSEX", 5, "Original on SENSEX"),
]


def run_rules(sid: str, params: dict, mk: Market, candles: list) -> tuple[list[dict], list[dict], object]:
    strat = STRATEGY_REGISTRY[sid](params=params)
    ctx = StrategyContext(max_bars=max(500, strat.warmup + 2))
    entries, exits = [], []
    for i, day in enumerate(candles):
        for bar in day:
            ctx.push(bar)
            if len(ctx.bars) < strat.warmup:
                continue
            sig = strat.on_bar(ctx)
            if sig is None:
                continue
            start = int((bar.ts.astimezone(IST) - mk.minute_ts(i, 0)).total_seconds() // 60)
            if sig.signal in ENTRY:
                plan = strat.last_plan
                entries.append({"day": i, "start": start, **{k: plan[k] for k in ("side", "entry", "stop", "target",
                                                                                     "risk", "levels")}})
            else:
                exits.append({"day": i, "start": start, "why": sig.reasoning})
    return entries, exits, strat


def walk_v(mk: Market, i: int, m0: int, side: int, entry: float, stop: float, target, be_r: float,
           risk: float, candle: int):
    """The versions' 1-minute walk: target may be None; with be_r > 0 the stop moves to entry from the
    first candle after the one in which price reached +be_r R (the strategy's own rule)."""
    be_from = None
    for m in range(m0, SQUARE_OFF):
        if be_from is not None and m >= be_from:
            stop = entry
        o, h, lo = mk.o[i, m], mk.h[i, m], mk.l[i, m]
        if side < 0:
            if h >= stop:
                return max(o, stop), ("breakeven" if be_from is not None and m >= be_from else "stop"), m
            if target is not None and lo <= target:
                return target, "target", m
            if be_r > 0 and be_from is None and lo <= entry - be_r * risk:
                be_from = (m // candle + 1) * candle
        else:
            if lo <= stop:
                return min(o, stop), ("breakeven" if be_from is not None and m >= be_from else "stop"), m
            if target is not None and h >= target:
                return target, "target", m
            if be_r > 0 and be_from is None and h >= entry + be_r * risk:
                be_from = (m // candle + 1) * candle
    return float(mk.c[i, SQUARE_OFF - 1]), "15:15", SQUARE_OFF - 1


def fill(mk: Market, e: dict, candle: int, own_exits: dict, be_r: float, lot: int) -> dict:
    i, side = e["day"], e["side"]
    d = mk.dates[i]
    px, reason, xm = walk_v(mk, i, e["start"] + candle, side, e["entry"], e["stop"], e["target"], be_r, e["risk"], candle)
    entry_fill, exit_fill = e["entry"] + side * SLIP_PTS, px - side * SLIP_PTS
    fees = futures_fees(entry_fill, exit_fill, lot, side, d)
    gross = side * (px - e["entry"])
    net = side * (exit_fill - entry_fill) - fees / lot
    own = next((x for x in own_exits.get(i, []) if x["start"] > e["start"]), None)
    return {"date": d.isoformat(), "entry_time": mk.minute_ts(i, e["start"]).strftime("%H:%M"),
            "side": "long" if side > 0 else "short",
            "levels": "+".join(sorted({n for lv in e["levels"] for n in lv[0].split("+")})),
            "entry": round(e["entry"], 2), "stop": round(e["stop"], 2),
            "target": None if e["target"] is None else round(e["target"], 2), "risk_pts": round(e["risk"], 2),
            "exit": round(float(px), 2), "exit_reason": reason, "exit_time": mk.minute_ts(i, xm).strftime("%H:%M"),
            "gross_pts": round(gross, 2), "fees_rs": fees, "net_pts": round(net, 2),
            "r_gross": round(gross / e["risk"], 4), "r_net": round(net / e["risk"], 4),
            "parity": own is not None and own["start"] == (xm // candle) * candle}


def _t(xs: list[float]):
    if len(xs) < 2:
        return None
    sd = statistics.stdev(xs)
    return round(statistics.fmean(xs) / (sd / math.sqrt(len(xs))), 2) if sd > 0 else None


def stats(trades: list[dict], sessions: int, lot: int) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0, "sessions": sessions}
    rg, rn, pts = [t["r_gross"] for t in trades], [t["r_net"] for t in trades], [t["net_pts"] for t in trades]
    gain, loss = sum(x for x in pts if x > 0), -sum(x for x in pts if x < 0)
    eq = peak = dd = 0.0
    for x in pts:
        eq += x
        peak, dd = max(peak, eq), max(dd, max(peak, eq) - eq)
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["exit_reason"]] += 1
    return {"trades": n, "sessions": sessions, "per_session": round(n / max(sessions, 1), 2),
            "targets": reasons["target"], "stops": reasons["stop"], "breakeven": reasons["breakeven"],
            "at_1515": reasons["15:15"], "win_rate_net": round(sum(x > 0 for x in pts) / n * 100, 1),
            "mean_r_gross": round(statistics.fmean(rg), 4), "t_gross": _t(rg),
            "mean_r_net": round(statistics.fmean(rn), 4), "t_net": _t(rn),
            "net_points": round(sum(pts), 1), "net_rupees": round(sum(pts) * lot),
            "profit_factor_net": round(gain / loss, 3) if loss > 0 else None, "max_drawdown_points": round(dd, 1),
            "median_risk_pts": round(statistics.median(t["risk_pts"] for t in trades), 1)}


def verdict(per: dict) -> str:
    S, V, P = per["S"], per["V"], per["P"]
    if not (S.get("trades") and V.get("trades") and P.get("trades")):
        return "NO EDGE"
    if S["mean_r_net"] > 0 and (S["t_net"] or 0) >= 3 and V["mean_r_net"] > 0 and P["mean_r_net"] > 0:
        return "PASS"
    if S["mean_r_gross"] > 0 and (S["t_gross"] or 0) >= 3 and V["mean_r_gross"] > 0 and P["mean_r_gross"] > 0:
        return "RAW EDGE"
    return "NO EDGE"


def main() -> None:
    t0 = time.time()
    summary = {"prereg_sha256": __import__("hashlib").sha256(
                   (HERE / "PREREGISTRATION_VERSIONS.md").read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
               "generated": datetime.now(IST).isoformat(timespec="seconds"),
               "periods": {k: [a.isoformat(), b.isoformat()] for k, (a, b) in PERIODS.items()},
               "slippage_pts_per_fill": SLIP_PTS, "lots": LOTS, "versions": {}}
    rows, all_trades = [], []
    markets: dict[str, Market] = {}
    order = sorted(VERSIONS, key=lambda v: (v[3], v[4]))     # group by (market, candle) so candles build once
    built_key, candles = None, None
    for vid, sid, params, market, minutes, label in order:
        if market not in markets:
            markets[market] = Market(load_minutes() if market == "NIFTY" else load_minutes_named(market))
            summary.setdefault("data", {})[market] = markets[market].days.quality
        mk = markets[market]
        if built_key != (market, minutes):
            candles = [mk.candles(i, minutes) for i in range(len(mk.dates))]
            built_key = (market, minutes)
        entries, exits, strat = run_rules(sid, params, mk, candles)
        own = defaultdict(list)
        for x in exits:
            own[x["day"]].append(x)
        be_r = getattr(strat.params, "breakeven_r", 0.0)
        trades = [fill(mk, e, minutes, own, be_r, LOTS[market]) for e in entries]
        per = {}
        for pname, (first, last) in PERIODS.items():
            sel = [t for t in trades if first.isoformat() <= t["date"] <= last.isoformat()]
            per[pname] = stats(sel, sum(first <= d <= last for d in mk.dates), LOTS[market])
        per["ALL"] = stats(trades, len(mk.dates), LOTS[market])
        block = {"strategy_id": sid, "params": params, "market": market, "candle_minutes": minutes, "label": label,
                 "parity_mismatches": sum(not t["parity"] for t in trades), "periods": per, "verdict": verdict(per)}
        summary["versions"][vid] = block
        for t in trades:
            all_trades.append({"version": vid, **t})
        S, V, P, A = per["S"], per["V"], per["P"], per["ALL"]
        rows.append({"id": vid, "label": label, "strategy_id": sid, "market": market, "candle": minutes,
                     "trades": A["trades"], "win_rate": A["win_rate_net"],
                     "S_gross_r": S.get("mean_r_gross"), "S_t_gross": S.get("t_gross"), "S_net_r": S.get("mean_r_net"),
                     "S_t_net": S.get("t_net"), "V_gross_r": V.get("mean_r_gross"), "V_net_r": V.get("mean_r_net"),
                     "P_trades": P.get("trades"), "P_gross_r": P.get("mean_r_gross"), "P_net_r": P.get("mean_r_net"),
                     "P_t_net": P.get("t_net"), "P_rupees": P.get("net_rupees"), "all_gross_r": A["mean_r_gross"],
                     "all_net_r": A["mean_r_net"], "all_rupees": A["net_rupees"], "median_risk": A["median_risk_pts"],
                     "verdict": block["verdict"], "parity_mismatches": block["parity_mismatches"]})
        print(f"{vid:>3} {label:42} {A['trades']:5d} tr | S gross {S.get('mean_r_gross', 0):+.3f} (t {S.get('t_gross')}) "
              f"net {S.get('mean_r_net', 0):+.3f} | V net {V.get('mean_r_net', 0):+.3f} | P net {P.get('mean_r_net', 0):+.3f} "
              f"Rs {P.get('net_rupees', 0):>10,} | {block['verdict']} | parity {block['parity_mismatches']} "
              f"[{time.time() - t0:.0f}s]", flush=True)

    rank = {v[0]: k for k, v in enumerate(VERSIONS)}
    rows.sort(key=lambda r: rank[r["id"]])
    with open(OUT / "scoreboard.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with gzip.open(OUT / "trades.csv.gz", "wt", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(all_trades[0].keys()))
        w.writeheader()
        w.writerows(all_trades)
    summary["verdicts"] = {r["id"]: r["verdict"] for r in rows}
    json.dump(summary, open(OUT / "summary.json", "w"), indent=1, default=str)
    print("verdicts:", json.dumps(summary["verdicts"]), f"[{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
