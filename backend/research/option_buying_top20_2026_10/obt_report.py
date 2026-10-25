"""REPORT.md and report/option-buying-top20.html from results/summary.json and the trade files.

    python -I backend/research/option_buying_top20_2026_10/obt_report.py
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "niftybees_orb_2026_10"))
from orb_report import dt, e, inline_bar, inr, num  # noqa: E402

RES, OUT = HERE / "results", HERE / "report"
NB_TEMPLATE = HERE.parent / "niftybees_orb_2026_10" / "report_template.html"
LOT = 65
ACCOUNT = 200_000


def load() -> dict:
    S = json.load(open(RES / "summary.json", encoding="utf-8"))
    last = json.load(gzip.open(HERE / "data" / "trades_last_month.json.gz", "rt"))
    # twenty DISTINCT strategies: a name whose trades repeat a higher-ranked one's exactly is dropped
    seen, top, dupes = {}, [], []
    for r in S["last_month"]:
        sig = json.dumps([[t[0], t[1], t[2]] for t in last[r["name"]]])
        if sig in seen:
            dupes.append((r["name"], seen[sig]))
            continue
        seen[sig] = r["name"]
        if len(top) < 20:
            top.append(r)
    # the basket: all twenty at once, one lot each
    ev, daily = [], {}
    for r in top:
        for t in last[r["name"]]:
            ev += [(t[1], t[6] * LOT), (t[9], -t[6] * LOT)]
            daily[t[0]] = daily.get(t[0], 0.0) + t[10]
    ev.sort(key=lambda x: (x[0], x[1]))
    cur = peak_cap = 0.0
    for _, x in ev:
        cur += x
        peak_cap = max(peak_cap, cur)
    eq = pk = dd = 0.0
    for d in sorted(daily):
        eq += daily[d]
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    basket = {"net": sum(r["net"] for r in top), "trades": sum(r["trades"] for r in top), "peak_capital": peak_cap,
              "max_dd": dd, "days": len(daily), "up_days": sum(1 for v in daily.values() if v > 0),
              "real_trades": sum(r["trades_real"] for r in top)}
    nets = sorted(r["net"] for r in S["last_month"])
    pers = S["persistence"]
    return {"S": S, "top": top, "dupes": dupes, "basket": basket, "median": nets[len(nets) // 2], "all_sum": sum(nets),
            "pers": pers, "p_top": sum(p["top20_next_month"] for p in pers), "p_avg": sum(p["all_avg_x20_next_month"] for p in pers),
            "p_bot": sum(p["bottom20_next_month"] for p in pers), "p_up": sum(1 for p in pers if p["top20_next_month"] > 0),
            "p_beat": sum(1 for p in pers if p["top20_next_month"] > p["all_avg_x20_next_month"])}


def verdict(g: dict) -> list[str]:
    b, S = g["basket"], g["S"]
    return [
        f"**The top 20 of {S['pairs']} option-buying strategies, 24 Sep to 23 Oct 2026.** Together, one lot each, they made "
        f"{inr(b['net'], True)} in {b['days']} sessions ({b['trades']} trades, {b['up_days']} of {b['days']} days up). Running all of "
        f"them at once tied up at most {inr(b['peak_capital'])} of premium; the worst drawdown was {inr(b['max_dd'])}.",
        f"**Half the library made money last month: {S['positive_last_month']} of {S['pairs']}.** The median strategy made "
        f"{inr(g['median'], True)}. With that many strategies, twenty will look strong in any month by luck alone.",
        f"**A month's top 20 does not keep winning.** Over the 12 months before, the top 20 of each month lost money the "
        f"following month {12 - g['p_up']} times out of 12: {inr(g['p_top'], True)} in all on one lot each. They did better than an "
        f"average 20 ({inr(g['p_avg'], True)}) and the bottom 20 ({inr(g['p_bot'], True)}) in {g['p_beat']} of 12 months, but they still "
        "lost. Last month's list is a record of what happened, not a basket to trade.",
    ]


def write_md(g: dict) -> None:
    L = []
    w = L.append
    w("# Top 20 NIFTY option-buying strategies of the last month (24 Sep to 23 Oct 2026)")
    w("")
    for x in verdict(g):
        w(x)
        w("")
    w("## The twenty")
    w("")
    w("One lot (65) per trade. Investment = the average premium paid for one lot. Return on ₹2 lakh = the month's net on a "
      "₹2,00,000 account running that one strategy.")
    w("")
    w("| # | Strategy | Timeframe | Trades | Win rate | Net (month) | Return on ₹2L | Profit factor | Max drawdown | Investment / trade | Trades at real quotes |")
    w("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i, r in enumerate(g["top"], 1):
        sid, tf = r["name"].split("@")
        w(f"| {i} | {sid} | {tf} | {r['trades']} | {r['win_rate']:.1f}% | {inr(r['net'], True)} | {num(r['net'] / ACCOUNT * 100, 1, True)}% | "
          f"{r['profit_factor']:.2f} | {inr(r['max_dd'])} | {inr(r['avg_premium'] * LOT)} | {r['trades_real']} of {r['trades']} |")
    w("")
    if g["dupes"]:
        w("Left out as duplicates (identical trades to a higher-ranked strategy): " +
          ", ".join(f"{a} (= {b})" for a, b in g["dupes"] if any(r['name'] == b for r in g['top'])) + ".")
        w("")
    w("## Does a month's top 20 keep winning?")
    w("")
    w("Rank every strategy on one month, then look at what its top 20 made the NEXT month (model prices throughout).")
    w("")
    w("| Ranked on | Top 20 that month | Top 20 the next month | Average 20 next month | Bottom 20 next month | Top 20 up next month |")
    w("|---|---:|---:|---:|---:|---:|")
    for p in g["pers"]:
        w(f"| {dt(p['rank_on'][0])} – {dt(p['rank_on'][1])} | {inr(p['top20_in_rank_month'], True)} | **{inr(p['top20_next_month'], True)}** | "
          f"{inr(p['all_avg_x20_next_month'], True)} | {inr(p['bottom20_next_month'], True)} | {p['top20_positive_next_month']} of 20 |")
    w(f"| **12 months** | | **{inr(g['p_top'], True)}** | {inr(g['p_avg'], True)} | {inr(g['p_bot'], True)} | |")
    w("")
    w("## How it was tested")
    w("")
    for x in method_items(g):
        w(f"- {x}")
    w("")
    (HERE / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def method_items(g: dict) -> list[str]:
    return [
        f"The library: every option-buying strategy in the app (strategy-service `options_buying`, the Pre-Live desk's library): "
        f"{g['S']['pairs']} strategy and timeframe pairs (5-minute, 15-minute, 1-hour), on NIFTY 50.",
        "The live desk's rules: a fresh instance every session warmed on 400 bars; a signal at each bar close unless a position is "
        "open; at most 6 trades a day; BUY buys the at-the-money call, SELL the at-the-money put, of the nearest weekly expiry; one "
        "lot of 65; the category's premium stop and target (scalp 25% / 50%, intraday 30% / 60%, breakout 35% / 100%), else out at 15:15.",
        "Prices on 5–23 Oct 2026: the REAL quotes the app's recorder kept every minute, bought at the ask and sold at the bid. On "
        "24 Sep – 3 Oct (no recorder yet): the premium model validated in the NIFTY options study (previous day's real NSE prices, "
        "India VIX, intraday variance clock), with half the spread and a tick on each fill. The persistence check uses the model for every month.",
        "Charges: Angel One's option rate card at today's rates on every trade.",
        "Real recorded quotes are one snapshot a minute, so a stop or target is checked once a minute, not on every tick.",
    ]


def write_html(g: dict) -> None:
    t = NB_TEMPLATE.read_text(encoding="utf-8")
    head = t[: t.index('<div class="page">')]
    head = re.sub(r"<title>.*?</title>", "<title>Option Buying Top 20</title>", head, flags=re.S)
    b = g["basket"]
    kpis = [("Top 20 together", inr(b["net"], True), f"{b['days']} sessions, one lot each"),
            ("Most premium at once", inr(b["peak_capital"]), "running all twenty"),
            ("Worst drawdown", inr(b["max_dd"]), f"{b['up_days']} of {b['days']} days up"),
            ("Strategies up", f"{g['S']['positive_last_month']} of {g['S']['pairs']}", "the whole library, last month"),
            ("Next month, 12 tries", inr(g["p_top"], True), f"a month's top 20 lost {12 - g['p_up']} of 12 times"),
            ("Real-quote trades", f"{b['real_trades']} of {b['trades']}", "5–23 Oct at recorded bid/ask")]
    kpi_html = "\n".join(f'<div class="kpi"><dt>{e(a)}</dt><dd><span class="kv">{e(x)}</span><span class="kn">{e(c)}</span></dd></div>'
                         for a, x, c in kpis)
    vmax = max(abs(r["net"]) for r in g["top"])
    rows = "\n".join(
        f"<tr><td>{i}</td><th scope=\"row\" class=\"mono\">{e(r['name'].split('@')[0])}</th><td>{e(r['name'].split('@')[1])}</td>"
        f"<td>{r['trades']}</td><td>{r['win_rate']:.1f}%</td><td class=\"barcol\">{inline_bar(r['net'], vmax)}</td>"
        f"<td class=\"strong\">{e(inr(r['net'], True))}</td><td>{e(num(r['net'] / ACCOUNT * 100, 1, True))}%</td>"
        f"<td>{r['profit_factor']:.2f}</td><td>{e(inr(r['max_dd']))}</td><td>{e(inr(r['avg_premium'] * LOT))}</td>"
        f"<td>{r['trades_real']} / {r['trades']}</td></tr>" for i, r in enumerate(g["top"], 1))
    pmax = max(abs(p["top20_next_month"]) for p in g["pers"])
    prow = "\n".join(
        f"<tr><th scope=\"row\">{e(dt(p['rank_on'][0]))} – {e(dt(p['rank_on'][1]))}</th><td>{e(inr(p['top20_in_rank_month'], True))}</td>"
        f"<td class=\"barcol\">{inline_bar(p['top20_next_month'], pmax)}</td><td class=\"strong\">{e(inr(p['top20_next_month'], True))}</td>"
        f"<td>{e(inr(p['all_avg_x20_next_month'], True))}</td><td>{e(inr(p['bottom20_next_month'], True))}</td>"
        f"<td>{p['top20_positive_next_month']} of 20</td></tr>" for p in g["pers"])
    prow += (f"\n<tr class=\"total\"><th scope=\"row\">12 months</th><td></td><td class=\"barcol\"></td><td class=\"strong\">{e(inr(g['p_top'], True))}</td>"
             f"<td>{e(inr(g['p_avg'], True))}</td><td>{e(inr(g['p_bot'], True))}</td><td></td></tr>")
    md = lambda x: "".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(e(x).split("**")))  # noqa: E731
    dup = ""
    if g["dupes"]:
        dup = "<p>" + e("Left out as duplicates (identical trades to a higher-ranked strategy): " + ", ".join(
            f"{a} (= {b_})" for a, b_ in g["dupes"] if any(r["name"] == b_ for r in g["top"])) + ".") + "</p>"
    body = f"""<div class="page">
  <header class="masthead">
    <p class="eyebrow">Backtest · NSE: NIFTY 50 weekly options · option buying · 24 Sep to 23 Oct 2026</p>
    <h1>Option Buying Top 20</h1>
    <p class="dek">Every option-buying strategy in the app, replayed over the last month with the live desk's rules, ranked by what one lot made after costs, and checked against the question that matters: does a month's top 20 keep winning?</p>
    <div class="verdict prose">{"".join(f"<p>{md(x)}</p>" for x in verdict(g))}</div>
    <dl class="kpis">
{kpi_html}
    </dl>
  </header>
  <section aria-labelledby="h-top">
    <h2 id="h-top">The twenty</h2>
    <div class="prose"><p>One lot (65) per trade. Investment is the average premium paid for one lot; return is the month's net on a ₹2,00,000 account running that one strategy.</p>{dup}</div>
    <div class="tablewrap"><table>
      <thead><tr><th>#</th><th>Strategy</th><th>Timeframe</th><th>Trades</th><th>Win rate</th><th></th><th>Net, month</th><th>On ₹2L</th><th>Profit factor</th><th>Max drawdown</th><th>Investment a trade</th><th>Real quotes</th></tr></thead>
      <tbody>
{rows}
      </tbody></table></div>
  </section>
  <section aria-labelledby="h-pers">
    <h2 id="h-pers">Does a month's top 20 keep winning?</h2>
    <div class="prose"><p>Every strategy ranked on one month; what that month's top 20 made the next month, one lot each, against an average 20 and the bottom 20 (model prices throughout).</p></div>
    <div class="tablewrap"><table>
      <thead><tr><th>Ranked on</th><th>Top 20 that month</th><th></th><th>Top 20 next month</th><th>Average 20 next month</th><th>Bottom 20 next month</th><th>Top 20 up next month</th></tr></thead>
      <tbody>
{prow}
      </tbody></table></div>
  </section>
  <section aria-labelledby="h-how">
    <h2 id="h-how">How it was tested</h2>
    <ul class="prose">{"".join(f"<li>{e(x)}</li>" for x in method_items(g))}</ul>
  </section>
  <footer><p>Code and outputs: <code>backend/research/option_buying_top20_2026_10/</code>; <code>obt_run.py</code> replays, <code>obt_report.py</code> rebuilds this page.</p></footer>
</div>
"""
    OUT.mkdir(exist_ok=True)
    (OUT / "option-buying-top20.html").write_text(head + body, encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    g = load()
    write_md(g)
    write_html(g)
    for i, r in enumerate(g["top"], 1):
        print(i, r["name"], r["trades"], r["win_rate"], round(r["net"]), r["profit_factor"], round(r["max_dd"]), round(r["avg_premium"] * LOT), f"{r['trades_real']}/{r['trades']}")
    print("basket", {k: round(v) for k, v in g["basket"].items()}, "dupes", g["dupes"][:5])
    print("persistence top", round(g["p_top"]), "avg", round(g["p_avg"]), "bottom", round(g["p_bot"]), "up", g["p_up"], "beat", g["p_beat"])


if __name__ == "__main__":
    main()
