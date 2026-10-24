"""Report for the trader-style test: report/trader-style-gold-test.html and REPORT.md."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import html
import json
import math

import numpy as np
import pandas as pd

import ts_strategies as S
from ts_run import COSTS

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"
REPO = "https://github.com/raghavar8088/Alpha-engine-in/tree/main/backend/research/xauusd_trader_style_2026_10"
INTRADAY = "https://claude.ai/artifact/YVNZjkqgMz3mKhQYe74N4S"
MK = [("XAUUSD_IS", "Gold 2010–21"), ("XAUUSD_OOS", "Gold 2021–26"), ("XAGUSD_ALL", "Silver 2010–26"), ("EURUSD_ALL", "EUR/USD 2010–26"), ("GBPUSD_ALL", "GBP/USD 2010–26")]


def esc(x):
    return html.escape("" if x is None else str(x))


def r(v, dp=3):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    return f"{v:+.{dp}f}R".replace("-", "−")


def pct(v, dp=1, sign=True):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    s = f"{v * 100:+.{dp}f}%" if sign else f"{v * 100:.{dp}f}%"
    return s.replace("-", "−")


def tone(v):
    return "" if v is None or v == 0 or (isinstance(v, float) and math.isnan(v)) else ("pos" if v > 0 else "neg")


def main():
    ev = json.load(open(RES / "evaluation.json"))
    lock = json.load(open(RES / "selection_locked.json"))
    setups = {s.key: s for s in S.SETUPS}
    main_rows, cost_rows, acct_rows = [], [], []
    for key, s in setups.items():
        e = ev["setups"][key]
        lk = lock["setups"][key]
        cells = []
        for mk, _ in MK:
            m = e["markets"].get(mk, {})
            b = m.get("base", {})
            n = b.get("trades", 0)
            cells.append(f'<td class="{tone(b.get("expectancy_R"))}"><b>{r(b.get("expectancy_R"))}</b><div class="sub">{n} trades · {pct(b.get("win_rate"), 0, False)} won</div></td>')
        main_rows.append(f'<tr><td class="l"><b>{esc(s.name)}</b><div class="sub">{esc(e["label"])}</div><div class="sub">in-sample best {r(lk.get("best_IS_expectancy_R"))} ({esc(lk.get("best_label"))})</div></td>{"".join(cells)}</tr>')
        for mk, nm in MK:
            p = RES / "trades" / f"{key}_{mk}.csv"
            if not p.exists():
                continue
            t = pd.read_csv(p)
            sym = mk.split("_")[0]
            gross = float((t["side"] * (t["xp"] - t["ep"]) / t["risk"]).mean())
            cost_r = float((COSTS[sym]["base"] / t["risk"]).mean())
            m = e["markets"][mk]
            cost_rows.append(f'<tr><td class="l">{esc(s.name)}</td><td class="l">{esc(nm)}</td><td class="{tone(gross)}">{r(gross)}</td><td class="neg">−{cost_r:.3f}R</td>'
                             f'<td class="{tone(m["base"]["expectancy_R"])}"><b>{r(m["base"]["expectancy_R"])}</b></td>'
                             f'<td class="{tone(m.get("low", {}).get("expectancy_R"))}">{r(m.get("low", {}).get("expectancy_R"))}</td>'
                             f'<td>{r(m.get("random_entry_R"))}</td><td>{float(t["risk"].mean()):.4g}</td></tr>')
        for mk, nm in MK:
            m = e["markets"].get(mk)
            if not m or not m["base"].get("trades"):
                continue
            a = m["accounts"]["1%"]
            acct_rows.append(f'<tr><td class="l">{esc(s.name)}</td><td class="l">{esc(nm)}</td><td>{m["trades_per_month"]:.1f}</td>'
                             f'<td class="{tone(a["month_compounded"])}"><b>{pct(a["month_compounded"], 2)}</b></td><td>{pct(a["months_up"], 0, False)}</td>'
                             f'<td class="neg">{pct(a["worst_month"])}</td><td class="neg">{pct(a["max_drawdown"], 0)}</td><td class="{tone(a["total"])}">{pct(a["total"], 0)}</td>'
                             f'<td>{m["base"]["longest_losing_streak"]}</td></tr>')
    css = (ROOT.parent / "xauusd_intraday_2026_10" / "report" / "xauusd-intraday-study.html").read_text(encoding="utf-8")
    style = css[css.index("<style>"):css.index("</style>") + 8]
    head_mk = "".join(f"<th>{esc(n)}</th>" for _, n in MK)
    page = f'''<title>Trader-Style Gold Test</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..800&family=JetBrains+Mono:wght@400;600&family=Source+Sans+3:wght@400;600;700&display=swap">
{style}
<div class="wrap">
<header style="display:flex;flex-direction:column;gap:12px">
  <div class="eyebrow">Backtest · how profitable gold traders say they trade · one-minute bars · 2010–2026</div>
  <h1>Do the profitable traders' rules work when coded?</h1>
  <div class="meta"><span><b>3</b> setups</span><span><b>{lock["configurations_tested"]}</b> parameter sets</span><span>chosen on gold <b>2010-01 → 2021-09</b></span>
  <span>then run unchanged on <b>silver, EUR/USD, GBP/USD</b></span><span>rules registered before any result · code <code>{esc(lock["code_hash"])}</code></span></div>
  <div class="lede">No. The rules were coded the way successful gold traders describe them:
  <ul class="plain">
    <li>risk 1% of the account per trade with a fixed stop;</li>
    <li>target 2–3 times the risk;</li>
    <li>one setup at a fixed time (the London open or the New York open);</li>
    <li>at most one trade a day, and only in the direction of the daily trend.</li>
  </ul>
  On gold 2010–2021 the best setting of each setup still lost money after costs, and the same rules lost on silver, EUR/USD and GBP/USD.
  Only gold 2021–2026, a strong bull market, showed a small profit, below the bar set in advance.</div>
  <p class="callout"><b>Why.</b> The setups are slightly better than chance before costs: +0.00R to +0.14R a trade. Costs take 0.04R to 0.43R a trade, because the stops are tight and a fixed cost is a large share of a small stop.
  Risk control decides how fast an account wins or loses; it cannot make a setup with no edge after costs profitable. (R = the amount risked on the trade.)</p>
  <p class="sub">Rules: <a href="{REPO}/PREREGISTRATION.md" target="_blank" rel="noopener">PREREGISTRATION.md</a>, written before any result. Earlier studies: <a href="{INTRADAY}" target="_blank" rel="noopener">intraday</a>.
  Backtests on past prices; not a forecast.</p>
</header>

<section><h2>Average result per trade, after base costs</h2>
<div class="tw"><table class="data"><thead><tr><th class="l">Setup (default settings shown; none qualified in-sample)</th>{head_mk}</tr></thead><tbody>{"".join(main_rows)}</tbody></table></div>
<p class="sub">Pass needed +0.15R a trade on gold out of sample (profit factor above 1.2) and a positive result in at least 2 of the 3 other markets. No setup reached +0.15R in-sample, so none was eligible.
The New York pullback rarely triggers on EUR/USD and GBP/USD: its stop must sit 0.1–0.5 daily ATRs away, and a five-minute pullback there is usually smaller.</p>
</section>

<section><h2>Where the money goes</h2>
<div class="tw"><table class="data"><thead><tr><th class="l">Setup</th><th class="l">Market</th><th>Before costs</th><th>Costs</th><th>After base costs</th><th>Low-cost account (gold)</th><th>Same trades, random days</th><th>Average stop (price)</th></tr></thead><tbody>{"".join(cost_rows)}</tbody></table></div>
<p class="sub">Costs in R = the round-trip cost ÷ the stop distance. Gold's round trip is about $0.67 an ounce at base costs. With a $3.60 stop that is 0.19R; with an $18 stop it is 0.04R. The setups beat the same trades placed on random days, so the timing has some value, but less than the costs.</p>
</section>

<section><h2>The account at 1% risk a trade</h2>
<div class="tw"><table class="data"><thead><tr><th class="l">Setup</th><th class="l">Market</th><th>Trades a month</th><th>A month, compounded</th><th>Months up</th><th>Worst month</th><th>Max drawdown</th><th>Total</th><th>Longest losing streak (trades)</th></tr></thead><tbody>{"".join(acct_rows)}</tbody></table></div>
</section>

<section><h2>What this rules in, and out</h2>
<ul class="plain">
<li><b>Ruled out:</b> trend-aligned session breakouts and pullbacks with fixed stops and 2–3R targets, as commonly taught, on gold, silver, EUR/USD and GBP/USD, at ordinary retail costs.</li>
<li><b>Not tested:</b> the trader's judgment, meaning which days to skip, how to read the news and how to manage a trade by feel. That can only be tested by keeping a journal of real or paper trades over months.</li>
<li><b>One lead:</b> costs were smallest in R where the stops were widest (gold 2021–26, stops of about $11–18). A setup that trades less often with wider stops faces a lower cost hurdle. It would still need a real edge before costs of at least +0.2R.</li>
</ul></section>
</div>'''
    out = ROOT / "report"
    out.mkdir(exist_ok=True)
    (out / "trader-style-gold-test.html").write_text(page, encoding="utf-8")
    md = ["# Trader-style gold setups: do the profitable traders' rules work when coded?", "",
          f"Rules registered first (PREREGISTRATION.md); selection on gold 2010-01 → 2021-09; locked code `{lock['code_hash']}`. Average R a trade after base costs:", "",
          "| Setup | " + " | ".join(n for _, n in MK) + " |", "|---" * (len(MK) + 1) + "|"]
    for key, s in setups.items():
        e = ev["setups"][key]
        md.append(f"| {s.name} | " + " | ".join(f"{r(e['markets'].get(mk, {}).get('base', {}).get('expectancy_R'))} ({e['markets'].get(mk, {}).get('base', {}).get('trades', 0)})" for mk, _ in MK) + " |")
    md += ["", "No setup qualified in-sample (needed +0.15R). Before costs the setups make +0.00R to +0.14R a trade; costs take 0.04R to 0.43R. Backtests; not a forecast."]
    (ROOT / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("written", out / "trader-style-gold-test.html")


if __name__ == "__main__":
    main()
