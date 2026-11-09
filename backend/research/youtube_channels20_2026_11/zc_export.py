"""Writes the 20-channel study's reports and the page's data from the saved files (nothing is re-run here):
  registry/SELECTION.md                                    the 20 channels, the skipped ones and the video coverage
  results/BACKTEST.md                                      every book's backtest, net of costs
  frontend/app/premium-strategies/channels20Data.ts         the cards of the Premium Strategies page ("20 channels" tab)
    python -I zc_export.py"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[2]

import zc_selection as SEL  # noqa: E402
import zc_strategies as ZS  # noqa: E402

TF_NAME = {1: "1m", 2: "2m", 3: "3m", 5: "5m", 9: "9m", 10: "10m", 15: "15m", 30: "30m", 60: "1h", 240: "4h", 1440: "1D"}
BOOK = {"XAUUSD": "XAUTUSD"}
DESK_MARKET = {"NIFTY": "Nifty 50 index", "BANKNIFTY": "Nifty Bank index", "NSE5": "NSE stocks (5-minute)",
               "NSE15": "NSE stocks (15-minute)", "NSED": "NSE stocks (daily)", "NIFTY_D": "Nifty 50 (daily)",
               "BTCUSD": "Bitcoin", "XAUUSD": "Gold", "ETHUSD": "Ether"}
INSTRUMENT = {"NIFTY": "Nifty 50 index, futures lot of 65 (Angel One data)", "BANKNIFTY": "Nifty Bank index, futures lot of 30 (Angel One data)",
              "NSE5": "NSE cash stocks, 5-minute bars (Angel One)", "NSE15": "NSE cash stocks, 15-minute bars (Angel One)",
              "NSED": "NSE cash stocks, daily bhavcopy", "NIFTY_D": "Nifty 50 daily, futures lot of 65",
              "BTCUSD": "Delta Exchange BTCUSD perpetual, 0.001 BTC contracts",
              "XAUUSD": "Delta Exchange XAUTUSD perpetual, 0.001 contracts", "ETHUSD": "Delta Exchange ETHUSD perpetual, 0.01 ETH contracts"}
RISK = {"NIFTY": "1% of equity a trade, whole lots (one lot if that risks at most 5%)", "BANKNIFTY": "1% of equity a trade, whole lots",
        "NSE5": "0.25% of equity a trade, at most 25% of equity in one stock, 4 positions at once",
        "NSE15": "0.25% of equity a trade, at most 25% of equity in one stock, 4 positions at once",
        "NSED": "1% of equity a trade, at most 10% of equity in one stock, 10 positions at once",
        "NIFTY_D": "1% of equity a trade, whole lots", "BTCUSD": "1% of equity a trade, 10x margin",
        "XAUUSD": "1% of equity a trade, 20x margin", "ETHUSD": "1% of equity a trade, 10x margin"}


def verdict(s: dict) -> str:
    n, mr, t = s.get("n") or 0, s.get("mean_r"), s.get("t_stat")
    if not n:
        return "No trades in the window"
    if n < 30:
        return "Too few trades to judge"
    if mr is None or mr <= 0:
        return "Not supported (loses after costs)"
    if t is not None and t >= 2:
        return "Positive after costs (t >= 2), in-sample only"
    return "Positive after costs, not significant"


def rules_of() -> dict:
    """{sid: [(label, text)]} from specs/RULES.md (the bullets of each strategy)."""
    out, cur = {}, None
    for ln in (HERE / "specs" / "RULES.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^### ([A-Z]{2}-\d+H?) ", ln)
        if m:
            cur = m.group(1)
            out[cur] = []
            continue
        if ln.startswith("## "):
            cur = None
            continue
        if cur is None or not ln.strip():
            continue
        if ln.startswith("- "):
            mm = re.match(r"^- \*\*(.+?)\*\*:\s*(.*)$", ln)
            out[cur].append([mm.group(1), mm.group(2)] if mm else ["", ln[2:].strip()])
        elif ln.startswith("  ") and out[cur]:
            out[cur][-1][1] += " " + ln.strip()
    return out


def coverage() -> dict:
    cand = json.loads((HERE / "registry" / "candidates.json").read_text(encoding="utf-8"))
    by_slug = {}
    for cid, v in cand.items():
        h = (v["channel"].get("handle") or "").lstrip("@").lower().replace("_", "").replace("-", "")
        by_slug[cid] = v
    out = {}
    pe = json.loads((HERE / "registry" / "playlist_entries.json").read_text(encoding="utf-8"))
    pls = json.loads((HERE / "registry" / "playlists.json").read_text(encoding="utf-8"))
    for slug, cid in ZS.CHANNEL_IDS.items():
        raw = HERE / "catalogue" / "raw" / f"{cid}.json"
        n_up = len(json.loads(raw.read_text(encoding="utf-8")).get("entries", [])) if raw.exists() else None
        with open(HERE / "catalogue" / "selection" / f"{slug}.tsv", encoding="utf-8") as f:
            sel = [r for r in csv.DictReader(f, delimiter="\t")]
        outside = {e["id"] for p in pe.values() if p.get("channel") == slug for e in p.get("not_in_uploads", [])}
        out[slug] = {"uploads": n_up, "strategy_titles": by_slug.get(cid, {}).get("p1"), "selected": len(sel),
                     "playlists": len((pls.get(slug) or {}).get("playlists") or []),
                     "playlists_opened": len((pls.get(slug) or {}).get("strategy_like") or []), "outside_uploads": len(outside),
                     "videos": [r["id"] for r in sel]}
    return out


def main():
    bt = json.loads((HERE / "results" / "backtest.json").read_text())
    ck = json.loads((HERE / "results" / "checks.json").read_text())["results"]
    rules = rules_of()
    cov = coverage()

    # ── SELECTION.md ──
    L = ["# The 20-channel study: channel selection", "",
         "From 417 channels found by search (registry/discovery.json), the 70 channels the earlier studies covered were",
         "removed (registry/covered.json) and 40 were shortlisted by the share of their uploads that are strategy videos",
         "(registry/candidates.json). These 20 were chosen for depth and clarity of rules, chart demonstrations and",
         "relevance to Indian equity intraday, Indian options, crypto and gold - not for subscribers, views or profit claims.", "",
         "| # | Channel | URL / id | Markets | Strategy coverage | Language | Why | Status | Uploads | Strategy titles | Videos analysed |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    tot_sel = tot_up = tot_out = 0
    for i, (slug, (mk, strat, lang, why)) in enumerate(SEL.SELECTED.items(), 1):
        c = cov[slug]
        tot_sel += c["selected"]
        tot_up += c["uploads"] or 0
        tot_out += c["outside_uploads"]
        cid = ZS.CHANNEL_IDS[slug]
        L.append(f"| {i} | {ZS.CHANNELS[slug]} | https://www.youtube.com/channel/{cid} ({cid}) | {mk} | {strat} | {lang} | {why} | "
                 f"analysed | {c['uploads']} | {c['strategy_titles']} | {c['selected']} |")
    L += ["", f"Uploads catalogued: {tot_up}. Videos selected and analysed: {tot_sel} (four of them through Whisper because the",
          "caption track was missing or in the wrong language: EGyyxeQgLfw, ioDiVekuOTs, pCmJ8wsAS_w, 2NI44nAh3co).",
          f"Strategy playlists opened: {sum(c['playlists_opened'] for c in cov.values())}; they list {tot_out} videos that are not in the",
          "channels' upload catalogues (mostly Shorts and older uploads). They are recorded in registry/playlist_entries.json as",
          "queued: not analysed in this cycle.", "", "## Shortlisted but skipped", "", "| Channel | id | Reason |", "|---|---|---|"]
    for cid, (name, why) in SEL.SKIPPED.items():
        L.append(f"| {name} | {cid} | {why} |")
    L += ["", "All 70 channels of the earlier studies (registry/COVERED.md) were skipped as already analysed.", ""]
    (HERE / "registry" / "SELECTION.md").write_text("\n".join(L), encoding="utf-8", newline="\n")

    # ── BACKTEST.md ──
    B = ["# The 20-channel study: backtests (net of costs)", "",
         "Run by zc_backtest.py through the paper desk's own code (yc_run.run, the 11-channel fill engine): next-bar fills at",
         "the bid / ask with slippage and fees; Indian pools with the desk's 4-position rule. R = result / risk at entry, net.",
         "% = the sum at the desk's risk a trade (1%; 0.25% in the NSE pools), no compounding. Windows: Nifty / Bank Nifty",
         "500 sessions, gold 520 sessions, bitcoin 730 days, ether Aug-Oct 2026, NSE 5-minute pool 520 sessions (268 stocks),",
         "NSE daily stocks from 2019, Nifty daily from 2016. These windows include the years the videos were made in: a",
         "positive result is in-sample, not evidence of an edge.", "",
         "| Strategy | Market | Trades | Win % | Net R / trade | Gross R | Cost R | Total R | % at desk risk | PF | Max DD R | t | Verdict |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    n_books = n_pos = 0
    for sid in ZS.NEW:
        for mk, s in (bt.get(sid) or {}).items():
            if not isinstance(s, dict):
                continue
            n_books += 1
            n_pos += bool(s.get("n") and (s.get("mean_r") or 0) > 0)
            f = lambda k, nd=2: "-" if s.get(k) is None else (f"{s[k]:.{nd}f}" if isinstance(s[k], float) else str(s[k]))  # noqa: E731
            B.append(f"| {sid} | {mk} | {s.get('n', 0)} | {'-' if s.get('win_rate') is None else round(100 * s['win_rate'])} | "
                     f"{f('mean_r', 3)} | {f('mean_r_gross', 3)} | {f('cost_r', 3)} | {f('total_r', 1)} | {f('pct', 1)} | {f('pf')} | "
                     f"{f('max_dd_r', 1)} | {f('t_stat')} | {verdict(s)} |")
    B += ["", f"Books: {n_books}; positive after costs: {n_pos}.", ""]
    (HERE / "results" / "BACKTEST.md").write_text("\n".join(B), encoding="utf-8", newline="\n")

    # ── the page's data ──
    strategies = []
    for sid, st in ZS.NEW.items():
        books = []
        for mk in st.markets:
            s = (bt.get(sid) or {}).get(mk) or {}
            books.append({"market": DESK_MARKET[mk], "book": BOOK.get(mk, mk), "instrument": INSTRUMENT[mk], "risk": RISK[mk],
                          "n": s.get("n", 0), "winRate": s.get("win_rate"), "meanR": s.get("mean_r"), "grossR": s.get("mean_r_gross"),
                          "costR": s.get("cost_r"), "totalR": s.get("total_r"), "pct": s.get("pct"), "pf": s.get("pf"),
                          "maxDdR": s.get("max_dd_r"), "t": s.get("t_stat"), "window": s.get("window"),
                          "byYear": s.get("by_year"), "verdict": verdict(s)})
        c = ck.get(sid) or {}
        strategies.append({
            "id": sid, "version": st.version, "name": st.name, "channel": ZS.CHANNELS[st.channel],
            "channelUrl": f"https://www.youtube.com/channel/{ZS.CHANNEL_IDS[st.channel]}", "section": ZS.section_of(sid),
            "timeframes": [TF_NAME.get(t, f"{t}m") for t in st.tfs] or ["4h"], "videos": list(ZS.VIDEOS[sid]),
            "readiness": st.readiness, "proxy": ZS.PROXY.get(sid), "overnight": bool(st.overnight or any(m in ("NSED", "NIFTY_D") for m in st.markets)),
            "lookahead": bool(c.get("lookahead_ok")) and not c.get("fill_problems"), "rules": rules.get(sid, []), "books": books,
        })
    blocked = [{"id": b[0], "name": b[1], "channel": ZS.CHANNELS[b[2]], "videos": list(b[3]), "section": b[4], "reason": b[5]}
               for b in ZS.BLOCKED]
    channels = [{"slug": slug, "name": ZS.CHANNELS[slug], "id": ZS.CHANNEL_IDS[slug],
                 "url": f"https://www.youtube.com/channel/{ZS.CHANNEL_IDS[slug]}", "markets": v[0], "coverage": v[1], "language": v[2],
                 "why": v[3], "status": "analysed", **{k: cov[slug][k] for k in ("uploads", "strategy_titles", "selected")},
                 "coded": sum(1 for s in ZS.NEW if ZS.PREFIX[s.split('-')[0]] == slug),
                 "blocked": sum(1 for b in ZS.BLOCKED if b[2] == slug)} for slug, v in SEL.SELECTED.items()]
    meta = {"discovered": 417, "covered_before": 70, "shortlisted": 40, "selected": 20,
            "uploads": sum(c["uploads"] or 0 for c in cov.values()), "videos_analysed": sum(c["selected"] for c in cov.values()),
            "whisper": 4, "playlist_videos_queued": sum(c["outside_uploads"] for c in cov.values()),
            "coded": len(ZS.NEW), "blocked": len(ZS.BLOCKED), "duplicates": len(ZS.DUPLICATES), "merged": len(ZS.MERGED),
            "not_strategies": len(ZS.NOT_STRATEGIES), "books": n_books, "books_positive": n_pos,
            "lookahead_ok": sum(1 for s in strategies if s["lookahead"])}
    dups = [{"video": d[0], "channel": ZS.CHANNELS[d[1]], "what": d[2], "duplicateOf": d[3]} for d in ZS.DUPLICATES]
    skipped = [{"id": cid, "name": n, "reason": r} for cid, (n, r) in SEL.SKIPPED.items()]
    head = ("// GENERATED by backend/research/youtube_channels20_2026_11/zc_export.py - do not edit by hand.\n"
            "// The 20-channel study (Nov 2026): every coded strategy with its rules (specs/RULES.md), evidence, assumptions and\n"
            "// backtest (results/backtest.json, net of costs), the blocked ones with the reason, and the channel selection.\n\n"
            "export type Ch20Book = { market: string; book: string; instrument: string; risk: string; n: number; winRate: number | null;\n"
            "  meanR: number | null; grossR: number | null; costR: number | null; totalR: number | null; pct: number | null; pf: number | null;\n"
            "  maxDdR: number | null; t: number | null; window: [string, string] | null; byYear: Record<string, [number, number]> | null; verdict: string };\n"
            "export type Ch20Strategy = { id: string; version: string; name: string; channel: string; channelUrl: string; section: string;\n"
            "  timeframes: string[]; videos: string[]; readiness: string; proxy: string | null; overnight: boolean; lookahead: boolean;\n"
            "  rules: [string, string][]; books: Ch20Book[] };\n"
            "export type Ch20Blocked = { id: string; name: string; channel: string; videos: string[]; section: string; reason: string };\n\n")
    body = (f"export const CH20_META = {json.dumps(meta)};\n"
            f"export const CH20_CHANNELS = {json.dumps(channels, ensure_ascii=False, indent=1)};\n"
            f"export const CH20_SKIPPED = {json.dumps(skipped, ensure_ascii=False, indent=1)};\n"
            f"export const CH20_DUPLICATES = {json.dumps(dups, ensure_ascii=False, indent=1)};\n"
            f"export const CH20_BLOCKED: Ch20Blocked[] = {json.dumps(blocked, ensure_ascii=False, indent=1)};\n"
            f"export const CH20: Ch20Strategy[] = {json.dumps(strategies, ensure_ascii=False, indent=1)};\n")
    (ROOT / "frontend" / "app" / "premium-strategies" / "channels20Data.ts").write_text(head + body, encoding="utf-8", newline="\n")
    print("selection", len(channels), "strategies", len(strategies), "blocked", len(blocked), "books", n_books, "positive", n_pos, meta)


if __name__ == "__main__":
    main()
