"""Audit of the 54 tournament strategies — markdown tables from tables.json (read-only).

    python audit54_tables.py [--name audit54]

Writes DATA/runs/<name>/tables.md: the master table of all 54, one card per family (15m /
45m / 1h side by side), the day setups, and the cross-cutting tables the report quotes.
Verdicts follow fixed rules stated in VERDICT below, never judgement per row.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stubpkg import DATA  # noqa: E402

VERDICT = ("**None** — no edge even before costs (raw <= 0 bp); **Weak** — raw > 0 but t < 2 (indistinguishable "
           "from luck); **Small, unproven** — raw > 0 with 2 <= t < 3.3 (with 52 rules tested, about 3.3 is needed "
           "before an edge is believable); **Real, below costs** — raw > 0 with t >= 3.3 but smaller than the "
           "~10.5 bp a round trip costs; t is day-clustered. Every replayable rule loses money after costs")


def lakh(x, sign=True):
    if x is None:
        return "—"
    return f"{x / 1e5:+.1f}" if sign else f"{x / 1e5:.1f}"


def verdict(r):
    e = r.get("every_trade")
    if r["family"].startswith("orb_sel"):
        return "Pre-registered (forward test)"
    if not e:
        return "—"
    if e["raw_bp"] <= 0:
        return "None"
    t = e.get("raw_t") or 0
    if t < 2:
        return "Weak"
    if t < 3.3:
        return "Small, unproven"
    return "Real, below costs"


def fidelity(path):
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"(iv2_\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%\s+([\d.]+)%", line)
        if m:
            out[m.group(1)] = {"live": int(m.group(2)), "bt": int(m.group(3)), "shared": int(m.group(4)),
                               "repro": float(m.group(5)), "same_exit": float(m.group(6))}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="audit54")
    a = ap.parse_args()
    run = DATA / "runs" / a.name
    d = json.load(open(run / "tables.json", encoding="utf-8"))
    fid = fidelity(run / "fidelity.txt")
    S = d["strategies"]
    by = {r["sid"]: r for r in S}
    L = []
    w = L.append

    # ── master table ──
    w("| # | Strategy | TF | Signals / day | Edge before costs bp (t, clustered by day) | Costs bp | Net / trade bp | Win % | "
      "Solo 2-yr ₹L | Return % | Max DD % | Months up | Last 6 mo ₹L | Tournament 2-yr ₹L | Live 20 d ₹L (trades) | Verdict |")
    w("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for k, r in enumerate(S, 1):
        e, s, t, lp, sg = r.get("every_trade"), r["solo"], r["tournament"], r.get("live_paper") or {}, r.get("signals") or {}
        live = f"{lakh(lp.get('net'))} ({lp.get('trades')})" if lp else "—"
        if e:
            w(f"| {k} | {r['name']} | {r['tf']} | {sg.get('per_session', '—')} | {e['raw_bp']:+.2f} ({e.get('raw_t')}) | "
              f"{e['slip_bp'] + e['fee_bp']:.1f} | {e['net_bp']:+.2f} | {e['win_pct']} | {lakh(s.get('net'))} | "
              f"{s.get('return_pct')} | {s.get('max_dd_pct')} | {s.get('months_positive')} | {lakh(s.get('h6'))} | "
              f"{lakh(t.get('net'))} | {live} | {verdict(r)} |")
        else:
            w(f"| {k} | {r['name']} | {r['tf']} | — | — | — | — | — | — | — | — | — | — | — | {live} | {verdict(r)} |")
    w("")

    # ── family cards ──
    fams = []
    for r in S:
        if r["tf"] != "day" and r["family"] not in fams:
            fams.append(r["family"])

    def card(rows, heads):
        out = ["| | " + " | ".join(heads) + " |", "|---|" + "---:|" * len(heads)]

        def line(label, f):
            vals = []
            for r in rows:
                try:
                    v = f(r)
                except (KeyError, TypeError, ZeroDivisionError):
                    v = "—"
                vals.append("—" if v is None else str(v))
            out.append(f"| {label} | " + " | ".join(vals) + " |")
        sg = lambda r: r["signals"]  # noqa: E731
        e = lambda r: r["every_trade"]  # noqa: E731
        so = lambda r: r["solo"]  # noqa: E731
        line("Signals per session", lambda r: sg(r)["per_session"])
        line("Stop / target, median bp", lambda r: f"{sg(r)['stop_bp_med']:.0f} / " +
             (f"{sg(r)['tgt_bp_med']:.0f}" if sg(r)["tgt_bp_med"] else "none (close)"))
        line("Planned reward : risk", lambda r: sg(r)["rr_med"] if sg(r)["rr_med"] else "—")
        line("Signals in the first hour (to 10:15)", lambda r: f"{sg(r)['first_hour_pct']}%")
        line("Same signal on the bar before", lambda r: f"{sg(r)['consecutive_bar_repeat_pct']}%")
        if any(r["family"] == "donchian" for r in rows):
            line("Previous bar had already broken out", lambda r: f"{sg(r)['repeat_break_pct']}%")
        line("Signals that became trades", lambda r: f"{sg(r)['traded_pct']}%")
        line("**Every signal as a trade:** trades", lambda r: f"{e(r)['n']:,}")
        line("Edge before costs, bp (t, clustered by day)", lambda r: f"{e(r)['raw_bp']:+.2f} ({e(r)['raw_t']})")
        line("Same edge with every day weighted equally, bp", lambda r: f"{e(r)['raw_bp_day_weighted']:+.2f}")
        line("Slippage + charges, bp", lambda r: f"{e(r)['slip_bp']:.1f} + {e(r)['fee_bp']:.1f}")
        line("Net per trade, bp (t, clustered by day)", lambda r: f"{e(r)['net_bp']:+.2f} ({e(r)['net_t_days']})")
        line("Win rate / direction right", lambda r: f"{e(r)['win_pct']}% / {e(r)['direction_pct']}%")
        line("Average win ÷ average loss", lambda r: e(r)["payoff"])
        line("Exits: target / stop / time / close", lambda r: " / ".join(
            f"{e(r)['exit_pct'].get(k, 0):.0f}" for k in ("target", "stoploss", "time", "eod")) + " %")
        line("Median hold, minutes", lambda r: int(e(r)["hold_min_med"]))
        line("Net bp: first 18 months / last 6 months", lambda r: f"{e(r)['dev']['net_bp']:+.1f} / {e(r)['last6m']['net_bp']:+.1f}")
        line("**Solo book (₹50 lakh):** trades", lambda r: f"{so(r)['trades']:,}")
        line("2-year P&L, ₹ lakh (return)", lambda r: f"{lakh(so(r)['net'])} ({so(r)['return_pct']}%)")
        line("Win rate / profit factor", lambda r: f"{so(r)['win_rate']}% / {so(r)['profit_factor']}")
        line("Max drawdown, ₹ lakh (% of capital)", lambda r: f"{lakh(so(r)['max_dd'], False)} ({so(r)['max_dd_pct']}%)")
        line("Sharpe (annualised)", lambda r: so(r)["sharpe"])
        line("Months up / worst month ₹ lakh", lambda r: f"{so(r)['months_positive']} / {lakh(so(r)['worst_month'])}")
        line("Year 1 / year 2 / last 6 months, ₹ lakh", lambda r: f"{lakh(so(r)['y1'])} / {lakh(so(r)['y2'])} / {lakh(so(r)['h6'])}")
        line("**Tournament:** 2-year ₹ lakh (vs solo)", lambda r: f"{lakh(r['tournament']['net'])} ({lakh(r['interference']['net_difference'])})")
        line("**Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %)", lambda r: (
            f"{lakh(r['live_paper']['net'])} ({r['live_paper']['trades']}, {r['live_paper']['win_pct']}%)") if r.get("live_paper") else "—")
        line("Live trades the backtest reproduces / same exit", lambda r: (
            f"{fid[r['sid']]['repro']:.0f}% / {fid[r['sid']]['same_exit']:.0f}%") if r["sid"] in fid else "—")
        line("Verdict", verdict)
        return out

    for fam in fams:
        rows = [by[f"iv2_{fam}_{tf}"] for tf in ("15m", "45m", "1h")]
        w(f"### {rows[0]['name'].split(' · ')[0]} (`{fam}`)")
        w("")
        L.extend(card(rows, ["15 min", "45 min", "1 hour"]))
        w("")
    day = [by[s] for s in ("iv2_orb_inplay_10", "iv2_orb_inplay_25", "iv2_gap_go", "iv2_gap_fade")]
    w("### Day setups")
    w("")
    L.extend(card(day, ["ORB in play 10%", "ORB in play 25%", "Gap and Go", "Gap Fade"]))
    w("")

    # ── cross-cutting ──
    w("### Priority scale by family (the number the tournament sorts every signal by)")
    w("")
    w("| Family | What `priority` holds | Median | 90th percentile |")
    w("|---|---|---:|---:|")
    holds = {"vwap_reversion": "stretch from VWAP, ATRs", "rsi2": "5 − RSI(2) / RSI(2) − 95",
             "zscore": "z-score (absolute)", "gap_fade": "gap, %", "orb_sel30": "expected move, bp", "orb_sel15": "expected move, bp"}
    seen = set()
    for r in S:
        if r["family"] in seen or not r.get("signals"):
            continue
        seen.add(r["family"])
        rows = [x for x in S if x["family"] == r["family"] and x.get("signals")]
        med = sorted(x["signals"]["prio_med"] for x in rows)[len(rows) // 2]
        p90 = max(x["signals"]["prio_p90"] for x in rows)
        w(f"| {r['name'].split(' · ')[0]} | {holds.get(r['family'], 'relative volume')} | {med} | {p90} |")
    w("")
    w("### First hour vs later, F&O vs non-F&O (every signal as a trade; descriptive, not a filter)")
    w("")
    w("| Strategy | First hour: n, raw, net bp | Later: n, raw, net bp | F&O (CAS): n, net bp | Non-F&O: n, net bp |")
    w("|---|---:|---:|---:|---:|")
    for r in S:
        sp = (r.get("every_trade") or {}).get("splits")
        if not sp:
            continue
        f = lambda k: (f"{sp[k]['n']:,}, {sp[k]['raw_bp']:+.1f}, {sp[k]['net_bp']:+.1f}" if sp.get(k, {}).get("n") else "—")  # noqa: E731
        g = lambda k: (f"{sp[k]['n']:,}, {sp[k]['net_bp']:+.1f}" if sp.get(k, {}).get("n") else "—")  # noqa: E731
        w(f"| {r['name']} | {f('first_hour')} | {f('later')} | {g('fno')} | {g('non_fno')} |")
    w("")
    w(f"Verdict rules: {VERDICT}.")
    (run / "tables.md").write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {run / 'tables.md'} ({len(L)} lines)")


if __name__ == "__main__":
    main()
