"""Report for the champion traders' intraday test: report/champions-intraday-test.html and REPORT.md.
Reads results/ (ch_run.py evaluate, ch_diagnostics.py); changes nothing there."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import html
import json
import math

import pandas as pd

import ch_strategies as S

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"
REPO = "https://github.com/raghavar8088/Alpha-engine-in/tree/main/backend/research/champions_intraday_2026_10"
EARLIER = {"position": "https://claude.ai/artifact/NDp8N4foGWVT2DFs12fGZN", "intraday": "https://claude.ai/artifact/YVNZjkqgMz3mKhQYe74N4S",
           "trader": "https://claude.ai/artifact/KjkfoKp8FM5pCks8Xo742F"}
MK = [("XAUUSD", "Gold"), ("SPXUSD", "S&P 500"), ("NSXUSD", "Nasdaq 100"), ("GRXEUR", "DAX")]
NAMES = dict(MK)
SHORT = {"crabel_orb": "Crabel breakout, every day", "crabel_nr": "Crabel breakout after a narrow day", "williams_vbo": "Williams volatility breakout",
         "williams_oops": "Williams Oops! gap reversal", "unger_range": "Unger first-hours breakout", "unger_reversal": "Unger false-breakout reversal",
         "unger_bias": "Unger time-of-day bias"}


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def pct(v, dp=3, sign=True) -> str:
    if nan(v):
        return "–"
    s = f"{v * 100:+.{dp}f}%" if sign else f"{v * 100:.{dp}f}%"
    return s.replace("-", "−")


def num(v, dp=2) -> str:
    return "–" if nan(v) else f"{v:+.{dp}f}".replace("-", "−")


def tone(v) -> str:
    return "" if nan(v) or v == 0 else ("pos" if v > 0 else "neg")


def chip(verdict: str) -> str:
    cls = {"TARGET": "ok", "EDGE": "ok", "WORKING": "ok"}.get(verdict, "no")
    return f'<span class="chip {cls}">{esc(verdict)}</span>'


def cfg_text(label: str) -> str:
    return label.replace("side=-1", "short").replace("side=1", "long").replace("start=", "start +").replace("hold=", "hold ")


def month_chart(monthly: dict) -> str:
    """Bars of the portfolio's out-of-sample months at 1x, to one scale."""
    items = list(monthly.items())
    vals = [v * 100 for _, v in items]
    lo, hi = min(-1.0, math.floor(min(vals))), max(1.0, math.ceil(max(vals)))
    W, H, left, right, top, bot = 920, 260, 46, 10, 12, 30
    pw, ph = W - left - right, H - top - bot
    y = lambda v: top + (hi - v) / (hi - lo) * ph
    bw = pw / len(vals)
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Monthly returns of the portfolio, out of sample, at 1x">']
    for t in range(int(lo), int(hi) + 1):
        out.append(f'<line class="grid{" zero" if t == 0 else ""}" x1="{left}" x2="{W - right}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="axis" x="{left - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{t:+d}%</text>'.replace("+0%", "0%").replace("-", "−"))
    for i, ((m, _), v) in enumerate(zip(items, vals)):
        x = left + i * bw + bw * 0.15
        y0, y1 = (y(v), y(0)) if v >= 0 else (y(0), y(v))
        out.append(f'<rect class="{"up" if v >= 0 else "down"}" x="{x:.1f}" y="{y0:.1f}" width="{bw * 0.7:.1f}" height="{max(y1 - y0, 0.8):.1f}"><title>{m}: {v:+.2f}%</title></rect>')
        if m.endswith("-01") or i == 0:
            out.append(f'<text class="axis" x="{x:.1f}" y="{H - 10}">{m[:4] if m.endswith("-01") else m}</text>')
    out.append("</svg>")
    return "".join(out)


