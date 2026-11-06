"""The pre-registered liquidity-sweep test (PREREGISTRATION.md): runs A/B/C over every session on disk,
fills each entry on 1-minute candles, costs it as a NIFTY futures lot, replays and matches the PDF's 42
trades, and scores the app's own options engine on run A. Writes results/."""

import csv
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I leaves the script's folder off sys.path
from ls_common import (HERE, IST, LOT, OPEN_MIN, PERIODS, RUNS, SLIP_PTS, SQUARE_OFF, STRATEGY_ID,  # noqa: E402
                       STRATEGY_REGISTRY, Market, SignalAction, StrategyContext, futures_fees, load_minutes,
                       prereg_hash, walk)

sys.stdout.reconfigure(encoding="utf-8")
OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
ENTRY = (SignalAction.BUY, SignalAction.SELL)


def run_rules(mk: Market, minutes: int, params: dict) -> tuple[list[dict], list[dict]]:
    """Feed every session's candles through the library class exactly as a runner would."""
    strat = STRATEGY_REGISTRY[STRATEGY_ID](params=params)
    ctx = StrategyContext(max_bars=max(500, strat.warmup + 2))
    entries, exits = [], []
    for i in range(len(mk.dates)):
        for bar in mk.candles(i, minutes):
            ctx.push(bar)
            if len(ctx.bars) < strat.warmup:
                continue
            sig = strat.on_bar(ctx)
            if sig is None:
                continue
            start = int((bar.ts.astimezone(IST) - mk.minute_ts(i, 0)).total_seconds() // 60)
            if sig.signal in ENTRY:
                plan = strat.last_plan
                assert plan["ts"] == bar.ts and sig.stop_loss == round(plan["stop"], 2)
                entries.append({"day": i, "start": start, **{k: plan[k] for k in ("side", "entry", "stop", "target",
                                                                                     "risk", "extreme", "levels")},
                                "why": sig.reasoning})
            else:
                exits.append({"day": i, "start": start, "why": sig.reasoning})
    return entries, exits


def fill(mk: Market, e: dict, minutes: int, exits_by_day: dict) -> dict:
    i, side = e["day"], e["side"]
    d = mk.dates[i]
    m0 = e["start"] + minutes                     # first minute after the confirmation candle closed
    px, reason, xd, xm, both = walk(mk, i, m0, side, e["stop"], e["target"])
    entry_fill = e["entry"] + side * SLIP_PTS
    exit_fill = px - side * SLIP_PTS
    fees = futures_fees(entry_fill, exit_fill, LOT, side, d)
    gross = side * (px - e["entry"])
    net = side * (exit_fill - entry_fill) - fees / LOT
    # parity: the strategy's own exit should land on the candle holding the harness's exit minute
    candle = (xm // minutes) * minutes
    own = next((x for x in exits_by_day.get(i, []) if x["start"] > e["start"]), None)
    names = sorted({n for lv in e["levels"] for n in lv[0].split("+")})
    return {
        "date": d.isoformat(), "entry_time": (mk.minute_ts(i, e["start"])).strftime("%H:%M"),
        "side": "long" if side > 0 else "short", "levels": " | ".join(f"{n} {p:.2f}" for n, p in e["levels"]),
        "level_types": names, "entry": round(e["entry"], 2), "stop": round(e["stop"], 2),
        "target": round(e["target"], 2), "risk_pts": round(e["risk"], 2),
        "risk_pct": round(e["risk"] / e["entry"] * 100, 4), "exit": round(float(px), 2), "exit_reason": reason,
        "exit_time": mk.minute_ts(xd, xm).strftime("%H:%M"), "both_in_one_minute": both,
        "gross_pts": round(gross, 2), "fees_rs": fees, "net_pts": round(net, 2),
        "r_gross": round(gross / e["risk"], 4), "r_net": round(net / e["risk"], 4),
        "own_exit_candle_matches": own is not None and own["start"] == candle,
        "own_exit_why": own["why"] if own else None,
    }


def stats(trades: list[dict], sessions: int) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0, "sessions": sessions}
    rn = [t["r_net"] for t in trades]
    rg = [t["r_gross"] for t in trades]
    pts = [t["net_pts"] for t in trades]
    sd = statistics.stdev(rn) if n > 1 else 0.0
    gain, loss = sum(x for x in pts if x > 0), -sum(x for x in pts if x < 0)
    eq = peak = dd = 0.0
    for x in pts:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["exit_reason"]] += 1
    return {
        "trades": n, "sessions": sessions, "trades_per_session": round(n / max(sessions, 1), 3),
        "targets": reasons["target"], "stops": reasons["stop"], "squared_off_1515": reasons["15:15"],
        "win_rate_net": round(sum(x > 0 for x in pts) / n * 100, 1),
        "mean_r_gross": round(statistics.fmean(rg), 4), "mean_r_net": round(statistics.fmean(rn), 4),
        "t_net": round(statistics.fmean(rn) / (sd / math.sqrt(n)), 2) if sd > 0 else None,
        "total_r_net": round(sum(rn), 2), "net_points": round(sum(pts), 1),
        "net_rupees_one_lot": round(sum(pts) * LOT), "gross_points": round(sum(t["gross_pts"] for t in trades), 1),
        "costs_points": round(sum(t["gross_pts"] - t["net_pts"] for t in trades), 1),
        "profit_factor_net": round(gain / loss, 3) if loss > 0 else None,
        "max_drawdown_points": round(dd, 1), "median_risk_pts": round(statistics.median(t["risk_pts"] for t in trades), 1),
        "ambiguous_minutes": sum(t["both_in_one_minute"] for t in trades),
    }


