"""Build the report from the results: an HTML page (inline SVG charts, no scripts) and REPORT.md.

    python xa_report.py                 # from results/
    python xa_report.py results_debug   # the pipeline test (never published)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # own modules only; data/ is never on the path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import html
import inspect
import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import xa_strategies as S

# Display names (the registry in xa_strategies.py is part of the locked code hash, so names are
# adjusted here): the Faber family is tested at 6-12 months, not only Faber's 10.
for _f in S.FAMILIES:
    _f.name = {"faber_sma": "Faber monthly SMA timing"}.get(_f.key, _f.name)

ROOT = Path(__file__).resolve().parent
REPO_URL = "https://github.com/raghavar8088/Alpha-engine-in/tree/main/backend/research/xauusd_2026_10"
CAT = {"trend": "Trend-following", "volatility": "Breakout / volatility", "mean reversion": "Mean reversion",
       "session": "Session-based", "seasonal": "Seasonal (calendar sessions)"}


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def pct(v, dp=2, sign=True) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "–"
    s = f"{v * 100:+.{dp}f}%" if sign else f"{v * 100:.{dp}f}%"
    return s.replace("-", "−")


def num(v, dp=2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v))):
        return "–"
    if isinstance(v, float) and math.isinf(v):
        return "∞"
    return f"{v:.{dp}f}".replace("-", "−")


def tone(v) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


# ── load ────────────────────────────────────────────────────────────────────────


def load(resdir: Path) -> dict:
    lock = json.loads((resdir / "selection_locked.json").read_text())
    det = json.loads((resdir / "oos_detail.json").read_text())
    summ = pd.read_csv(resdir / "summary.csv")
    isall = pd.read_csv(resdir / "is_all_configs.csv")
    dq = json.loads((resdir / "data_quality.json").read_text()) if (resdir / "data_quality.json").exists() else None
    trades = {}
    for f in (resdir / "trades").glob("*.csv"):
        trades[f.stem] = pd.read_csv(f)
    sup = json.loads((resdir / "supplementary.json").read_text()) if (resdir / "supplementary.json").exists() else {}
    return {"lock": lock, "det": det, "summ": summ, "isall": isall, "dq": dq, "trades": trades, "resdir": resdir, "sup": sup}


def oos_concentration(R: dict, key: str) -> dict:
    """How much of a strategy's out-of-sample profit came from its single best trade."""
    t = R["trades"].get(key)
    if t is None or not len(t):
        return {}
    o = t[t["window"] == "OOS"]
    r = o["net_C1"].values
    if not len(r):
        return {}
    i = int(np.argmax(r))
    best = o.iloc[i]
    pos = r[r > 0].sum()
    rest = np.delete(r, i)
    return {"best": float(r[i]), "best_from": str(best["entry_date"])[:10], "best_to": str(best["exit_date"])[:10],
            "best_share": float(r[i] / pos) if pos > 0 else None, "rest_avg": float(rest.mean()) if len(rest) else None,
            "rest_n": int(len(rest)), "median": float(np.median(r)), "winners": int((r > 0).sum()), "n": int(len(r))}


# ── the out-of-sample halves, measured on the equity curve ──────────────────────
# (a per-trade split by entry date would credit a trade opened in December 2023 and closed in
# 2026 to 2021-23; the equity curve puts each day's gain or loss in the half it happened)

CUT = "2024-01-01"


def halves(det: dict, key: str) -> tuple:
    c = (det.get("curves", {}).get(key) or {}).get("OOS")
    if not c or not c["dates"]:
        return (None, None)
    d, e = c["dates"], c["equity"]
    i = next((k for k, x in enumerate(d) if x >= CUT), None)
    if i is None or i == 0:
        return (None, None)
    return (e[i - 1] / e[0] - 1, e[-1] / e[i - 1] - 1)


# ── verdicts and ranking ────────────────────────────────────────────────────────


def verdicts(R: dict) -> list[dict]:
    lock, det, summ = R["lock"], R["det"], R["summ"]
    rules = lock["rules"]
    fams = {f.key: f for f in S.FAMILIES}
    bh_oos = det["buy_and_hold"]["OOS"]["C1"]
    rows = []
    for _, r in summ.iterrows():
        key = r["family"]
        f = fams[key]
        d = det["families"][key]
        o, i = d["OOS"]["C1"], d["IS"]["C1"]
        sel = lock["families"][key]
        checks = {}
        if r["is_status"] == "selected":
            checks = {
                "harsh_costs": (d["OOS"]["C2"].get("avg") or -1) >= rules["target_avg_per_trade"],
                "timing": (r["timing_p_holm"] if r["timing_p_holm"] == r["timing_p_holm"] else 1.0) < 0.05,
                "ci_above_zero": (d["oos_ci95"][0] or -1) > 0,
                "both_halves": all(v is not None and v > 0 for v in halves(det, key)),
                "neighbours": d["neighbours"]["count"] > 0 and d["neighbours"]["pass"] / d["neighbours"]["count"] >= 0.5,
                "beats_hold": (o.get("sharpe") or -9) > (bh_oos.get("sharpe") or 9),
            }
        if r["PASS"]:
            status, why = "PASS", f"{pct(o.get('avg'))} a trade over {int(o.get('trades', 0))} out-of-sample trades"
        elif r["is_status"] == "selected":
            parts = []
            if (o.get("trades") or 0) < rules["min_oos_trades"]:
                parts.append(f"only {int(o.get('trades') or 0)} out-of-sample trades")
            if (o.get("avg") or -1) < rules["target_avg_per_trade"]:
                parts.append(f"out-of-sample average {pct(o.get('avg'))} < 2%")
            if (o.get("profit_factor") or 0) <= 1:
                parts.append("profit factor ≤ 1")
            status, why = "FAIL", "; ".join(parts) or "failed"
        else:
            b = sel.get("best_is_avg_with_enough_trades")
            status = "FAIL"
            why = (f"no in-sample configuration reached 2% a trade (best {pct(b)} with ≥{rules['min_is_trades']} trades)"
                   if b is not None else f"no in-sample configuration had ≥{rules['min_is_trades']} trades")
        rows.append({"key": key, "f": f, "r": r, "d": d, "status": status, "why": why, "checks": checks,
                     "score": sum(checks.values()) if checks else -1,
                     "small": r["PASS"] and (o.get("trades") or 0) < 20})
    def order(x):
        tier = 0 if x["status"] == "PASS" else (1 if x["r"]["is_status"] == "selected" else 2)
        oos = x["d"]["OOS"]["C1"].get("avg") or -9
        best_is = lock["families"][x["key"]].get("best_is_avg_with_enough_trades")
        isav = best_is if best_is is not None else -9
        return (tier, -x["score"], -oos if tier < 2 else -isav)
    rows.sort(key=order)
    for n, x in enumerate(rows, 1):
        x["rank"] = n
    return rows


# ── charts (inline SVG, colours from the page's theme tokens) ───────────────────


