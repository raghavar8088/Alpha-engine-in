"""Writes frontend/app/premium-strategies/shortlistData.ts: every strategy of the channel-shortlist study with its video,
rules (tagged E / I / A with their times), what is missing or ambiguous, the claims as said, the status (coded, blocked
or duplicate) and the look-ahead / fill check of the coded ones (results/checks.json), plus the coverage of every listed
channel (158 over the owner's four lists: picked, analysed, skipped and why). Generated: never edit the .ts by hand.      python -I ze_export.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))

import ze_cardlib as CL  # noqa: E402
import ze_strategies as ZS  # noqa: E402

OUT = ROOT / "frontend" / "app" / "premium-strategies" / "shortlistData.ts"
MARKET_LABEL = {"NIFTY": "Nifty 50", "BANKNIFTY": "Bank Nifty", "NSE5": "NSE stocks (5-minute pool)",
                "NSE15": "NSE stocks (15-minute bars)", "NSED": "NSE stocks (daily, long only)", "BTCUSD": "Bitcoin (Delta BTCUSD)",
                "XAUUSD": "Gold (Delta XAUTUSD)", "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "NAS100": "Nasdaq 100 (cash session)",
                "ETHUSD": "Ether (Delta ETHUSD)"}
PROXY = {"PW-01": "the video buys ATM options; coded on the index as a labelled proxy (delta 0.5)",
         "DH-09": "the video trades index futures; coded on the index", "DH-10": "coded on the index",
         "CK-01": "the video scalps Nifty options; coded on the index",
         "FP-01": "the video buys the ATM option; coded on the index as a labelled proxy (delta 0.5: a 30-point premium move is 60 index points)",
         "RT-02": "the video trades Russell 1000 stocks on daily bars; coded on bitcoin 4-hour bars with the same bands, the coin's own 300-bar average standing in for the index filter",
         "TT-02": "the video trades forex; coded on Delta bitcoin and gold, as he says he also uses it on crypto",
         "FL-02": "the video tests EUR/USD and USD/JPY; coded on Delta gold, bitcoin and ether",
         "VS-03": "the desk's gold is Delta XAUTUSD, which also trades at weekends: its gap is the Sunday 17:00 New York open against the Friday 17:00 close, the weekend drift standing in for the spot gap"}
TOPICS = ["india_index", "india_stocks", "crypto", "forex_us"]
# when each batch's books start on the desk (premium-paper-service settings.YC3_START_T / YC3B_START_T)
START1, START2, START3 = "2026-11-13T03:40:00Z", "2026-11-13T05:00:00Z", "2026-11-13T16:00:00Z"
START4 = "2026-11-13T17:00:00Z"
START5 = "2026-11-14T11:00:00Z"
BATCH2 = {r.sid for r in ZS._NEW[31:54]}
BATCH3 = {r.sid for r in ZS._NEW[54:69]}
BATCH4 = {r.sid for r in ZS._NEW[69:90]}
BATCH5 = {r.sid for r in ZS._NEW[90:]}
SKIP_REASON = {
    "boomingbulls": "fully covered by the Booming Bulls study (96 strategy videos analysed)",
    "sensibull": "options education (premiums, Greeks): no rule the desk can trade without option prices",
    "cmegroup": "exchange education on contracts and hedging: one strategy-titled upload",
    "mcxindia": "exchange education on contracts and settlement",
    "futurestrader71": "daily market commentary (TraderBite): no strategy titles",
    "traderxo": "36 uploads, market commentary, no strategy titles", "tradersz": "market discussion streams",
    "exocharts": "order-flow platform tutorials (9 uploads)", "deribit": "crypto options and macro discussion (needs option prices)",
    "glassnode": "on-chain data analysis, not price rules", "cryptoquant": "on-chain data analysis, not price rules",
    "cryptojebb": "daily bitcoin commentary", "wolfofallstreets": "macro and market interviews", "datadash": "indicator tutorials and macro commentary",
    "jigsawtrading": "order-book (DOM) and tape reading: needs data the desk lacks", "quantpy": "option pricing and quant theory",
    "marketgurukul": "2013-16 indicator foundations", "sharekhan": "market updates and a proprietary indicator",
    "motilaloswal": "investing and market news", "stockedge": "scanner and product tutorials", "thetagainers": "option selling (needs premiums); covered by the 11-channel study",
    "siddharthbhanushali": "swing moving-average courses; covered by the top-20 study", "adamkhoo": "swing Fibonacci; covered by the top-20 study",
    "toritrades": "discretionary trend lines; covered by the top-20 study", "sunilminglani": "rules of thumb; covered by the top-20 study",
    "pushkarrajthakur": "option-chain strategies; covered by the top-20 and 11-channel studies", "vijaythakkar": "option selling and swing; covered by the 20-channel study",
    "imantrading": "US single-stock options and general guides",
    # the fourth list (crypto and gold channels)
    "bitcoinhyper": "no candidate strategy video in the screen (5 strategy-titled uploads of 546)",
    "morecryptoonline": "Elliott Wave price forecasts and targets (CME gaps, Fibonacci levels): forecasts, not testable rules",
    "cryptoanup": "daily bitcoin level calls ('final retest', 'trap'): forecasts, not rules",
    "cryptoface": "live scalping streams of discretionary trades, no stated rule set",
    "jasonpizzino": "market-cycle warnings and forecasts: no entry, stop and exit rules",
    "rektcapital": "bitcoin market-cycle analysis on weekly and monthly charts: forecasts, too slow for a paper book",
    "alessiorastani": "market forecasts and gap-fill commentary: no stated entry, stop and exit",
    "cryptokirby": "2019-20 bitcoin price-analysis streams: forecasts, not rules",
    "opticalartcrypto": "live bitcoin scalp calls: discretionary, no stated rule set",
    "investanswers": "macro, company and portfolio commentary: no trading rules",
    "cryptozombie": "bitcoin price forecasts and news: no trading rules",
    "garethsoloway": "daily trade-idea commentary on stocks, gold and crypto: discretionary calls without a fixed rule set",
    "goldsilverclub": "2016-17 weekly commodity reports: market commentary",
    "capitalcom": "broker beginner explainers of single indicators (MACD, stochastics), not complete strategies",
    "interactivebrokers": "broker platform and indicator tutorials (TWS tools, MACD)",
    "tradewithaaro": "Hindi live gold and bitcoin trading streams and broker promotions: no stated rules",
    "tradingview": "platform tool tutorials (VWAP, volume profile, Fibonacci drawing tools), not strategies",
}


def main():
    checks = {}
    cp = HERE / "results" / "checks.json"
    if cp.exists():
        checks = json.loads(cp.read_text())["results"]
    reg = {r.sid: r for r in ZS._NEW}
    rows = []
    for c in CL.all_cards():
        meta = CL.video_meta(c["video"])
        for s in c["strategies"]:
            sid = s["sid"]
            rec = reg.get(sid)
            status = "duplicate" if s["duplicate"] else ("coded" if rec else "blocked")
            ch = checks.get(sid) or {}
            rows.append({
                "id": sid, "version": "v1", "name": s["name"], "topic": c["topic"], "status": status,
                "readiness": "ready" if s["status"] == "ready" else "assumptions", "cardStatus": s["status"],
                "channel": meta["channel"], "video": c["video"], "title": meta["title"], "uploaded": meta["uploaded"],
                "minutes": meta["minutes"], "summary": c["summary"], "instruments": c["instruments"], "timeframes": c["timeframes"],
                "markets": [MARKET_LABEL.get(x, x) for x in (rec.markets if rec else ())],
                "deskMarkets": list(rec.markets) if rec else [], "overnight": bool(rec and (rec.overnight or "NSED" in rec.markets)),
                "proxy": PROXY.get(sid),
                "paperStart": (START5 if sid in BATCH5 else START4 if sid in BATCH4 else START3 if sid in BATCH3
                               else START2 if sid in BATCH2 else START1) if rec else None,
                "rules": [{"kind": r["kind"], "label": CL.KIND_LABEL[r["kind"]], "tag": r["tag"], "text": r["text"], "times": r["times"]}
                          for r in sorted(s["rules"], key=lambda r: (r["tag"] == "A", CL.KINDS_ORDER.index(r["kind"])))],
                "why": s["reasons"], "vague": c["vague"], "unclear": c["unclear"], "claims": c["claims"], "examples": c["examples"],
                "blockedReason": ZS.BLOCKED.get(sid), "duplicateOf": s["duplicate"]["of"] if s["duplicate"] else None,
                "duplicateWhy": s["duplicate"]["why"] if s["duplicate"] else None,
                "checks": ({"lookahead": bool(ch.get("lookahead_ok")), "fills": not ch.get("fill_problems"),
                            # the slow books were also checked on long windows (gold 300 days, bitcoin 400): their counts
                            "signals": int((ch.get("long_window") or ch).get("signals", 0)),
                            "trades": int((ch.get("long_window") or ch).get("trades", 0))} if ch else None),
            })
    rows.sort(key=lambda r: (TOPICS.index(r["topic"]), r["status"] != "coded", r["id"]))
    # channel coverage
    chans = json.loads((HERE / "registry" / "channels.json").read_text(encoding="utf-8"))
    cand = json.loads((HERE / "registry" / "candidates.json").read_text(encoding="utf-8"))
    picks = [l.split("\t") for l in (HERE / "catalogue" / "selection" / "picks.tsv").read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    carded = {p.stem for p in (HERE / "cards").glob("*.txt")}
    by_key: dict = {}
    for vid, key, _wave, reason in picks:
        by_key.setdefault(key, []).append({"video": vid, "why": reason, "analysed": vid in carded})
    sid_by_video = {r["video"]: r["id"] for r in rows}
    channels = []
    for key, r in chans.items():
        c = cand.get(key) or {}
        pk = by_key.get(key, [])
        channels.append({
            "key": key, "name": r["name"], "star": bool(r["star"]), "group": r["group"], "earlier": r["earlier"],
            "uploads": c.get("videos", 0), "strategyTitles": c.get("p1", 0),
            "picked": [{"video": x["video"], "why": x["why"], "analysed": x["analysed"], "id": sid_by_video.get(x["video"])} for x in pk],
            "skip": SKIP_REASON.get(key) if not pk else None,
        })
    coded = [r for r in rows if r["status"] == "coded"]
    meta = {"channels": len(chans), "coveredBefore": sum(1 for r in chans.values() if r["earlier"] and "skipped" not in r["earlier"]),
            "picked": len(picks), "analysed": len({r["video"] for r in rows}), "queued": sum(1 for v, *_ in picks if v not in carded),
            "strategies": len(rows), "coded": len(coded), "blocked": sum(1 for r in rows if r["status"] == "blocked"),
            "duplicates": sum(1 for r in rows if r["status"] == "duplicate"),
            "checked": sum(1 for r in coded if r["checks"] and r["checks"]["lookahead"] and r["checks"]["fills"]),
            "paperStart": START1, "paperStart2": START2, "paperStart3": START3, "paperStart4": START4,
            "paperStart5": START5,
            "batch1": len(ZS._NEW) - len(BATCH2) - len(BATCH3) - len(BATCH4) - len(BATCH5), "batch2": len(BATCH2),
            "batch3": len(BATCH3), "batch4": len(BATCH4), "batch5": len(BATCH5),
            "built": "2026-11-14"}
    head = (
        "// GENERATED by backend/research/youtube_shortlist_2026_11/ze_export.py - do not edit by hand.\n"
        "// The channel-shortlist study (Nov 2026): strategies from the owner's four lists of YouTube channels, each with its\n"
        "// rules (E stated / I inferred / A our assumption, with the video times), what the video leaves missing or vague, its\n"
        "// claims as said, its status and code checks; plus the coverage of every listed channel.\n\n"
        "export type SlRule = { kind: string; label: string; tag: \"E\" | \"I\" | \"A\"; text: string; times: string[] };\n"
        "export type SlVague = { term: string; rule: string; at: string; why: string; suggestion: string };\n"
        "export type SlClaim = { kind: string; at: string; value: string; period: string; quote: string };\n"
        "export type SlExample = { date: string; at: string; instrument: string; direction: string; setup: string; entry: string;\n"
        "  stop: string; target: string; outcome: string; note: string };\n"
        "export type SlStrategy = { id: string; version: string; name: string; topic: string; status: \"coded\" | \"blocked\" | \"duplicate\";\n"
        "  readiness: \"ready\" | \"assumptions\"; cardStatus: string; channel: string; video: string; title: string; uploaded: string;\n"
        "  minutes: number; summary: string; instruments: string[]; timeframes: string[]; markets: string[]; deskMarkets: string[];\n"
        "  overnight: boolean; proxy: string | null; paperStart: string | null; rules: SlRule[]; why: string[]; vague: SlVague[];\n"
        "  unclear: string[];\n"
        "  claims: SlClaim[]; examples: SlExample[]; blockedReason: string | null; duplicateOf: string | null; duplicateWhy: string | null;\n"
        "  checks: { lookahead: boolean; fills: boolean; signals: number; trades: number } | null };\n"
        "export type SlChannel = { key: string; name: string; star: boolean; group: string; earlier: string; uploads: number;\n"
        "  strategyTitles: number; picked: { video: string; why: string; analysed: boolean; id: string | null }[]; skip: string | null };\n\n")
    body = (f"export const SL_META = {json.dumps(meta)};\n\n"
            f"export const SL: SlStrategy[] = {json.dumps(rows, ensure_ascii=False, indent=1)};\n\n"
            f"export const SL_CHANNELS: SlChannel[] = {json.dumps(channels, ensure_ascii=False, indent=1)};\n")
    OUT.write_text(head + body, encoding="utf-8")
    print("wrote", OUT, "strategies", len(rows), "coded", len(coded), meta)


if __name__ == "__main__":
    main()