def by(trades: list[dict], key) -> dict:
    groups = defaultdict(list)
    for t in trades:
        for k in key(t):
            groups[k].append(t)
    return {k: {"trades": len(v), "mean_r_net": round(statistics.fmean(x["r_net"] for x in v), 4),
                "mean_r_gross": round(statistics.fmean(x["r_gross"] for x in v), 4),
                "win_rate_net": round(sum(x["net_pts"] > 0 for x in v) / len(v) * 100, 1),
                "net_points": round(sum(x["net_pts"] for x in v), 1)} for k, v in sorted(groups.items())}


def pdf_checks(mk: Market, trades_by_run: dict) -> tuple[list[dict], dict]:
    rows = list(csv.DictReader(open(HERE / "pdf_examples.csv", encoding="utf-8")))
    out = []
    for r in rows:
        d = date.fromisoformat(r["date"])
        i = mk.index[d]
        tf = int(r["tf"])
        side = 1 if r["side"] == "long" else -1
        hh, mm = map(int, r["time"].split(":"))
        start = hh * 60 + mm - OPEN_MIN
        entry, stop = float(r["entry"]), float(r["stop"])
        risk = abs(entry - stop)
        target = float(r["target"]) if r["target"] else entry + side * 2 * risk
        m0 = start + tf
        px, reason, xd, xm, both = walk(mk, i, m0, side, stop, target, carry_days=1 if m0 >= SQUARE_OFF else 0)
        r_pdf = side * (px - entry) / risk
        run = "A" if tf == 5 else "C"
        same_day = [t for t in trades_by_run[run] if t["date"] == r["date"]]
        cands = [t for t in same_day if t["side"] == r["side"]]
        best, gap = None, None
        for t in cands:
            th, tm = map(int, t["entry_time"].split(":"))
            g = abs((th * 60 + tm - OPEN_MIN) - start)
            if gap is None or g < gap:
                best, gap = t, g
        match = "same candle" if gap == 0 else ("within 30 min" if gap is not None and gap <= 30 else
                                                ("same day, later/earlier" if gap is not None else "no trade that side"))
        out.append({
            "id": int(r["id"]), "date": r["date"], "time": r["time"], "tf": tf, "side": r["side"],
            "pdf_entry": entry, "pdf_stop": stop, "pdf_target": round(target, 2),
            "pdf_rr": round(abs(target - entry) / risk, 2), "pdf_risk_pts": round(risk, 2),
            "replay_exit": round(float(px), 2), "replay_reason": reason,
            "replay_exit_when": f"{mk.dates[xd].isoformat()} {mk.minute_ts(xd, xm).strftime('%H:%M')}",
            "replay_r": round(r_pdf, 3), "rules_run": run, "rules_match": match, "rules_gap_min": gap,
            "rules_trade": f"{best['entry_time']} {best['side']} {best['levels']} -> {best['exit_reason']} {best['r_net']:+.2f}R"
                           if best else None,
            "rules_trades_that_day": len(same_day),
        })
    tally = defaultdict(int)
    for o in out:
        tally[o["rules_match"]] += 1
    rr = [o["replay_r"] for o in out]
    replay = {"trades": len(out), "targets": sum(o["replay_reason"] == "target" for o in out),
              "stops": sum(o["replay_reason"] == "stop" for o in out),
              "closed_1515": sum(o["replay_reason"] == "15:15" for o in out),
              "mean_r_gross": round(statistics.fmean(rr), 3), "total_r_gross": round(sum(rr), 2)}
    return out, {"replay": replay, "replication": dict(tally)}


