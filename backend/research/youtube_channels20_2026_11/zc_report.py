"""Writes REPORT.md, the study's final report, from the saved files: the selection (zc_selection), the registry
(zc_strategies), the backtests (results/backtest.json) and a snapshot of the paper desk's summary
(results/paper_snapshot_<UTC>.json, the API's /api/premium-paper/summary saved at that time).
    python -I zc_report.py results/paper_snapshot_20261110T0109Z.json"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import zc_selection as SEL  # noqa: E402
import zc_strategies as ZS  # noqa: E402

SECT = {"india_intraday": "Indian Market - Equity Intraday", "india_options": "Indian Market - Options", "crypto": "Crypto",
        "gold": "Gold", "crypto_gold": "Crypto and Gold (shown in both sections)"}
NOTE = {"DE-04": "long-only gold trend; R = 1% of price (no stop)", "TB-04": "long-only daily Nifty; R = 3% of price",
        "DT-04": "long-only daily bitcoin; R = 1% of price; too few trades", "TP-01H": "too few trades",
        "VT-02": "long-only weekly stocks in a rising market", "VT-03": "long-only swing stocks in a rising market"}


def main(snapshot: str) -> None:
    bt = json.loads((HERE / "results" / "backtest.json").read_text())
    snap = json.loads((HERE / snapshot).read_text(encoding="utf-8"))
    stamp = re.search(r"(\d{8}T\d{4}Z)", snapshot).group(1)
    when = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]} UTC"
    acc = {a["id"]: a for a in snap["accounts"] if a.get("source") == ZS.SOURCE}
    books = snap["status"]["books"]
    L = ["# The 20-channel study: final report", "",
         "Research, rules and code: this folder. Channel selection: registry/SELECTION.md. Rules with evidence and",
         "assumptions: specs/RULES.md (from analyses/<channel>.md). Backtests: results/BACKTEST.md. Checks: results/checks.json.",
         f"Paper desk snapshot quoted below: {snapshot} ({when}). Paper only: simulated orders on real market data; the",
         "desk has no real-money execution.", "",
         "## 1. Coverage", "",
         "- Channels: 417 found by search; the 70 covered by earlier studies removed; 40 shortlisted by their share of",
         "  strategy videos; 20 selected (section 2) and 20 skipped with reasons (registry/SELECTION.md).",
         "- Uploads catalogued for the 20 channels: 9,021. Videos selected and analysed: 117, all from transcripts; 4 through",
         "  Whisper because the caption track was missing (EGyyxeQgLfw, ioDiVekuOTs) or in the wrong language (pCmJ8wsAS_w,",
         "  2NI44nAh3co). No selected video was left unread; the Hindi Whisper transcript of ioDiVekuOTs is poor but classifiable.",
         "- Playlists: 65 strategy-like playlists opened; they list 240 videos missing from the upload catalogues (mostly",
         "  Shorts and older uploads). They are queued in registry/playlist_entries.json and were NOT analysed in this cycle.", "",
         "## 2. The 20 channels", "", "| Channel | Markets | Why chosen | Coded / blocked |", "|---|---|---|---|"]
    for slug, (mk, _strat, _lang, why) in SEL.SELECTED.items():
        coded = sum(1 for s in ZS.NEW if ZS.PREFIX[s.split("-")[0]] == slug)
        blocked = sum(1 for b in ZS.BLOCKED if b[2] == slug)
        L.append(f"| {ZS.CHANNELS[slug]} ({ZS.CHANNEL_IDS[slug]}) | {mk} | {why} | {coded} / {blocked} |")
    n_ready = sum(1 for s in ZS.NEW.values() if s.readiness == "ready")
    L += ["", "## 3. Strategies", "",
          f"- Coded: {len(ZS.NEW)}, version v1 each: {n_ready} with every rule stated, {len(ZS.NEW) - n_ready} with documented",
          "  research assumptions (the [A] lines of each analysis).",
          f"- Blocked: {len(ZS.BLOCKED)} (section 6). Duplicates of the existing library: {len(ZS.DUPLICATES)}. Second-source videos",
          f"  merged into a strategy: {len(ZS.MERGED)}. Videos that teach no strategy: {len(ZS.NOT_STRATEGIES)}.",
          "- Indian option strategies trade the index (or the stock) as a labelled proxy: the desk has no intraday option",
          "  premiums. Strategies that need the premiums themselves are blocked.",
          "- Checks: the truncation (look-ahead) test at 3 random cuts and the fill test pass for all 90.",
          "- Fixed before activation: UP-06's order-side check was inverted (it gave no signal); its band became Supertrend's",
          "  ratcheted band (analyses/upsurgeclub.md).", "", "By section:", ""]
    by = defaultdict(list)
    for s in ZS.NEW:
        by[ZS.section_of(s)].append(s)
    for k in ("india_intraday", "india_options", "crypto", "gold", "crypto_gold"):
        L.append(f"- {SECT[k]} ({len(by[k])}): {', '.join(by[k])}")
    st = Counter(r["state"] for k, v in books.items() if k in ZS.NEW for r in v)
    L += ["", "## 4. Activation", "",
          "- All 90 accounts (128 strategy-market books, Rs 10 lakh each) started at 2026-11-09 20:20 UTC (10 Nov 01:50 IST),",
          "  flat. Indicators warm up on earlier bars; only signals after that minute trade, and a trade the desk has not seen",
          "  before is taken only if its entry bar is fresh (bars that arrive late after a stale feed never become entries).",
          "- Data: Delta Exchange India 1-minute candles (BTCUSD, ETHUSD, XAUTUSD, read every 2 minutes); Angel One through the",
          "  app's backend (Nifty 50 and Nifty Bank minutes, NSE stocks on 5-minute bars); NSE bhavcopy (daily stocks); Nifty",
          "  daily from the stored minutes. Gold trades XAUTUSD at 0.001 contracts, bitcoin BTCUSD at 0.001 BTC, ether ETHUSD",
          "  at 0.01 ETH.",
          f"- Book states at {when}: " + ", ".join(f"{n} {k}" for k, n in sorted(st.items(), key=lambda x: -x[1])) +
          " (armed = waiting for the NSE open at 09:15 IST; daily books act on the next daily bar).", "",
          "## 5. Backtests (net of costs, in-sample)", "",
          "Through the desk's own code (next-row fills at the bid/ask, slippage, fees). The windows include the years the",
          "videos were made in, so a positive result is not evidence of an edge.", "",
          "| Strategy | Market | Trades | Net R / trade | t | Note |", "|---|---|---|---|---|---|"]
    pos, neg = [], 0
    for sid, mk in bt.items():
        for m, s in mk.items():
            if isinstance(s, dict) and s.get("n"):
                if (s.get("mean_r") or 0) > 0:
                    pos.append((sid, m, s))
                else:
                    neg += 1
    pos.sort(key=lambda x: -x[2]["mean_r"])
    for sid, m, s in pos:
        L.append(f"| {sid} | {m} | {s['n']} | {s['mean_r']:+.3f} | {s.get('t_stat')} | {NOTE.get(sid, '')} |")
    L += ["", f"Positive after costs: {len(pos)} of {len(pos) + neg} books; the rest lose, most of them to costs on short stops",
          "(scalps on 1- to 5-minute bars). Full table: results/BACKTEST.md.", "", "## 6. Blocked (no account)", ""]
    for b in ZS.BLOCKED:
        L.append(f"- {b[0]} {b[1]} ({ZS.CHANNELS[b[2]]}; {', '.join(b[3])}): {b[5]}")
    L += ["", "Duplicates of the library:", ""]
    for d in ZS.DUPLICATES:
        L.append(f"- {d[0]} ({ZS.CHANNELS[d[1]]}): {d[2]} - duplicate of {d[3]}")
    tr = [a for a in acc.values() if a["closed"] + a["open"]]
    pnl = sum(a["equity"] - a["capital"] for a in acc.values())
    L += ["", f"## 7. Paper results at {when}", "",
          f"- {len(tr)} of {len(acc)} accounts have traded: {sum(a['closed'] for a in acc.values())} closed trades "
          f"({sum(a['wins'] for a in acc.values())} winners), {sum(a['open'] for a in acc.values())} open.",
          f"- Combined P&L of the {len(acc)} accounts: Rs {round(pnl):,} (realised Rs {round(sum(a['realised'] for a in acc.values())):,},"
          f" unrealised Rs {round(sum(a['unrealised'] for a in acc.values())):,}).",
          "- Far too early to judge any strategy; the page's 20 channels tab shows each account live.", ""]
    (HERE / "REPORT.md").write_text("\n".join(L), encoding="utf-8", newline="\n")
    print("written", len(L), "lines; positive books", len(pos), "negative", neg, "traded accounts", len(tr), "pnl", round(pnl))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/paper_snapshot_20261110T0109Z.json")