def svg_equity(curves: dict, bh: dict, oos_from: str, height: int = 260) -> str:
    W, H = 760, height
    pl, pr, pt, pb = 48, 14, 14, 30
    series = []
    for wn in ("IS", "OOS"):
        c = curves.get(wn)
        if c and c["dates"]:
            series.append((wn, pd.to_datetime(c["dates"]), np.array(c["equity"], float)))
    if not series:
        return ""
    # chain OOS onto the end of IS so the line reads as one account
    is_end = series[0][2][-1] if series[0][0] == "IS" else 1.0
    pts = []
    for wn, dts, eq in series:
        scale = is_end if wn == "OOS" and series[0][0] == "IS" else 1.0
        pts.append((wn, dts, eq * scale))
    bh_pts = []
    bh_is_end = 1.0
    for wn in ("IS", "OOS"):
        c = bh.get(wn, {}).get("curve")
        if c:
            eq = np.array(c["equity"], float)
            if wn == "OOS":
                eq = eq * bh_is_end
            else:
                bh_is_end = eq[-1]
            bh_pts.append((pd.to_datetime(c["dates"]), eq))
    alld = pd.DatetimeIndex(np.concatenate([p[1].values for p in pts] + [b[0].values for b in bh_pts]))
    allv = np.concatenate([p[2] for p in pts] + [b[1] for b in bh_pts])
    t0, t1 = alld.min(), alld.max()
    lo, hi = math.log(max(allv.min(), 1e-3)), math.log(allv.max())
    pad = (hi - lo) * 0.06 or 0.1
    lo, hi = lo - pad, hi + pad

    def X(t):
        return pl + (W - pl - pr) * ((t - t0).total_seconds() / max((t1 - t0).total_seconds(), 1))

    def Y(v):
        return pt + (H - pt - pb) * (1 - (math.log(max(v, 1e-6)) - lo) / (hi - lo))

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Equity, strategy against holding gold, log scale">']
    xo = X(pd.Timestamp(oos_from))
    out.append(f'<rect class="oosband" x="{xo:.1f}" y="{pt}" width="{W - pr - xo:.1f}" height="{H - pt - pb}"/>')
    out.append(f'<text class="axlab" x="{xo + 6:.1f}" y="{pt + 12}">out of sample</text>')
    # y ticks: equity multiples
    cand = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20]
    for v in cand:
        if lo <= math.log(v) <= hi:
            y = Y(v)
            out.append(f'<line class="grid" x1="{pl}" x2="{W - pr}" y1="{y:.1f}" y2="{y:.1f}"/>')
            out.append(f'<text class="axlab" x="{pl - 6}" y="{y + 4:.1f}" text-anchor="end">{v:g}×</text>')
    for yr in range(t0.year + 1, t1.year + 1):
        t = pd.Timestamp(f"{yr}-01-01")
        if (yr % 2 == 0) and t0 <= t <= t1:
            x = X(t)
            out.append(f'<line class="tick" x1="{x:.1f}" x2="{x:.1f}" y1="{H - pb}" y2="{H - pb + 4}"/>')
            out.append(f'<text class="axlab" x="{x:.1f}" y="{H - 8}" text-anchor="middle">{yr}</text>')
    for dts, eq in bh_pts:
        d = " ".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in zip(dts, eq))
        out.append(f'<polyline class="bh" points="{d}"/>')
    for wn, dts, eq in pts:
        d = " ".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in zip(dts, eq))
        out.append(f'<polyline class="strat" points="{d}"/>')
    out.append("</svg>")
    return "".join(out)


# ── page pieces ─────────────────────────────────────────────────────────────────


def chip(status: str, small: bool = False) -> str:
    s = f'<span class="chip {"ok" if status == "PASS" else "no"}">{esc(status)}</span>'
    if small:
        s += ' <span class="chip warn" title="fewer than 20 out-of-sample trades">small sample</span>'
    return s


def ranked_table(V: list[dict], det: dict) -> str:
    h = ['<div class="tw"><table class="data"><thead><tr><th>#</th><th class="l">Strategy</th><th class="l">Type</th><th class="l">Verdict</th>',
         '<th>IS trades</th><th>IS avg / trade</th><th>OOS trades</th><th>OOS avg / trade</th><th>OOS profit factor</th>',
         '<th>OOS avg, harsh costs</th><th>OOS return<br><span class="sub">Oct 2021 – Dec 2023</span></th><th>OOS return<br><span class="sub">Jan 2024 – latest</span></th><th>Drift alone<br><span class="sub">random entries</span></th><th>Timing p<br><span class="sub">Holm</span></th></tr></thead><tbody>']
    for x in V:
        r, d = x["r"], x["d"]
        o = d["OOS"]["C1"]
        h1, h2 = halves(det, x["key"])
        ra = d.get("random_entry") or {}
        ph = r["timing_p_holm"]
        h.append(f'<tr class="{"pass" if x["status"] == "PASS" else ""}"><td>{x["rank"]}</td>'
                 f'<td class="l"><b>{esc(x["f"].name)}</b><div class="sub">{esc(x["d"]["label"])}</div></td>'
                 f'<td class="l sub">{esc(CAT.get(x["f"].category, x["f"].category))}</td>'
                 f'<td class="l">{chip(x["status"], x["small"])}<div class="sub why">{esc(x["why"])}</div></td>'
                 f'<td>{int(r["IS_trades"]) if r["IS_trades"] == r["IS_trades"] else "–"}</td><td class="{tone(r["IS_avg"])}">{pct(r["IS_avg"])}</td>'
                 f'<td>{int(o.get("trades") or 0)}</td><td class="{tone(o.get("avg"))}"><b>{pct(o.get("avg"))}</b></td>'
                 f'<td>{num(o.get("profit_factor"))}</td><td class="{tone(d["OOS"]["C2"].get("avg"))}">{pct(d["OOS"]["C2"].get("avg"))}</td>'
                 f'<td class="{tone(h1)}">{pct(h1, 1)}</td><td class="{tone(h2)}">{pct(h2, 1)}</td>'
                 f'<td>{pct(ra.get("random_mean_avg")) if x["r"]["is_status"] == "selected" else "–"}</td>'
                 f'<td>{num(ph, 3) if ph == ph else "–"}</td></tr>')
    h.append("</tbody></table></div>")
    return "".join(h)


METRICS = [("trades", "Trades", "int"), ("avg", "Average net return a trade", "pct"), ("median", "Median trade", "pct"),
           ("win_rate", "Win rate", "pct0"), ("avg_win", "Average win", "pct"), ("avg_loss", "Average loss", "pct"),
           ("profit_factor", "Profit factor", "num"), ("longest_losing_streak", "Longest losing streak (trades)", "int"),
           ("total_return", "Total return", "pct1"), ("cagr", "CAGR", "pct"), ("max_drawdown", "Maximum drawdown", "pct1"),
           ("sharpe", "Sharpe ratio (daily, ×√252)", "num")]


def fmt(v, kind):
    if kind == "int":
        return "–" if v is None else f"{int(v)}"
    if kind == "pct":
        return pct(v)
    if kind == "pct0":
        return pct(v, 1, sign=False)
    if kind == "pct1":
        return pct(v, 1)
    return num(v)


def year_table(x: dict, det: dict, trades: pd.DataFrame | None) -> str:
    d = x["d"]
    by = {}
    for wn in ("IS", "OOS"):
        for y, v in (d[wn]["C1"].get("by_year") or {}).items():
            by.setdefault(int(y), []).append(v)
    bh = {}
    for wn in ("IS", "OOS"):
        for y, v in (det["buy_and_hold"][wn]["C1"].get("by_year") or {}).items():
            bh.setdefault(int(y), []).append(v)
    tr = None
    if trades is not None and len(trades):
        t = trades.copy()
        t["year"] = pd.to_datetime(t["exit_date"]).dt.year
        tr = t.groupby("year")["net_C1"].agg(["count", "mean"])
    rows = ['<div class="tw"><table class="data compact"><thead><tr><th>Year</th><th>Strategy</th><th>Holding gold</th><th>Trades closed</th><th>Average trade</th></tr></thead><tbody>']
    for y in sorted(by):
        sv = float(np.prod([1 + v for v in by[y]]) - 1)
        bv = float(np.prod([1 + v for v in bh.get(y, [0])]) - 1)
        n = int(tr.loc[y, "count"]) if tr is not None and y in tr.index else 0
        a = float(tr.loc[y, "mean"]) if tr is not None and y in tr.index else None
        rows.append(f'<tr><td>{y}{" *" if y == 2021 else ""}</td><td class="{tone(sv)}">{pct(sv, 1)}</td><td class="{tone(bv)}">{pct(bv, 1)}</td>'
                    f'<td>{n}</td><td class="{tone(a)}">{pct(a)}</td></tr>')
    rows.append("</tbody></table></div>")
    return "".join(rows)


