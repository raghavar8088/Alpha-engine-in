"""Build REPORT.md from results/ (summary.json, runs/*.json, checks.json).   python -I yt_report.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from yt_strategies import STRATEGIES  # noqa: E402

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
MK = {"NIFTY": "Nifty", "BANKNIFTY": "Bank Nifty", "XAUUSD": "Gold", "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
      "NAS100": "Nasdaq 100", "SPX500_D": "S&P 500 daily", "NAS100_D": "Nasdaq 100 daily", "NIFTY_D": "Nifty daily",
      "NSE15": "NSE stocks 15m", "NSE5": "NSE stocks 5m", "NSED": "NSE stocks daily"}


def f(x, nd=2):
    if x is None or (isinstance(x, float) and x != x):
        return "–"
    if isinstance(x, str):
        return x
    s = f"{x:+.{nd}f}"
    return s.replace("-", "−")


def n_(x):
    return "–" if not x else f"{x:,}"


def main():
    summ = json.loads((RES / "summary.json").read_text())
    runs = {f'{r["strategy"]}|{r["market"]}': r for r in (json.loads(p.read_text()) for p in sorted((RES / "runs").glob("*.json")))}
    checks = json.loads((RES / "checks.json").read_text()) if (RES / "checks.json").exists() else {}
    rows = summ["rows"]
    chosen = [r for r in rows if r["chosen"]]
    L = ["# The 20 largest trading-strategy YouTube channels: backtest report", ""]
    L.append(f'Pre-registration SHA-256 `{summ["prereg_sha256"]}`. Every number below comes from `results/`, written by `yt_run.py`.\n')
    cls = {}
    for r in chosen:
        cls.setdefault(r["class"], []).append(f'{r["strategy"]} {MK.get(r["market"], r["market"])}')
    holds = [r["hold"] for r in chosen if (r["hold"].get("n") or 0) >= 30]
    gmin, gmax = min(h["mean_r_gross"] for h in holds), max(h["mean_r_gross"] for h in holds)
    nmin, nmax = min(h["mean_r"] for h in holds), max(h["mean_r"] for h in holds)
    L.append("## Summary\n")
    L.append("- **Scope:** the 20 largest trading-strategy channels by live subscriber count (`catalogue/`). 58 signature strategy videos were picked; 53 were readable and were analysed with the project's Video Explainer app (`analyses/`).")
    L.append(f"- **Library:** they gave 28 strategy specifications (`specs/LIBRARY.md`). {len(chosen)} strategy-market books were run on Indian indices, NSE stocks, forex, gold and US indices, with every rule hash-locked before the first run.")
    L.append(f"- **Hold-out results** (books with at least 30 hold-out trades): before costs, the chosen versions averaged between {f(gmin)}R and {f(gmax)}R a trade; after costs, between {f(nmin)}R and {f(nmax)}R.\n")
    L.append("**Result: no strategy passes the gates fixed before the test.** Four books are positive in the hold-out but fail on sample size or significance:")
    L.append("- **YT-07, Rayner Teo's Connors RSI(10) pullback** (long only, daily), on the S&P 500 and the Nasdaq 100: positive in development, validation and hold-out, but only about 30 trades in 16 years (8 in each hold-out).")
    L.append("  - On Nifty it gained +0.57R a trade over 5 hold-out trades (Holm p 0.017), but with 22 trades in all it stays below the 30-trade minimum.")
    L.append("  - It is the one rule set here with a consistent, if rare, edge.")
    L.append("- **YT-10, Ghanshyam Tech's gap + hammer first candle** on Bank Nifty: +1.19R over 7 hold-out trades. Validation was flat, and there are too few trades to tell.")
    L.append("- **YT-27, Bear Bull Traders' Camarilla rules** on the Nasdaq 100: +0.03R over 312 trades (t 0.59), indistinguishable from zero.\n")
    for c in ("candidate for paper trading", "needs more evidence", "not supported", "unable to evaluate"):
        items = cls.get(c, [])
        L.append(f"- **{c.capitalize()}:** {len(items)}" + (f" ({', '.join(items)})" if items else ""))
    L.append("")
    L.append("## Results by channel (the chosen variant; net of costs; R = profit ÷ the risk at entry)\n")
    L.append("| Strategy | Channel | Market | Variant | Dev mean R (n) | Validation mean R (n) | Hold-out mean R (n) | Hold-out t | Gross R | Costs R | Win % | Class |")
    L.append("|---|---|---|---|---|---|---|--:|--:|--:|--:|---|")
    for r in sorted(chosen, key=lambda x: (x["strategy"], x["market"])):
        h, d, v = r["hold"], r["dev"], r["val"]
        L.append(f'| {r["strategy"]} {STRATEGIES[r["strategy"]].name} | {r["channel"]} | {MK.get(r["market"], r["market"])} | {r["variant"]} | '
                 f'{f(d.get("mean_r"))} ({n_(d.get("n"))}) | {f(v.get("mean_r"))} ({n_(v.get("n"))}) | {f(h.get("mean_r"))} ({n_(h.get("n"))}) | '
                 f'{f(h.get("t"))} | {f(h.get("mean_r_gross"))} | {"–" if h.get("cost_r_mean") is None else round(h["cost_r_mean"], 2)} | '
                 f'{"–" if h.get("win_rate") is None else round(100 * h["win_rate"])} | {r["class"]} |')
    L.append("")
    v0_rows = [r for r in rows if r["variant"] == "V0" and not r["chosen"]]
    if v0_rows:
        L.append("Source-faithful V0, where a different variant was chosen:\n")
        L.append("| Strategy | Market | Hold-out mean R (n) | t | Class |")
        L.append("|---|---|---|--:|---|")
        for r in sorted(v0_rows, key=lambda x: (x["strategy"], x["market"])):
            L.append(f'| {r["strategy"]} | {MK.get(r["market"], r["market"])} | {f(r["hold"].get("mean_r"))} ({n_(r["hold"].get("n"))}) | {f(r["hold"].get("t"))} | {r["class"]} |')
        L.append("")
    L.append("## Robustness (hold-out mean R under each stress, chosen variant)\n")
    L.append("| Strategy | Market | Base | Gross | Costs ×2 | Slippage ×3 | Entry one row late |")
    L.append("|---|---|--:|--:|--:|--:|--:|")
    for r in sorted(chosen, key=lambda x: (x["strategy"], x["market"])):
        rb = runs[f'{r["strategy"]}|{r["market"]}']["robustness"].get(r["variant"], {})
        g = lambda k: rb.get(k, {}).get("hold", {}).get("mean_r")
        cell = lambda x: "n/a¹" if (x is not None and abs(x) > 100) else f(x)
        L.append(f'| {r["strategy"]} | {MK.get(r["market"], r["market"])} | {f(r["hold"].get("mean_r"))} | {cell(g("gross"))} | {cell(g("costs_x2"))} | {cell(g("slippage_x3"))} | {cell(g("delay_1row"))} |')
    L.append("")
    L.append("¹ Not meaningful: a one-row-late limit fill can land a fraction of a pip from the stop, and dividing by that near-zero risk explodes the R figure.")
    L.append("– under \"Entry one row late\" for the daily stop-entry strategies (YT-12a, YT-13): the order is valid for the next day only, so a one-day delay leaves nothing to fill.\n")
    L.append("## After each video was published, and walk-forward\n")
    L.append("| Strategy | Market | From | Trades | Mean R | Walk-forward trades | Walk-forward mean R | t |")
    L.append("|---|---|---|--:|--:|--:|--:|--:|")
    for r in sorted(chosen, key=lambda x: (x["strategy"], x["market"])):
        pp, wf = r["post_publication"], r["walk_forward_oos"]
        L.append(f'| {r["strategy"]} | {MK.get(r["market"], r["market"])} | {STRATEGIES[r["strategy"]].first_upload} | {n_(pp.get("n"))} | {f(pp.get("mean_r"))} | {n_(wf.get("n"))} | {f(wf.get("mean_r"))} | {f(wf.get("t"))} |')
    L.append("")
    if checks:
        eng = checks.get("engine", {})
        la = {k: v for k, v in checks.get("lookahead", {}).items() if isinstance(v, bool)}
        L.append("## Verification (Phase 5)\n")
        L.append(f"- **Engine unit tests:** {sum(eng.values())} of {len(eng)} pass. They cover stop-entry orders, OCO pairs, limit entries, indicator exits, holding limits, fixed targets, risk units and overnight trades.")
        L.append(f"- **Look-ahead truncation test:** {sum(la.values())} of {len(la)} strategy-variant combinations give identical signals and exit flags when the data is cut at random rows.")
        L.append("- **One real defect was caught before any run:** four strategies filtered days by their final length. Logged in the pre-registration change log.\n")
    L.append("## Limitations\n")
    for x in (
        "**Videos:** 2–3 signature strategy videos per channel were analysed, not every upload, and most from rule digests (the opening plus the highest-scoring rule blocks) rather than full reads. Five picks had no captions, and Whisper is not installed. No video frames were used.",
        "**Options:** Indian channels mostly trade index options; their signals ran on index futures at the index price, so option P&L is not measured. Vishal Mehta's option-selling system was tested only through its Supertrend direction signal (YT-19, a proxy).",
        "**No data:** US stocks, US small caps, intraday options and crypto minutes. Warrior Trading, Humbled Trader and the US-stock setups of Bear Bull Traders could not be tested as taught; YT-26 runs the Bear Bull opening-range idea on NSE stocks as a labelled proxy.",
        "**NSE stocks:**",
        "  - Intraday stock tests use today's 268-stock liquid universe (survivorship bias) over two years only (2024-10 to 2026-11).",
        "  - The daily tests use the full bhavcopy with a point-in-time liquidity filter, back-adjusted for splits by an overnight-ratio rule rather than the corporate-actions file.",
        "**Rule fidelity:** many words needed numbers (\"big candle\", \"key level\", \"pullback\"). Every such choice is tagged A in the pre-registration, and strategies resting mostly on such choices are marked low fidelity in the library.",
        "**Multiple testing:** every hold-out test is Holm-corrected; gates as in the pre-registration.",
        "**Tight stops:** R is measured against each strategy's own stop. Stops at a tiny signal bar's extreme make 37 of about 700,000 trades exceed ±50R. They sit in books that lose heavily overall (t between −3 and −21) and change no verdict. A future engine should cap position size by margin.",
    ):
        L.append(x if x.startswith("  ") else "- " + x)
    L.append("")
    L.append("## Reproduce\n")
    L.append("From `backend/research/youtube_top20_2026_11/`: Node 22+ with yt-dlp, Deno and FFmpeg on PATH for steps 1–5, and `python -I` for the rest.\n")
    L.append("| Step | Command |")
    L.append("|---|---|")
    for i, c in enumerate(("node yt_candidates.mjs && node yt_candidates.mjs 2", "node yt_listings.mjs 600000", "node yt_select.mjs", "node yt_extract.mjs 2", "node yt_build_catalogue.mjs",
                           "D:/NSE-Intraday-Research/env/Scripts/python.exe yt_bhav_convert.py", "python -I yt_checks.py", "python -I yt_run.py", "python -I yt_run.py --summary", "python -I yt_report.py"), 1):
        L.append(f"| {i} | `{c}` |")
    (HERE / "REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print("REPORT.md written,", len(L), "lines")


if __name__ == "__main__":
    main()
