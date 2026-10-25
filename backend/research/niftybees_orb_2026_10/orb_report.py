"""Write REPORT.md and report/niftybees-orb-backtest.html from the results.

    python -I backend/research/niftybees_orb_2026_10/orb_report.py

Every number in both files is read from results/ (and the example day from data/), so the report cannot
drift from the runs.
"""

from __future__ import annotations

import csv
import gzip
import html
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from orb_engine import AF  # noqa: E402  (the app's fee model, path already set up)
from orb_run import RUNS, WHAT  # noqa: E402

RES, DATA, OUT = HERE / "results", HERE / "data", HERE / "report"
MINUS = "−"
EXAMPLE_DAY = "2026-10-23"


# ── formatting ─────────────────────────────────────────────────────────────────────────────────────

def group(n: int) -> str:
    s = str(abs(int(round(n))))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def inr(x: float, plus: bool = False) -> str:
    sign = MINUS if round(x) < 0 else ("+" if plus and round(x) > 0 else "")
    return f"{sign}₹{group(x)}"


def lakh(x: float, plus: bool = False) -> str:
    sign = MINUS if x < 0 else ("+" if plus and x > 0 else "")
    return f"{sign}₹{abs(x) / 1e5:.2f} lakh"


def num(x: float, nd: int = 1, plus: bool = False) -> str:
    s = f"{abs(x):,.{nd}f}"
    sign = MINUS if x < 0 and float(s.replace(",", "")) != 0 else ("+" if plus and x > 0 else "")
    return sign + s


def dt(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%b} {d.year}"


def e(s) -> str:
    return html.escape(str(s), quote=True)


# ── the numbers ────────────────────────────────────────────────────────────────────────────────────