def detail_card(x: dict, det: dict, R: dict) -> str:
    f, d, r = x["f"], x["d"], x["r"]
    bh = det["buy_and_hold"]
    rows = []
    for k, lab, kind in METRICS:
        iv, ov = d["IS"]["C1"].get(k), d["OOS"]["C1"].get(k)
        bi = bh["IS"]["C1"].get(k) if k in ("total_return", "cagr", "max_drawdown", "sharpe") else None
        bo = bh["OOS"]["C1"].get(k) if k in ("total_return", "cagr", "max_drawdown", "sharpe") else None
        rows.append(f'<tr><td class="l">{esc(lab)}</td><td class="{tone(iv) if kind.startswith("pct") else ""}">{fmt(iv, kind)}</td>'
                    f'<td class="{tone(ov) if kind.startswith("pct") else ""}"><b>{fmt(ov, kind)}</b></td>'
                    f'<td class="muted">{fmt(bi, kind) if bi is not None else ""}</td><td class="muted">{fmt(bo, kind) if bo is not None else ""}</td></tr>')
    rows.append(f'<tr><td class="l">Time in the market</td><td>{pct(d["IS"]["exposure"], 0, False)}</td><td>{pct(d["OOS"]["exposure"], 0, False)}</td><td class="muted">100%</td><td class="muted">100%</td></tr>')
    rows.append(f'<tr><td class="l">Average holding (sessions)</td><td>{num(d["IS"]["avg_hold_sessions"], 1)}</td><td>{num(d["OOS"]["avg_hold_sessions"], 1)}</td><td></td><td></td></tr>')
    rows.append(f'<tr><td class="l">Share of trades long</td><td>{pct(d["IS"]["long_share"], 0, False)}</td><td>{pct(d["OOS"]["long_share"], 0, False)}</td><td></td><td></td></tr>')
    ra = d.get("random_entry") or {}
    ck = x["checks"]
    def li(ok, text):
        return f'<li class="{"ok" if ok else "no"}"><span class="mark">{"✓" if ok else "✗"}</span> {text}</li>'
    sp = d.get("oos_split") or {}
    bsp = det.get("buy_and_hold_oos_split") or {}
    checks = "".join([
        f'<li class="info"><span class="mark">·</span> Costs: out-of-sample average {pct(d["OOS"]["C0"].get("avg"))} with the brief&#39;s costs only (no financing), '
        f'{pct(d["OOS"]["C1"].get("avg"))} with financing (base), {pct(d["OOS"]["C2"].get("avg"))} at harsh costs</li>',
        li(ck.get("harsh_costs"), f"Harsh costs (spread $0.50, slippage $0.25 a side, financing T-bill + 2%): out-of-sample average {pct(d['OOS']['C2'].get('avg'))}"),
        li(ck.get("timing"), f"Timing beyond gold's drift: the same trades entered at random dates average {pct(ra.get('random_mean_avg'))}; "
                             f"p = {num(r['timing_p'], 3)}, {num(r['timing_p_holm'], 3)} after Holm's correction for {len(det.get('holm') or {})} strategies"),
        li(ck.get("ci_above_zero"), f"95% bootstrap interval of the out-of-sample average: {pct(d['oos_ci95'][0])} to {pct(d['oos_ci95'][1])}"),
        li(ck.get("both_halves"), "Both halves of the out-of-sample period profitable (equity curve): "
                                  f"October 2021 – December 2023 {pct(halves(det, x['key'])[0], 1)} (gold {pct(bsp.get('2021-10..2023-12'), 1)}); "
                                  f"January 2024 – latest {pct(halves(det, x['key'])[1], 1)} (gold {pct(bsp.get('2024-01..latest'), 1)})"),
        li(ck.get("neighbours"), f"Neighbouring parameter sets that also pass out of sample: {d['neighbours']['pass']} of {d['neighbours']['count']} "
                                 f"(whole grid: {d['grid_oos']['pass']} of {d['grid_oos']['count']})"),
        li(ck.get("beats_hold"), f"Better risk-adjusted than holding gold out of sample: Sharpe {num(d['OOS']['C1'].get('sharpe'))} vs {num(bh['OOS']['C1'].get('sharpe'))}"),
    ])
    chart = svg_equity({wn: det["curves"][x["key"]][wn] for wn in ("IS", "OOS")}, det["buy_and_hold"], det["windows"]["OOS"][0])
    return f'''
<article class="card" id="{esc(x["key"])}">
  <header class="card-h">
    <div><div class="eyebrow">#{x["rank"]} · {esc(CAT.get(f.category, f.category))} · {esc(f.timeframe)}</div>
    <h3>{esc(f.name)}</h3></div>
    <div class="right">{chip(x["status"], x["small"])}</div>
  </header>
  <div class="cols">
    <div class="prose">
      <p><b>Rules.</b> {esc(f.rules)}</p>
      <p><b>Stop-loss and take-profit.</b> {esc(f.stops)}</p>
      <p><b>Locked parameters</b> (chosen on 2010–2021 only): <code>{esc(d["label"])}</code></p>
      <p><b>Source.</b> {esc(f.source)} <a href="{esc(f.url)}" target="_blank" rel="noopener">link</a></p>
      <p><b>Position sizing.</b> Published: {esc(f.sizing_published)}. Tested: 1× notional, the whole account in one unlevered position, compounding trade to trade.</p>
      <p><b>Deviations from the source.</b> {esc(f.deviations)}</p>
    </div>
    <figure class="chart">{chart}<figcaption><span class="key strat"></span> strategy &nbsp; <span class="key bh"></span> holding gold (same costs) · log scale, 1× = starting equity · base costs (C1)</figcaption></figure>
  </div>
  <h4>In-sample vs out-of-sample (base costs C1)</h4>
  <div class="tw"><table class="data"><thead><tr><th class="l">Metric</th><th>In-sample<br><span class="sub">{esc(det["windows"]["IS"][0][:7])} → {esc(det["windows"]["IS"][1][:7])}</span></th><th>Out-of-sample<br><span class="sub">{esc(det["windows"]["OOS"][0][:7])} → {esc(det["windows"]["OOS"][1][:7])}</span></th><th>Gold held, IS</th><th>Gold held, OOS</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
  <h4>Robustness (reported, not used to pass)</h4>
  <ul class="checks">{checks}</ul>
  <h4>Year by year</h4>
  {year_table(x, det, R["trades"].get(x["key"]))}
  <p class="sub">* 2021 is split between the two periods: an open position was closed at 2021-09-30 and the out-of-sample run started flat on 2021-10-01. A year's average trade counts trades by the year they closed.</p>
</article>'''