def options_engine_view(mk: Market) -> dict:
    """Run A in the app's own Options Buying Lab engine (synthetic Black-Scholes premiums)."""
    try:
        from options_service.options_backtest import run_options_backtest
    except Exception as exc:  # noqa: BLE001
        return {"error": f"import failed: {exc!r}"}
    first, last = PERIODS["P"]
    lead = [i for i, d in enumerate(mk.dates) if d < first][-80:]            # daily history for the IV proxy
    span = lead + [i for i, d in enumerate(mk.dates) if first <= d <= last]
    bars = [b for i in span for b in mk.candles(i, 5)]
    res = run_options_backtest(STRATEGY_ID, "NIFTY", bars[0].timeframe, bars, lot_size=LOT, strike_step=50.0,
                               expiry_weekday=1, include_trades=True)
    trades = [t for t in res.get("trades", []) if _d(t) >= first]
    pnl = [float(t["pnl"]) for t in trades]
    if len(pnl) < 2:
        return {"trades": len(pnl)}
    reasons = defaultdict(int)
    for t in trades:
        reasons[t.get("exit_reason")] += 1

    def tstat(xs):
        return round(statistics.fmean(xs) / (statistics.stdev(xs) / math.sqrt(len(xs))), 2)

    # the engine charges statutory fees only: no bid-ask spread on its Black-Scholes premiums
    spread = {f"{s}_pt_a_side": {"net_rupees": round(sum(p - 2 * s * LOT for p in pnl)),
                                 "t": tstat([p - 2 * s * LOT for p in pnl])} for s in (0.25, 0.5, 1.0)}
    lab = res.get("metrics", {})
    return {"trades": len(trades), "net_rupees_one_lot": round(sum(pnl)), "avg_rupees": round(statistics.fmean(pnl), 1),
            "t": tstat(pnl), "win_rate": round(sum(p > 0 for p in pnl) / len(pnl) * 100, 1),
            "median_entry_premium": round(statistics.median(abs(float(t["entry_price"])) for t in trades), 2),
            "exit_reasons": dict(reasons), "with_bid_ask_spread": spread,
            "lab_metrics_incl_80_lead_in_sessions": {k: lab.get(k) for k in (
                "net_profit", "total_trades", "win_rate", "profit_factor", "sharpe", "max_drawdown_value")}}


def _d(t) -> date:
    ts = t.get("entry_ts")
    ts = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    return ts.astimezone(IST).date()


def main() -> None:
    t0 = time.time()
    days = load_minutes()
    mk = Market(days)
    summary = {"prereg_sha256": prereg_hash(), "generated": datetime.now(IST).isoformat(timespec="seconds"),
               "data": days.quality, "lot": LOT, "slippage_pts_per_fill": SLIP_PTS, "runs": {}}
    trades_by_run = {}
    for name, cfg in RUNS.items():
        entries, exits = run_rules(mk, cfg["minutes"], cfg["params"])
        exits_by_day = defaultdict(list)
        for x in exits:
            exits_by_day[x["day"]].append(x)
        trades = [fill(mk, e, cfg["minutes"], exits_by_day) for e in entries]
        trades_by_run[name] = trades
        with open(OUT / f"trades_{name}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(trades[0].keys()))
            w.writeheader()
            for t in trades:
                w.writerow({**t, "level_types": "+".join(t["level_types"])})
        block = {"minutes": cfg["minutes"], "params": cfg["params"],
                 "parity_mismatches": sum(not t["own_exit_candle_matches"] for t in trades),
                 "periods": {}}
        for pname, (first, last) in PERIODS.items():
            sel = [t for t in trades if first.isoformat() <= t["date"] <= last.isoformat()]
            sessions = sum(first <= d <= last for d in mk.dates)
            block["periods"][pname] = {"from": first.isoformat(), "to": min(last, mk.dates[-1]).isoformat(),
                                       **stats(sel, sessions)}
            if pname in ("P", "H"):
                block["periods"][pname]["by_level_type"] = by(sel, lambda t: t["level_types"])
                block["periods"][pname]["by_side"] = by(sel, lambda t: [t["side"]])
                block["periods"][pname]["by_entry_hour"] = by(sel, lambda t: [t["entry_time"][:2]])
                block["periods"][pname]["by_year"] = by(sel, lambda t: [t["date"][:4]])
            if pname == "P":
                block["periods"][pname]["by_month"] = by(sel, lambda t: [t["date"][:7]])
        summary["runs"][name] = block
        p = block["periods"]["P"]
        h = block["periods"]["H"]
        print(f"run {name}: P {p['trades']} trades, net {p['mean_r_net']:+.3f}R (t {p['t_net']}), gross "
              f"{p['mean_r_gross']:+.3f}R, win {p['win_rate_net']}%, PF {p['profit_factor_net']}, "
              f"Rs {p['net_rupees_one_lot']:,} | H {h['trades']} trades, net {h['mean_r_net']:+.3f}R (t {h['t_net']}) "
              f"| parity mismatches {block['parity_mismatches']}  [{time.time() - t0:.0f}s]")

    pdf_rows, pdf_summary = pdf_checks(mk, trades_by_run)
    with open(OUT / "pdf_trades.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(pdf_rows[0].keys()))
        w.writeheader()
        w.writerows(pdf_rows)
    summary["pdf"] = pdf_summary
    print("PDF:", json.dumps(pdf_summary))

    summary["options_engine_A_P"] = options_engine_view(mk)
    print("options engine (A, P):", json.dumps(summary["options_engine_A_P"])[:600])

    a = summary["runs"]["A"]["periods"]
    works = (a["P"]["trades"] > 0 and a["P"]["mean_r_net"] > 0 and (a["P"]["t_net"] or 0) >= 2
             and a["H"]["trades"] > 0 and a["H"]["mean_r_net"] > 0)
    summary["verdict"] = {"rule": "A works only if P mean net R > 0 with t >= 2 AND H mean net R > 0",
                          "works": works}
    json.dump(summary, open(OUT / "summary.json", "w"), indent=1, default=str)
    print("verdict:", summary["verdict"], f"[{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