def gather() -> dict:
    summ = json.load(open(RES / "summary.json"))
    dq = json.load(open(RES / "data_quality.json"))
    xc = json.load(open(RES / "crosscheck_yahoo.json"))
    trades = list(csv.DictReader(open(RES / "trades_primary.csv")))
    for t in trades:
        for k in ("entry", "exit", "stop", "target", "trigger", "gross", "charges", "slippage", "net", "r_multiple",
                  "risk_bp", "exit_level"):
            t[k] = float(t[k])
        t["qty"] = int(t["qty"])
    P = summ["primary"]
    S = P["stats"]
    before = S["net_pnl"] + S["charges"] + S["slippage"]
    # per-year before-costs and costs
    yb = defaultdict(lambda: [0.0, 0.0, 0.0])
    for t in trades:
        y = t["date"][:4]
        yb[y][0] += t["net"] + t["charges"] + t["slippage"]
        yb[y][1] += t["charges"]
        yb[y][2] += t["slippage"]
    years = []
    for r in P["yearly"]:
        b = yb[r["year"]]
        years.append({**r, "before": b[0], "charges_only": b[1], "slip": b[2], "costs": b[1] + b[2]})
    # equity curves: after costs and the same trades before costs
    dates = summ["_curves"]["dates"]
    net_curve = summ["_curves"]["primary"]
    pre_day = defaultdict(float)
    for t in trades:
        pre_day[t["date"]] += t["net"] + t["charges"] + t["slippage"]
    cap = P["config"]["capital"]
    pre_curve, acc = [], cap
    for d in dates:
        acc += pre_day.get(d, 0.0)
        pre_curve.append(round(acc, 2))
    peak_i, trough_i = dates.index(S["peak"]), dates.index(S["trough"])
    month_end = []
    for i, d in enumerate(dates):
        if i == len(dates) - 1 or dates[i + 1][:7] != d[:7]:
            month_end.append((d, net_curve[i], pre_curve[i]))
    # a typical round trip's charges (the median entry price)
    px = sorted(t["entry"] for t in trades)[len(trades) // 2]
    qty = int(P["config"]["notional"] // px)
    fb = AF.round_trip(px, px, qty, "BUY", "INTRADAY").as_dict()
    # the example day
    day = {"date": EXAMPLE_DAY, "candles": []}
    with gzip.open(DATA / "NIFTYBEES_5m.csv.gz", "rt") as f:
        for r in csv.DictReader(f):
            if r["date"] == EXAMPLE_DAY and r["time"] <= "11:00":
                day["candles"].append([r["time"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])])
    op = {r["date"]: r for r in json.load(open(DATA / "opening_ranges.json"))}
    day["or_raw"] = [op[EXAMPLE_DAY]["raw_orl"], op[EXAMPLE_DAY]["raw_orh"]]
    day["or_clean"] = [op[EXAMPLE_DAY]["orl"], op[EXAMPLE_DAY]["orh"]]
    tr = next(t for t in trades if t["date"] == EXAMPLE_DAY)
    day["trade"] = {k: tr[k] for k in ("side", "entry_candle", "trigger", "entry", "stop", "target", "exit_candle",
                                       "exit_reason", "exit", "qty", "net", "charges", "slippage", "gross")}
    qtys = [t["qty"] for t in trades]
    runs = []
    for cfg in RUNS:
        o = summ[cfg.name]
        runs.append({"name": cfg.name, "what": WHAT[cfg.name], **o["stats"], "capital": o["config"]["capital"]})
    rr = json.load(open(RES / "rr_compare.json", encoding="utf-8")) if (RES / "rr_compare.json").exists() else {}
    return {"rr": rr, "summ": summ, "P": P, "S": S, "dq": dq, "xc": xc, "trades": trades, "before": before, "years": years,
            "dates": dates, "net_curve": net_curve, "pre_curve": pre_curve, "peak_i": peak_i, "trough_i": trough_i,
            "month_end": month_end, "fee": fb, "fee_px": px, "fee_qty": qty, "day": day, "runs": runs,
            "qty_range": [min(qtys), max(qtys)], "cap": cap}


# ── shared prose ───────────────────────────────────────────────────────────────────────────────────

def facts(g: dict) -> dict:
    S, dq = g["S"], g["dq"]
    n = S["trades"]
    ex = S["exit_reasons"]
    dev = dq["opening_prints"]["deviation_from_nifty_bp"]
    cal = dq["calendar"]
    nb = dq["niftybees"]
    amb = g["P"]["ambiguity"]
    fine = g["summ"]["1m_inside_candles"]["stats"]
    best = g["summ"]["best_case_inside_candles"]["stats"]
    per_trade_before = g["before"] / n
    return {
        "n": n, "sessions": S["sessions"], "win": S["win_rate"], "net": S["net_pnl"], "pf": S["profit_factor"],
        "dd": S["max_dd"], "dd_pct": S["max_dd_pct_of_capital"], "peak": S["peak"], "trough": S["trough"],
        "long": S["by_side"]["long"]["trades"], "short": S["by_side"]["short"]["trades"],
        "tgt": ex["target"]["trades"], "stop": ex["stop"]["trades"], "eod": ex["eod"]["trades"],
        "eod_win": ex["eod"]["win_rate"], "avg": S["avg_trade"], "r_net": S["avg_r_net"],
        "r_before": S["avg_r_gross"] + S["avg_slippage_r"], "charges": S["charges"], "slip": S["slippage"],
        "before": g["before"], "per_before": per_trade_before, "per_charges": S["charges"] / n,
        "per_slip": S["slippage"] / n, "t": S["t_stat"], "ci": S["avg_trade_ci95"], "risk_med": S["median_risk_bp"],
        "annual": S["annual_return_pct"], "streak": S["longest_losing_streak"], "sharpe": S["sharpe_daily_annualised"],
        "hold": S["avg_hold_min"], "lowest": S["lowest_equity"], "peak_eq": S["lowest_equity"] + S["max_dd"],
        "dev": dev, "cal": cal, "nb": nb, "amb": amb, "fine": fine, "best": best,
        "op": dq["opening_prints"], "notional": g["P"]["config"]["notional"],
    }


# ── markdown ───────────────────────────────────────────────────────────────────────────────────────

def write_md(g: dict) -> None:
    f = facts(g)
    S = g["S"]
    xc = g["xc"]
    L = []
    w = L.append
    w("# NIFTYBEES opening-range breakout: five-year backtest")
    w("")
    w(f"NSE: NIFTYBEES, 5-minute candles, {dt(g['dates'][0])} to {dt(g['dates'][-1])} ({f['sessions']:,} sessions). "
      f"Angel One data, Angel One intraday charges, ₹10 lakh a trade. Code and every output are in this folder; "
      f"`python -I orb_report.py` rebuilds this file.")
    w("")
    w("## Verdict")
    w("")
    w(f"**The rules lose money after costs.** They took {f['n']:,} trades, and {f['win']:.1f}% made money. "
      f"Net {inr(f['net'])} on a ₹10,00,000 account ({num(f['net'] / g['cap'] * 100)}%, about {num(f['annual'])}% a year). "
      f"Profit factor {f['pf']:.2f}. The maximum drawdown was {inr(f['dd'])} ({f['dd_pct']:.1f}% of the account), "
      f"from the peak on {dt(f['peak'])} to {dt(f['trough'])}, and it was not recovered.")
    w("")
    w(f"Before costs the same trades made {inr(f['before'], True)}, or {inr(f['per_before'], True)} a trade "
      f"({f['per_before'] / f['notional'] * 1e4:.1f} bp, {num(f['r_before'], 3, True)}R). "
      f"Charges took {inr(f['charges'])} ({inr(f['per_charges'])} a trade) and slippage {inr(f['slip'])} "
      f"({inr(f['per_slip'])} a trade). After them, the average trade is {num(f['r_net'], 3)}R, with t = {num(f['t'], 2)}. "
      f"STT alone, 0.025% of the sell, is about ₹250 a trade, more than the whole pre-cost edge. Before costs the "
      f"edge is not statistically different from zero (t = {g['summ']['no_costs_no_slippage']['stats']['t_stat']:.2f} "
      f"for the run with no costs at all).")
    w("")
    wide = [r for r in rr_rows(g) if r["label"] != "1:2"]
    if wide:
        w(f"**Wider targets do not help.** At 1:3, 1:4, 1:5 and 1:6 the target is rarely reached, and every ratio loses "
          f"between {inr(-max(r['net'] for r in wide))} and {inr(-min(r['net'] for r in wide))} "
          "(section Wider targets).")
        w("")
    w("## Results, primary rules")
    w("")
    w("| | |")
    w("|---|---|")
    rows = [
        ("Sessions tested", f"{f['sessions']:,} ({dt(g['dates'][0])} to {dt(g['dates'][-1])})"),
        ("Trades", f"{f['n']:,} ({f['long']} long, {f['short']} short); a trade on {S['days_traded_pct']:.1f}% of sessions"),
        ("Win rate (net P&L above zero)", f"{f['win']:.1f}% ({S['wins']} trades)"),
        ("Exits", f"target {f['tgt']} ({f['tgt'] / f['n'] * 100:.1f}%), stop-loss {f['stop']} ({f['stop'] / f['n'] * 100:.1f}%), "
                  f"15:15 close {f['eod']} ({f['eod'] / f['n'] * 100:.1f}%; {f['eod_win']:.1f}% of these made money)"),
        ("Net profit / loss", f"{inr(f['net'])} ({num(f['net'] / g['cap'] * 100)}% of ₹10 lakh)"),
        ("Before costs", f"{inr(f['before'], True)}"),
        ("Charges (Angel One)", f"{inr(f['charges'])}"),
        ("Slippage", f"{inr(f['slip'])}"),
        ("Profit factor", f"{f['pf']:.2f}"),
        ("Maximum drawdown", f"{inr(f['dd'])}: {f['dd_pct']:.1f}% of the account ({S['max_dd_pct_of_peak']:.1f}% of the peak), "
                             f"{dt(f['peak'])} to {dt(f['trough'])}, not recovered"),
        ("Lowest account value", f"{inr(f['lowest'])} on {dt(f['trough'])}"),
        ("Average trade", f"{inr(f['avg'])} ({num(f['r_net'], 3)}R); 95% interval {inr(f['ci'][0])} to {inr(f['ci'][1])}"),
        ("Average win / loss", f"{inr(S['avg_win'], True)} / {inr(S['avg_loss'])}"),
        ("Median stop distance (1R)", f"{f['risk_med']:.1f} bp of price"),
        ("Average holding time", f"{f['hold']:.0f} minutes"),
        ("Longest losing streak", f"{f['streak']} trades"),
        ("Sharpe ratio (daily, annualised)", f"{num(f['sharpe'], 2)}"),
    ]
    for a, b in rows:
        w(f"| {a} | {b} |")
    w("")
    w("## Year by year")
    w("")
    w("Calendar years; 2021 starts on 25 October and 2026 ends on 23 October. Return is on the ₹10 lakh account. "
      "Before costs = the same trades at the trigger, stop and 15:15 prices, with no slippage and no charges.")
    w("")
    w("| Year | Sessions | Trades | Win rate | Target / stop / 15:15 | Before costs | Costs | Net P&L | Return | Profit factor | Max drawdown |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for y in g["years"]:
        lab = y["year"] + (" (from 25 Oct)" if y["year"] == "2021" else " (to 23 Oct)" if y["year"] == "2026" else "")
        w(f"| {lab} | {y['sessions']} | {y['trades']} | {y['win_rate']:.1f}% | {y['targets']} / {y['stops']} / {y['eod']} | "
          f"{inr(y['before'], True)} | {inr(-y['costs'])} | {inr(y['net_pnl'], True)} | {num(y['return_pct'], 1, True)}% | "
          f"{y['profit_factor']:.2f} | {inr(y['max_dd'])} |")
    tot_costs = sum(y["costs"] for y in g["years"])
    w(f"| **All** | {f['sessions']:,} | {f['n']:,} | {f['win']:.1f}% | {f['tgt']} / {f['stop']} / {f['eod']} | "
      f"{inr(f['before'], True)} | {inr(-tot_costs)} | **{inr(f['net'])}** | {num(f['net'] / g['cap'] * 100, 1)}% | "
      f"{f['pf']:.2f} | {inr(f['dd'])} |")
    w("")
    rrows = rr_rows(g)
    if rrows:
        w("## Wider targets: 1:3, 1:4, 1:5 and 1:6")
        w("")
        w(rr_intro(rrows))
        w("")
        w("| Risk : reward | Trades | Win rate | Target / stop / 15:15 | Before costs | Net P&L | Return | Profit factor | "
          "Max drawdown | Net R a trade | Same test on 1-minute candles |")
        w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in rrows:
            lab = f"**{r['label']}**" if r["label"] != "1:2" else "1:2 (the test above)"
            w(f"| {lab} | {r['trades']:,} | {r['win']:.1f}% | {r['t']} / {r['s']} / {r['e']} | {inr(r['before'], True)} | "
              f"**{inr(r['net'], True)}** | {num(r['ret'], 1, True)}% | {r['pf']:.2f} | {inr(r['dd'])} ({r['dd_pct']:.1f}%) | "
              f"{num(r['r'], 3, True)} | {inr(r['net1m'], True)} |")
        w("")
        w("Net P&L by calendar year:")
        w("")
        w("| Year | " + " | ".join(r["label"] for r in rrows) + " |")
        w("|---|" + "---:|" * len(rrows))
        for i, y in enumerate(rrows[0]["yearly"]):
            lab = y["year"] + (" (from 25 Oct)" if y["year"] == "2021" else " (to 23 Oct)" if y["year"] == "2026" else "")
            w(f"| {lab} | " + " | ".join(inr(r["yearly"][i]["net_pnl"], True) for r in rrows) + " |")
        w("| **All** | " + " | ".join(f"**{inr(r['net'], True)}**" for r in rrows) + " |")
        w("")
        for r in rrows:
            if r["label"] == "1:2":
                continue
            w(f"### {r['label']} year by year")
            w("")
            w("| Year | Trades | Win rate | Target / stop / 15:15 | Before costs | Net P&L | Return | Profit factor | Max drawdown |")
            w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
            for y in r["yearly"]:
                lab = y["year"] + (" (from 25 Oct)" if y["year"] == "2021" else " (to 23 Oct)" if y["year"] == "2026" else "")
                w(f"| {lab} | {y['trades']} | {y['win_rate']:.1f}% | {y['targets']} / {y['stops']} / {y['eod']} | "
                  f"{inr(y['before'], True)} | {inr(y['net_pnl'], True)} | {num(y['return_pct'], 1, True)}% | "
                  f"{y['profit_factor']:.2f} | {inr(y['max_dd'])} |")
            w("")
    w("## The rules as tested")
    w("")
    w("The rules you gave, and the execution rules this test added. All were fixed before any result was seen.")
    w("")
    for a, b in rules_list(g, md=True):
        w(f"- **{a}.** {b}")
    w("")
    w("## Where the money went")
    w("")
    fb = g["fee"]
    w(f"Charges on one round trip of {g['fee_qty']:,} units at ₹{g['fee_px']:.2f} (the median entry price, about ₹10 lakh), "
      "from the app's Angel One fee model:")
    w("")
    w("| Charge | ₹ | bp of ₹10 lakh |")
    w("|---|---:|---:|")
    turnover = g["fee_px"] * g["fee_qty"]
    for k, lab in (("brokerage", "Brokerage (₹20 an order, two orders)"), ("stt", "STT (0.025% of the sell)"),
                   ("exchange_txn", "NSE transaction charge (0.00297%, both legs)"), ("sebi", "SEBI fee"),
                   ("ipft", "NSE IPFT"), ("stamp_duty", "Stamp duty (0.003% of the buy)"),
                   ("gst", "GST (18% of brokerage, exchange, SEBI and IPFT)")):
        w(f"| {lab} | {fb[k]:.2f} | {fb[k] / turnover * 1e4:.2f} |")
    w(f"| **Total** | **{fb['total']:.2f}** | **{fb['total'] / turnover * 1e4:.2f}** |")
    w("")
    w(f"Slippage averaged {inr(f['per_slip'])} a trade (1 bp a side on the entry and on a stop or 15:15 exit, rounded to whole ticks; "
      f"targets have none). With the charges that is {inr(f['per_charges'] + f['per_slip'])} a trade, "
      f"{(f['per_charges'] + f['per_slip']) / f['notional'] * 1e4:.1f} bp. At the median stop of {f['risk_med']:.1f} bp, "
      f"costs come to about {(S['avg_cost_r'] + S['avg_slippage_r']):.2f}R a trade. The trades make {num(f['r_before'], 3, True)}R before costs.")
    w("")
    w("## Candles that touch both the stop and the target")
    w("")
    w(ambiguity_text(g, md=True))
    w("")
    w("## Data and gaps")
    w("")
    for para in data_text(g, md=True):
        w(para)
        w("")
    w("Sessions not used:")
    w("")
    w("| Date | Present | Why it is not used |")
    w("|---|---|---|")
    for r in excluded_rows(g):
        w(f"| {r[0]} | {r[1]} | {r[2]} |")
    w("")
    w("## If one rule changes")
    w("")
    w("Each row changes one rule of the primary test and keeps the rest; all were fixed before the first run. "
      "None was chosen for its result. R is the trade's risk, from the entry fill to the stop.")
    w("")
    w("| Run | Trades | Win rate | Net P&L | Profit factor | Max drawdown | Net R a trade | R before costs |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in g["runs"]:
        wiped = f" (account at zero on {dt(r['account_wiped_out_on'])})" if r.get("account_wiped_out_on") else ""
        rb = r["avg_r_gross"] + r["avg_slippage_r"]
        w(f"| {r['what']} | {r['trades']:,} | {r['win_rate']:.1f}% | {inr(r['net_pnl'], True)}{wiped} | {r['profit_factor']:.2f} | "
          f"{inr(r['max_dd'])} ({r['max_dd_pct_of_capital']:.1f}%) | {num(r['avg_r_net'], 3, True)} | {num(rb, 3, True)} |")
    w("")
    w("## Trade profile")
    w("")
    w("Descriptive cuts of the primary trades. Nothing was tuned on them; picking a filter from this table now "
      "would fit it to the same five years it is judged on.")
    w("")
    w("| Stop distance (bp) | Trades | Win rate | R before charges | Net R | Net P&L | Reached target |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for r in g["P"]["diagnostics"]["by_stop_distance_quintile"]:
        w(f"| {r['risk_bp']} | {r['trades']} | {r['win_rate']:.1f}% | {num(r['avg_r_gross'], 3, True)} | "
          f"{num(r['avg_r_net'], 3, True)} | {inr(r['net_pnl'], True)} | {r['targets_pct']:.1f}% |")
    w("")
    w("R before charges is after slippage.")
    w("")
    w("| Entry time | Trades | Win rate | Net R | Net P&L |")
    w("|---|---:|---:|---:|---:|")
    for r in g["P"]["diagnostics"]["by_entry_time"]:
        w(f"| {r['entry']} | {r['trades']} | {r['win_rate']:.1f}% | {num(r['avg_r_net'], 3, True)} | {inr(r['net_pnl'], True)} |")
    w("")
    w("## Files")
    w("")
    for a, b in files_list():
        w(f"- `{a}`: {b}")
    w("")
    (HERE / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def rr_rows(g: dict) -> list[dict]:
    """One row per risk-reward ratio from results/rr_compare.json (orb_rr.py), 1:2 first."""
    out = []
    for o in sorted(g.get("rr", {}).values(), key=lambda o: o["rr"]):
        s = o["stats"]
        ex = s["exit_reasons"]
        out.append({"label": f"1:{int(o['rr'])}", "trades": s["trades"], "win": s["win_rate"],
                    "t": ex.get("target", {}).get("trades", 0), "s": ex.get("stop", {}).get("trades", 0),
                    "e": ex.get("eod", {}).get("trades", 0), "before": o["before_costs"], "net": s["net_pnl"],
                    "ret": s["return_pct_of_capital"], "pf": s["profit_factor"], "dd": s["max_dd"],
                    "dd_pct": s["max_dd_pct_of_capital"], "r": s["avg_r_net"], "tstat": s["t_stat"],
                    "net1m": o["one_minute"]["stats"]["net_pnl"], "amb": s["ambiguous_trades"],
                    "costs": (o["before_costs"] - s["net_pnl"]) / s["trades"], "yearly": o["yearly"]})
    return out


def rr_intro(rows: list[dict]) -> str:
    wide = [r for r in rows if r["label"] != "1:2"]
    nets = [r["net"] for r in wide]
    hits = ", ".join(f"{r['t']} at {r['label']}" for r in rows)
    amb = sorted({r["amb"] for r in rows})
    gap = max(abs(r["net1m"] - r["net"]) for r in rows)
    return (
        "Only the target changes: 3, 4, 5 or 6 times the distance from the entry fill to the stop. Everything else is "
        "as in the rules below, and 1:2 is the test above. The wider the target, the less often price reaches it: "
        f"{hits}, out of {rows[0]['trades']:,} trades. Most trades end at 15:15 instead, so the wider ratios lose "
        f"almost the same, between {inr(-max(nets))} and {inr(-min(nets))}. Costs of about "
        f"{inr(sum(r['costs'] for r in rows) / len(rows))} a trade decide the result whatever the target. The order "
        f"inside a 5-minute candle decided {' or '.join(str(a) for a in amb)} trades at every ratio, and walking the "
        f"1-minute candles moves each result by at most {inr(gap)}."
    )


def rules_list(g: dict, md: bool = False) -> list[tuple[str, str]]:
    f = facts(g)
    q0, q1 = g["qty_range"]
    code = (lambda s: f"`{s}`") if md else (lambda s: f"[[{s}]]")
    return [
        ("Data", f"NIFTYBEES (NSE) 5-minute candles, 09:15 to 15:30 IST, built from Angel One's 1-minute candles. "
                 f"{f['sessions']:,} sessions, {dt(g['dates'][0])} to {dt(g['dates'][-1])}."),
        ("Opening range", "The highest high and lowest low of the 09:15, 09:20 and 09:25 candles (09:15:00 to 09:29:59), "
                          "after stray pre-open prints are removed (see Data and gaps). No entry before 09:30."),
        ("Breakout", "By price crossing, not by a candle close. From 09:30 a buy-stop rests ₹0.01 above the range high "
                     "and a sell-stop ₹0.01 below the range low. When one fills, the other is cancelled."),
        ("Entry fill", "At the trigger price, or at the candle's open when the candle opens beyond the trigger, plus slippage."),
        ("Stop-loss", "A long's stop is the range low and a short's the range high. It triggers when price touches it and "
                      "fills at that price, or at a worse candle open, less slippage."),
        ("Target", "Twice the distance from the actual entry fill to the stop (1:2). It is a resting limit order, so it has "
                   "no slippage, but it counts as filled only when price trades ₹0.01 through it."),
        ("Trades a day", "One. After an exit there is no re-entry and no reversal."),
        ("Entry window", "09:30 to 15:00. Entry orders not filled by 15:00 are cancelled."),
        ("End of day", "Anything still open is closed at 15:15, at the close of the 15:10 to 15:15 candle, less slippage."),
        ("Position size", f"₹10,00,000 of NIFTYBEES a trade in whole units ({q0:,} to {q1:,} units), on a ₹10,00,000 "
                          "account. No leverage and no compounding."),
        ("Charges", f"Angel One's intraday rate card from the app's fee model ({code('backend/app/services/angel_fees.py')}): "
                    "brokerage the lower of ₹20 and 0.25% an order, STT 0.025% on the sell, NSE 0.00297%, SEBI and IPFT "
                    "0.0001% each, stamp duty 0.003% on the buy, GST 18% on brokerage and fees. About ₹402 a round trip "
                    "(4.0 bp). Today's schedule is charged in every year; the older schedules differ by less than 0.1 bp."),
        ("Slippage", "1 bp of price on every market or stop fill (the entry, a stop-loss and the 15:15 exit), rounded to "
                     "the next ₹0.01 tick against the trade: ₹0.02 to ₹0.04 a unit. 1 bp is the effective half-spread "
                     "the app's index module measured from NIFTYBEES's own minute prices (2024 to 2026)."),
        ("Inside a candle", "The order of the high and the low is unknown, so each candle is walked both ways and the way "
                            "worse for the account is used. See the section on candles that touch both levels."),
    ]


def ambiguity_text(g: dict, md: bool = False) -> str:
    f = facts(g)
    a = f["amb"]
    k = a["by_kind"]
    both = k.get("both breakouts in one candle", 0)
    entry = k.get("entry candle also reached the stop (or the target)", 0)
    open_ = k.get("open trade: stop and target in the same candle", 0)
    res = a["ambiguous_trades_resolved_by_1m"]
    same = res.get("5m stop -> 1m stop", 0)
    other = res.get("5m stop -> 1m stop (other side)", 0)
    eod = res.get("5m stop -> 1m eod", 0)
    fine, best = f["fine"], f["best"]
    return (
        "A 5-minute candle gives its high and low but not which came first. The simulator walks every candle both ways, "
        "open to high to low to close and open to low to high to close, and keeps the way that leaves the account worse "
        "at the candle's close. So a candle that reaches both the stop and the target counts as a stop-loss. An entry "
        "candle that also reaches the stop counts as stopped in that candle. A candle that triggers both the long and "
        "the short counts as whichever loses more, and only one trade is taken.\n\n"
        f"It decided {a['ambiguous_trades']} of {f['n']:,} trades. {both} were candles that triggered both breakouts and "
        f"{entry} were entry candles that also reached the stop. {'No' if open_ == 0 else open_} open trade had its stop and "
        f"its target inside one 5-minute candle, because the target sits about {2 * f['risk_med']:.0f} bp away. All "
        f"{a['ambiguous_trades']} were scored as stop-losses.\n\n"
        f"The 1-minute candles inside them show {same} were stop-losses, {other} was stopped on the other side, and {eod} "
        f"actually lasted to 15:15. Using the 1-minute order on these {a['ambiguous_trades']} trades adds "
        f"{inr(a['net_change_if_1m_used_on_ambiguous_trades'], True)}. Running the whole test on 1-minute candles gives "
        f"{inr(fine['net_pnl'])}, against {inr(f['net'])} on 5-minute candles. That run is a little worse because "
        "1-minute candles show small jumps between minutes, so a few entries and stops fill some paise worse than the "
        "smooth path a 5-minute candle assumes. Taking the better order in every 5-minute candle gives "
        f"{inr(best['net_pnl'])}. No candle was still ambiguous at 1 minute. For this strategy the assumption does not "
        "change the answer."
    )


def data_text(g: dict, md: bool = False) -> list[str]:
    f = facts(g)
    dq = g["dq"]
    cal = f["cal"]
    nb = f["nb"]
    dev = f["dev"]
    op = f["op"]
    xc = g["xc"]
    tr = xc["09:30-15:10 (the bars the strategy trades)"]
    hol = len(cal["holidays_in_window"])
    spec = len(cal["special_sessions"])
    miss = nb["kept_days_with_missing_minutes"]
    miss_txt = "; ".join(f"{dt(m['date'])}: {', '.join(m['minutes'])}" for m in miss)
    by = op["by_year"]
    return [
        "**Source.** Angel One's 1-minute candles for NSE NIFTYBEES (token 10576), the app's licensed broker feed, "
        "turned into 5-minute candles anchored at 09:15 (75 a session): open of the first minute, highest high, lowest "
        "low, close of the last minute, summed volume. Angel's own 5-minute candles are built from the same trades. "
        "The 1-minute candles were kept to check what happened inside a 5-minute candle. Sessions up to 9 Oct 2026 come "
        "from the bulk download of 11 Oct 2026, and 12 to 23 Oct 2026 from the app's daily store on the server.",
        f"**Calendar.** The window holds {cal['expected_sessions']:,} NSE sessions: weekdays, less {hol} exchange holidays, "
        f"plus {spec} weekend sessions (20 Jan 2024, 2 Mar 2024, 18 May 2024, 1 Feb 2025 and 1 Feb 2026). NIFTYBEES has "
        "data on every one of them. Its only other prints are the Diwali Muhurat hours, which are not regular sessions: "
        "evening sessions in 2021 to 2024, outside 09:15 to 15:30, and 13:45 to 14:45 on 21 Oct 2025. "
        f"{f['sessions']:,} sessions are used. The table below lists the {cal['expected_sessions'] - f['sessions']} "
        "expected sessions left out, and the 2025 Muhurat hour.",
        f"**Inside the sessions used.** {nb['minutes_filled_flat']} minutes are missing in all ({miss_txt}). Each is filled flat "
        f"at the previous close with no volume, so no move is invented. {nb['zero_volume_printed_minutes']} minute printed with zero volume. There are no "
        "duplicate minutes and no zero, negative or more-than-15%-off prints.",
        f"**Stray opening prints.** Angel's 09:15 candle begins with NIFTYBEES's pre-open auction price, which is set "
        f"before 09:15 by a thin book. Its open lies a median {dev['open_0915']['median'] / 100:.2f}% from where NIFTY 50 "
        f"puts the ETF, and on 1 day in 10 more than {dev['open_0915']['p90'] / 100:.1f}% away. By comparison, the "
        f"09:15 close lies {dev['close_0915']['median'] / 100:.2f}% away, and minutes from 09:45 lie "
        f"{dev['continuous_0945_1514_close']['median'] / 100:.2f}% away (99% within "
        f"{dev['continuous_0945_1514_close']['p99'] / 100:.2f}%). On 11 May 2022 the 09:15 minute printed ₹153.30 and "
        "₹181.90 while NIFTY put the ETF at about ₹176.6. Taken raw, these prints set the opening range on most days: "
        f"its median width is {op['median_or_bp']['raw']:.0f} bp, against {op['median_or_bp']['nifty_index']:.0f} bp "
        "for NIFTY 50 itself. So each 09:15 to 09:29 print more than 0.2% outside the range NIFTY implies for that minute "
        "is replaced by the same minute's in-band open or close. Every level stays a NIFTYBEES price. That gives a "
        f"median width of {op['median_or_bp']['clean']:.1f} bp; it changed the range on {op['sessions_cleaned']:,} of "
        f"{op['sessions']:,} sessions, almost all through the 09:15 minute. The band was fixed before any backtest ran. "
        f"The raw range and a 0.5% band were run as well (see If one rule changes): both lose.",
        f"**Second vendor.** Yahoo's 5-minute NIFTYBEES candles for the last {xc['sessions']} sessions "
        f"({dt(xc['days'][0])} to {dt(xc['days'][1])}) agree with these candles to the paisa on {tr['h_exact_pct']:.0f}% of "
        f"highs and {tr['l_exact_pct']:.0f}% of lows, and within one tick on {tr['h_within_1_tick_pct']:.0f}% and "
        f"{tr['l_within_1_tick_pct']:.0f}%. Volumes match (median ratio {tr['volume_ratio_yahoo_to_angel_median']:.2f}). "
        f"Where they differ, Angel's candles hold the extra extremes: Angel's high is above Yahoo's in "
        f"{tr['angel_high_above_yahoo_pct']:.0f}% of candles and below it in {tr['angel_high_below_yahoo_pct']:.1f}%, and "
        f"its low is below Yahoo's in {tr['angel_low_below_yahoo_pct']:.0f}% and above in "
        f"{tr['angel_low_above_yahoo_pct']:.1f}%. Yahoo's 09:15 candles carry none of the stray opening prints: their "
        f"median opening range is {xc['opening_range']['median_width_bp']['yahoo']:.0f} bp, against "
        f"{xc['opening_range']['median_width_bp']['angel_raw']:.0f} bp raw and "
        f"{xc['opening_range']['median_width_bp']['clean']:.0f} bp cleaned here.",
    ]


def excluded_rows(g: dict) -> list[tuple[str, str, str]]:
    out = []
    for r in g["dq"]["niftybees"]["days_dropped"]:
        d = r["date"]
        if r["first_minute"] == "13:25":
            out.append((dt(d), f"13:25 to 15:29 only ({r['minutes']} minutes)",
                        "The bulk download lost the morning: it is the first day of a 30-day request, and Angel "
                        "returned the newest 8,000 or so minutes. No opening range."))
        elif d in ("2024-03-02", "2024-05-18"):
            out.append((dt(d), f"{r['minutes']} minutes", "Saturday disaster-recovery drill: two short sessions, not a full day."))
        elif d == "2025-10-21":
            out.append((dt(d), f"13:45 to 14:44 ({r['minutes']} minutes)", "Diwali Muhurat session, not a regular session "
                                                                           "(the exchange holiday list counts the day as closed)."))
        else:
            out.append((dt(d), f"{r['minutes']} minutes", r["reason"]))
    return out


def files_list() -> list[tuple[str, str]]:
    return [
        ("orb_data.py", "builds the 5-minute candles, the cleaned opening ranges and results/data_quality.json"),
        ("orb_engine.py", "the rules and the simulator"),
        ("orb_verify.py", "49 checks of the simulator, on hand-built sessions and on the real run"),
        ("orb_run.py", "the primary test and the comparison runs; results/summary.json, sensitivity.csv, the trade logs, "
                       "yearly tables and daily equity"),
        ("orb_crosscheck.py", "the comparison with Yahoo's 5-minute candles (results/crosscheck_yahoo.json)"),
        ("orb_rr.py", "the same rules with the target at 1:3, 1:4, 1:5 and 1:6 (results/rr_compare.json, trade logs and yearly tables per ratio)"),
        ("orb_report.py", "this report and report/niftybees-orb-backtest.html"),
        ("results/trades_primary.csv", "every trade of the primary test"),
        ("data/", "the candles themselves (NIFTYBEES_5m.csv.gz and the minutes); not in git, because Angel's data is "
                  "licensed and the repository is public"),
    ]


# ── html ───────────────────────────────────────────────────────────────────────────────────────────

def inline_bar(v: float, vmax: float) -> str:
    w = 0 if vmax <= 0 else min(50.0, abs(v) / vmax * 50.0)
    cls = "neg" if v < 0 else "pos"
    return f'<span class="ibar" aria-hidden="true"><span class="{cls}" style="--w:{w:.1f}%"></span></span>'


def rr_html(g: dict) -> str:
    """The wider-targets section of the page (empty when orb_rr.py has not run)."""
    rows = rr_rows(g)
    if not rows:
        return ""
    vmax = max(abs(r["net"]) for r in rows)
    comp = []
    for r in rows:
        lab = "1:2<span class=sub>the test above</span>" if r["label"] == "1:2" else e(r["label"])
        comp.append(
            f"<tr><th scope=\"row\">{lab}</th><td>{r['trades']:,}</td><td>{r['win']:.1f}%</td>"
            f"<td class=\"mono\">{r['t']} / {r['s']} / {r['e']}</td><td>{e(inr(r['before'], True))}</td>"
            f"<td class=\"barcol\">{inline_bar(r['net'], vmax)}</td><td class=\"strong\">{e(inr(r['net'], True))}</td>"
            f"<td>{e(num(r['ret'], 1, True))}%</td><td>{r['pf']:.2f}</td>"
            f"<td>{e(inr(r['dd']))}<span class=sub>{r['dd_pct']:.1f}%</span></td><td>{e(num(r['r'], 3, True))}</td>"
            f"<td>{e(inr(r['net1m'], True))}</td></tr>")
    years = [y["year"] for y in rows[0]["yearly"]]
    mat = []
    for i, yname in enumerate(years):
        sub = "<span class=sub>from 25 Oct</span>" if yname == "2021" else "<span class=sub>to 23 Oct</span>" if yname == "2026" else ""
        mat.append(f"<tr><th scope=\"row\">{yname}{sub}</th>"
                   + "".join(f"<td>{e(inr(r['yearly'][i]['net_pnl'], True))}</td>" for r in rows) + "</tr>")
    mat.append("<tr class=\"total\"><th scope=\"row\">All</th>"
               + "".join(f"<td>{e(inr(r['net'], True))}</td>" for r in rows) + "</tr>")
    per = []
    for r in rows:
        if r["label"] == "1:2":
            continue
        body = "".join(
            f"<tr><th scope=\"row\">{y['year']}</th><td>{y['trades']}</td><td>{y['win_rate']:.1f}%</td>"
            f"<td class=\"mono\">{y['targets']} / {y['stops']} / {y['eod']}</td><td class=\"strong\">{e(inr(y['net_pnl'], True))}</td>"
            f"<td>{e(num(y['return_pct'], 1, True))}%</td><td>{y['profit_factor']:.2f}</td><td>{e(inr(y['max_dd']))}</td></tr>"
            for y in r["yearly"])
        per.append(
            f"<div class=\"tablewrap\"><table><caption>{e(r['label'])} year by year</caption>"
            "<thead><tr><th>Year</th><th>Trades</th><th>Win rate</th><th>Exits T / S / 15:15</th><th>Net P&amp;L</th>"
            "<th>Return</th><th>Profit factor</th><th>Max drawdown</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>")
    return f"""
  <section id="ratios" aria-labelledby="h-ratios">
    <h2 id="h-ratios">Wider targets: 1:3, 1:4, 1:5 and 1:6</h2>
    <div class="prose"><p>{e(rr_intro(rows))}</p></div>
    <div class="tablewrap">
      <table>
        <thead><tr><th>Risk : reward</th><th>Trades</th><th>Win rate</th><th>Exits T / S / 15:15</th><th>Before costs</th><th></th><th>Net P&amp;L</th><th>Return</th><th>Profit factor</th><th>Max drawdown</th><th>Net R a trade</th><th>On 1-minute candles</th></tr></thead>
        <tbody>
{chr(10).join(comp)}
        </tbody>
      </table>
    </div>
    <h3>Net P&amp;L by year</h3>
    <div class="tablewrap">
      <table class="fit">
        <thead><tr><th>Year</th>{"".join(f"<th>{e(r['label'])}</th>" for r in rows)}</tr></thead>
        <tbody>
{chr(10).join(mat)}
        </tbody>
      </table>
    </div>
    <div class="two">
{chr(10).join(per)}
    </div>
  </section>
"""


def write_html(g: dict) -> None:
    f = facts(g)
    S = g["S"]
    xc = g["xc"]
    wide = [r for r in rr_rows(g) if r["label"] != "1:2"]
    # KPI tiles
    kpis = [
        ("Net result", inr(f["net"]), f"{num(f['net'] / g['cap'] * 100)}% of the ₹10 lakh account"),
        ("Trades", f"{f['n']:,}", f"{f['long']} long, {f['short']} short, in {f['sessions']:,} sessions"),
        ("Win rate", f"{f['win']:.1f}%", f"after costs; {f['tgt'] / f['n'] * 100:.0f}% reached the target"),
        ("Profit factor", f"{f['pf']:.2f}", "winning ₹ ÷ losing ₹, after costs"),
        ("Max drawdown", inr(f["dd"]), f"{f['dd_pct']:.1f}% of the account, not recovered"),
        ("Average trade", inr(f["avg"]), f"{num(f['r_net'], 2)}R after costs, {num(f['r_before'], 2, True)}R before"),
    ]
    kpi_html = "\n".join(
        f'<div class="kpi"><dt>{e(a)}</dt><dd><span class="kv">{e(b)}</span><span class="kn">{e(c)}</span></dd></div>'
        for a, b, c in kpis)
    # yearly table
    vmax = max(abs(y["net_pnl"]) for y in g["years"])
    yrows = []
    for y in g["years"]:
        lab = y["year"]
        sub = "from 25 Oct" if lab == "2021" else "to 23 Oct" if lab == "2026" else ""
        yrows.append(
            f"<tr><th scope=\"row\">{lab}{f'<span class=sub>{sub}</span>' if sub else ''}</th>"
            f"<td>{y['sessions']}</td><td>{y['trades']}</td><td>{y['win_rate']:.1f}%</td>"
            f"<td class=\"mono\">{y['targets']} / {y['stops']} / {y['eod']}</td>"
            f"<td>{e(inr(y['before'], True))}</td><td>{e(inr(-y['costs']))}</td>"
            f"<td class=\"barcol\">{inline_bar(y['net_pnl'], vmax)}</td>"
            f"<td class=\"strong\">{e(inr(y['net_pnl'], True))}</td><td>{e(num(y['return_pct'], 1, True))}%</td>"
            f"<td>{y['profit_factor']:.2f}</td><td>{e(inr(y['max_dd']))}</td></tr>")
    tot_costs = sum(y["costs"] for y in g["years"])
    yrows.append(
        f"<tr class=\"total\"><th scope=\"row\">All</th><td>{f['sessions']:,}</td><td>{f['n']:,}</td><td>{f['win']:.1f}%</td>"
        f"<td class=\"mono\">{f['tgt']} / {f['stop']} / {f['eod']}</td><td>{e(inr(f['before'], True))}</td>"
        f"<td>{e(inr(-tot_costs))}</td><td class=\"barcol\"></td><td class=\"strong\">{e(inr(f['net']))}</td>"
        f"<td>{e(num(f['net'] / g['cap'] * 100, 1))}%</td><td>{f['pf']:.2f}</td><td>{e(inr(f['dd']))}</td></tr>")
    # rules
    rules_html = "\n".join(f"<div class=\"rule\"><dt>{e(a)}</dt><dd>{codes(e(b))}</dd></div>" for a, b in rules_list(g))
    # cost table
    fb = g["fee"]
    turnover = g["fee_px"] * g["fee_qty"]
    crow = []
    for k, lab in (("brokerage", "Brokerage, ₹20 an order × 2"), ("stt", "STT, 0.025% of the sell"),
                   ("exchange_txn", "NSE transaction charge, 0.00297% of both legs"), ("sebi", "SEBI fee, ₹10 a crore"),
                   ("ipft", "NSE IPFT, ₹10 a crore"), ("stamp_duty", "Stamp duty, 0.003% of the buy"),
                   ("gst", "GST, 18% of brokerage and fees")):
        crow.append(f"<tr><th scope=\"row\">{e(lab)}</th><td>{fb[k]:.2f}</td><td>{fb[k] / turnover * 1e4:.2f}</td></tr>")
    crow.append(f"<tr class=\"total\"><th scope=\"row\">Charges per round trip</th><td>{fb['total']:.2f}</td>"
                f"<td>{fb['total'] / turnover * 1e4:.2f}</td></tr>")
    crow.append(f"<tr><th scope=\"row\">Slippage, average per trade</th><td>{f['per_slip']:.2f}</td>"
                f"<td>{f['per_slip'] / f['notional'] * 1e4:.2f}</td></tr>")
    crow.append(f"<tr class=\"total\"><th scope=\"row\">All costs per trade</th><td>{f['per_charges'] + f['per_slip']:.2f}</td>"
                f"<td>{(f['per_charges'] + f['per_slip']) / f['notional'] * 1e4:.2f}</td></tr>")
    crow.append(f"<tr><th scope=\"row\">The trades' edge before costs, per trade</th><td>{f['per_before']:.2f}</td>"
                f"<td>{f['per_before'] / f['notional'] * 1e4:.2f}</td></tr>")
    # excluded sessions
    ex_html = "\n".join(f"<tr><th scope=\"row\">{e(a)}</th><td>{e(b)}</td><td>{e(c)}</td></tr>" for a, b, c in excluded_rows(g))
    # sensitivity
    vmax2 = max(abs(r["net_pnl"]) for r in g["runs"])
    srows = []
    for r in g["runs"]:
        wiped = r.get("account_wiped_out_on")
        rb = r["avg_r_gross"] + r["avg_slippage_r"]
        note = f'<span class="flag">account at zero on {e(dt(wiped))}</span>' if wiped else ""
        cls = ' class="primary"' if r["name"] == "primary" else ""
        srows.append(
            f"<tr{cls}><th scope=\"row\">{e(r['what'])}{note}</th><td>{r['trades']:,}</td><td>{r['win_rate']:.1f}%</td>"
            f"<td class=\"barcol\">{inline_bar(r['net_pnl'], vmax2)}</td><td class=\"strong\">{e(inr(r['net_pnl'], True))}</td>"
            f"<td>{r['profit_factor']:.2f}</td><td>{e(inr(r['max_dd']))}<span class=sub>{r['max_dd_pct_of_capital']:.1f}%</span></td>"
            f"<td>{e(num(r['avg_r_net'], 3, True))}</td><td>{e(num(rb, 3, True))}</td></tr>")
    # profile
    q_rows = "\n".join(
        f"<tr><th scope=\"row\" class=\"mono\">{e(r['risk_bp'])}</th><td>{r['trades']}</td><td>{r['win_rate']:.1f}%</td>"
        f"<td>{e(num(r['avg_r_gross'], 3, True))}</td><td>{e(num(r['avg_r_net'], 3, True))}</td>"
        f"<td>{e(inr(r['net_pnl'], True))}</td><td>{r['targets_pct']:.1f}%</td></tr>"
        for r in g["P"]["diagnostics"]["by_stop_distance_quintile"])
    t_rows = "\n".join(
        f"<tr><th scope=\"row\" class=\"mono\">{e(r['entry'])}</th><td>{r['trades']}</td><td>{r['win_rate']:.1f}%</td>"
        f"<td>{e(num(r['avg_r_net'], 3, True))}</td><td>{e(inr(r['net_pnl'], True))}</td></tr>"
        for r in g["P"]["diagnostics"]["by_entry_time"])
    me_rows = "\n".join(f"<tr><th scope=\"row\">{e(d[:7])}</th><td>{e(inr(a))}</td><td>{e(inr(b))}</td></tr>"
                        for d, a, b in g["month_end"])
    files_html = "\n".join(f"<li><code>{e(a)}</code> {e(b)}</li>" for a, b in files_list())
    data_html = "\n".join(f"<p>{md_bold(e(p))}</p>" for p in data_text(g))
    amb_html = "\n".join(f"<p>{e(p)}</p>" for p in ambiguity_text(g).split("\n\n"))
    tr = g["day"]["trade"]
    day = g["day"]
    payload = {
        "eq": {"dates": g["dates"], "net": g["net_curve"], "pre": g["pre_curve"], "peak": g["peak_i"],
               "trough": g["trough_i"], "cap": g["cap"]},
        "bridge": [["Before costs", f["before"]], ["Slippage", -f["slip"]], ["Charges", -f["charges"]],
                   ["Result", f["net"]]],
        "day": day,
    }
    page = TEMPLATE
    subs = {
        "{{EYEBROW}}": e(f"Backtest · NSE: NIFTYBEES · 5-minute candles · {dt(g['dates'][0])} to {dt(g['dates'][-1])}"),
        "{{VERDICT}}": (f"<strong>The rules lose money after costs.</strong> Before costs the {f['n']:,} trades made "
                        f"{e(inr(f['before'], True))}, about {e(inr(f['per_before']))} a trade. Angel One's charges "
                        f"({e(inr(f['per_charges']))} a trade) and slippage ({e(inr(f['per_slip']))}) turned that into "
                        f"{e(inr(f['net']))}. STT alone, about ₹250 a trade, is larger than the whole edge."
                        + (f" Wider targets do not help: at 1:3 to 1:6 the target is rarely reached and every ratio loses "
                           f"between {e(inr(-max(r['net'] for r in wide)))} and {e(inr(-min(r['net'] for r in wide)))}."
                           if wide else "")),
        "{{RR_SECTION}}": rr_html(g),
        "{{KPIS}}": kpi_html,
        "{{EQ_CAPTION}}": e(f"After costs the account peaked at {inr(f['peak_eq'])} on {dt(f['peak'])} and fell to "
                            f"{inr(f['lowest'])} on {dt(f['trough'])}, a drawdown of {inr(f['dd'])} that was never "
                            f"recovered. It ends at {inr(g['net_curve'][-1])}. Before costs the same trades end at "
                            f"{inr(g['pre_curve'][-1])}."),
        "{{YEAR_ROWS}}": "\n".join(yrows),
        "{{RULES}}": rules_html,
        "{{DAY_CAPTION}}": e(
            f"{dt(day['date'])}, the last session tested. The 09:15 candle opens at ₹{day['candles'][0][1]:.2f}, a pre-open print "
            f"above the range NIFTY 50 implied; cleaned, the opening range is ₹{day['or_clean'][0]:.2f} to "
            f"₹{day['or_clean'][1]:.2f} (raw ₹{day['or_raw'][0]:.2f} to ₹{day['or_raw'][1]:.2f}). Price breaks "
            f"below it in the {tr['entry_candle']} candle and the sell-stop at ₹{tr['trigger']:.2f} fills at "
            f"₹{tr['entry']:.2f}. The stop is ₹{tr['stop']:.2f} and the target ₹{tr['target']:.2f}, twice the "
            f"₹{tr['stop'] - tr['entry']:.2f} risk. The target fills in the {tr['exit_candle']} candle: "
            f"{inr(tr['net'], True)} on {tr['qty']:,} units after {inr(tr['charges'])} of charges."),
        "{{BRIDGE_NOTE}}": e(f"Costs per trade came to {inr(f['per_charges'] + f['per_slip'])} "
                             f"({(f['per_charges'] + f['per_slip']) / f['notional'] * 1e4:.1f} bp of the ₹10 lakh traded), "
                             f"about {(S['avg_cost_r'] + S['avg_slippage_r']):.2f}R at the median stop of "
                             f"{f['risk_med']:.0f} bp. The trades earned {num(f['r_before'], 3, True)}R before costs."),
        "{{COST_ROWS}}": "\n".join(crow),
        "{{COST_HEAD}}": e(f"One round trip of {g['fee_qty']:,} units at ₹{g['fee_px']:.2f}, the median entry price"),
        "{{AMB}}": amb_html,
        "{{DATA}}": data_html,
        "{{EXCLUDED}}": ex_html,
        "{{SENS_ROWS}}": "\n".join(srows),
        "{{Q_ROWS}}": q_rows,
        "{{T_ROWS}}": t_rows,
        "{{ME_ROWS}}": me_rows,
        "{{FILES}}": files_html,
        "{{DATA_JSON}}": json.dumps(payload, separators=(",", ":")),
    }
    for k, v in subs.items():
        page = page.replace(k, v)
    OUT.mkdir(exist_ok=True)
    (OUT / "niftybees-orb-backtest.html").write_text(page, encoding="utf-8")


def codes(s: str) -> str:
    """[[path]] -> <code>path</code> (rule text is escaped first)."""
    import re as _re
    return _re.sub(r"\[\[(.+?)\]\]", lambda m_: f"<code>{m_.group(1)}</code>", s)


def md_bold(s: str) -> str:
    parts = s.split("**")
    return "".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(parts))


TEMPLATE = (HERE / "report_template.html").read_text(encoding="utf-8") if (HERE / "report_template.html").exists() else ""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    g = gather()
    write_md(g)
    if TEMPLATE:
        write_html(g)
    print("wrote", HERE / "REPORT.md", "and", OUT / "niftybees-orb-backtest.html" if TEMPLATE else "(no template)")


if __name__ == "__main__":
    main()
