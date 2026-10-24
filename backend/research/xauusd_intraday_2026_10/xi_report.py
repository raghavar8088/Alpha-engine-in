"""Build the intraday report (report/xauusd-intraday-study.html and REPORT.md) from results/."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import html
import inspect
import json
import math

import numpy as np
import pandas as pd

import xi_strategies as S

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"
REPO = "https://github.com/raghavar8088/Alpha-engine-in/tree/main/backend/research/xauusd_intraday_2026_10"
POSITION_STUDY = "https://claude.ai/artifact/NDp8N4foGWVT2DFs12fGZN"
CAT = {"breakout": "Breakout", "volatility": "Volatility", "session": "Session", "trend": "Intraday momentum", "mean reversion": "Mean reversion"}


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def pct(v, dp=2, sign=True):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "–"
    s = f"{v * 100:+.{dp}f}%" if sign else f"{v * 100:.{dp}f}%"
    return s.replace("-", "−")


def num(v, dp=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    if isinstance(v, float) and math.isinf(v):
        return "∞"
    return f"{v:.{dp}f}".replace("-", "−")


def tone(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def chip(ok: bool, text: str) -> str:
    return f'<span class="chip {"ok" if ok else "no"}">{esc(text)}</span>'


def load():
    lock = json.loads((RES / "selection_locked.json").read_text())
    det = json.loads((RES / "oos_detail.json").read_text())
    summ = pd.read_csv(RES / "summary.csv")
    diag = json.loads((RES / "diagnostics.json").read_text()) if (RES / "diagnostics.json").exists() else {}
    dm = json.loads((RES / "data_minute.json").read_text())
    return lock, det, summ, diag, dm


def page(lock, det, summ, diag, dm) -> str:
    fams = {f.key: f for f in S.FAMILIES}
    rules = lock["rules"]
    tgt = rules["target_position_per_trade"]
    rows = []
    order = sorted(summ.itertuples(), key=lambda r: (not r.PASS, r.is_status != "selected", -(r.OOS_avg if r.OOS_avg == r.OOS_avg else -9)))
    for n, r in enumerate(order, 1):
        f = fams[r.family]
        e = lock["families"][r.family]
        if r.PASS:
            verdict = chip(True, "PASS (as tested)") + ' <span class="chip warn">fails with realistic fills</span>'
            why = f"{pct(r.OOS_avg, 3)} a trade over {int(r.OOS_trades)} out-of-sample trades"
        elif r.is_status == "selected":
            verdict = chip(False, "FAIL")
            why = f"out-of-sample {pct(r.OOS_avg, 3)} a trade"
        else:
            verdict = chip(False, "FAIL")
            why = f"in-sample best {pct(e['best_is_avg'], 3)} a trade ({esc(e['best_is_label'])}); needs {pct(tgt, 2)}"
        lev = r.lev_for_2pct
        rows.append(f'<tr class="{"pass" if r.PASS else ""}"><td>{n}</td><td class="l"><b>{esc(f.name)}</b><div class="sub">{esc(e["label"])}</div></td>'
                    f'<td class="l sub">{esc(CAT.get(f.category, f.category))}</td><td class="l">{verdict}<div class="sub why">{why}</div></td>'
                    f'<td>{int(r.IS_trades) if r.IS_trades == r.IS_trades else "–"}</td><td class="{tone(r.IS_avg)}">{pct(r.IS_avg, 3)}</td>'
                    f'<td>{int(r.OOS_trades) if r.OOS_trades == r.OOS_trades else "–"}</td><td class="{tone(r.OOS_avg)}"><b>{pct(r.OOS_avg, 3)}</b></td>'
                    f'<td>{num(r.OOS_pf)}</td><td class="{tone(r.OOS_avg_C2)}">{pct(r.OOS_avg_C2, 3)}</td><td>{pct(r.random_avg, 3)}</td>'
                    f'<td>{num(lev, 0) + "×" if lev == lev and lev is not None else "never"}</td>'
                    f'<td class="{tone(r.OOS_20x_total)}">{pct(r.OOS_20x_total, 0)}{"<div class=sub>wiped out " + esc(r.OOS_20x_ruined) + "</div>" if isinstance(r.OOS_20x_ruined, str) else ""}</td></tr>')
    ranked = ('<div class="tw"><table class="data"><thead><tr><th>#</th><th class="l">Strategy</th><th class="l">Type</th><th class="l">Verdict</th>'
              '<th>IS trades</th><th>IS avg / trade</th><th>OOS trades</th><th>OOS avg / trade</th><th>OOS profit factor</th><th>OOS avg, harsh costs</th>'
              '<th>Same trades, random days</th><th>Leverage for 2% a trade</th><th>Account at 20×, OOS</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")
    # the pass, in detail
    passed = [r for r in summ.itertuples() if r.PASS]
    detail = ""
    if passed and diag:
        k = passed[0].family
        f = fams[k]
        d = det["families"][k]
        ds_is, ds_oos = diag["IS"], diag["OOS"]

        def line(lbl, i, o, fmt=lambda v: pct(v, 3)):
            return f'<tr><td class="l">{esc(lbl)}</td><td class="{tone(i) if isinstance(i, float) else ""}">{fmt(i)}</td><td class="{tone(o) if isinstance(o, float) else ""}"><b>{fmt(o)}</b></td></tr>'

        stress = [
            line("As tested: stop orders filled at their level", ds_is["C1"]["avg"], ds_oos["C1"]["avg"]),
            line("Harsh costs (spread $0.50, slippage $0.25 a side)", d["IS"]["C2"]["avg"], d["OOS"]["C2"]["avg"]),
            *[line(f"Extra slippage {kk} a side on every fill", ds_is["extra_slippage"][kk]["avg"], ds_oos["extra_slippage"][kk]["avg"]) for kk in ("+$1", "+$2", "+$3", "+$5")],
            line("Entry at the close of the minute the stop triggered", ds_is["fill_trigger_close"]["avg"], ds_oos["fill_trigger_close"]["avg"]),
            line("Entry at the open of the next minute", ds_is["fill_next_open"]["avg"], ds_oos["fill_next_open"]["avg"]),
            line("Placebo: the same straddle on every non-payroll weekday", ds_is["placebo_non_payroll_days"]["avg"], ds_oos["placebo_non_payroll_days"]["avg"]),
            f'<tr><td class="l">Break-even extra slippage a side</td><td>${num(ds_is["breakeven_extra_slippage_usd_a_side"])}</td><td><b>${num(ds_oos["breakeven_extra_slippage_usd_a_side"])}</b></td></tr>',
        ]
        acc = []
        for name, lab in (("as_tested", "As tested"), ("entry_at_trigger_close", "Entry one minute late")):
            for L in ("10x", "20x"):
                ai, ao = ds_is["accounts"][f"{name}_{L}"], ds_oos["accounts"][f"{name}_{L}"]
                acc.append(f'<tr><td class="l">{esc(lab)}, {L.replace("x", "×")}</td><td class="{tone(ai["total_return"])}">{pct(ai["total_return"], 0)}</td>'
                           f'<td class="{tone(ai["cagr"])}">{pct(ai["cagr"], 1)}</td><td class="neg">{pct(ai["max_drawdown"], 0)}</td>'
                           f'<td class="{tone(ao["total_return"])}"><b>{pct(ao["total_return"], 0)}</b></td><td class="{tone(ao["cagr"])}">{pct(ao["cagr"], 1)}</td>'
                           f'<td class="neg">{pct(ao["max_drawdown"], 0)}</td></tr>')
        by_year = "".join(f'<tr><td>{y}</td><td>{v["trades"]}</td><td class="{tone(v["avg"])}">{pct(v["avg"], 3)}</td></tr>'
                          for y, v in list(ds_is["by_year"].items()) + list(ds_oos["by_year"].items()))
        months = ""
        for name, lab in (("as_tested_10x", "As tested, 10×"), ("entry_at_trigger_close_10x", "Entry one minute late, 10×")):
            mm = ds_oos["monthly"][name]
            by_y = {}
            for ym, v in mm.items():
                by_y.setdefault(int(ym[:4]), {})[int(ym[5:7])] = v
            body = []
            for y in sorted(by_y):
                cells = "".join(f'<td><span class="{tone(by_y[y].get(m_))}">{pct(by_y[y][m_], 1) if (m_ in by_y[y] and by_y[y][m_] != 0) else ("·" if m_ in by_y[y] else "")}</span></td>' for m_ in range(1, 13))
                yr = float(np.prod([1 + x for x in by_y[y].values()]) - 1)
                body.append(f'<tr><td class="l"><b>{y}</b></td>{cells}<td class="{tone(yr)}"><b>{pct(yr, 1)}</b></td></tr>')
            head = "".join(f"<th>{m_}</th>" for m_ in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
            months += (f'<h4>Monthly account returns out of sample: {esc(lab)}</h4><div class="tw"><table class="data compact grid"><thead><tr><th class="l">Year</th>{head}<th>Year</th></tr></thead>'
                       f'<tbody>{"".join(body)}</tbody></table></div>')
        o = d["OOS"]["C1"]
        detail = f'''
<section id="pass"><h2>The one pass, and why it does not hold up</h2>
<article class="card">
<div class="eyebrow">{esc(CAT.get(f.category))} · US payroll Fridays, 08:30 New York</div>
<h3>{esc(f.name)}</h3>
<p><b>Rules.</b> {esc(f.rules)} <b>Locked parameters:</b> <code>{esc(d["label"])}</code>.</p>
<p><b>Stop-loss and take-profit.</b> {esc(f.stops)}</p>
<p><b>Source.</b> {esc(f.source)}</p>
<p>Out of sample it made {pct(o["avg"], 3)} a trade over {o["trades"]} trades (profit factor {num(o["profit_factor"])}, {pct(o["win_rate"], 0, False)} winners), about $7 a trade on gold near $2,700.
That is 2% of the account a trade at about {num(d["OOS"].get("leverage_for_2pct"), 0)}× leverage. The same entries on random days averaged {pct(d["OOS"].get("random_mean_avg"), 3)}, so the payroll release is what pays,
and the same straddle on every other weekday lost money. In-sample it earned {pct(d["IS"]["C1"]["avg"], 3)} a trade (t = {num(lock["families"][k]["IS_t"])}), the only one of {lock["configurations_tested"]} configurations to clear the bar.</p>
<p><b>The catch.</b> The test fills the stop order exactly at its level in the minute the jobs report comes out. Gold moves several dollars in that minute and spreads widen, so real stop orders fill further away.
Filled at the close of that minute, or at the next minute's open, the out-of-sample average falls to {pct(ds_oos["fill_trigger_close"]["avg"], 3)} a trade and the in-sample average to {pct(ds_is["fill_trigger_close"]["avg"], 3)}.
In-sample, $1 of extra slippage a side already makes it a loser.</p>
<h4>Stress tests (base costs unless stated)</h4>
<div class="tw"><table class="data"><thead><tr><th class="l">Variant</th><th>In-sample avg / trade</th><th>Out-of-sample avg / trade</th></tr></thead><tbody>{"".join(stress)}</tbody></table></div>
<h4>The account at 10× and 20×</h4>
<div class="tw"><table class="data"><thead><tr><th class="l">Fills, leverage</th><th>IS total</th><th>IS CAGR</th><th>IS max drawdown</th><th>OOS total</th><th>OOS CAGR</th><th>OOS max drawdown</th></tr></thead><tbody>{"".join(acc)}</tbody></table></div>
<h4>Year by year (unlevered, as tested)</h4>
<div class="tw"><table class="data compact"><thead><tr><th>Year</th><th>Trades</th><th>Average a trade</th></tr></thead><tbody>{by_year}</tbody></table></div>
{months}
<p class="sub">A dot is a month with no trade (payrolls fall once a month; a few releases were cancelled or rescheduled). The account compounds trade by trade at the stated leverage.</p>
</article>
</section>'''
    best_fail = sorted((lock["families"][k]["best_is_avg"], k) for k in lock["families"] if lock["families"][k]["status"] != "selected")
    others = summ[~summ["PASS"]]
    o_lo, o_hi = float(others["OOS_avg"].min()), float(others["OOS_avg"].max())
    is_best = max(v for v, _ in best_fail) if best_fail else None
    gross = []
    for k in others["family"]:
        t = pd.read_csv(RES / "trades" / f"{k}.csv")
        gross.append(float(t[t["window"] == "OOS"]["gross"].mean()))
    g_lo, g_hi = min(gross), max(gross)
    ruined = [(fams[r.family].name.split(" (")[0], r.OOS_20x_ruined) for r in others.itertuples() if isinstance(r.OOS_20x_ruined, str)]
    near_zero = int((others["OOS_20x_total"] <= -0.9).sum())
    beat = [(fams[r.family].name.split(" (")[0], r.timing_p, r.OOS_avg) for r in others.itertuples() if r.timing_p == r.timing_p and r.timing_p < 0.05]
    if beat:
        beat_txt = ("Out of sample, " + "; ".join(f"{n} (p = {num(p_, 3)} before correcting for {len(summ)} tests)" for n, p_, _ in beat)
                    + f" beat the same trades placed at the same clock times on random days by more than chance would explain, yet made only "
                    + ", ".join(pct(a_, 3) for _, _, a_ in beat) + " a trade. The rest did no better than random days.")
    else:
        beat_txt = "Out of sample, none beat the same trades placed at the same clock times on random days by more than chance would explain."
    fail_line = ", ".join(f"{fams[k].name.split(' (')[0]} {pct(v, 3)}" for v, k in sorted(best_fail, reverse=True)[:4])
    reg = "".join(f'<tr><td class="l"><b>{esc(f.name)}</b><div class="sub">{esc(CAT.get(f.category))}</div></td><td class="l">{esc(f.rules)}</td>'
                  f'<td class="l">{esc(f.stops)}</td><td class="l sub">{esc(f.sizing_published)}</td>'
                  f'<td class="l sub">{esc("; ".join(f"{a}: {", ".join(str(x) for x in v)}" for a, v in f.grid.items()))} <b>({len(list(f.configs()))})</b></td>'
                  f'<td class="l sub">{esc(f.source)} <a href="{esc(f.url)}" target="_blank" rel="noopener">link</a></td></tr>' for f in S.FAMILIES)
    code = ""
    if passed:
        code = f'<pre><code>{esc(inspect.getsource(fams[passed[0].family].fn))}</code></pre>'
    spreads = ", ".join(f"{y}: ${v:.2f}" for y, v in dm["median_spread_by_year"].items() if int(y) >= 2010)
    oos = det["windows"]["OOS"]
    return f'''<title>XAUUSD Intraday Study</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..800&family=JetBrains+Mono:wght@400;600&family=Source+Sans+3:wght@400;600;700&display=swap">
<style>
/* Layout: one reading column for prose; tables and the strategy card run full width in the same gutter. */
:root {{
  --bg: #f6f7f5; --panel: #ffffff; --ink: #17191d; --muted: #5d636c; --rule: #d9dbd6;
  --gold: #8b6414; --gold-soft: #f2ead8; --pos: #1d7a4b; --neg: #b23a30; --warn: #94650a;
  --display: "Archivo", "Helvetica Neue", Arial, sans-serif; --body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #121316; --panel: #191b1f; --ink: #ebe8e1; --muted: #a3a8b0; --rule: #2d3036;
  --gold: #d8aa47; --gold-soft: #2c2616; --pos: #55c38b; --neg: #f07a6c; --warn: #e3b14c; color-scheme: dark; }} }}
:root[data-theme="dark"] {{ --bg: #121316; --panel: #191b1f; --ink: #ebe8e1; --muted: #a3a8b0; --rule: #2d3036;
  --gold: #d8aa47; --gold-soft: #2c2616; --pos: #55c38b; --neg: #f07a6c; --warn: #e3b14c; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--ink); font-family: var(--body); font-size: 16px; line-height: 1.55; }}
.wrap {{ max-width: 1120px; margin: 0 auto; padding-inline: 20px; padding-block: 28px 64px; display: flex; flex-direction: column; gap: 32px; }}
h1, h2, h3, h4 {{ font-family: var(--display); text-wrap: balance; margin: 0; }}
h1 {{ font-size: clamp(30px, 5vw, 44px); font-weight: 800; font-stretch: 85%; line-height: 1.05; }}
h2 {{ font-size: 24px; font-weight: 750; font-stretch: 90%; padding-bottom: 6px; border-bottom: 2px solid var(--gold); }}
h3 {{ font-size: 21px; font-weight: 750; font-stretch: 92%; }}
h4 {{ font-size: 13px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); margin-top: 8px; }}
section {{ display: flex; flex-direction: column; gap: 14px; }}
p {{ margin: 0; max-width: 74ch; }}
.lede {{ font-size: 19px; max-width: 68ch; }}
.eyebrow {{ font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--gold); font-weight: 700; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13.5px; color: var(--muted); }}
.meta b {{ color: var(--ink); font-weight: 600; }}
a {{ color: var(--gold); }}
code, pre {{ font-family: var(--mono); font-size: 12.5px; }}
code {{ background: var(--gold-soft); padding: 1px 5px; border-radius: 4px; }}
pre {{ background: var(--panel); border: 1px solid var(--rule); border-radius: 8px; padding: 14px; overflow-x: auto; margin: 0; }}
pre code {{ background: none; padding: 0; }}
.tw {{ overflow-x: auto; border: 1px solid var(--rule); border-radius: 8px; background: var(--panel); }}
table.data {{ border-collapse: collapse; width: 100%; font-size: 13.5px; font-variant-numeric: tabular-nums; }}
table.data th {{ font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); text-align: right; padding: 9px 10px; border-bottom: 1px solid var(--rule); vertical-align: bottom; }}
table.data td {{ padding: 8px 10px; border-bottom: 1px solid var(--rule); text-align: right; font-family: var(--mono); font-size: 12.5px; vertical-align: top; }}
table.data tr:last-child td {{ border-bottom: none; }}
table.data .l {{ text-align: left; font-family: var(--body); font-size: 13.5px; }}
table.data tr.pass td {{ background: var(--gold-soft); }}
table.compact td, table.compact th {{ padding: 6px 10px; }}
table.grid td, table.grid th {{ padding: 5px 7px; font-size: 11.5px; }}
.sub {{ font-size: 12px; color: var(--muted); font-weight: 400; text-transform: none; letter-spacing: 0; font-family: var(--body); }}
.why {{ margin-top: 3px; max-width: 36ch; }}
.pos {{ color: var(--pos); }} .neg {{ color: var(--neg); }}
.chip {{ display: inline-block; font-size: 11.5px; font-weight: 700; letter-spacing: 0.04em; padding: 2px 8px; border-radius: 999px; border: 1px solid currentColor; margin: 0 4px 3px 0; }}
.chip.ok {{ color: var(--pos); }} .chip.no {{ color: var(--neg); }} .chip.warn {{ color: var(--warn); }}
.card {{ background: var(--panel); border: 1px solid var(--rule); border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 12px; }}
.callout {{ border-left: 3px solid var(--gold); padding: 10px 14px; background: var(--panel); border-radius: 0 8px 8px 0; max-width: 82ch; }}
ul.plain {{ margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; max-width: 84ch; }}
</style>
<div class="wrap">
<header style="display:flex;flex-direction:column;gap:12px">
  <div class="eyebrow">Intraday backtest · spot gold (XAUUSD) · one-minute bars · 2010–2026</div>
  <h1>Can an intraday gold strategy make 2% a trade?</h1>
  <div class="meta"><span><b>{len(S.FAMILIES)}</b> published intraday families</span><span><b>{lock["configurations_tested"]}</b> parameter sets</span>
    <span>in-sample <b>{esc(lock["in_sample"][0][:7])} → {esc(lock["in_sample"][1][:7])}</b></span><span>out-of-sample <b>{esc(oos[0][:7])} → {esc(oos[1])}</b></span>
    <span>selection locked · code <code>{esc(lock["code_hash"])}</code></span></div>
  <p class="lede">Not reliably. Ten of the eleven intraday families fall far short of the {pct(tgt, 2, False)} a trade needed: at their best in-sample settings none made more than {pct(is_best, 3)} a trade after costs,
  and out of sample they made between {pct(o_lo, 3)} and {pct(o_hi, 3)}. One, a breakout straddle on US payroll Fridays, passes the test as written:
  {pct(passed[0].OOS_avg if passed else None, 3)} a trade out of sample, 2% of the account at about {num(passed[0].lev_for_2pct, 0) if passed else "–"}× leverage. But that result assumes stop orders fill exactly at their level in the minute the jobs report is released.
  Filled one minute later it makes {pct(diag["OOS"]["fill_trigger_close"]["avg"], 3) if diag else "–"} a trade, which would need about {num(0.02 / diag["OOS"]["fill_trigger_close"]["avg"], 0) if diag and diag["OOS"]["fill_trigger_close"]["avg"] > 0 else "–"}× leverage for 2%.</p>
  <p class="callout"><b>What 2% a trade means intraday.</b> From 2010 gold's median session spanned 1.25% from high to low, and the COMEX day session (08:20–13:30 New York) only 0.84%; just 5% of COMEX day sessions spanned 2%.
  So 2% a trade can only come from leverage. This study allows up to 20× (the EU retail cap for gold CFDs, close to MCX gold futures margins). At 20×, 2% of the account needs +{pct(tgt, 2, False)} a trade on the position after costs.
  At 20×, a 5% move against the position wipes out the account. Out of sample, {near_zero} of the other ten families lost 90% or more of a 20× account, and
  {len(ruined)} went to zero in a single trade ({esc("; ".join(f"{n}, {d}" for n, d in ruined))}).</p>
  <p class="sub">This is the intraday companion to the <a href="{POSITION_STUDY}" target="_blank" rel="noopener">position-trading study</a>. Backtests on past prices; not a forecast.</p>
</header>

<section id="ranking"><h2>All intraday strategies</h2>
<p>Pass = the configuration chosen on 2010–2021 data alone makes at least {pct(tgt, 2, False)} a trade out of sample after base costs (2% of the account at 20×), over at least {rules["min_oos_trades"]} trades, with a profit factor above 1.</p>
{ranked}
<p class="sub">Averages are unlevered net returns a trade (base costs C1; no financing, since every trade closes before 17:00 New York). "Same trades, random days" re-runs each trade at the same minute of the session, for the same time, on random days of the period.
"Leverage for 2% a trade" is 2% ÷ the out-of-sample average. Account at 20× compounds every trade at 20× leverage; "wiped out" marks the day it reached zero. Failed in-sample families show their published default configuration.</p>
</section>

{detail}

<section id="why"><h2>Why intraday rules fail on gold</h2>
<ul class="plain">
<li><b>Costs are large next to intraday moves.</b> A round trip costs about $0.67 an ounce in spread, slippage and commission (base), 0.05% on gold at $1,300 and 0.02% at $3,500. Out of sample the ten other families captured {pct(g_lo, 3)} to {pct(g_hi, 3)} a trade before costs, so the costs take most or all of it.</li>
<li><b>Not enough edge to pay for them.</b> At their best in-sample settings the closest families made {esc(fail_line)} a trade after costs, against the {pct(tgt, 2, False)} needed. {esc(beat_txt)}</li>
<li><b>Gold's intraday drift is small.</b> The Asia/London overnight drift earned +0.05% a trade out of sample, mostly because gold rose. In-sample it lost, and at 20× it was wiped out in January 2026.</li>
<li><b>Opening-range and momentum rules from equities do not carry over.</b> The Zarattini ORB and noise-area rules and Gao's half-hour momentum were built on US stock indexes. On gold they lose after costs in every period.</li>
</ul>
</section>

<section id="data"><h2>Data</h2>
<p><b>One-minute bars:</b> HistData.com XAUUSD M1, {esc(dm["first"][:10])} → {esc(dm["last"][:10])}, {dm["minutes"]:,} minutes in {dm["sessions"]:,} sessions. Two checks against Dukascopy's hourly bid and ask changed how the data is used.
HistData's prices are Dukascopy's bid quotes (median difference $0.000), so the feed is the same one at minute resolution, not an independent source. Its timestamps follow New York time with daylight saving
(hourly returns match only at UTC−5 in winter and UTC−4 in summer, correlation 0.9997–1.0000). HistData's own notes say they are fixed at UTC−5, which would have shifted every session window by an hour for half of each year.</p>
<p><b>Mid prices</b> = bid + half the spread Dukascopy quoted in that hour. The median spread by year was {esc(spreads)}. Sessions roll at 17:00 New York, and October 2026 ends on the 16th, where HistData's file ends.
The minute bars carry no volume, so rules that need VWAP were run without it.</p>
</section>

<section id="method"><h2>Method</h2>
<ul class="plain">
<li><b>Split and lock.</b> In-sample {esc(lock["in_sample"][0])} → {esc(lock["in_sample"][1])}; out-of-sample from {esc(lock["out_of_sample_from"])}. One configuration per family was chosen on in-sample data only, written to a lock file with a hash of the code, and evaluated out of sample once.</li>
<li><b>Selection.</b> {esc(rules["selection"])}; at least {rules["min_is_trades"]} in-sample trades.</li>
<li><b>Fills.</b> Decisions use only earlier minutes; market entries fill at the next minute's open; stop entries at their level (or a worse open); within one minute the worse outcome is assumed, a stop before a target; every position is closed by 16:59 New York.</li>
<li><b>Costs.</b> Base: $0.40 spread, $0.10 slippage and $0.035 commission an ounce a side. Harsh: $0.50, $0.25 and $0.05. Measured: Dukascopy's quoted spread in the entry and exit hours. No financing, since nothing is held over the 17:00 roll.</li>
<li><b>Payroll days.</b> Release dates follow BLS's published rule (the third Friday after the week containing the 12th), which reproduces every 2019 release. Releases delayed by government shutdowns (October 2013, autumn 2025) are not modelled; on those days the rule trades an ordinary Friday.</li>
<li><b>Stress tests</b> of the pass were added after the locked run and change no verdict.</li>
</ul>
</section>

<section id="register"><h2>Strategies tested</h2>
<div class="tw"><table class="data"><thead><tr><th class="l">Strategy</th><th class="l">Rules</th><th class="l">Stop / target</th><th class="l">Published sizing</th><th class="l">Grid</th><th class="l">Source</th></tr></thead><tbody>{reg}</tbody></table></div>
<p class="sub">Not tested: FOMC-day rules (no reliable free release calendar reachable from here), Asian-range fade scripts and commercial gold EAs (no fixed published rules or closed source), scalping on seconds data (not available free).</p>
</section>

<section id="limits"><h2>Assumptions and limitations</h2>
<ul class="plain">
<li>One broker feed (Dukascopy, via HistData). Another broker's spreads, especially around news, differ.</li>
<li>One-minute bars hide the order of prices inside a minute; the engine takes the worse outcome, but it cannot see the slippage of a stop order in a news minute. That is why the payroll straddle is stress-tested.</li>
<li>Leverage is applied as a constant multiple. A real account also faces margin calls, and many brokers widen spreads or halt trading around releases.</li>
<li>{lock["configurations_tested"]} configurations were tried. One clearing a t of about 2 in-sample is roughly what chance alone would produce, which is why the out-of-sample run and stress tests matter more than the in-sample result.</li>
</ul></section>

<section id="code"><h2>Code</h2>
<p>Everything re-runs from <a href="{REPO}" target="_blank" rel="noopener">backend/research/xauusd_intraday_2026_10</a>: <code>xi_fetch.py</code> → <code>xi_data.py</code> → <code>xi_run.py select</code> → <code>xi_run.py evaluate</code> → <code>xi_diagnostics.py</code> → <code>xi_report.py</code>.
The engine is <code>xi_engine.py</code>, and each rule is in <code>xi_strategies.py</code>. The rule that passed:</p>
{code}
</section>
</div>'''


def markdown(lock, det, summ, diag) -> str:
    fams = {f.key: f for f in S.FAMILIES}
    tgt = lock["rules"]["target_position_per_trade"]
    L = ["# Intraday XAUUSD strategies: can one make 2% a trade?", "",
         f"One-minute bars (HistData = Dukascopy bid, New York time with DST), mid prices, {len(S.FAMILIES)} published intraday families, "
         f"{lock['configurations_tested']} configurations. In-sample {lock['in_sample'][0]} -> {lock['in_sample'][1]}; out-of-sample "
         f"{det['windows']['OOS'][0]} -> {det['windows']['OOS'][1]}. Locked code `{lock['code_hash']}`, lock `{lock['lock_sha256']}`.", "",
         f"2% of the account a trade at up to 20x leverage needs {pct(tgt, 2, False)} a trade on the position after costs. Pass: out of sample, "
         f">= {lock['rules']['min_oos_trades']} trades, average >= {pct(tgt, 2, False)}, profit factor > 1.", "",
         "| Strategy | Verdict | IS trades | IS avg | OOS trades | OOS avg | OOS PF | OOS harsh | Random days | Leverage for 2% | 20x account OOS |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in summ.itertuples():
        e = lock["families"][r.family]
        v = "PASS as tested; fails with realistic fills" if r.PASS else ("FAIL out of sample" if r.is_status == "selected" else f"FAIL in-sample (best {pct(e['best_is_avg'], 3)})")
        L.append(f"| {fams[r.family].name} (`{e['label']}`) | {v} | {int(r.IS_trades)} | {pct(r.IS_avg, 3)} | {int(r.OOS_trades)} | {pct(r.OOS_avg, 3)} | "
                 f"{num(r.OOS_pf)} | {pct(r.OOS_avg_C2, 3)} | {pct(r.random_avg, 3)} | {(num(r.lev_for_2pct, 0) + 'x') if r.lev_for_2pct == r.lev_for_2pct else 'never'} | "
                 f"{pct(r.OOS_20x_total, 0)}{(' (zero on ' + r.OOS_20x_ruined + ')') if isinstance(r.OOS_20x_ruined, str) else ''} |")
    if diag:
        i, o = diag["IS"], diag["OOS"]
        L += ["", "## The payroll straddle under stress", "", "| Variant | In-sample avg | Out-of-sample avg |", "|---|---|---|",
              f"| As tested (stops filled at their level) | {pct(i['C1']['avg'], 3)} | {pct(o['C1']['avg'], 3)} |",
              *[f"| Extra slippage {k} a side | {pct(i['extra_slippage'][k]['avg'], 3)} | {pct(o['extra_slippage'][k]['avg'], 3)} |" for k in ("+$1", "+$2", "+$3", "+$5")],
              f"| Entry at the close of the trigger minute | {pct(i['fill_trigger_close']['avg'], 3)} | {pct(o['fill_trigger_close']['avg'], 3)} |",
              f"| Entry at the next minute's open | {pct(i['fill_next_open']['avg'], 3)} | {pct(o['fill_next_open']['avg'], 3)} |",
              f"| Placebo: non-payroll weekdays | {pct(i['placebo_non_payroll_days']['avg'], 3)} | {pct(o['placebo_non_payroll_days']['avg'], 3)} |", "",
              "Accounts (total return, max drawdown): " + "; ".join(f"{k}: IS {pct(i['accounts'][k]['total_return'], 0)} / {pct(i['accounts'][k]['max_drawdown'], 0)}, "
                                                                    f"OOS {pct(o['accounts'][k]['total_return'], 0)} / {pct(o['accounts'][k]['max_drawdown'], 0)}" for k in i["accounts"])]
    L += ["", "Backtests on past prices; not a forecast. Full report: report/xauusd-intraday-study.html."]
    return chr(10).join(L) + chr(10)


if __name__ == "__main__":
    lock, det, summ, diag, dm = load()
    (ROOT / "REPORT.md").write_text(markdown(lock, det, summ, diag), encoding="utf-8")
    out = ROOT / "report"
    out.mkdir(exist_ok=True)
    (out / "xauusd-intraday-study.html").write_text(page(lock, det, summ, diag, dm), encoding="utf-8")
    print("written", out / "xauusd-intraday-study.html")
