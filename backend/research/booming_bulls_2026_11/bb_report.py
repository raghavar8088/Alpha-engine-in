"""Build REPORT.md (Phase 9-10) from results/: summary.json, runs/*.json, checks.json, data_quality.json.

    python -I bb_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I does not add the script's folder
from bb_strategies import STRATEGIES  # noqa: E402

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def f(x, nd=2, pct=False):
    if x is None:
        return "–"
    if isinstance(x, str):
        return x
    try:
        if x != x:
            return "–"
    except Exception:  # noqa: BLE001
        return str(x)
    if x in (float("inf"), float("-inf")):
        return "∞"
    s = f"{x:+.{nd}f}" if not pct else f"{x:.{nd}f}%"
    return s.replace("-", "−")


def n_(x):
    return "–" if x in (None, 0) else f"{x:,}"


def main():
    summ = json.loads((RES / "summary.json").read_text())
    runs = {f'{r["strategy"]}|{r["market"]}': r for r in (json.loads(p.read_text()) for p in sorted((RES / "runs").glob("*.json")))}
    checks = json.loads((RES / "checks.json").read_text()) if (RES / "checks.json").exists() else {}
    dq = json.loads((RES / "data_quality.json").read_text()) if (RES / "data_quality.json").exists() else {}
    rows = summ["rows"]
    L = []
    L.append("# Booming Bulls strategies: backtest report (Phases 7–10)\n")
    L.append(f'Pre-registration SHA-256 `{summ["prereg_sha256"]}`. Every number below comes from `results/`, written by `bb_run.py`.\n')
    b01 = runs.get("BB-01|NIFTY", {}).get("variants", {}).get("V0", {})
    b01a, b01h = b01.get("all", {}), b01.get("hold", {})
    inr = b01.get("inr_10_lakh_hold", {})
    holds = [r["hold"] for r in rows if r["hold"].get("n")]
    gmin = min(h["mean_r_gross"] for h in holds)
    gmax = max(h["mean_r_gross"] for h in holds)
    L.append("## Summary\n")
    L.append("**Scope.** The channel has 2,965 public uploads: 1,083 videos, 1,604 Shorts and 278 live streams. Of these, 222 were selected as strategy-related (`catalogue/`).")
    L.append("- **Captions:** extracted with the project's Video Explainer app for 221 of the 222; a 25-second Short had none.")
    L.append("- **Analyses:** the 96 strategy videos (P1) and 13 worked examples (P3) were analysed with timestamps (`analyses/`).")
    L.append("- **Library:** the result is a library of 18 strategies (`specs/LIBRARY.md`). 17 were run on the markets their videos name, or the nearest on disk: Nifty, BankNifty, gold, EURUSD, GBPUSD and the Nasdaq 100. That gives 25 strategy-market books.")
    L.append("- **Rules:** every rule was written down and hash-locked before the first run (`specs/PREREGISTRATION.md`).\n")
    L.append('**Result: none of the 25 passes. All are "not supported".**')
    L.append(f"- **Before costs:** the hold-out results are close to zero, between {f(gmin)}R and {f(gmax)}R a trade.")
    L.append("- **After costs:** spread, slippage, commission and, for Nifty, India's futures charges cost 0.10-0.44R a trade. That makes every book lose.")
    L.append("- **Only BB-06 was positive in development and validation** (+0.31R and +0.46R a trade, 100 trades); it lost in the hold-out (-0.07R, 36 trades).")
    L.append("- **Nearest to break-even:** BB-11 on EURUSD and BB-13 on the Nasdaq. Each was within 0.02R of zero in the hold-out, but both lost in development and validation.\n")
    if b01a:
        L.append("**The Nifty video analysed first (gNoByC3ZEOo, BB-01).** Executed on NIFTY futures:")
        L.append(f"- **2016-2026:** {f(b01a.get('mean_r'))}R a trade after costs ({f(b01a.get('mean_r_gross'))}R before) over {b01a.get('n'):,} trades.")
        L.append(f"- **Hold-out:** {f(b01h.get('mean_r'))}R from January 2024.")
        L.append(f"- **Rs 10 lakh account:** Rs 10,00,000 became Rs {inr.get('end_inr', 0):,} over the hold-out.")
        L.append("- **September 2025:** in the month the video walks through, the same rules made +3.1R before costs and -0.8R after, over 13 trades. The presenter's own count for that month was about +12R.\n")
    L.append("**What this does and does not show.** The rules as the videos state them, executed mechanically with realistic costs, do not make money on these markets. That does not show the presenter's own discretionary trading has no edge. It does show that the edge, if any, is not in the stated rules. The videos' profit claims remain unverified.\n")
    classes = {}
    for r in rows:
        if r["chosen"]:
            classes.setdefault(r["class"], []).append(f'{r["strategy"]} {r["market"]}')
    L.append("## Verdicts (the chosen variant of each strategy and market)\n")
    for c in ("candidate for paper trading", "needs more evidence", "not supported", "unable to evaluate"):
        items = classes.get(c, [])
        L.append(f"- **{c.capitalize()}:** {len(items)}" + (f" ({', '.join(items)})" if items else ""))
    L.append("- **Unable to evaluate (no data):** BB-15 Apple opening-range trap; option P&L of every Nifty strategy (no intraday option prices).\n")
    L.append(f'Hold-out tests in the study: {summ["holdout_tests"]} (V0 and each chosen variant), Holm-corrected.\n')

    L.append("## Results (net of costs; R = profit ÷ the risk at entry; 1% of equity risked a trade)\n")
    L.append("| Strategy | Market | Variant | Dev mean R (n) | Validation mean R (n) | Hold-out mean R (n) | Hold-out t | Hold-out gross R | Win % | PF | Max DD | Class |")
    L.append("|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|")
    for r in rows:
        h, d, v = r["hold"], r["dev"], r["val"]
        star = " (chosen)" if r["chosen"] and r["variant"] != "V0" else ""
        L.append(f'| {r["strategy"]} {STRATEGIES[r["strategy"]].name} | {r["market"]} | {r["variant"]}{star} | '
                 f'{f(d.get("mean_r"))} ({n_(d.get("n"))}) | {f(v.get("mean_r"))} ({n_(v.get("n"))}) | '
                 f'{f(h.get("mean_r"))} ({n_(h.get("n"))}) | {f(h.get("t"))} | {f(h.get("mean_r_gross"))} | '
                 f'{"–" if h.get("win_rate") is None else round(100 * h["win_rate"])} | {f(h.get("profit_factor"), 2).lstrip("+")} | '
                 f'{"–" if h.get("max_dd_pct") is None else str(h["max_dd_pct"]) + "%"} | {r["class"]} |')
    L.append("")

    L.append("## Robustness (hold-out mean R under each stress; V0 and the chosen variant)\n")
    L.append("| Strategy | Market | Variant | Base | Gross (no costs) | Costs ×2 | Slippage ×3 | Entry 1 min late | Entry 1 bar late | Target −0.5R | Target +0.5R |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        run = runs[f'{r["strategy"]}|{r["market"]}']
        rb = run["robustness"].get(r["variant"], {})
        tg = [k for k in rb if k.startswith("target_")]
        tg.sort(key=lambda k: float(k[7:-1]))
        cells = [rb.get(k, {}).get("hold", {}).get("mean_r") for k in ("gross", "costs_x2", "slippage_x3", "delay_1min", "delay_1bar")]
        tcells = [rb.get(k, {}).get("hold", {}).get("mean_r") for k in tg] + [None] * (2 - len(tg))
        L.append(f'| {r["strategy"]} | {r["market"]} | {r["variant"]} | {f(r["hold"].get("mean_r"))} | ' + " | ".join(f(c) for c in cells + tcells) + " |")
    L.append("")

    L.append("## After each video was published (the only span the presenter could not have seen)\n")
    L.append("| Strategy | Market | Variant | From | Trades | Mean R | t |")
    L.append("|---|---|---|---|---:|---:|---:|")
    for r in rows:
        pp = r["post_publication"]
        L.append(f'| {r["strategy"]} | {r["market"]} | {r["variant"]} | {STRATEGIES[r["strategy"]].first_upload} | {n_(pp.get("n"))} | {f(pp.get("mean_r"))} | {f(pp.get("t"))} |')
    L.append("")

    L.append("## Walk-forward (each year trades the variant with the best record in all earlier years)\n")
    L.append("| Strategy | Market | Out-of-sample trades | Mean R | t | Picks by year |")
    L.append("|---|---|---:|---:|---:|---|")
    for key, run in runs.items():
        wf = run["walk_forward"]
        o = wf["oos"]
        picks = ", ".join(f"{y}:{p}" for y, p in wf["picks"].items())
        L.append(f'| {run["strategy"]} | {run["market"]} | {n_(o.get("n"))} | {f(o.get("mean_r"))} | {f(o.get("t"))} | {picks} |')
    L.append("")

    nifty = [r for r in rows if r["market"] == "NIFTY" and r.get("inr_10_lakh_hold")]
    if nifty:
        L.append("## A ₹10 lakh account on NIFTY futures, hold-out only (whole lots of 65, 1% risk, 12% margin a lot)\n")
        L.append("| Strategy | Variant | Start | End | Return | Max drawdown | Trades | Skipped (0 lots) |")
        L.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for r in nifty:
            a = r["inr_10_lakh_hold"]
            L.append(f'| {r["strategy"]} | {r["variant"]} | ₹{a["start_inr"]:,} | ₹{a["end_inr"]:,} | {f(a["return_pct"], 1, True)} | '
                     f'{a["max_dd_pct"]}% | {a["trades"]} | {a["skipped_zero_lots"]} |')
        L.append("\nRupee figures use today's lot of 65 for every year. NIFTY's lot size changed several times over the decade, and the R figures do not depend on it.\n")

    if checks:
        L.append("## Verification (Phase 5)\n")
        eng = checks.get("engine", {})
        la = {k: v for k, v in checks.get("lookahead", {}).items() if isinstance(v, bool)}
        L.append(f'- **Engine unit tests:** {sum(eng.values())} of {len(eng)} pass (next-minute fills at the ask/bid plus slippage, stop first, gap fills at the open, breakeven, partials, forced exits, rejections).')
        L.append(f'- **Look-ahead truncation test:** {sum(la.values())} of {len(la)} strategy-market-variant combinations give identical signals before three random cut points.')
        fb = checks.get("fidelity_bb01_sep2025", {})
        if fb:
            L.append(f'- **Fidelity, BB-01 against the video\'s own September 2025 replay:** the video trades {fb["video_trade_days"]} of {fb["days"]} days; '
                     f'our rules trade {fb["our_trade_days"]}. Both trade on {fb["both_trade"]} days and both stand aside on {fb["both_no_trade"]}. '
                     f'The setup family matches on {fb["same_setup_family"]} of {fb["both_trade"]}, and the direction matches on {fb.get("same_direction")} of '
                     f'{fb.get("direction_stated_and_both_trade")} days where he states it. Our retest stops are tighter than his (about 13 vs 23–25 points). '
                     "No rule was changed after this comparison.")
        L.append("")
    if dq:
        L.append("## Data (Phase 6)\n")
        L.append("| Market | Days | First | Last | Excluded days (feed defect) | Median half-spread |")
        L.append("|---|---:|---|---|---:|---:|")
        for k, q in dq.items():
            L.append(f'| {k} | {q["days"]:,} | {q["first"]} | {q["last"]} | {q["excluded_days"]} | {q["median_half_spread"]:.5g} |')
        L.append("")
    LIMITS = ['**Options are not evaluated.** The Nifty videos (BB-01 to BB-04) teach buying calls and puts. No intraday option prices are on disk, so the signals were traded on futures instead. An option version would differ: premium decay, wider spreads and a non-linear payoff. It cannot be inferred from the index.', "**Futures at the index price.** No intraday NIFTY/BANKNIFTY futures minutes exist, so fills use the index plus 1 point (BankNifty 3 points) of slippage a side, with Angel One's full futures charges. Intraday basis changes are ignored.", "**Volume proxy.** The value-area profile (BB-09) uses Dukascopy's hourly tick volume spread over each hour's minutes, not the broker volume TradingView shows.", '**Spot gold, forex and Nasdaq:**', "  - Gold uses HistData minutes, which are Dukascopy's bid, with Dukascopy's quoted spread.", '  - EURUSD, GBPUSD and NAS100 use fixed modelled spreads.', '  - February-July 2023 is excluded for all four (HistData thinned the feed).', '**Markets blocked on data.** Dukascopy throttled the US30 and Apple download (HTTP 503), so:', '  - BB-15 (Apple) is unevaluated;', '  - BB-12 ran on gold only;', '  - BB-14 ran on the Nasdaq 100 (the video\'s own "homework" market) instead of US30.', '**Rule fidelity.** Discretionary words ("big candle", "good candle", "with space", "logical stop") had to be fixed as numbers; every such choice is tagged A in the pre-registration.', "  - The BB-01 check against the video's own September 2025 replay matched 12 of his 15 trade days and 9 of the 10 directions he states. Our retest stops were tighter than his.", '  - BB-03 to BB-06 and BB-16 to BB-18 rest mostly on my definitions (low fidelity).', '**Video coverage:**', '  - The 113 concept videos (P2) were transcribed but not analysed one by one.', '  - 2020-2022 auto-captions are badly garbled.', "  - No video frames were analysed (the app's media download needs the owner's approval), and Whisper is not installed. On-screen-only details, such as the strike table at 05:15 of gNoByC3ZEOo, were not read.", '**Multiple testing.** 44 hold-out tests were run and Holm-corrected. With none positive and significant, the correction did not change any verdict.']
    STEPS = ["| 7 | `python -I bb_markets.py` | Builds `data/cache/*.npz` from the earlier studies' minute data and writes `results/data_quality.json` |", '| 8 | `python -I bb_checks.py` | Engine unit tests, look-ahead truncation test, BB-01 fidelity check -> `results/checks.json` |', '| 9 | `python -I bb_run.py` | All strategies, variants and robustness runs -> `results/runs/`, `results/trades/`, `results/equity/` |', '| 10 | `python -I bb_run.py --summary` | Opens the hold-out, applies Holm and the gates -> `results/summary.json` |', '| 11 | `python -I bb_report.py` | This file |']
    NEXTS = ['1. **Do not paper-trade or arm any of these rule sets.** None passed the pre-registered gates, and live trading was out of scope.', '2. **Test the option-buying versions** of BB-01 to BB-04 only with real intraday option prices (Angel or Dhan candles for live contracts, recorded forward). Results should not be inferred from the index.', '3. **Re-run the frozen rules on new data in 6-12 months,** without re-tuning, for the three near-zero books: BB-06, BB-11 EURUSD and BB-13 NAS100. The hold-out is spent, so only data after 16-23 Oct 2026 counts as new.', '4. **Fetch US30 and Apple minutes** when Dukascopy stops throttling, then run BB-12 (US30), BB-14 (US30) and BB-15 exactly as pre-registered.', "5. **With the owner's OK,** download frames (`--media`) for the on-screen-only rules, and install Whisper for the garbled 2020-2022 videos."]
    L.append("## Limitations\n")
    for x in LIMITS:
        L.append(x if x.startswith("  ") else "- " + x)
    L.append("\n## Reproduce\n")
    L.append("From `backend/research/booming_bulls_2026_11/`, Python 3.12 with numpy and pandas, always run with `python -I`.")
    L.append("- **Steps 1-6** (catalogue and transcripts): in the README.")
    L.append("- **Steps 7-11:**\n")
    L.append("| Step | Command | Does |")
    L.append("|---|---|---|")
    L.extend(STEPS)
    L.append("\n## Next steps\n")
    L.extend(NEXTS)
    (HERE / "REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print("REPORT.md written,", len(L), "lines")


if __name__ == "__main__":
    main()
