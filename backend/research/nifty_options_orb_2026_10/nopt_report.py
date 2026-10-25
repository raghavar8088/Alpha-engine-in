"""Write REPORT.md and report/nifty-options-orb-backtest.html from the results.

    python -I backend/research/nifty_options_orb_2026_10/nopt_report.py

Every number is read from results/ (summary.json = the final model, summary_flat.json = the first). The
page reuses the NIFTYBEES report's design and chart code (../niftybees_orb_2026_10/report_template.html),
so the two studies read as a pair.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nopt_common as C  # noqa: E402
from orb_report import dt, e, inline_bar, inr, num  # noqa: E402

RES, OUT = HERE / "results", HERE / "report"
NB_TEMPLATE = HERE.parent / "niftybees_orb_2026_10" / "report_template.html"
KEYS = ["rr_1_2", "rr_1_3", "rr_1_4", "rr_1_5", "rr_1_6"]


def load() -> dict:
    j = lambda n: json.load(open(RES / n, encoding="utf-8"))  # noqa: E731
    g = {"S": j("summary.json"), "F": j("summary_flat.json"), "cal": j("calibration.json"), "ic": j("intraday_check.json"),
         "icf": j("intraday_check_flat.json"), "sq": j("surface_quality.json"), "mq": j("data_quality_minutes.json"),
         "clock": j("clock_profile.json")}
    for side in ("buy", "sell"):
        g[f"tr_{side}"] = list(csv.DictReader(open(RES / f"trades_{side}_rr_1_2.csv", encoding="utf-8")))
        for t in g[f"tr_{side}"]:
            for k in ("net", "before_costs"):
                t[k] = float(t[k])
    return g


def lab(key: str) -> str:
    return "1:" + key.split("_")[-1]


def rows(g: dict, side: str, src: str = "S") -> list[dict]:
    out = []
    for key in KEYS:
        o = g[src][side][key]
        s = o["stats"]
        ex = s["exit_reasons"]
        out.append({"label": lab(key), "s": s, "m": o["monthly"], "yearly": o["yearly"],
                    "t": ex.get("target", {}).get("trades", 0), "st": ex.get("stop", {}).get("trades", 0),
                    "eod": ex.get("eod", {}).get("trades", 0)})
    return out


def yname(y: str) -> str:
    return y + (" (from 25 Oct)" if y == "2021" else " (to 23 Oct)" if y == "2026" else "")


def facts(g: dict) -> dict:
    S = g["S"]
    b, s = S["buy"]["rr_1_2"], S["sell"]["rr_1_2"]
    return {"b": b["stats"], "s": s["stats"], "bm": b["monthly"], "sm": s["monthly"], "acct": S["meta"]["account"],
            "lot": S["meta"]["lot"], "sens": S["sensitivity_rr_1_2"], "rcb": b.get("real_price_check", {}),
            "bf": g["F"]["buy"]["rr_1_2"]["stats"], "sf": g["F"]["sell"]["rr_1_2"]["stats"],
            "buy_rows": rows(g, "buy"), "sell_rows": rows(g, "sell"), "cal": g["cal"]["chosen"]}


def verdict(f: dict) -> list[str]:
    b, s, bm, sm = f["b"], f["s"], f["bm"], f["sm"]
    br, sr = f["buy_rows"], f["sell_rows"]
    exp_s = s["by_days_to_expiry"].get("expiry day (0DTE)", {})
    no0 = f["sens"]["sell"]["no trades on the contract's expiry day"]
    nxt = f["sens"]["sell"]["next week's expiry instead"]
    return [
        f"**Buying loses at every ratio.** At 1:2 the {b['trades']:,} trades made {inr(b['net_pnl'])} on one lot "
        f"({inr(bm['net_per_month'])} a month, {num(bm['return_pct_per_month_on_account'], 2)}% a month on a {inr(f['acct'])} account; "
        f"t = {num(b['t_stat'], 2)}). 1:3 to 1:6 lost between {inr(-max(r['s']['net_pnl'] for r in br[1:]))} and "
        f"{inr(-min(r['s']['net_pnl'] for r in br[1:]))}. Before any cost the options already lost {inr(-b['before_costs'])}: time decay "
        "costs more than the breakouts earn.",
        f"**Selling (the mirror) is about break-even after costs.** Doing the opposite earns the buyer's pre-cost loss, "
        f"{inr(s['before_costs'], True)}, but pays the spread and the charges again ({inr(s['spread_slippage'] + s['charges'])}): "
        f"net {inr(s['net_pnl'], True)} at 1:2 ({inr(sm['net_per_month'], True)} a month, {num(sm['return_pct_per_month_on_account'], 2, True)}% "
        f"a month on {inr(f['acct'])}; t = {num(s['t_stat'], 2, True)}, not significant). It ranges from "
        f"{inr(min(r['s']['net_pnl'] for r in sr), True)} to {inr(max(r['s']['net_pnl'] for r in sr), True)} across the ratios.",
        f"**The seller's small profit is not reliable.** It all comes from expiry-day trades ({inr(exp_s.get('net', 0), True)}), the one "
        "place the model is still off, and off in the seller's favour (it lets expiry-day options decay 7–11% of their premium faster "
        f"than the recorded real quotes). Without expiry-day trades the seller made {inr(no0['net_pnl'], True)}; selling next week's "
        f"expiry instead made {inr(nxt['net_pnl'], True)}.",
    ]


def invest_rows(f: dict) -> list[tuple[str, str, str]]:
    b, s, bm, sm = f["b"], f["s"], f["bm"], f["sm"]
    return [
        ("What one trade ties up", f"the premium: {inr(b['avg_capital'])} a lot on average (expiry day ~{inr(b['by_days_to_expiry']['expiry day (0DTE)']['avg_capital'])}, "
                                   f"2-4 days out ~{inr(b['by_days_to_expiry']['2-4 sessions left']['avg_capital'])})",
         f"the margin: {inr(s['avg_capital'])} a lot on average (expiry day ~{inr(s['by_days_to_expiry']['expiry day (0DTE)']['avg_capital'])} "
         f"with the extra 2% ELM), up to {inr(s['max_capital'])}"),
        ("Trades a month", f"{bm['trades_per_month']:.0f}, one at a time", f"{sm['trades_per_month']:.0f}, one at a time"),
        ("Premium spent / margin blocked over a month", f"{inr(bm['capital_sum_per_month'])} of premium in total (recycled; never more than one lot at once)",
         f"{inr(s['avg_capital'])} blocked during each trade; the premium received, ~{inr(s['avg_premium'] * f['lot'])}, is credited"),
        ("Net P&L a month (average)", inr(bm["net_per_month"], True), inr(sm["net_per_month"], True)),
        ("Return a month on a ₹2,00,000 account", f"{num(bm['return_pct_per_month_on_account'], 2, True)}%", f"{num(sm['return_pct_per_month_on_account'], 2, True)}%"),
        ("Monthly net as a share of what one trade ties up", f"{num(bm['net_per_month'] / b['avg_capital'] * 100, 1, True)}% of one lot's premium",
         f"{num(sm['net_per_month'] / s['avg_capital'] * 100, 2, True)}% of one lot's margin"),
        ("Months up", f"{bm['months_positive']} of {bm['months']}", f"{sm['months_positive']} of {sm['months']}"),
        ("Median / best / worst month", f"{inr(bm['median_month'], True)} / {inr(bm['best_month'], True)} / {inr(bm['worst_month'], True)}",
         f"{inr(sm['median_month'], True)} / {inr(sm['best_month'], True)} / {inr(sm['worst_month'], True)}"),
        ("Five years in total", f"{inr(b['net_pnl'], True)}; max drawdown {inr(b['max_dd'])}" + (f"; a ₹2 lakh account hits zero on {dt(b['account_wiped_out_on'])}" if b.get("account_wiped_out_on") else ""),
         f"{inr(s['net_pnl'], True)}; max drawdown {inr(s['max_dd'])}"),
    ]


def rule_items(f: dict) -> list[tuple[str, str]]:
    return [
        ("Signal", "The NIFTYBEES study's rules, read on the NIFTY 50 index itself: the opening range is the high and low of "
                   "09:15:00 to 09:29:59; from 09:30 the first move above the high or below the low is the breakout."),
        ("Contract", "A break above uses the at-the-money CALL, a break below the at-the-money PUT: the strike nearest NIFTY at "
                     "the breakout (50 apart), of the nearest weekly expiry on or after the trade day as NSE listed it "
                     "(Thursdays to August 2025, Tuesdays after). On expiry day that is the contract expiring that afternoon."),
        ("Buying", "The option is bought at the breakout and sold at the exit."),
        ("Selling (the mirror)", "The same option is SOLD at the same moment and bought back at the same exits. Nothing else changes."),
        ("Exits", "Levels on the index, as before: the stop is the other side of the opening range, the target 2 (3, 4, 5, 6) "
                  "times the entry-to-stop distance beyond the entry. When NIFTY touches either, the option is closed at market. "
                  "Anything still open is closed at 15:15. For a seller the index 'target' is the losing exit and the 'stop' the winning one."),
        ("Trades a day", "One. No re-entry, no reversal. No entry from 15:00."),
        ("Size", f"One lot of {f['lot']} units (today's NIFTY lot; it was 50, then 25, then 75 during the five years)."),
        ("Fills", "Every fill pays half the spread (0.15% of the premium) and one ₹0.05 tick: bought above the mid, sold below "
                  "it. The recorded at-the-money same-week spread is a median 0.23% of the premium, so this is a little worse."),
        ("Charges", "Angel One's option rate card at today's rates (the app's fee model): ₹20 an order, STT 0.15% of the premium "
                    "sold (a seller pays it on the opening sale), NSE 0.03503%, SEBI and stamp duty, GST 18%."),
        ("Margin (selling)", "The app's SPAN-lite engine (±6% scan plus 3% exposure, calibrated on NIFTY), plus the extra 2% "
                             "ELM on short options on their expiry day."),
        ("Account", f"{inr(f['acct'])}, no compounding: drawdowns and monthly returns are measured on it."),
    ]


def model_paras(f: dict, g: dict) -> list[str]:
    cal = f["cal"]
    h = cal.get("holdout", {})
    ic, icf = g["ic"]["change_error"], g["icf"]["change_error"]
    def ce(d, hold, b):  # noqa: E301
        v = d.get(hold, {}).get(b)
        return f"{num(v['mean'] * 100, 1, True)}%" if v else "n/a"
    clock = g["clock"]
    return [
        "No source this app can reach keeps intraday prices of EXPIRED NIFTY options: Angel One and Dhan serve candles only "
        "for live contracts, and the app's own option-chain recorder started on 5 Oct 2026. So every entry and exit premium "
        "is modelled, with the method the NIFTY BANK study built and validated, redone for weekly options.",
        "Each contract's volatility comes from the previous session's REAL NSE closing prices (bhavcopy) for that very expiry; "
        "nothing from the trade day's own option prices is used. During the day it moves with India VIX (exponent "
        f"{cal['beta']:g}, smile rule '{cal['smile']}', chosen on 2021-23 only). Time runs on a clock of trading minutes plus 0.2 "
        "of a session a night.",
        f"Check 1, real closing prices, 2024-26 (not used for any choice): the model's day-over-day change was off by "
        f"{num(h.get('bias', 0) * 100, 2, True)}% of the premium on average over {h.get('n', 0):,} option-days.",
        "Check 2, the real intraday quotes the recorder kept (14 sessions, 5-23 Oct 2026, entries every 30 minutes). The first "
        "model ran the clock flat through the day; it overpriced expiry-day options at entry and decayed them too fast "
        f"(change to 15:15 {ce(icf, 'to 15:15', '0')} of the premium on expiry day). NIFTY's variance is not flat: "
        f"{(1 - clock['expiry'][15]) * 100:.0f}% of an expiry day's has gone by 09:30, against 4% of its minutes. So the final model "
        "counts each minute by its share of a day's variance, measured on NIFTY's own 2021-23 minutes (no option prices). "
        f"Change errors with it: 2-4 days to expiry {ce(ic, '60', '2-4')} (60 min) and {ce(ic, 'to 15:15', '2-4')} (to 15:15); "
        f"1 day {ce(ic, '60', '1')} and {ce(ic, 'to 15:15', '1')}; expiry day still {ce(ic, '120', '0')} (120 min) and "
        f"{ce(ic, 'to 15:15', '0')} (to 15:15). Expiry-day options still decay too fast in the model: that makes buying look a "
        "little worse and selling a little better than they were.",
        f"Check 3, the strategy's own trades: {f['rcb'].get('n_priced', 0)} of its October 2026 trades fall inside the recorded "
        f"sessions. At the real quotes of their minutes the buyer made {inr(f['rcb'].get('real_sum', 0), True)} before costs; "
        f"the model said {inr(f['rcb'].get('model_sum', 0), True)} (the seller: the same amounts with the sign flipped).",
        f"The first (flat-clock) model gave buying {inr(f['bf']['net_pnl'], True)} and selling {inr(f['sf']['net_pnl'], True)} at 1:2. "
        "Both are reported; the conclusions are the same.",
    ]


def data_items(f: dict, g: dict) -> list[str]:
    sq, mq = g["sq"], g["mq"]
    dropped = [d["date"] for d in mq["nifty"]["days_dropped"]] + [d["date"] for d in mq["nifty"].get("days_dropped_short", [])]
    inw = sorted(d for d in dropped if d >= "2021-10-25")
    return [
        f"NSE F&O bhavcopies for {sq['bhav_files']:,} sessions (2021-10-01 to 2026-10-23); exchange holidays have none. "
        f"{sq['sessions_with_surface']:,} sessions gave a smile; Diwali Muhurat files are not used.",
        "NSE moved the 2023 Bakri Id holiday from 28 to 29 June at short notice: its files list that week's expiry as 29 June "
        "until 27 June, but the contracts expired on 28 June. The one such case; corrected.",
        f"NIFTY 50 and India VIX 1-minute candles from Angel One. {len(inw)} sessions in the window have no 09:15 minute or are "
        f"not full sessions and are left out: {', '.join(dt(d) for d in inw)}.",
        "Since 3 Aug 2026 Angel serves almost no index minutes after 15:14 (NSE's closing auction); the 15:15 exit uses the 15:14 minute.",
        "Intraday option quotes: the app's recorder, 14 sessions, every minute, ATM ±10 strikes. Lot sizes in the window: 50, "
        "25 (Jul-Dec 2024 in NSE's files), 75, now 65; every trade here uses 65.",
    ]


def write_md(g: dict) -> None:
    f = facts(g)
    S = g["S"]
    L = []
    w = L.append
    w("# NIFTY 50 ATM option opening-range breakout, buying and selling: five-year backtest")
    w("")
    w(f"NSE: NIFTY 50 weekly options, at the money, same-week expiry, {dt(S['meta']['window'][0])} to {dt(S['meta']['window'][1])} "
      f"({S['meta']['sessions']:,} sessions), one lot of {f['lot']}. `python -I nopt_report.py` rebuilds this file.")
    w("")
    w("## Verdict")
    w("")
    for x in verdict(f):
        w(x)
        w("")
    w("## Investment and monthly return (1:2)")
    w("")
    w("| | Buying | Selling (mirror) |")
    w("|---|---|---|")
    for a, b, c in invest_rows(f):
        w(f"| {a} | {b} | {c} |")
    w("")
    for side, title in (("buy", "Buying"), ("sell", "Selling (the mirror)")):
        w(f"## {title}: results by risk : reward")
        w("")
        w("| Risk : reward | Trades | Win rate | Index target / stop / 15:15 | Before costs | Spread & slippage | Charges | Net P&L | "
          "Profit factor | Max drawdown | Net a month | % a month on ₹2L |")
        w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in f[f"{side}_rows"]:
            s = r["s"]
            w(f"| {r['label']} | {s['trades']:,} | {s['win_rate']:.1f}% | {r['t']} / {r['st']} / {r['eod']} | {inr(s['before_costs'], True)} | "
              f"{inr(-s['spread_slippage'])} | {inr(-s['charges'])} | **{inr(s['net_pnl'], True)}** | {s['profit_factor']:.2f} | "
              f"{inr(s['max_dd'])} | {inr(r['m']['net_per_month'], True)} | {num(r['m']['return_pct_per_month_on_account'], 2, True)}% |")
        w("")
        w("Net P&L by year:")
        w("")
        w("| Year | " + " | ".join(r["label"] for r in f[f"{side}_rows"]) + " |")
        w("|---|" + "---:|" * len(KEYS))
        for i, y in enumerate(f[f"{side}_rows"][0]["yearly"]):
            w(f"| {yname(y['year'])} | " + " | ".join(inr(r["yearly"][i]["net_pnl"], True) for r in f[f"{side}_rows"]) + " |")
        w("")
        s = f["b"] if side == "buy" else f["s"]
        w(f"By days to expiry (1:2): " + "; ".join(f"{k}: {v['trades']} trades, {inr(v['net'], True)} net ({inr(v['before_costs'], True)} before costs)"
                                                  for k, v in s["by_days_to_expiry"].items()) + ".")
        w("")
    w("## The rules as tested")
    w("")
    for a, b in rule_items(f):
        w(f"- **{a}.** {b}")
    w("")
    w("## How the option prices were obtained, and how good they are")
    w("")
    for x in model_paras(f, g):
        w(x)
        w("")
    w("## If one assumption changes (1:2)")
    w("")
    w("| Change | Buying net | Selling net |")
    w("|---|---:|---:|")
    w(f"| None (the results above) | {inr(f['b']['net_pnl'], True)} | {inr(f['s']['net_pnl'], True)} |")
    for k in f["sens"]["buy"]:
        w(f"| {k} | {inr(f['sens']['buy'][k]['net_pnl'], True)} | {inr(f['sens']['sell'][k]['net_pnl'], True)} |")
    w(f"| The first model (flat clock) | {inr(f['bf']['net_pnl'], True)} | {inr(f['sf']['net_pnl'], True)} |")
    w("")
    w("## Data and gaps")
    w("")
    for x in data_items(f, g):
        w(f"- {x}")
    w("")
    (HERE / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ── html ─────────────────────────────────────────────────────────────────────────────────────────────

AUTO_STEP = ("const span = (Math.max.apply(null, all) - Math.min.apply(null, all)) || 1; "
             "const step = [1e4, 2e4, 25e3, 5e4, 1e5, 2e5, 25e4, 5e5, 1e6].find(s => span / s <= 6) || 1e6;")
EXTRA_CSS = """<style>
:root { --sell: #eb6834; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --sell: #d95926; } }
:root[data-theme="dark"] { --sell: #d95926; }
svg .ln-pre { stroke: var(--sell); }
svg .dot-pre { fill: var(--sell); }
.key.pre { border-color: var(--sell); }
.tip .tk.k-pre { border-color: var(--sell); }
.invest td, .invest th { white-space: normal; text-align: left; vertical-align: top; }
.invest td { min-width: 14rem; }
</style>
"""


def page_parts() -> tuple[str, str]:
    t = NB_TEMPLATE.read_text(encoding="utf-8")
    head = t[: t.index('<div class="page">')]
    script = t[t.index('<div class="tip"'):]
    rep = [
        ('"Account value after costs falls from 10 lakh to " + lakh(net[n - 1]) + "; before costs it ends at " + lakh(pre[n - 1])',
         '"One lot on a 2 lakh account: buying ends at " + lakh(net[n - 1]) + ", selling at " + lakh(pre[n - 1])'),
        ("const all = net.concat(pre), step = 2e5;", "const all = net.concat(pre); " + AUTO_STEP),
        ("const step = 2e5;\n    const lo = Math.floor(Math.min.apply(null, ext) / step) * step",
         "const all = ext; " + AUTO_STEP + "\n    const lo = Math.floor(Math.min.apply(null, ext) / step) * step"),
        ('RS + (v / 1e5) + "L"', '(v < 0 ? MINUS : "") + RS + +Math.abs(v / 1e5).toFixed(2) + "L"'),
        ('fdate(E.dates[pk]), "lab", "start")', 'fdate(E.dates[pk]), "note", "start")'),
        ('fdate(E.dates[tr]), "lab", "end")', 'fdate(E.dates[tr]), "note", "end")'),
        ('(v > 0 ? "+" : MINUS) + RS + Math.abs(v / 1e5) + "L"', '(v > 0 ? "+" : MINUS) + RS + +Math.abs(v / 1e5).toFixed(2) + "L"'),
        ('[[pre, "Before costs"], [net, "After costs"]]', '[[pre, "Selling"], [net, "Buying"]]'),
        ('[inr(net[i]), "after costs", "k-net"], [inr(pre[i]), "before costs", "k-pre"]', '[inr(net[i]), "buying", "k-net"], [inr(pre[i]), "selling", "k-pre"]'),
        ('"Peak " + lakh(net[pk])', '"Buying peak " + lakh(net[pk])'),
        ('"Low " + lakh(net[tr])', '"Buying low " + lakh(net[tr])'),
        ("function bridge(host) {", "function bridge(host) {\n    const B = D[host.dataset.src || \"bridge\"];"),
        ('const what = last ? "net result after costs" : (k === 0 ? "the trades before any cost" : (s.lab === "Slippage" ? "1 bp a side on market and stop fills" : "Angel One charges, about " + RS + "402 a trade"));',
         'const what = last ? "net result after costs" : (k === 0 ? "the trades at mid prices, before any cost" : (s.lab === "Charges" ? "Angel One option charges" : "half the spread and a tick on every fill"));'),
        ('[["eq-chart", equity], ["bridge-chart", bridge], ["day-chart", day]]', '[["eq-chart", equity], ["bridge-chart", bridge], ["bridge-chart-sell", bridge]]'),
    ]
    for a, b in rep:
        if a not in script:
            raise RuntimeError(f"template changed, cannot find: {a[:60]}")
        script = script.replace(a, b)
    script = re.sub(r"\bD\.bridge\b", "B", script)
    head = re.sub(r"<title>.*?</title>", "<title>NIFTY Options Opening-Range Breakout</title>", head, flags=re.S)
    return head + EXTRA_CSS, script


def equity_payload(g: dict) -> dict:
    import numpy as np
    z = np.load(C.DATA / "minutes.npz")
    dates = [str(d) for d in z["days"] if "2021-10-25" <= str(d) <= "2026-10-23"]
    acct = g["S"]["meta"]["account"]
    curves = {}
    for side in ("buy", "sell"):
        by = {}
        for t in g[f"tr_{side}"]:
            by[t["date"]] = by.get(t["date"], 0.0) + t["net"]
        a, c = acct, []
        for d in dates:
            a += by.get(d, 0.0)
            c.append(round(a, 2))
        curves[side] = c
    net = curves["buy"]
    tr_i = net.index(min(net))
    pk = max(range(tr_i + 1), key=lambda i: net[i])
    return {"dates": dates, "net": net, "pre": curves["sell"], "peak": pk, "trough": tr_i, "cap": acct}


def table(head: list[str], body: list[list[str]], cls: str = "") -> str:
    th = "".join(f"<th>{h}</th>" for h in head)
    tb = "\n".join("<tr>" + "".join((f"<th scope=\"row\">{c}</th>" if i == 0 else f"<td>{c}</td>") for i, c in enumerate(r)) + "</tr>" for r in body)
    return f'<div class="tablewrap"><table{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}><thead><tr>{th}</tr></thead><tbody>\n{tb}\n</tbody></table></div>'


def write_html(g: dict) -> None:
    f = facts(g)
    b, s = f["b"], f["s"]
    head, script = page_parts()
    kpis = [("Buying, 1:2", inr(b["net_pnl"]), f"{num(f['bm']['return_pct_per_month_on_account'], 2)}% a month on ₹2 lakh"),
            ("Selling, 1:2", inr(s["net_pnl"], True), f"{num(f['sm']['return_pct_per_month_on_account'], 2, True)}% a month on ₹2 lakh"),
            ("Buying ties up", inr(b["avg_capital"]), "premium of one lot, average"),
            ("Selling ties up", inr(s["avg_capital"]), "margin of one lot, average"),
            ("Trades", f"{b['trades']:,}", f"about {f['bm']['trades_per_month']:.0f} a month"),
            ("Costs a trade", inr((b["spread_slippage"] + b["charges"]) / b["trades"]), "spread, slippage, charges")]
    kpi_html = "\n".join(f'<div class="kpi"><dt>{e(a)}</dt><dd><span class="kv">{e(x)}</span><span class="kn">{e(c)}</span></dd></div>'
                         for a, x, c in kpis)
    inv = table(["", "Buying", "Selling (mirror)"], [[e(a), e(x), e(y)] for a, x, y in invest_rows(f)], "invest")

    def ratio_table(side: str) -> str:
        rr = f[f"{side}_rows"]
        vmax = max(abs(r["s"]["net_pnl"]) for r in rr)
        body = []
        for r in rr:
            st = r["s"]
            body.append([e(r["label"]), f"{st['trades']:,}", f"{st['win_rate']:.1f}%", f"<span class=mono>{r['t']} / {r['st']} / {r['eod']}</span>",
                         e(inr(st["before_costs"], True)), e(inr(-(st["spread_slippage"] + st["charges"]))),
                         inline_bar(st["net_pnl"], vmax), f"<strong>{e(inr(st['net_pnl'], True))}</strong>", f"{st['profit_factor']:.2f}",
                         e(inr(st["max_dd"])), e(inr(r["m"]["net_per_month"], True)), f"{e(num(r['m']['return_pct_per_month_on_account'], 2, True))}%"])
        return table(["Risk : reward", "Trades", "Win rate", "Index T / S / 15:15", "Before costs", "Costs", "", "Net P&amp;L",
                      "Profit factor", "Max drawdown", "Net a month", "% a month on ₹2L"], body)

    def year_table(side: str) -> str:
        rr = f[f"{side}_rows"]
        body = [[f"{y['year']}" + ("<span class=sub>from 25 Oct</span>" if y["year"] == "2021" else "<span class=sub>to 23 Oct</span>" if y["year"] == "2026" else "")]
                + [e(inr(r["yearly"][i]["net_pnl"], True)) for r in rr] for i, y in enumerate(rr[0]["yearly"])]
        body.append(["All"] + [f"<strong>{e(inr(r['s']['net_pnl'], True))}</strong>" for r in rr])
        return table(["Year"] + [e(r["label"]) for r in rr], body, "fit")

    def dte_table() -> str:
        body = []
        for k in b["by_days_to_expiry"]:
            vb, vs = b["by_days_to_expiry"][k], s["by_days_to_expiry"].get(k, {})
            body.append([e(k), f"{vb['trades']}", e(inr(vb["avg_capital"])), e(inr(vb["net"], True)), e(inr(vs.get("avg_capital", 0))),
                         e(inr(vs.get("net", 0), True))])
        return table(["Contract", "Trades", "Buying: premium", "Buying: net", "Selling: margin", "Selling: net"], body)

    sens_body = [[e("None (the results above)"), e(inr(b["net_pnl"], True)), e(inr(s["net_pnl"], True))]]
    for k in f["sens"]["buy"]:
        sens_body.append([e(k), e(inr(f["sens"]["buy"][k]["net_pnl"], True)), e(inr(f["sens"]["sell"][k]["net_pnl"], True))])
    sens_body.append([e("The first model (flat clock)"), e(inr(f["bf"]["net_pnl"], True)), e(inr(f["sf"]["net_pnl"], True))])
    sens = table(["Change (1:2)", "Buying net", "Selling net"], sens_body)
    ic, icf = g["ic"]["change_error"], g["icf"]["change_error"]
    ic_body = []
    for bucket, name in (("0", "Expiry day"), ("1", "1 day to expiry"), ("2-4", "2–4 days"), ("5+", "5+ days")):
        cells = [e(name)]
        for hold in ("60", "to 15:15"):
            for d in (icf, ic):
                v = d.get(hold, {}).get(bucket)
                cells.append(f"{num(v['mean'] * 100, 1, True)}%" if v else "–")
        ic_body.append(cells)
    ic_tab = table(["Option", "60 min, first model", "60 min, final", "To 15:15, first", "To 15:15, final"], ic_body)
    rc_body = [[e(dt(t["date"])), e(f"{t['option']} {int(float(t['strike']))}"), f"<span class=mono>{e(t['entry_time'])}–{e(t['exit_time'])}</span>",
                f"{t['model_in']:.2f} / {t['real_in']:.2f}", f"{t['model_out']:.2f} / {t['real_out']:.2f}",
                e(inr(t["model_before_costs"], True)), f"<strong>{e(inr(t['real_before_costs'], True))}</strong>"]
               for t in f["rcb"].get("trades", []) if t.get("real_in") is not None]
    rc_tab = table(["Date", "Option", "Held", "Entry, model / real", "Exit, model / real", "Buyer, model", "Buyer, real"], rc_body)
    payload = {"eq": equity_payload(g),
               "bridge": [["Before costs", b["before_costs"]], ["Spread & slippage", -b["spread_slippage"]], ["Charges", -b["charges"]], ["Result", b["net_pnl"]]],
               "bridge_sell": [["Before costs", s["before_costs"]], ["Spread & slippage", -s["spread_slippage"]], ["Charges", -s["charges"]], ["Result", s["net_pnl"]]],
               "day": {}}
    script = script.replace("{{DATA_JSON}}", json.dumps(payload, separators=(",", ":")))
    md = lambda x: "".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(e(x).split("**")))  # noqa: E731
    body = f"""<div class="page">
  <header class="masthead">
    <p class="eyebrow">{e(f"Backtest · NSE: NIFTY 50 weekly options · ATM, same-week expiry · {dt(g['S']['meta']['window'][0])} to {dt(g['S']['meta']['window'][1])}")}</p>
    <h1>NIFTY Options Opening-Range Breakout</h1>
    <p class="dek">The NIFTYBEES opening-range rules, read on the NIFTY 50 index and traded with the at-the-money call or put of the nearest weekly expiry: bought, and then the exact opposite, sold. One lot, the stop and target on the index, out by 15:15.</p>
    <div class="verdict prose">{"".join(f"<p>{md(x)}</p>" for x in verdict(f))}</div>
    <dl class="kpis">
{kpi_html}
    </dl>
  </header>
  <section id="invest" aria-labelledby="h-invest">
    <h2 id="h-invest">Investment and monthly return, 1:2</h2>
    {inv}
  </section>
  <section id="equity" aria-labelledby="h-equity">
    <h2 id="h-equity">Account value, 1:2</h2>
    <figure>
      <ul class="legend">
        <li><span class="key net"></span>Buying the option</li>
        <li><span class="key pre"></span>Selling it (the mirror)</li>
      </ul>
      <div class="chart" id="eq-chart"></div>
      <figcaption>{e(f"One lot of {f['lot']} on a {inr(f['acct'])} account, no compounding, after every cost. Hover or use the arrow keys for any day's values.")}</figcaption>
    </figure>
  </section>
  <section id="buy" aria-labelledby="h-buy">
    <h2 id="h-buy">Buying: every risk : reward</h2>
    {ratio_table("buy")}
    <h3>Net P&amp;L by year</h3>
    {year_table("buy")}
  </section>
  <section id="sell" aria-labelledby="h-sell">
    <h2 id="h-sell">Selling (the mirror): every risk : reward</h2>
    {ratio_table("sell")}
    <h3>Net P&amp;L by year</h3>
    {year_table("sell")}
  </section>
  <section id="costs" aria-labelledby="h-costs">
    <h2 id="h-costs">Where the money went, 1:2</h2>
    <div class="two">
      <figure><div class="chart" id="bridge-chart" data-src="bridge"></div><figcaption>Buying: the options lose before any cost; spread and charges add to it.</figcaption></figure>
      <figure><div class="chart" id="bridge-chart-sell" data-src="bridge_sell"></div><figcaption>Selling: the same pre-cost amount the other way, then the same costs again.</figcaption></figure>
    </div>
    <h3>By days to expiry</h3>
    {dte_table()}
  </section>
  <section id="rules" aria-labelledby="h-rules">
    <h2 id="h-rules">The rules as tested</h2>
    <dl class="rules">
{"".join(f'<div class="rule"><dt>{e(a)}</dt><dd>{e(x)}</dd></div>' for a, x in rule_items(f))}
    </dl>
  </section>
  <section id="model" aria-labelledby="h-model">
    <h2 id="h-model">How the option prices were obtained</h2>
    <div class="prose">{"".join(f"<p>{e(x)}</p>" for x in model_paras(f, g))}</div>
    <h3>Model minus real, change in the premium over the hold (recorded quotes, % of premium)</h3>
    {ic_tab}
    <h3>The strategy's own October 2026 trades at real quotes</h3>
    {rc_tab}
  </section>
  <section id="variants" aria-labelledby="h-variants">
    <h2 id="h-variants">If one assumption changes</h2>
    {sens}
  </section>
  <section id="data" aria-labelledby="h-data">
    <h2 id="h-data">Data and gaps</h2>
    <ul class="prose">{"".join(f"<li>{e(x)}</li>" for x in data_items(f, g))}</ul>
  </section>
  <footer>
    <p>Code and outputs are in <code>backend/research/nifty_options_orb_2026_10/</code> of the app repository; <code>nopt_report.py</code> rebuilds this page. The ETF version of the same rules is in <code>backend/research/niftybees_orb_2026_10/</code>.</p>
  </footer>
</div>
"""
    OUT.mkdir(exist_ok=True)
    (OUT / "nifty-options-orb-backtest.html").write_text(head + body + script, encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    g = load()
    write_md(g)
    write_html(g)
    print("wrote", HERE / "REPORT.md", "and", OUT / "nifty-options-orb-backtest.html")


if __name__ == "__main__":
    main()