def page(R: dict, V: list[dict]) -> str:
    lock, det, dq = R["lock"], R["det"], R["dq"]
    rules = lock["rules"]
    passed = [x for x in V if x["status"] == "PASS"]
    timing = [x for x in passed if x["checks"].get("timing")]
    beat = [x for x in passed if x["checks"].get("beats_hold")]
    bh = det["buy_and_hold"]
    n_cfg = lock["configurations_tested"]
    oos_end = det["windows"]["OOS"][1]
    fams_selected = sum(1 for x in V if x["r"]["is_status"] == "selected")
    headline = (f"{len(passed)} of {len(V)} strategies pass the 2%-a-trade test out of sample" if passed
                else f"None of {len(V)} strategies passes the 2%-a-trade test out of sample")
    bsp = det.get("buy_and_hold_oos_split") or {}
    gold = f"Holding gold returned {pct(bh['OOS']['C1']['total_return'], 0)} over the out-of-sample period after financing"
    if bsp:
        gold += (f": {pct(bsp.get('2021-10..2023-12'), 0)} from October 2021 to December 2023 and "
                 f"{pct(bsp.get('2024-01..latest'), 0)} from January 2024")
    drift = [x for x in passed if ((x["d"].get("random_entry") or {}).get("random_mean_avg") or -1) >= rules["target_avg_per_trade"]]
    n = len(passed)
    if n == 1:
        x = passed[0]
        ra = (x["d"].get("random_entry") or {}).get("random_mean_avg")
        first = (f"1 of {len(V)} strategies passes the 2%-a-trade test out of sample: {esc(x['f'].name)}. "
                 f"It {'times' if x['checks'].get('timing') else 'does not time'} gold better than the same trades entered at random dates, "
                 f"and it {'beats' if x['checks'].get('beats_hold') else 'does not beat'} simply holding gold on a risk-adjusted basis.")
        second = (f"{gold}. The same trades entered on random dates would have averaged {pct(ra)}, "
                  + ("so the pass comes from the period, not from the rule's timing." if x in drift else "less than the strategy did.")
                  + " The checks under the strategy below separate the two.")
    elif n > 1:
        first = (f"{n} of {len(V)} strategies pass the 2%-a-trade test out of sample: " + ", ".join(esc(x["f"].name) for x in passed) + ". "
                 f"{len(timing)} of them time gold better than the same trades entered at random dates, after correcting for the number of strategies tested. "
                 f"{len(beat)} beat simply holding gold on a risk-adjusted basis over the same period.")
        second = (f"{gold}. For {len(drift)} of the {n}, the same trades entered on random dates would also have averaged "
                  f"{pct(rules['target_avg_per_trade'], 0, False)} or more, so for those the pass comes from the period, not from the timing. "
                  "The checks under each passing strategy separate the two.")
    else:
        second = f"{gold}."
        first = f"{headline}."
    rests = []
    for x in passed:
        c = oos_concentration(R, x["key"])
        if c and c.get("best_share") and c["best_share"] > 0.5:
            rests.append(f"{x['f'].name} owes its average to one trade: {c['best_from']} to {c['best_to']}, {pct(c['best'], 1)}. "
                         f"Its other {c['rest_n']} trades averaged {pct(c['rest_avg'])}, and its median trade was {pct(c['median'])}.")
    sup = R.get("sup") or {}
    later = ""
    if sup.get("presample") and sup.get("walk_forward"):
        ps = [k for k, v in sup["presample"]["families"].items() if v.get("passes_2pct") and v.get("status_is") == "selected"]
        wf = [k for k, v in sup["walk_forward"]["families"].items() if v.get("PASS")]
        names = {f.key: f.name for f in S.FAMILIES}
        def vs(v):
            return f"{pct((v['C1'] or {}).get('avg'))} against {pct(v.get('random_mean_avg'))} for random entries, p = {num(v.get('timing_p'), 2)}"
        ps_txt = "; ".join(f"{names[k]} {vs(sup['presample']['families'][k])}" for k in ps)
        wf_txt = "; ".join(f"{names[k]} {vs(sup['walk_forward']['families'][k])}" for k in wf)
        later = (f"Two later checks. On 2005–2009, years no stage had used, {len(ps)} of the locked choices clear 2% a trade"
                 + (f" ({ps_txt})" if ps else "") + ". "
                 f"In a walk-forward from 2014 that re-picks each year's parameters from earlier years only, {len(wf)} "
                 f"{'family passes' if len(wf) == 1 else 'families pass'}" + (f" ({wf_txt})" if wf else "") + ". "
                 "None of these results is better than random timing by a margin that rules out luck.")
    answer = f'''
<p class="lede">{first}</p>
<p>{esc(second)}</p>
{"".join(f"<p>{esc(t)}</p>" for t in rests)}
{f"<p>{esc(later)}</p>" if later else ""}'''
    data_html = ""
    if dq:
        yrs = dq.get("by_year", {})
        yr_rows = "".join(f'<tr><td>{y}</td><td>{v["sessions"]}</td><td>{v["hours"]:,}</td><td>{num(v["spread_median"])}</td><td>{num(v["spread_p90"])}</td><td>{num(v["price_first"], 0)}</td><td>{num(v["price_last"], 0)}</td></tr>'
                          for y, v in yrs.items())
        cx = dq.get("vs_comex_daily") or {}
        ch = dq.get("vs_comex_hourly") or {}
        dk = dq.get("vs_dukascopy_daily_candles") or {}
        cs = dq.get("vs_comex_daily_at_settlement") or {}
        gaps = dq.get("intra_session_gaps_over_2h") or []
        data_html = f'''
<p><b>Source.</b> {esc(dq["source"])}. Free, public, with both bid and ask, so the spread is measured rather than assumed. <b>Timezone:</b> {esc(dq["timezone"])}.
Coverage {esc(dq["first_hour"][:10])} → {esc(dq["last_hour"][:16])} UTC: {dq["hours"]:,} trading hours in {dq["sessions"]:,} sessions.
Years before 2008 are bid-only warm-up for the indicators; no trade is taken before 2010.</p>
<p><b>Checks.</b> Daily closes rebuilt from the hourly file match Dukascopy's own daily candles on {esc(dk.get("days_compared"))} days (median difference ${esc(dk.get("close_abs_diff_median"))}). {esc(dq.get("vs_dukascopy_daily_candles_note", ""))}.</p>
<p>Against COMEX gold futures (Yahoo GC=F): Yahoo's daily close is the COMEX settlement (~13:30 New York). Measured at that hour, daily returns correlate {esc(cs.get("return_correlation"))} over {esc(cs.get("days"))} days,
and {esc(cs.get("days_return_diff_over_1pct"))} days differ by more than 1% (mostly contract rolls). Measured at 17:00 New York instead, the correlation is {esc(cx.get("return_correlation"))}: that gap is the 3½ hours between the two closes, not bad data.
Hourly returns correlate {esc(ch.get("return_correlation"))} over the last {esc(ch.get("hours"))} hours Yahoo provides. The futures trade at a median premium of {esc(cx.get("basis_median_pct"))}% (carry).
Gold's sharpest hours in the file (for example −5.9% at 15:00 UTC on 2026-01-29, with gold near $5,500) appear in the COMEX hourly data too.</p>
<p><b>Gaps.</b> {len(dq.get("weekdays_without_a_session") or [])} weekdays have no session (Christmas, New Year and Good Friday closures); {len(gaps)} sessions have a gap of more than two hours inside them (holiday early closes).
{"Stray stub sessions dropped: " + esc(", ".join(dq.get("stray_sessions_dropped") or [])) + "." if dq.get("stray_sessions_dropped") else ""}
<b>Not verifiable here:</b> Dukascopy is one bank's feed, not a consolidated tape, and the ask history cannot be checked against another free source.</p>
<div class="tw"><table class="data compact"><thead><tr><th>Year</th><th>Sessions</th><th>Hours</th><th>Median spread $</th><th>90th pct spread $</th><th>First close</th><th>Last close</th></tr></thead><tbody>{yr_rows}</tbody></table></div>'''
    costs = det["costs"]
    cost_rows = "".join(f'<tr><td class="l"><b>{k}</b></td><td class="l">{esc(v["name"])}</td></tr>' for k, v in costs.items())
    cards = "".join(detail_card(x, det, R) for x in passed)
    near = [x for x in V if x["status"] != "PASS" and x["r"]["is_status"] == "selected"]
    near_cards = "".join(detail_card(x, det, R) for x in near[:2])
    fail_items = "".join(f'<li><b>{esc(x["f"].name)}</b> <span class="sub">({esc(CAT.get(x["f"].category))})</span>: {esc(x["why"])}.</li>' for x in V if x["status"] != "PASS")
    disc = "".join(f'<li><b>{esc(n)}</b>: {esc(w)}.{" <a href=" + chr(34) + esc(u) + chr(34) + " target=" + chr(34) + "_blank" + chr(34) + " rel=" + chr(34) + "noopener" + chr(34) + ">source</a>" if u else ""}</li>' for n, w, u in S.DISCARDED)
    code_blocks = ""
    for x in passed:
        try:
            src = inspect.getsource(x["f"].builder)
        except (TypeError, OSError):
            src = ""
        code_blocks += f'<h4>{esc(x["f"].name)} <span class="sub">(xa_strategies.py)</span></h4><pre><code>{esc(src)}</code></pre>'
    srcs = "".join(f'<li>{esc(f.source)} <a href="{esc(f.url)}" target="_blank" rel="noopener">{esc(f.url)}</a></li>' for f in S.FAMILIES if f.url.startswith("http"))
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f'''<title>XAUUSD 2% Trade Study</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..800&family=JetBrains+Mono:wght@400;600&family=Source+Sans+3:wght@400;600;700&display=swap">
<style>
/* Layout: one reading column for prose (~70ch); tables, charts and cards run full width inside the same gutter. */
:root {{
  --bg: #f6f7f5; --panel: #ffffff; --ink: #17191d; --muted: #5d636c; --rule: #d9dbd6;
  --gold: #8b6414; --gold-soft: #f2ead8; --pos: #1d7a4b; --neg: #b23a30; --warn: #94650a; --band: rgba(139, 100, 20, 0.07);
  --bh: #8c939c;
  --display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #121316; --panel: #191b1f; --ink: #ebe8e1; --muted: #a3a8b0; --rule: #2d3036;
  --gold: #d8aa47; --gold-soft: #2c2616; --pos: #55c38b; --neg: #f07a6c; --warn: #e3b14c; --band: rgba(216, 170, 71, 0.08); --bh: #8d949e; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #121316; --panel: #191b1f; --ink: #ebe8e1; --muted: #a3a8b0; --rule: #2d3036;
  --gold: #d8aa47; --gold-soft: #2c2616; --pos: #55c38b; --neg: #f07a6c; --warn: #e3b14c; --band: rgba(216, 170, 71, 0.08); --bh: #8d949e; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--ink); font-family: var(--body); font-size: 16px; line-height: 1.55; }}
.wrap {{ max-width: 1120px; margin: 0 auto; padding-inline: 20px; padding-block: 28px 64px; display: flex; flex-direction: column; gap: 34px; }}
h1, h2, h3, h4 {{ font-family: var(--display); text-wrap: balance; margin: 0; }}
h1 {{ font-size: clamp(30px, 5vw, 46px); font-weight: 800; font-stretch: 85%; letter-spacing: -0.01em; line-height: 1.05; }}
h2 {{ font-size: 24px; font-weight: 750; font-stretch: 90%; padding-bottom: 6px; border-bottom: 2px solid var(--gold); }}
h3 {{ font-size: 21px; font-weight: 750; font-stretch: 92%; }}
h4 {{ font-size: 13px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); margin-top: 6px; }}
section {{ display: flex; flex-direction: column; gap: 14px; }}
p {{ margin: 0; max-width: 72ch; }}
.lede {{ font-size: 19px; line-height: 1.5; max-width: 66ch; }}
.eyebrow {{ font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--gold); font-weight: 700; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13.5px; color: var(--muted); }}
.meta b {{ color: var(--ink); font-weight: 600; }}
a {{ color: var(--gold); }}
a:focus-visible {{ outline: 2px solid var(--gold); outline-offset: 2px; }}
code, pre {{ font-family: var(--mono); font-size: 12.5px; }}
code {{ background: var(--gold-soft); padding: 1px 5px; border-radius: 4px; }}
pre {{ background: var(--panel); border: 1px solid var(--rule); border-radius: 8px; padding: 14px; overflow-x: auto; margin: 0; }}
pre code {{ background: none; padding: 0; }}
.tw {{ overflow-x: auto; border: 1px solid var(--rule); border-radius: 8px; background: var(--panel); }}
table.data {{ border-collapse: collapse; width: 100%; font-size: 13.5px; font-variant-numeric: tabular-nums; }}
table.data th {{ font-family: var(--body); font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted);
  text-align: right; padding: 9px 10px; border-bottom: 1px solid var(--rule); white-space: nowrap; vertical-align: bottom; }}
table.data td {{ padding: 8px 10px; border-bottom: 1px solid var(--rule); text-align: right; font-family: var(--mono); font-size: 12.5px; vertical-align: top; }}
table.data tr:last-child td {{ border-bottom: none; }}
table.data .l {{ text-align: left; font-family: var(--body); font-size: 13.5px; }}
table.data tr.pass td {{ background: var(--gold-soft); }}
table.compact td, table.compact th {{ padding: 6px 10px; }}
.sub {{ font-size: 12px; color: var(--muted); font-weight: 400; text-transform: none; letter-spacing: 0; font-family: var(--body); }}
.why {{ margin-top: 3px; max-width: 34ch; }}
.pos {{ color: var(--pos); }} .neg {{ color: var(--neg); }} .muted {{ color: var(--muted); }}
.chip {{ display: inline-block; font-family: var(--body); font-size: 11.5px; font-weight: 700; letter-spacing: 0.05em; padding: 2px 8px; border-radius: 999px; border: 1px solid currentColor; }}
.chip.ok {{ color: var(--pos); }} .chip.no {{ color: var(--neg); }} .chip.warn {{ color: var(--warn); }}
.card {{ background: var(--panel); border: 1px solid var(--rule); border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 14px; }}
.card-h {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }}
.cols {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr); gap: 20px; align-items: start; }}
@media (max-width: 860px) {{ .cols {{ grid-template-columns: minmax(0, 1fr); }} }}
.prose {{ display: flex; flex-direction: column; gap: 8px; font-size: 14.5px; min-width: 0; }}
figure.chart {{ margin: 0; min-width: 0; }}
figcaption {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
.key {{ display: inline-block; width: 18px; height: 3px; vertical-align: middle; border-radius: 2px; }}
.key.strat {{ background: var(--gold); }} .key.bh {{ background: var(--bh); }}
svg .strat {{ fill: none; stroke: var(--gold); stroke-width: 1.8; }}
svg .bh {{ fill: none; stroke: var(--bh); stroke-width: 1.2; stroke-dasharray: 4 3; }}
svg .grid {{ stroke: var(--rule); stroke-width: 1; }}
svg .tick {{ stroke: var(--muted); stroke-width: 1; }}
svg .axlab {{ fill: var(--muted); font-family: var(--mono); font-size: 11px; }}
svg .oosband {{ fill: var(--band); }}
ul.checks {{ list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; font-size: 14px; }}
ul.checks li {{ display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 6px; }}
ul.checks .mark {{ font-weight: 700; }}
ul.checks li.ok .mark {{ color: var(--pos); }} ul.checks li.no .mark {{ color: var(--neg); }} ul.checks li.info .mark {{ color: var(--muted); }}
ul.plain {{ margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; max-width: 80ch; }}
.callout {{ border-left: 3px solid var(--gold); padding: 10px 14px; background: var(--panel); border-radius: 0 8px 8px 0; max-width: 80ch; }}
@media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto; }} }}
</style>
<div class="wrap">
<header style="display:flex;flex-direction:column;gap:12px">
  <div class="eyebrow">Backtest study · spot gold (XAUUSD) · {esc(det["windows"]["IS"][0][:4])}–{esc(oos_end[:4])}</div>
  <h1>Which published gold strategies make 2% a trade?</h1>
  <div class="meta"><span><b>{len(V)}</b> strategy families</span><span><b>{n_cfg}</b> parameter sets tested</span>
    <span>in-sample <b>{esc(det["windows"]["IS"][0][:7])} → {esc(det["windows"]["IS"][1][:7])}</b></span><span>out-of-sample <b>{esc(det["windows"]["OOS"][0][:7])} → {esc(oos_end)}</b></span>
    <span>selection locked <b>{esc(lock["locked_at"][:16].replace("T", " "))} UTC</b> · code <code>{esc(lock["code_hash"])}</code></span></div>
  {answer}
  <p class="callout">These are backtests on past prices. They do not predict future returns, and every losing year and drawdown is shown below.
  "Per trade" means the unlevered move a trade captured after all costs, on the whole account in one position; leverage would multiply it, risk included.</p>
</header>

<section id="ranking"><h2>All strategies, ranked</h2>
<p>Pass = the configuration chosen on 2010–2021 data alone makes at least {pct(rules["target_avg_per_trade"], 0, False)} a trade on average out of sample, after base costs,
over at least {rules["min_oos_trades"]} trades, with a profit factor above 1. Rank: passes first, then by how many robustness checks they clear, then by out-of-sample average.</p>
{ranked_table(V, det)}
<p class="sub">IS = in-sample (2010-01 → 2021-09), OOS = out-of-sample (2021-10 → {esc(oos_end)}). Averages are net returns a trade under base costs C1 unless marked harsh (C2).
The two OOS return columns come from the strategy's equity curve; holding gold returned {pct((det.get("buy_and_hold_oos_split") or {}).get("2021-10..2023-12"), 0)} and {pct((det.get("buy_and_hold_oos_split") or {}).get("2024-01..latest"), 0)} over the same halves.
"Drift alone" is what the same trades average when entered on random dates in the same period: the part of the result gold's rise pays for any timing.
For families that failed in-sample, the IS and OOS columns show their published default configuration, for information only: they were never eligible.</p>
</section>

<section id="passed"><h2>{"The strategies that pass" if passed else "No strategy passed"}</h2>
{cards if passed else "<p>No configuration chosen in-sample reached the target out of sample. The closest are shown next.</p>"}
{"" if passed else near_cards}
</section>

{why_section(R, V)}

{supplementary_section(R)}

<section id="failed"><h2>What failed, and why</h2>
<ul class="plain">{fail_items}</ul>
<p><b>Why session and mean-reversion rules cannot get there.</b> {session_line(dq)} Rules that are flat by the end of a session or two, like the London breakout, the session drift, Williams and Crabel breakouts, RSI(2), Double 7s and band reversion, would need nearly every trade to catch most of a day's range to average 2%. The London breakout caps its target at 2.5R with a stop of at most 0.6%, so no trade can make more than 1.5%. In this test only rules that hold for months averaged 2% a trade, and they trade so rarely that five years gave them three to six trades.</p>
</section>

<section id="data"><h2>Data</h2>{data_html or "<p>Data checks are written by xa_data.py.</p>"}</section>

<section id="method"><h2>Method</h2>
<ul class="plain">
<li><b>Split.</b> In-sample 2010-01-01 → 2021-09-30 (about 70%), out-of-sample 2021-10-01 → {esc(oos_end)} (about 30%). Each family's parameters were chosen on in-sample data only, then written to a lock file with a hash of the code. The out-of-sample stage refuses to run if the code changes after the lock, and it was run once.</li>
<li><b>Selection.</b> {esc(rules["selection"])}; at least {rules["min_is_trades"]} in-sample trades. Of {len(V)} families, {fams_selected} had at least one configuration that qualified.</li>
<li><b>No look-ahead.</b> Decisions are taken at a session's close (~17:00 New York) from bars up to that close, and acted on in the next session: market orders at the next hourly open, breakout orders as stop orders that fill at the level (or at a worse open). Stops, targets and stop entries are checked on hourly bars. When a stop and a target fall in the same hour, the stop is assumed hit first, and a stop touched in the hour a trade opened counts against it.</li>
<li><b>Prices.</b> Mid prices from Dukascopy's bid and ask. Daily sessions roll at 17:00 New York, the standard for spot metals.</li>
<li><b>Sizing.</b> Every strategy is tested at 1× notional, one position at a time, compounding, so its per-trade return is directly the percentage it captured. Published sizing rules (Turtle units, volatility scaling, 1% risk) are listed with each strategy but not applied.</li>
<li><b>Diagnostics.</b> Harsh costs; a random-entry test (5,000 sets of the strategy's own trades with the same side and holding length, entered at random dates in the same period); a 10,000-draw bootstrap of the out-of-sample trades; the 2021–23 vs 2024–26 split; neighbouring parameter sets; holding gold under the same costs. Timing p-values are corrected with Holm's method across the strategies tested.</li>
</ul>
<div class="tw"><table class="data compact"><thead><tr><th class="l">Costs</th><th class="l">What is charged</th></tr></thead><tbody>{cost_rows}</tbody></table></div>
<p class="sub">Spread is paid once a round trip (half on each side), slippage and commission on each side; commission $0.035/oz a side is $7 a 100-oz lot round trip. Financing is charged a night for every calendar day held, as CFD swaps are (T-bill from Yahoo ^IRX). Held cash earns nothing.</p>
</section>

<section id="limits"><h2>Assumptions and limitations</h2>
<ul class="plain">
<li>One bank's quotes (Dukascopy). Another broker's prices and spreads differ, most in fast markets.</li>
<li>Hourly bars hide the order of prices inside an hour; the engine takes the worse outcome each time, which may understate stop-and-target strategies slightly.</li>
<li>Financing follows a CFD-style model (T-bill plus a markup). On futures the carry is paid through the roll, and it is similar in size. Leaving financing out (cost set C0) flatters long trades, by more the longer they are held.</li>
<li>Out-of-sample is one regime: gold rose about {pct(bh["OOS"]["C1"]["total_return"], 0, False)} in five years. Long-biased rules are favoured by it, and the 2021–23 vs 2024–26 columns show how much.</li>
<li>Monthly and weekly rules trade a few times a year. Their averages rest on few trades, so the bootstrap interval is wide.</li>
<li>{n_cfg} parameter sets across {len(V)} families were tried. The more that are tried, the more likely a pass is luck. The random-entry test and Holm's correction address part of this; parameter neighbours address the rest.</li>
<li>Rules were coded from their published descriptions. Deviations are listed per strategy. The Turtle System 1 filter is a daily-bar approximation, and Clenow's rules come from summaries of the book.</li>
<li>Taxes, position limits, margin calls and broker outages are not modelled.</li>
</ul></section>

<section id="register"><h2>Candidate register</h2>
<p>Every strategy tested, with the rules as published and what the test changed. Parameter grids are centred on each source's published values.</p>
{register_table()}
</section>

<section id="discarded"><h2>Candidates discarded before testing</h2><ul class="plain">{disc}</ul></section>

<section id="code"><h2>Code</h2>
<p>The whole study, re-runnable with pandas and numpy only: <a href="{REPO_URL}" target="_blank" rel="noopener">backend/research/xauusd_2026_10</a>
(<code>xa_fetch.py</code> → <code>xa_data.py</code> → <code>xa_test_engine.py</code> → <code>xa_run.py select</code> → <code>xa_run.py evaluate</code>).
The engine (<code>xa_engine.py</code>) handles fills, costs and statistics; each strategy below only states its rules.</p>
{code_blocks}
</section>

<section id="sources"><h2>Sources</h2><ul class="plain">{srcs}</ul></section>
<p class="sub">Generated {esc(gen)} from {esc(R["resdir"].name)}/ · lock {esc(lock.get("lock_sha256"))}</p>
</div>'''


