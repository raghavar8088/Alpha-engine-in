"""Run the NIFTYBEES opening-range breakout: the primary rules and the comparisons fixed with them.

    python -I backend/research/niftybees_orb_2026_10/orb_run.py

Writes results/summary.json (every run), results/sensitivity.csv (one row a run), and for the primary
rules the trade log, the yearly table, the daily equity curve and the ambiguous-candle record.
Every run below was fixed before any result was seen; none was added or changed afterwards. They are
not a search for a better variant: each changes ONE rule of the primary to show what that rule does.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from orb_engine import Config, hhmm, load, run  # noqa: E402

RES = HERE / "results"
P = Config()
RUNS = [
    P,
    replace(P, name="1m_inside_candles", bars=1),
    replace(P, name="best_case_inside_candles", intrabar="best"),
    replace(P, name="raw_opening_range", orb="raw"),
    replace(P, name="opening_band_0.5pct", orb="clean05"),
    replace(P, name="candle_close_entry", entry="close"),
    replace(P, name="stop_and_reverse", max_trades=2, reverse=True),
    replace(P, name="slippage_0bp", slip_bp=0.0),
    replace(P, name="slippage_2bp", slip_bp=2.0),
    replace(P, name="slippage_3bp", slip_bp=3.0),
    replace(P, name="no_costs_no_slippage", costs=False, slip_bp=0.0),
    replace(P, name="target_fills_on_touch", target_fill="touch"),
    replace(P, name="risk_1pct_max_5x", sizing="risk"),
    replace(P, name="rs1_lakh_account", notional=100_000.0, capital=100_000.0, risk=1_000.0),
]
WHAT = {
    "primary": "Primary rules, as above",
    "1m_inside_candles": "Primary, but the path inside each 5-min candle read from its 1-min candles",
    "best_case_inside_candles": "Primary, but ambiguous candles resolved in the trade's favour (bound)",
    "raw_opening_range": "Primary, but the opening range from the raw prints (no cleaning)",
    "opening_band_0.5pct": "Primary, but opening prints cleaned with a 0.5% band instead of 0.2%",
    "candle_close_entry": "Entry on a 5-min close beyond the range, filled at the next candle's open",
    "stop_and_reverse": "After a stop-loss, the opposite breakout is taken once (max 2 trades a day)",
    "slippage_0bp": "No slippage",
    "slippage_2bp": "2 bp slippage a side",
    "slippage_3bp": "3 bp slippage a side",
    "no_costs_no_slippage": "No charges and no slippage (the raw price edge)",
    "target_fills_on_touch": "Target fills when price touches it (no tick through)",
    "risk_1pct_max_5x": "Size: lose ₹10,000 (1%) at the stop, notional capped at 5x (₹50 lakh)",
    "rs1_lakh_account": "₹1 lakh a trade on a ₹1 lakh account (brokerage weighs more)",
}


def inr(x: float) -> str:
    """Indian digit grouping: 1234567 -> 12,34,567."""
    s = f"{abs(x):.0f}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if x < 0 else "") + "Rs" + s


def drawdown(dates: list[str], pnl: np.ndarray, capital: float) -> dict:
    eq = capital + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.r_[capital, eq])[1:]
    dd = peak - eq
    if not len(dd) or dd.max() <= 0:
        return {"max_dd": 0.0, "max_dd_pct_of_peak": 0.0, "peak": None, "trough": None, "recovered": None}
    i = int(dd.argmax())
    pk = int(np.where(np.r_[capital, eq][: i + 2] == peak[i])[0][-1]) - 1
    rec = next((dates[j] for j in range(i, len(eq)) if eq[j] >= peak[i]), None)
    return {"max_dd": float(dd[i]), "max_dd_pct_of_peak": float(dd[i] / peak[i] * 100),
            "max_dd_pct_of_capital": float(dd[i] / capital * 100),
            "peak": dates[pk] if pk >= 0 else "start", "trough": dates[i], "recovered": rec}


def stats(trades: list, sessions: list[str], capital: float) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    net = np.array([t.net for t in trades])
    gross = np.array([t.gross for t in trades])
    fee = np.array([t.fees for t in trades])
    slip = np.array([t.slippage for t in trades])
    risk = np.array([t.risk_rs for t in trades])
    r = net / risk
    rg = gross / risk
    win = net > 0
    losses = -net[net < 0].sum()
    daily = defaultdict(float)
    for t in trades:
        daily[t.date] += t.net
    pnl = np.array([daily.get(d, 0.0) for d in sessions])
    dd = drawdown(sessions, pnl, capital)
    eq = capital + np.cumsum(pnl)
    dd["lowest_equity"] = float(eq.min())
    dd["account_wiped_out_on"] = next((d for d, e in zip(sessions, eq) if e <= 0), None)
    yrs = (np.datetime64(sessions[-1]) - np.datetime64(sessions[0])).astype(int) / 365.25
    streak = best = 0
    for x in net:
        streak = streak + 1 if x <= 0 else 0
        best = max(best, streak)
    reasons = Counter(t.exit_reason for t in trades)
    by_reason = {k: {"trades": int(v), "avg_net": float(net[[t.exit_reason == k for t in trades]].mean()),
                     "win_rate": float(win[[t.exit_reason == k for t in trades]].mean() * 100)}
                 for k, v in reasons.items()}
    side = {}
    for s, lab in ((1, "long"), (-1, "short")):
        m = np.array([t.side == s for t in trades])
        if m.any():
            side[lab] = {"trades": int(m.sum()), "win_rate": float(win[m].mean() * 100), "net": float(net[m].sum()),
                         "avg_r": float(r[m].mean())}
    sd = net.std(ddof=1) if n > 1 else 0.0
    daily_sd = pnl.std(ddof=1)
    out = {
        "trades": n, "sessions": len(sessions), "days_traded_pct": n / len(sessions) * 100,
        "wins": int(win.sum()), "win_rate": float(win.mean() * 100),
        "gross_pnl": float(gross.sum()), "charges": float(fee.sum()), "slippage": float(slip.sum()),
        "net_pnl": float(net.sum()), "return_pct_of_capital": float(net.sum() / capital * 100),
        "annual_return_pct": float(net.sum() / capital * 100 / yrs),
        "profit_factor": float(net[net > 0].sum() / losses) if losses > 0 else math.inf,
        "avg_trade": float(net.mean()), "avg_win": float(net[win].mean()) if win.any() else 0.0,
        "avg_loss": float(net[~win].mean()) if (~win).any() else 0.0,
        "avg_r_net": float(r.mean()), "avg_r_gross": float(rg.mean()),
        "avg_cost_r": float((fee / risk).mean()), "avg_slippage_r": float((slip / risk).mean()),
        "avg_risk_bp": float(np.mean([abs(t.entry_fill - t.stop) / t.entry_fill * 1e4 for t in trades])),
        "median_risk_bp": float(np.median([abs(t.entry_fill - t.stop) / t.entry_fill * 1e4 for t in trades])),
        "avg_notional": float(np.mean([t.qty * t.entry_fill / 100 for t in trades])),
        "t_stat": float(net.mean() / sd * math.sqrt(n)) if sd > 0 else 0.0,
        "avg_trade_ci95": [float(net.mean() - 1.96 * sd / math.sqrt(n)), float(net.mean() + 1.96 * sd / math.sqrt(n))],
        "sharpe_daily_annualised": float(pnl.mean() / daily_sd * math.sqrt(len(sessions) / yrs)) if daily_sd > 0 else 0.0,
        "longest_losing_streak": int(best),
        "exit_reasons": by_reason, "by_side": side,
        "ambiguous_trades": int(sum(t.ambiguous for t in trades)),
        "avg_hold_min": float(np.mean([(t.exit_bar - t.entry_bar) for t in trades])),
        **dd,
    }
    return out


def yearly(trades: list, sessions: list[str], capital: float) -> list[dict]:
    rows = []
    for y in sorted({d[:4] for d in sessions}):
        ss = [d for d in sessions if d.startswith(y)]
        tt = [t for t in trades if t.date.startswith(y)]
        s = stats(tt, ss, capital) if tt else {"trades": 0}
        rows.append({"year": y, "from": ss[0], "to": ss[-1], "sessions": len(ss), "trades": s["trades"],
                     "win_rate": s.get("win_rate", 0.0), "gross_pnl": s.get("gross_pnl", 0.0),
                     "charges": s.get("charges", 0.0), "net_pnl": s.get("net_pnl", 0.0),
                     "return_pct": s.get("return_pct_of_capital", 0.0), "profit_factor": s.get("profit_factor", 0.0),
                     "max_dd": s.get("max_dd", 0.0), "max_dd_pct_of_capital": s.get("max_dd_pct_of_capital", 0.0),
                     "avg_r_net": s.get("avg_r_net", 0.0), "targets": s.get("exit_reasons", {}).get("target", {}).get("trades", 0),
                     "stops": s.get("exit_reasons", {}).get("stop", {}).get("trades", 0),
                     "eod": s.get("exit_reasons", {}).get("eod", {}).get("trades", 0)})
    return rows


def ambiguity(primary: dict, fine: dict) -> dict:
    """What the 5-minute worst-case rule decided on candles whose order was unknown, against what the
    1-minute candles inside them show."""
    cats = Counter()
    for a in primary["ambiguous"]:
        ch, ot = a["chosen"], a["other"]
        if ("long" in ch and "short" in ot) or ("short" in ch and "long" in ot):
            cats["both breakouts in one candle"] += 1
        elif ch.split(">")[0] in ("long", "short"):
            cats["entry candle also reached the stop (or the target)"] += 1
        else:
            cats["open trade: stop and target in the same candle"] += 1
    by_day_fine = {t.date: t for t in fine["trades"]}
    flips = Counter()
    pnl_diff = 0.0
    for t in primary["trades"]:
        if not t.ambiguous:
            continue
        f = by_day_fine.get(t.date)
        key = f"5m {t.exit_reason} -> 1m {f.exit_reason if f else 'no trade'}"
        if f and f.side != t.side:
            key += " (other side)"
        flips[key] += 1
        pnl_diff += (f.net if f else 0.0) - t.net
    same = sum(1 for t in primary["trades"] if not t.ambiguous and by_day_fine.get(t.date)
               and by_day_fine[t.date].exit_reason == t.exit_reason and by_day_fine[t.date].side == t.side)
    return {"ambiguous_candles": len(primary["ambiguous"]), "by_kind": dict(cats),
            "ambiguous_trades": int(sum(t.ambiguous for t in primary["trades"])),
            "same_trade_days_unambiguous_matching_1m": same,
            "ambiguous_trades_resolved_by_1m": dict(flips),
            "net_change_if_1m_used_on_ambiguous_trades": pnl_diff,
            "candles_still_ambiguous_at_1m": len(fine["ambiguous"])}


def diagnostics(trades: list) -> dict:
    """Descriptive cuts of the primary trades (not filters: nothing was tuned on them)."""
    out = {}
    risk_bp = np.array([abs(t.entry_fill - t.stop) / t.entry_fill * 1e4 for t in trades])
    net = np.array([t.net for t in trades])
    r = np.array([t.net / t.risk_rs for t in trades])
    rg = np.array([t.gross / t.risk_rs for t in trades])
    qs = np.quantile(risk_bp, [0, .2, .4, .6, .8, 1])
    rows = []
    for i in range(5):
        m = (risk_bp >= qs[i]) & ((risk_bp < qs[i + 1]) if i < 4 else (risk_bp <= qs[i + 1]))
        rows.append({"risk_bp": f"{qs[i]:.0f}-{qs[i + 1]:.0f}", "trades": int(m.sum()),
                     "win_rate": float((net[m] > 0).mean() * 100), "avg_r_gross": float(rg[m].mean()),
                     "avg_r_net": float(r[m].mean()), "net_pnl": float(net[m].sum()),
                     "targets_pct": float(np.mean([t.exit_reason == "target" for t, k in zip(trades, m) if k]) * 100)})
    out["by_stop_distance_quintile"] = rows
    buckets = [(15, 30, "09:30-09:45"), (30, 60, "09:45-10:15"), (60, 120, "10:15-11:15"), (120, 240, "11:15-13:15"),
               (240, 345, "13:15-15:00")]
    rows = []
    eb = np.array([t.entry_bar for t in trades])
    for a, b, lab in buckets:
        m = (eb >= a) & (eb < b)
        if m.any():
            rows.append({"entry": lab, "trades": int(m.sum()), "win_rate": float((net[m] > 0).mean() * 100),
                         "avg_r_net": float(r[m].mean()), "net_pnl": float(net[m].sum())})
    out["by_entry_time"] = rows
    return out


def trade_rows(trades: list, bars: int) -> list[dict]:
    out = []
    for t in trades:
        out.append({"date": t.date, "side": "LONG" if t.side > 0 else "SHORT",
                    "entry_candle": hhmm(t.entry_bar), "trigger": t.entry_level / 100, "entry": t.entry_fill / 100,
                    "stop": t.stop / 100, "target": t.target / 100,
                    "risk_bp": round(abs(t.entry_fill - t.stop) / t.entry_fill * 1e4, 1), "qty": t.qty,
                    "exit_candle": hhmm(t.exit_bar), "exit_reason": t.exit_reason, "exit_level": t.exit_level / 100,
                    "exit": t.exit_fill / 100, "gross": round(t.gross, 2), "charges": round(t.fees, 2),
                    "slippage": round(t.slippage, 2), "net": round(t.net, 2),
                    "r_multiple": round(t.net / t.risk_rs, 3), "ambiguous_candle": int(t.ambiguous)})
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    RES.mkdir(exist_ok=True)
    data = load(HERE / "data")
    out, results = {}, {}
    for cfg in RUNS:
        r = run(cfg, data)
        results[cfg.name] = r
        s = stats(r["trades"], r["sessions"], cfg.capital)
        out[cfg.name] = {"what": WHAT[cfg.name], "config": asdict(cfg), "stats": s,
                         "yearly": yearly(r["trades"], r["sessions"], cfg.capital)}
        print(f"{cfg.name:26} trades {s['trades']:5}  win {s['win_rate']:5.1f}%  net {inr(s['net_pnl']):>14}  "
              f"PF {s['profit_factor']:.2f}  maxDD {inr(s['max_dd']):>12} ({s['max_dd_pct_of_capital']:.1f}%)  "
              f"R/trade {s['avg_r_net']:+.3f} (gross {s['avg_r_gross']:+.3f})  t {s['t_stat']:+.2f}", flush=True)
    prim, fine = results["primary"], results["1m_inside_candles"]
    out["primary"]["ambiguity"] = ambiguity(prim, fine)
    out["primary"]["diagnostics"] = diagnostics(prim["trades"])
    out["1m_inside_candles"]["diagnostics"] = diagnostics(fine["trades"])
    # equity curves for the report: primary, 1-minute check, raw range
    curves = {}
    for name in ("primary", "1m_inside_candles", "raw_opening_range", "no_costs_no_slippage"):
        r = results[name]
        daily = defaultdict(float)
        for t in r["trades"]:
            daily[t.date] += t.net
        cap = out[name]["config"]["capital"]
        eq = cap + np.cumsum([daily.get(d, 0.0) for d in r["sessions"]])
        curves[name] = [round(float(x), 2) for x in eq]
    out["_curves"] = {"dates": prim["sessions"], **curves}
    with open(RES / "summary.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
    write_csv(RES / "trades_primary.csv", trade_rows(prim["trades"], 5))
    write_csv(RES / "trades_1m_inside_candles.csv", trade_rows(fine["trades"], 1))
    write_csv(RES / "yearly_primary.csv", out["primary"]["yearly"])
    write_csv(RES / "yearly_1m_inside_candles.csv", out["1m_inside_candles"]["yearly"])
    daily = defaultdict(float)
    for t in prim["trades"]:
        daily[t.date] += t.net
    eq, peak, rows = P.capital, P.capital, []
    for d in prim["sessions"]:
        eq += daily.get(d, 0.0)
        peak = max(peak, eq)
        rows.append({"date": d, "pnl": round(daily.get(d, 0.0), 2), "equity": round(eq, 2), "drawdown": round(peak - eq, 2)})
    write_csv(RES / "equity_primary.csv", rows)
    with open(RES / "ambiguous_candles_primary.json", "w") as f:
        json.dump({"summary": out["primary"]["ambiguity"], "candles": prim["ambiguous"]}, f, indent=1, default=str)
    sens = []
    for name, o in out.items():
        if name.startswith("_"):
            continue
        s = o["stats"]
        sens.append({"run": name, "what": o["what"], "trades": s["trades"], "win_rate": round(s["win_rate"], 1),
                     "net_pnl": round(s["net_pnl"], 0), "return_pct": round(s["return_pct_of_capital"], 1),
                     "profit_factor": round(s["profit_factor"], 3), "max_dd": round(s["max_dd"], 0),
                     "max_dd_pct_of_capital": round(s["max_dd_pct_of_capital"], 1),
                     "avg_r_net": round(s["avg_r_net"], 3), "avg_r_gross": round(s["avg_r_gross"], 3),
                     "t_stat": round(s["t_stat"], 2)})
    write_csv(RES / "sensitivity.csv", sens)
    print(json.dumps(out["primary"]["ambiguity"], indent=1))
    print(json.dumps({k: v for k, v in out["primary"]["stats"].items()}, indent=1, default=str))
    for row in out["primary"]["yearly"]:
        print(row)


if __name__ == "__main__":
    main()