def main() -> None:
    ev = json.loads((RES / "evaluation.json").read_text())
    dg = json.loads((RES / "diagnostics.json").read_text())
    lock = json.loads((RES / "selection_locked.json").read_text())
    sm = pd.read_csv(RES / "summary.csv")
    by = {(r["market"], r["family"]): r for r in ev["results"]}
    row = {(r.market, r.family): r for r in sm.itertuples()}
    P = ev["portfolios"]["unger_all_markets"]
    G = ev["portfolios"]["unger_gold_only"]
    o1, oh1 = P["OOS_base_1x"], P["OOS_harsh_1x"]
    lev = dg["leverage"]
    fams = [f.key for f in S.FAMILIES]
    best = sm.sort_values("OOS_avg", ascending=False).iloc[0]
    gold_pos = int((sm[sm.market == "XAUUSD"]["OOS_avg"] > 0).sum())
    gold_best = sm[sm.market == "XAUUSD"].sort_values("OOS_avg", ascending=False).iloc[0]
    n_edge = int((sm.verdict != "NO EDGE").sum())
    earlier = pd.read_csv(ROOT.parent / "xauusd_intraday_2026_10" / "results" / "summary.csv").set_index("family")

    # matrix: rule x market
    head = "".join(f"<th>{esc(n)}</th>" for _, n in MK)
    mrows = []
    for k in fams:
        fam = next(f for f in S.FAMILIES if f.key == k)
        cells = []
        for sym, _ in MK:
            r = row.get((sym, k))
            if r is None:
                cells.append("<td>–</td>")
                continue
            member = f"{sym}:{k}" in P["members"]
            cells.append(f'<td class="{tone(r.OOS_avg)}"><b>{pct(r.OOS_avg)}</b><div class="sub">{int(r.OOS_trades)} trades · t {num(r.OOS_t)}</div>'
                         f'<div class="sub">in-sample {pct(r.IS_avg)}{" · in portfolio" if member else ""}</div></td>')
        mrows.append(f'<tr><td class="l"><b>{esc(SHORT[k])}</b><div class="sub">{esc(fam.trader)}</div></td>{"".join(cells)}</tr>')

    # detail table
    drows = []
    for sym, nm in MK:
        for k in fams:
            r = row.get((sym, k))
            if r is None:
                continue
            drows.append(f'<tr><td class="l">{esc(nm)}</td><td class="l">{esc(SHORT[k])}<div class="sub">{esc(cfg_text(r.config))}</div></td>'
                         f'<td>{int(r.IS_trades)}</td><td class="{tone(r.IS_avg)}">{pct(r.IS_avg)}</td><td>{int(r.OOS_trades)}</td>'
                         f'<td class="{tone(r.OOS_avg)}"><b>{pct(r.OOS_avg)}</b></td><td>{num(r.OOS_t)}</td><td>{num(r.OOS_pf)}</td>'
                         f'<td class="{tone(r.OOS_avg_harsh)}">{pct(r.OOS_avg_harsh)}</td><td>{"–" if nan(r.timing_p) else f"{r.timing_p:.3f}"}</td>'
                         f'<td class="{tone(r.OOS_month_1x)}">{pct(r.OOS_month_1x, 2)}</td><td class="neg">{pct(r.OOS_10x_mdd, 0)}</td>'
                         f'<td>{esc(r.OOS_20x_ruined) if isinstance(r.OOS_20x_ruined, str) else "–"}</td><td>{chip(r.verdict)}</td></tr>')

    # leverage ladder
    lrows = []
    for L in (1, 3, 5, 10):
        i, o = lev[f"IS_{L}x"], lev[f"OOS_{L}x"]
        lrows.append(f'<tr><td class="l">{L}× a share</td><td class="{tone(i["mean_month"])}">{pct(i["mean_month"], 2)}</td><td class="neg">{pct(i["worst_month"], 1)}</td>'
                     f'<td class="neg">{pct(i["max_drawdown"], 0)}</td><td class="{tone(i["cagr"])}">{pct(i["cagr"], 1)}</td>'
                     f'<td class="{tone(o["mean_month"])}"><b>{pct(o["mean_month"], 2)}</b></td><td>{pct(o["median_month"], 2)}</td><td class="neg">{pct(o["worst_month"], 1)}</td>'
                     f'<td class="neg">{pct(o["max_drawdown"], 0)}</td><td class="{tone(o["cagr"])}">{pct(o["cagr"], 1)}</td></tr>')
    crow = "".join(f'<td class="{tone(v["mean"])}">{pct(v["mean"], 3)}<div class="sub">t {num(v["t"])}</div></td>' for v in dg["cost_multiple"].values())
    chead = "".join(f"<th>{esc(k.replace('x', '×'))}</th>" for k in dg["cost_multiple"])
    yrs = "".join(f'<td class="{tone(v["1x"])}">{pct(v["1x"], 1)}<div class="sub">{pct(v["10x"], 0)} at 10×</div></td>' for v in dg["years"].values())
    yhead = "".join(f"<th>{y}{' (from Oct)' if y == '2021' else (' (to 16 Oct)' if y == '2026' else '')}</th>" for y in dg["years"])
    bym = "".join(f'<li><b>{esc(NAMES[s])}</b> ({v["members"]} rule{"s" if v["members"] > 1 else ""}): {pct(v["mean"], 3)} a month to the whole account, t {num(v["t"])}</li>'
                  for s, v in sorted(dg["by_market"].items(), key=lambda kv: -kv[1]["mean"]))
    members = ", ".join(f"{NAMES[m.split(':')[0]]} {SHORT[m.split(':')[1]].lower()}" for m in P["members"])

    css = (ROOT.parent / "xauusd_intraday_2026_10" / "report" / "xauusd-intraday-study.html").read_text(encoding="utf-8")
    style = css[css.index("<style>"):css.index("</style>")]
    style += """
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.tile { background: var(--panel); border: 1px solid var(--rule); border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.tile .big { font-family: var(--display); font-size: 30px; font-weight: 800; font-stretch: 88%; line-height: 1.1; font-variant-numeric: tabular-nums; }
.tile .lab { font-size: 13px; color: var(--muted); }
.chartbox { background: var(--panel); border: 1px solid var(--rule); border-radius: 8px; padding: 10px 8px 4px; overflow-x: auto; }
svg.chart { width: 100%; min-width: 560px; height: auto; display: block; }
svg.chart .grid { stroke: var(--rule); stroke-width: 1; }
svg.chart .grid.zero { stroke: var(--muted); }
svg.chart .axis { fill: var(--muted); font-family: var(--mono); font-size: 11px; }
svg.chart rect.up { fill: var(--pos); } svg.chart rect.down { fill: var(--neg); }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.two > * { min-width: 0; }
</style>"""
    lede = (f"On gold, no. All seven rules lost money or broke even after costs out of sample, as in every earlier gold study. "
            f"On the stock-index futures these traders built the rules for, the breakouts show a small edge. No single rule is strong enough to pass on its own, "
            f"but run together the way Unger runs his systems, the {len(P['members'])} rules that were profitable in-sample made "
            f"{pct(o1['mean_month'], 2)} a month out of sample at 1× (t = {o1['t_months']:.1f}), with every calendar year positive. "
            f"That is about {lev['OOS_1x']['cagr'] * 100:.0f}% a year without leverage, and nowhere near 2% a trade.")
    page = f'''<title>Champions' Intraday Rules</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..800&family=JetBrains+Mono:wght@400;600&family=Source+Sans+3:wght@400;600;700&display=swap">
{style}
<div class="wrap">
<header style="display:flex;flex-direction:column;gap:12px">
  <div class="eyebrow">Backtest · Crabel, Williams, Unger · one-minute bars · gold, S&amp;P 500, Nasdaq 100, DAX · 2010–2026</div>
  <h1>Do the champions' intraday rules work?</h1>
  <div class="meta"><span><b>7</b> rules</span><span><b>{lock["configurations_tested"]}</b> settings tried in-sample</span><span>one setting locked per rule and market</span>
  <span>out of sample run once</span><span>rules written down first · code <code>{esc(lock["code_hash"])}</code></span></div>
  <p class="lede">{esc(lede)}</p>
  <p class="callout"><b>What 2% a trade means here.</b> A day trade on gold or an index moves well under 2%, so 2% is only reachable on the account, with leverage.
  At 20×, the most the study allows, 2% of the account needs +0.10% a trade on the position after costs. The best single rule made {pct(best.OOS_avg)} a trade out of sample
  ({esc(NAMES[best.market])}, {esc(SHORT[best.family].lower())}) but only {pct(best.IS_avg)} in-sample, and at 10× it fell {pct(best.OOS_10x_mdd, 0)} at its worst.</p>
  <p class="sub">Rules: <a href="{REPO}/PREREGISTRATION.md" target="_blank" rel="noopener">PREREGISTRATION.md</a>, written before any strategy ran. Code: <a href="{REPO}" target="_blank" rel="noopener">champions_intraday_2026_10</a>.
  Earlier studies: <a href="{EARLIER['position']}" target="_blank" rel="noopener">position trades</a>, <a href="{EARLIER['intraday']}" target="_blank" rel="noopener">gold intraday</a>,
  <a href="{EARLIER['trader']}" target="_blank" rel="noopener">trader-style rules</a>. Backtests on past prices; not a forecast.</p>
</header>

<div class="tiles">
  <div class="tile"><span class="big neg">{gold_pos} of 7</span><span class="lab">gold rules with a profit after costs out of sample (best: {pct(gold_best.OOS_avg)} a trade)</span></div>
  <div class="tile"><span class="big neg">{n_edge} of {len(sm)}</span><span class="lab">single rules that pass on their own (after correcting for {len(sm)} tests)</span></div>
  <div class="tile"><span class="big pos">{pct(o1["mean_month"], 2)}</span><span class="lab">a month for Unger's portfolio at 1×, out of sample (t {o1["t_months"]:.1f}; {pct(oh1["mean_month"], 2)} at double costs)</span></div>
  <div class="tile"><span class="big">{pct(lev["OOS_10x"]["mean_month"], 1)}</span><span class="lab">a month at 10× a share out of sample, with a {pct(lev["OOS_10x"]["max_drawdown"], 0)} drawdown; in-sample the same fell {pct(lev["IS_10x"]["max_drawdown"], 0)} at its worst</span></div>
</div>

<section><h2>Each rule, out of sample</h2>
<p>Average net result a trade at base costs, from October 2021 (December 2023 for the DAX) to 16 October 2026. Each market chose its own setting in 2010–2021, as Unger matches a method to a market.</p>
<div class="tw"><table class="data compact"><thead><tr><th class="l">Rule</th>{head}</tr></thead><tbody>{"".join(mrows)}</tbody></table></div>
<p class="sub">A rule passes on its own only with: a profit in-sample; at least 50 trades out of sample, profitable at base and double costs; a positive mean that survives the correction for {len(sm)} tests;
and better timing than the same trades on random days. None does. The closest are breakouts on the Nasdaq and the DAX (t ≈ 2, before the correction).</p>
</section>

<section><h2>Unger's way: run them together</h2>
<p>Unger runs many simple systems at once, so that a bad month for one is a good month for another. The portfolio fixed in advance takes every rule that made money in-sample:
{len(P["members"])} rules ({esc(members)}). Each gets an equal share of the account.</p>
<div class="chartbox">{month_chart(o1["monthly"])}</div>
<p class="sub">The portfolio's return each month out of sample, at 1×. {o1["months_up"] * 100:.0f}% of months were up; the best was {esc(list(dg["best_months"])[0])} ({pct(list(dg["best_months"].values())[0], 1)}), the tariff shock.</p>
<div class="tw"><table class="data compact"><thead><tr><th class="l">Leverage</th><th>In-sample month</th><th>Worst month</th><th>Max drawdown</th><th>A year</th>
<th>Out-of-sample month</th><th>Median month</th><th>Worst month</th><th>Max drawdown</th><th>A year</th></tr></thead><tbody>{"".join(lrows)}</tbody></table></div>
<p class="sub">In-sample is 2010–2021 (gold from January 2010, the indices from November 2010); out of sample is October 2021 to October 2026. "× a share" means each rule trades its slice of the account at that leverage.</p>
<div class="two">
<div class="card"><h3>Checks on the result</h3><ul class="plain">
<li><b>Not the market's own rise.</b> Buying every session's open and selling its close on the same markets made {pct(dg["drift_benchmark"]["mean"], 3)} a month (t {num(dg["drift_benchmark"]["t"])}).</li>
<li><b>The days matter.</b> The same trades moved to random days lost {pct(dg["placebo"]["mean_month_placebo_avg"], 3)} a month on average; none of {dg["placebo"]["sims"]:,} random versions did as well (p &lt; 0.001).</li>
<li><b>Not one lucky month.</b> Without its best month the t-statistic is {dg["without_best_1"]["t"]:.2f}; without its best three, {dg["without_best_3"]["t"]:.2f}.</li>
<li><b>Costs.</b> Still significant at double the futures costs (t {dg["cost_multiple"]["2x"]["t"]:.2f}); at three times, not (t {dg["cost_multiple"]["3x"]["t"]:.2f}); at six times it loses.</li>
<li><b>Weaker before.</b> In-sample the same portfolio made {pct(P["IS_base_1x"]["mean_month"], 2)} a month, about half the out-of-sample figure, with a {pct(P["IS_base_1x"]["max_drawdown"], 0)} drawdown at 1×.</li>
</ul></div>
<div class="card"><h3>Where the money came from</h3><ul class="plain">{bym}</ul>
<p class="sub">The Nasdaq's breakout rules carried it. The best months were {esc(", ".join(list(dg["best_months"])[:3]))}, months of large swings. Gold's one member, Crabel's breakout after an inside day, lost.</p></div>
</div>
<div class="tw"><table class="data compact"><thead><tr><th class="l">Costs × base</th>{chead}</tr></thead><tbody><tr><td class="l">Portfolio, out-of-sample month at 1×</td>{crow}</tr></tbody></table></div>
<div class="tw"><table class="data compact"><thead><tr><th class="l">Calendar year</th>{yhead}</tr></thead><tbody><tr><td class="l">Portfolio at 1×</td>{yrs}</tr></tbody></table></div>
</section>

<section><h2>Gold</h2>
<p>Every rule was given its best in-sample setting on gold's COMEX day session (08:20–13:30 New York) and then lost or broke even after costs out of sample. Gold's one in-sample winner, Crabel's breakout after an inside day,
made {pct(by[("XAUUSD", "crabel_nr")]["IS"]["base"]["avg"])} a trade in 2010–2021 and {pct(by[("XAUUSD", "crabel_nr")]["OOS"]["base"]["avg"])} after.
Gold alone as a portfolio lost {pct(G["OOS_base_1x"]["mean_month"], 2)} a month. The earlier gold study, on the 18:00–17:00 day, found the same for Crabel's breakout
({pct(earlier.loc["crabel", "OOS_avg"])} a trade) and Williams' breakout ({pct(earlier.loc["williams_day", "OOS_avg"])} a trade, a 20× account wiped out on {esc(earlier.loc["williams_day", "OOS_20x_ruined"])}).</p>
<p>The cause is the same as before: at retail costs a round trip takes $0.67 an ounce, and these rules' gross edge on gold is smaller than that.
Even at COMEX futures costs ($0.35) the best gold rule made {pct(sm[sm.market == "XAUUSD"]["OOS_avg_futures"].max())} a trade.</p>
</section>

<section><h2>Every rule in detail</h2>
<div class="tw"><table class="data grid"><thead><tr><th class="l">Market</th><th class="l">Rule and setting chosen in-sample</th><th>Trades in</th><th>Average in</th><th>Trades out</th><th>Average out</th>
<th>t</th><th>Profit factor</th><th>Double costs</th><th>Timing p</th><th>Average month at 1×</th><th>Max drawdown at 10×</th><th>20× wiped out</th><th>Verdict</th></tr></thead><tbody>{"".join(drows)}</tbody></table></div>
<p class="sub">"Timing p" is the share of 2,000 random placements (same side, entry minute and holding time on random days; for the bias rule, a random minute on the same days) that did as well.
The bias rules' "start +N" is minutes after the open.</p>
</section>

<section><h2>Not tested, and why</h2><ul class="plain">
<li><b>Paul Rotter</b> scalped German bond futures for 3–5 ticks a trade by reading the order book, at an exchange member's costs. One-minute bars carry no order book and no queue position.
On gold, a $0.40 retail spread is already 4 COMEX ticks, about the size of his whole target.</li>
<li><b>The forex-contest winners</b> have not published their methods.</li>
<li><b>Michael Cook and Williams' original rules</b> hold 2–5 days, so they are not intraday. Williams' swing breakout was tested in the position study and failed.</li>
</ul></section>

<section><h2>Data and limits</h2><ul class="plain">
<li><b>Source.</b> HistData one-minute bars, free. Their clocks are New York time with daylight saving in every market (checked at each session's opening and data-release minutes).</li>
<li><b>Defects found and cut out before any strategy ran:</b> February–July 2023 in every market (about half the minutes missing); the DAX file from June 2020 to December 2023, which holds Euro Stoxx 50 prices;
WTI crude, which has no data for 2024 to May 2026 and jumps at contract rolls.</li>
<li><b>Gold's out-of-sample years are not unseen.</b> Two earlier studies used them. The index markets are new to this repository.</li>
<li><b>Fills are modelled,</b> worst case inside each minute, at futures-like costs for the indices and retail CFD costs for gold. No order of this study was ever placed.</li>
<li><b>The DAX's out-of-sample window is short:</b> December 2023 to October 2026.</li>
<li><b>For a resident of India,</b> money sent abroad under the Liberalised Remittance Scheme cannot be used for margin trading, so these US and German futures are out of reach.
The Indian equivalent, NIFTY and BANKNIFTY futures, was not part of this test.</li>
</ul></section>
</div>'''
    out = ROOT / "report"
    out.mkdir(exist_ok=True)
    (out / "champions-intraday-test.html").write_text(page, encoding="utf-8")
    md = ["# Champion traders' intraday rules: do they work?", "",
          f"Rules registered first (PREREGISTRATION.md); one setting per rule and market chosen in-sample and locked (code `{lock['code_hash']}`); out of sample run once. "
          "Average net return a trade out of sample, base costs (trades):", "",
          "| Rule | " + " | ".join(n for _, n in MK) + " |", "|---" * (len(MK) + 1) + "|"]
    for k in fams:
        md.append(f"| {SHORT[k]} | " + " | ".join(f"{pct(row[(s, k)].OOS_avg)} ({int(row[(s, k)].OOS_trades)})" if (s, k) in row else "–" for s, _ in MK) + " |")
    md += ["", f"No single rule passes. Unger's portfolio ({len(P['members'])} rules that were profitable in-sample, equal shares): {pct(o1['mean_month'], 2)} a month out of sample at 1× "
           f"(t {o1['t_months']:.2f}; {pct(oh1['mean_month'], 2)} at double costs), verdict {P['verdict']}. Gold: no rule better than break-even "
           f"(best {pct(gold_best.OOS_avg)} a trade). Backtests; not a forecast."]
    (ROOT / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("written", out / "champions-intraday-test.html")


if __name__ == "__main__":
    main()