def session_line(dq) -> str:
    sm = (dq or {}).get("session_moves_2010_on")
    if not sm:
        return "Gold rarely moves 2% in a session."
    return (f"From 2010 the median session spanned {sm['median_high_low_range_pct']:.2f}% from high to low; "
            f"{sm['share_range_2pct_or_more'] * 100:.0f}% of sessions had a range of 2% or more, and "
            f"{sm['share_open_to_close_2pct_or_more'] * 100:.0f}% moved 2% from open to close.")


def why_section(R: dict, V: list[dict]) -> str:
    lock = R["lock"]
    rules = lock["rules"]
    passed = [x for x in V if x["status"] == "PASS"]
    if len(passed) >= 3:
        return ""
    rows = []
    for x in V:
        if x["status"] == "PASS":
            continue
        o = x["d"]["OOS"]["C1"]
        sel = x["r"]["is_status"] == "selected"
        near_is = (not sel) and (lock["families"][x["key"]].get("best_is_avg_with_enough_trades") or -1) >= 0.019
        near_oos = sel and (o.get("avg") or -1) >= rules["target_avg_per_trade"]
        if not (near_is or near_oos or sel):
            continue
        c = oos_concentration(R, x["key"]) if sel else {}
        why = x["why"]
        rows.append(f'<tr><td class="l"><b>{esc(x["f"].name)}</b><div class="sub">{esc(x["d"]["label"])}</div></td>'
                    f'<td>{int(o.get("trades") or 0) if sel else "–"}</td><td class="{tone(o.get("avg")) if sel else ""}">{pct(o.get("avg")) if sel else "–"}</td>'
                    f'<td>{pct(c.get("best_share"), 0, False) if c.get("best_share") is not None else "–"}</td>'
                    f'<td class="l sub">{esc(why)}</td></tr>')
    table = ('<div class="tw"><table class="data"><thead><tr><th class="l">Near miss</th><th>OOS trades</th><th>OOS avg / trade</th>'
             '<th>Best trade\'s share of profit</th><th class="l">Why it does not count</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")
    n_cfg = lock["configurations_tested"]
    return f'''
<section id="why"><h2>Why fewer than three pass, and why the search stopped</h2>
<p>The brief asked for the search to continue until three strategies pass. It stopped at {len(passed)}. Any rule added from here would be designed after
seeing the out-of-sample answer: that from October 2021, rules that stayed long through the 2024–26 rally cleared 2% a trade and almost nothing else did.
A new family, a looser trade minimum or a re-tuned parameter chosen with that knowledge would pass because of it, and its out-of-sample result would no longer
test anything. The two checks in the next section use data and a procedure that avoid that problem.</p>
<p><b>What was tried.</b> {len(V)} families with published rules and {n_cfg} parameter sets: trend-following (monthly, weekly and daily), breakouts and volatility
systems with stops, mean reversion, London-session and overnight rules, and calendar seasonals. Each was tested long-only and long/short where the source allows,
under four cost sets, with entries at the next open or by stop orders.</p>
<p><b>Why they failed.</b> {why_failed(R, V)}</p>
{table}
</section>'''


def why_failed(R: dict, V: list[dict]) -> str:
    lock = R["lock"]
    best = {k: v.get("best_is_avg_with_enough_trades") for k, v in lock["families"].items()}
    fast = ["london_breakout", "session_drift", "williams_vbo", "nr_breakout", "shock", "connors_rsi2", "double_seven", "bb_reversion"]
    medium = ["turtle", "clenow", "keltner", "chandelier", "wilder_dmi", "macd", "ichimoku", "weinstein"]
    names = {f.key: f.name.split(" (")[0] for f in S.FAMILIES}

    def rng(keys):
        vals = [best[k] for k in keys if best.get(k) is not None and lock["families"][k]["status"] != "selected"]
        return (min(vals), max(vals)) if vals else (None, None)

    f_lo, f_hi = rng(fast)
    m_lo, m_hi = rng(medium)
    slow = []
    for x in V:
        if x["status"] != "PASS" and x["r"]["is_status"] == "selected" and (x["d"]["OOS"]["C1"].get("trades") or 0) < lock["rules"]["min_oos_trades"]:
            c = oos_concentration(R, x["key"])
            slow.append((x, c))
    parts = [f"Gold rarely moves 2% in a session, so the rules that hold for hours or days peaked at {pct(f_lo)} to {pct(f_hi)} a trade in-sample." if f_lo is not None else ""]
    if m_lo is not None:
        parts.append(f"The daily and weekly trend systems that trade more often ({', '.join(names[k] for k in medium if lock['families'][k]['status'] != 'selected')}) "
                     f"reached {pct(m_lo)} to {pct(m_hi)} a trade at their best in-sample settings; 2010–2021 held gold's long fall from 2011 and the sideways years to 2019.")
    if slow:
        n_lo = min(int(x["d"]["OOS"]["C1"].get("trades") or 0) for x, _ in slow)
        n_hi = max(int(x["d"]["OOS"]["C1"].get("trades") or 0) for x, _ in slow)
        dom = [x for x, c in slow if (c.get("best_share") or 0) > 0.5]
        parts.append(f"The slow rules ({', '.join(names[x['key']] for x, _ in slow)}) did clear 2% a trade, but they trade once or twice a year: five out-of-sample "
                     f"years gave them {n_lo} to {n_hi} trades each, below the minimum of {lock['rules']['min_oos_trades']}. In {len(dom)} of the {len(slow)}, the single best "
                     f"trade supplied more than half the profit.")
    return " ".join(p for p in parts if p)


def supplementary_section(R: dict) -> str:
    sup = R.get("sup") or {}
    if not (sup.get("presample") and sup.get("walk_forward")):
        return ""
    names = {f.key: f.name for f in S.FAMILIES}
    ps = sup["presample"]
    prow = []
    for k, v in sorted(ps["families"].items(), key=lambda kv: (kv[1]["status_is"] != "selected", -(kv[1]["C1"].get("avg") or -9))):
        c = v["C1"]
        sel = v["status_is"] == "selected"
        prow.append(f'<tr class="{"pass" if (v.get("passes_2pct") and sel) else ""}"><td class="l"><b>{esc(names[k])}</b><div class="sub">{esc(v["label"])}{"" if sel else " · default (failed in-sample)"}</div></td>'
                    f'<td>{int(c.get("trades") or 0)}</td><td class="{tone(c.get("avg"))}">{pct(c.get("avg"))}</td><td>{num(c.get("profit_factor"))}</td>'
                    f'<td>{pct(v.get("random_mean_avg"))}</td><td>{num(v.get("timing_p"), 3)}</td></tr>')
    wf = sup["walk_forward"]
    wrow = []
    for k, v in sorted(wf["families"].items(), key=lambda kv: (not kv[1].get("PASS"), -(kv[1]["C1"].get("avg") or -9) if kv[1]["C1"].get("trades") else 9)):
        c = v["C1"]
        n = int(c.get("trades") or 0)
        wrow.append(f'<tr class="{"pass" if v.get("PASS") else ""}"><td class="l"><b>{esc(names[k])}</b></td><td>{v["years_traded"]}</td><td>{n}</td>'
                    f'<td class="{tone(c.get("avg")) if n else ""}">{pct(c.get("avg")) if n else "–"}</td><td>{num(c.get("profit_factor")) if n else "–"}</td>'
                    f'<td>{pct(v.get("random_mean_avg")) if n else "–"}</td><td>{num(v.get("timing_p_holm"), 3) if n and v.get("timing_p_holm") is not None else "–"}</td>'
                    f'<td>{pct(v.get("share_of_profit_from_best_trade"), 0, False) if n and v.get("share_of_profit_from_best_trade") is not None else "–"}</td>'
                    f'<td>{chip("PASS") if v.get("PASS") else ""}</td></tr>')
    bp, bw = ps["buy_and_hold"], wf["buy_and_hold"]
    return f'''
<section id="later"><h2>Two more out-of-sample checks</h2>
<p>Both were added after the locked run had been seen, with their rules fixed before they ran. They do not change any verdict above.</p>
<h4>2005–2009: years no stage had read</h4>
<p>The locked configurations, unchanged, on {esc(ps["window"][0])} → {esc(ps["window"][1])}, the indicator warm-up years. Holding gold returned {pct(bp.get("total_return"), 0)} over these years after financing,
with a {pct(bp.get("max_drawdown"), 0)} drawdown in 2008. Before 2008 the ask is synthetic (bid plus 2008's median spread). Baur's autumn-effect paper covered these years,
so its result here is the paper's own sample, not new evidence.</p>
<div class="tw"><table class="data"><thead><tr><th class="l">Strategy</th><th>Trades</th><th>Avg / trade</th><th>Profit factor</th><th>Random entries</th><th>Timing p</th></tr></thead><tbody>{"".join(prow)}</tbody></table></div>
<h4>Walk-forward, {wf["first_year"]} → latest</h4>
<p>Each calendar year's configuration is re-chosen with the locked selection rule, using only 2010 to the end of the previous year. A year with no qualifying configuration is flat.
Pass: at least {wf["min_trades"]} trades, 2% a trade and a profit factor above 1. Holding gold returned {pct(bw.get("total_return"), 0)} over these years.</p>
<div class="tw"><table class="data"><thead><tr><th class="l">Family</th><th>Years traded</th><th>Trades</th><th>Avg / trade</th><th>Profit factor</th><th>Random entries</th><th>Timing p (Holm)</th><th>Best trade\'s share</th><th></th></tr></thead><tbody>{"".join(wrow)}</tbody></table></div>
</section>'''


def register_table() -> str:
    rows = ['<div class="tw"><table class="data"><thead><tr><th class="l">Strategy</th><th class="l">Type · timeframe</th><th class="l">Entry and exit</th>'
            '<th class="l">Stop-loss / take-profit</th><th class="l">Published sizing</th><th class="l">Grid tested</th><th class="l">Source</th></tr></thead><tbody>']
    for f in S.FAMILIES:
        grid = "; ".join(f"{k}: {', '.join(str(v) for v in vs)}" for k, vs in f.grid.items())
        n = len(list(f.configs()))
        link = f' <a href="{esc(f.url)}" target="_blank" rel="noopener">link</a>' if f.url.startswith("http") else ""
        rows.append(f'<tr><td class="l"><b>{esc(f.name)}</b></td><td class="l sub">{esc(CAT.get(f.category, f.category))}<br>{esc(f.timeframe)}</td>'
                    f'<td class="l" style="min-width:22ch">{esc(f.rules)}</td><td class="l" style="min-width:18ch">{esc(f.stops)}</td>'
                    f'<td class="l sub">{esc(f.sizing_published)}</td><td class="l sub">{esc(grid)} <b>({n})</b></td>'
                    f'<td class="l sub" style="min-width:18ch">{esc(f.source)}{link}</td></tr>')
    rows.append("</tbody></table></div>")
    return "".join(rows)


def markdown(R: dict, V: list[dict]) -> str:
    lock, det = R["lock"], R["det"]
    passed = [x for x in V if x["status"] == "PASS"]
    bh = det["buy_and_hold"]
    lines = [f"# XAUUSD strategies targeting 2% a trade", "",
             f"**Data:** Dukascopy XAUUSD bid/ask hourly, mid prices, New York-close sessions · **In-sample** 2010-01 → 2021-09 · **Out-of-sample** 2021-10 → {det['windows']['OOS'][1]} · "
             f"**Locked** {lock['locked_at']} (code `{lock['code_hash']}`, lock `{lock.get('lock_sha256')}`) · **Configurations tested** {lock['configurations_tested']}", "",
             f"**{len(passed)} of {len(V)}** strategy families pass the brief's test (out-of-sample average ≥ 2% a trade after base costs, ≥ {lock['rules']['min_oos_trades']} trades, profit factor > 1). "
             f"Gold itself returned {pct(bh['OOS']['C1']['total_return'], 0)} over the out-of-sample period after financing.", "",
             "| # | Strategy | Verdict | IS trades | IS avg | OOS trades | OOS avg | OOS PF | OOS avg (harsh) | OOS return Oct 2021–Dec 2023 | OOS return Jan 2024– | Drift alone | Timing p (Holm) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in V:
        r, d = x["r"], x["d"]
        o = d["OOS"]["C1"]
        h1, h2 = halves(det, x["key"])
        ra = d.get("random_entry") or {}
        lines.append(f"| {x['rank']} | {x['f'].name} (`{d['label']}`) | **{x['status']}**{' (small sample)' if x['small'] else ''}: {x['why']} | "
                     f"{int(r['IS_trades']) if r['IS_trades'] == r['IS_trades'] else '–'} | {pct(r['IS_avg'])} | {int(o.get('trades') or 0)} | {pct(o.get('avg'))} | {num(o.get('profit_factor'))} | "
                     f"{pct(d['OOS']['C2'].get('avg'))} | {pct(h1, 1)} | {pct(h2, 1)} | "
                     f"{pct(ra.get('random_mean_avg')) if r['is_status'] == 'selected' else '–'} | {num(r['timing_p_holm'], 3) if r['timing_p_holm'] == r['timing_p_holm'] else '–'} |")
    for x in passed:
        d, f = x["d"], x["f"]
        lines += ["", f"## {f.name}", "", f"- **Rules:** {f.rules}", f"- **Stop-loss / take-profit:** {f.stops}", f"- **Locked parameters:** `{d['label']}`", f"- **Source:** {f.source} ({f.url})",
                  f"- **Sizing:** published {f.sizing_published}; tested at 1× notional.", f"- **Deviations:** {f.deviations}", "",
                  "| Metric | In-sample | Out-of-sample |", "|---|---|---|"]
        for k, lab, kind in METRICS:
            lines.append(f"| {lab} | {fmt(d['IS']['C1'].get(k), kind)} | {fmt(d['OOS']['C1'].get(k), kind)} |")
        ra = d.get("random_entry") or {}
        lines += ["", f"Harsh-cost OOS average {pct(d['OOS']['C2'].get('avg'))}; random entries average {pct(ra.get('random_mean_avg'))} "
                      f"(timing p {num(x['r']['timing_p'], 3)}, Holm {num(x['r']['timing_p_holm'], 3)}); bootstrap 95% interval {pct(d['oos_ci95'][0])} to {pct(d['oos_ci95'][1])}; "
                      f"neighbours passing {d['neighbours']['pass']}/{d['neighbours']['count']}."]
    sup = R.get("sup") or {}
    if sup.get("presample") and sup.get("walk_forward"):
        names = {f.key: f.name for f in S.FAMILIES}
        lines += ["", "## Two more out-of-sample checks (added after the locked run)", "",
                  f"**2005–2009** (never read by any stage; gold {pct(sup['presample']['buy_and_hold']['total_return'], 0)} after financing):", "",
                  "| Strategy | Trades | Avg / trade | PF | Random entries | Timing p |", "|---|---|---|---|---|---|"]
        for k, v in sup["presample"]["families"].items():
            if v["status_is"] != "selected":
                continue
            c = v["C1"]
            lines.append(f"| {names[k]} (`{v['label']}`) | {int(c.get('trades') or 0)} | {pct(c.get('avg'))} | {num(c.get('profit_factor'))} | {pct(v.get('random_mean_avg'))} | {num(v.get('timing_p'), 3)} |")
        lines += ["", f"**Walk-forward {sup['walk_forward']['first_year']} → latest** (parameters re-chosen each year from earlier years only; pass ≥ {sup['walk_forward']['min_trades']} trades, ≥ 2%, PF > 1):", "",
                  "| Family | Trades | Avg / trade | PF | Random entries | Timing p (Holm) | Pass |", "|---|---|---|---|---|---|---|"]
        for k, v in sup["walk_forward"]["families"].items():
            c = v["C1"]
            if not c.get("trades"):
                continue
            lines.append(f"| {names[k]} | {int(c['trades'])} | {pct(c.get('avg'))} | {num(c.get('profit_factor'))} | {pct(v.get('random_mean_avg'))} | {num(v.get('timing_p_holm'), 3)} | {'PASS' if v.get('PASS') else ''} |")
    lines += ["", "## Failed", ""] + [f"- **{x['f'].name}**: {x['why']}." for x in V if x["status"] != "PASS"]
    lines += ["", "Code, data checks and full results: this folder (`results/`). Backtests on past prices; not a forecast."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    resdir = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "results")
    R = load(resdir)
    V = verdicts(R)
    outdir = ROOT / ("report_debug" if resdir.name.endswith("debug") else "report")
    outdir.mkdir(exist_ok=True)
    (outdir / "xauusd-2pct-study.html").write_text(page(R, V), encoding="utf-8")
    if not resdir.name.endswith("debug"):
        (ROOT / "REPORT.md").write_text(markdown(R, V), encoding="utf-8")
    for x in V:
        print(f"{x['rank']:>2} {x['status']:<4} {x['f'].name:<55} {x['why']}")
    print("written", outdir / "xauusd-2pct-study.html")
