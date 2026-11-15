"""Writes the app's data for The Trade Room tab (frontend/app/premium-strategies/traderoomData.ts) and the readable
analysis (analyses/thetraderoomsss.md) from zt_spec.py, with each video's title, date and length from the Trading Video
Lab's evidence and each coded strategy's code check (results/checks.json). Generated: never edit the outputs by hand.

    python -I zt_export.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))

import zt_spec as S  # noqa: E402

OUT_TS = ROOT / "frontend" / "app" / "premium-strategies" / "traderoomData.ts"
OUT_MD = HERE / "analyses" / "thetraderoomsss.md"
LAB = ROOT / "youtube-video-explainer-reviewed" / "evidence"
# when the books start on the desk: premium-paper-service settings.YC4_START_T (flat at the start, nothing back-filled)
START = "2026-11-15T19:30:00Z"
MARKET_LABEL = {"NIFTY": "Nifty 50 (index, Angel One minutes)", "BANKNIFTY": "Bank Nifty (index, Angel One minutes)",
                "BTCUSD": "Bitcoin (Delta Exchange BTCUSD)", "XAUUSD": "Gold (Delta Exchange XAUTUSD)"}
DESK_MARKET = {"XAUUSD": "XAUTUSD"}
KINDS_ORDER = ["market", "timeframe", "session", "indicator", "setup", "entry", "stop", "target", "exit", "management",
               "sizing", "filter", "no_trade"]
KIND_LABEL = {"market": "Market and instruments", "timeframe": "Timeframe", "session": "Session",
              "indicator": "Indicators and settings", "setup": "Setup", "entry": "Entry and confirmation",
              "stop": "Stop-loss", "target": "Target", "exit": "Exit", "management": "Trade management",
              "sizing": "Position sizing and risk", "filter": "Filters", "no_trade": "When not to trade"}


def meta(vid: str) -> dict:
    folders = sorted(LAB.glob(f"{vid}-*"), key=lambda p: p.name)
    for f in reversed(folders):
        mf = f / "manifest.json"
        if mf.exists():
            j = json.loads(mf.read_text(encoding="utf-8"))
            mm = j.get("meta") or {}
            up = mm.get("upload_date") or ""
            if len(up) == 8 and up.isdigit():
                up = f"{up[:4]}-{up[4:6]}-{up[6:]}"
            return {"title": j.get("title") or mm.get("title") or "", "uploaded": up,
                    "minutes": round(float(j.get("duration") or 0) / 60)}
    return {"title": "", "uploaded": "", "minutes": 0}


def short(t: str) -> str:
    h, m, s = (int(x) for x in t.split(":"))
    return f"{m:02d}:{s:02d}" if h == 0 else f"{h}:{m:02d}:{s:02d}"


def tm(c) -> dict | None:
    return None if not c else {"v": c[0], "t": short(c[1])}


def rows(checks: dict) -> list[dict]:
    out = []
    for s in S.CODED:
        md = meta(s["video"])
        ch = checks.get(s["id"]) or {}
        rules = sorted(s["rules"], key=lambda r: (r["tag"] == "A", KINDS_ORDER.index(r["kind"])))
        out.append({
            "id": s["id"], "version": "v1", "name": s["name"], "status": "coded", "readiness": s["readiness"],
            "video": s["video"], "title": md["title"], "uploaded": md["uploaded"], "minutes": md["minutes"],
            "summary": s["summary"], "markets": [MARKET_LABEL[m] for m in s["markets"]],
            "deskMarkets": [DESK_MARKET.get(m, m) for m in s["markets"]], "timeframes": s["timeframes"],
            "rules": [{"kind": r["kind"], "label": KIND_LABEL[r["kind"]], "tag": r["tag"], "text": r["text"],
                       "quote": r["quote"], "times": [tm(c) for c in r["cites"]]} for r in rules],
            "vague": [{"term": v["term"], "at": tm(v["at"]), "why": v["why"], "coded": v["coded"]} for v in s["vague"]],
            "unclear": s["unclear"],
            "claims": [{"at": tm(c["at"]), "value": c["value"], "period": c["period"]} for c in s["claims"]],
            "examples": [{**{k: v for k, v in x.items() if k != "at"}, "at": tm(x["at"])} for x in s["examples"]],
            "duplicateCheck": s["duplicate_check"], "reason": None, "duplicateOf": None, "cites": [],
            "paperStart": START,
            "checks": ({"lookahead": bool(ch.get("lookahead_ok")), "fills": not ch.get("fill_problems"),
                        "signals": int(ch.get("signals", 0)), "trades": int(ch.get("trades", 0))} if ch else None),
        })
    for s in S.NOT_CODED + S.DUPLICATES:
        md = meta(s["video"])
        out.append({
            "id": s["id"], "version": "v1", "name": s["name"], "status": s["status"], "readiness": "assumptions",
            "video": s["video"], "title": md["title"], "uploaded": md["uploaded"], "minutes": md["minutes"], "summary": "",
            "markets": [], "deskMarkets": [], "timeframes": [], "rules": [], "vague": [], "unclear": [], "claims": [],
            "examples": [], "duplicateCheck": "", "reason": s.get("reason") or s.get("why"),
            "duplicateOf": s.get("of"), "cites": [tm(c) for c in s.get("cites", [])], "paperStart": None, "checks": None,
        })
    return out


LABEL = {S.EP1: "EP-1", S.EP2: "EP-2", S.EP3: "EP-3", S.PSY: "psychology", S.SCALP915: "9/15 EMA video",
         S.BTC15: "bitcoin short"}


def label(vid: str, kind: str, title: str) -> str:
    """A short name for a video, shown next to a time that is not in the strategy's own video."""
    if vid in LABEL:
        return LABEL[vid]
    if kind == "live" and "||" in title:
        return "live " + title.split("||")[1].strip().title()
    if title.startswith("Master Scalping"):
        return "Master Scalping"
    return kind


def videos() -> list[dict]:
    out = []
    for vid, kind, gave in S.VIDEOS:
        md = meta(vid)
        out.append({"id": vid, "kind": kind, "label": label(vid, kind, md["title"]), "title": md["title"],
                    "uploaded": md["uploaded"], "minutes": md["minutes"], "gave": gave})
    for vid, why in S.SKIPPED:
        out.append({"id": vid, "kind": "skipped", "label": "skipped", "title": "", "uploaded": "", "minutes": 0, "gave": why})
    return out


def write_ts(R: list[dict], V: list[dict]) -> None:
    coded = [r for r in R if r["status"] == "coded"]
    meta_ = {"channel": S.CHANNEL, "handle": S.HANDLE, "built": S.BUILT, "paperStart": START,
             "read": sum(1 for v in V if v["kind"] != "skipped"), "skipped": sum(1 for v in V if v["kind"] == "skipped"),
             "teaching": sum(1 for v in V if v["kind"] == "teaching"), "lives": sum(1 for v in V if v["kind"] == "live"),
             "shorts": sum(1 for v in V if v["kind"] == "short"), "coded": len(coded),
             "blocked": sum(1 for r in R if r["status"] == "blocked"),
             "duplicates": sum(1 for r in R if r["status"] == "duplicate"),
             "checked": sum(1 for r in coded if r["checks"] and r["checks"]["lookahead"] and r["checks"]["fills"])}
    head = (
        "// GENERATED by backend/research/youtube_traderoom_2026_11/zt_export.py - do not edit by hand.\n"
        "// The Trade Room (Mayank Raj) study (15 Nov 2026): every video read, the strategies found with their rules\n"
        "// (E stated / I inferred / A our assumption, each stated rule with its quote and video time), what the videos leave\n"
        "// missing or vague, the strategies not coded and why, and the code checks of the coded ones.\n\n"
        "export type TrTime = { v: string; t: string };\n"
        "export type TrRule = { kind: string; label: string; tag: \"E\" | \"I\" | \"A\"; text: string; quote: string; times: TrTime[] };\n"
        "export type TrVague = { term: string; at: TrTime | null; why: string; coded: string };\n"
        "export type TrClaim = { at: TrTime | null; value: string; period: string };\n"
        "export type TrExample = { at: TrTime | null; date: string; instrument: string; direction: string; setup: string;\n"
        "  entry: string; stop: string; target: string; outcome: string };\n"
        "export type TrStrategy = { id: string; version: string; name: string; status: \"coded\" | \"blocked\" | \"duplicate\";\n"
        "  readiness: string; video: string; title: string; uploaded: string; minutes: number; summary: string;\n"
        "  markets: string[]; deskMarkets: string[]; timeframes: string[]; rules: TrRule[]; vague: TrVague[]; unclear: string[];\n"
        "  claims: TrClaim[]; examples: TrExample[]; duplicateCheck: string; reason: string | null; duplicateOf: string | null;\n"
        "  cites: TrTime[]; paperStart: string | null;\n"
        "  checks: { lookahead: boolean; fills: boolean; signals: number; trades: number } | null };\n"
        "export type TrVideo = { id: string; kind: string; label: string; title: string; uploaded: string; minutes: number;\n"
        "  gave: string };\n\n")
    body = (f"export const TR_META = {json.dumps(meta_)};\n\n"
            f"export const TR: TrStrategy[] = {json.dumps(R, ensure_ascii=False, indent=1)};\n\n"
            f"export const TR_VIDEOS: TrVideo[] = {json.dumps(V, ensure_ascii=False, indent=1)};\n")
    OUT_TS.write_text(head + body, encoding="utf-8", newline="\n")
    print("wrote", OUT_TS, meta_)


def _t(x) -> str:
    return f"{x['v']} {x['t']}" if x else "-"


def write_md(R: list[dict], V: list[dict]) -> None:
    L = [f"# {S.CHANNEL} ({S.HANDLE}): strategies for the Premium paper desk", "",
         f"Study of {S.BUILT}. Tags: E = stated in the video; I = inferred from his words; A = our assumption so the rule can "
         "run. Times are the caption where the quoted words start (video id, then MM:SS or H:MM:SS). Quotes are his romanized "
         "Hindi captions as saved by the Trading Video Lab. Generated by zt_export.py from zt_spec.py; zt_quotes.py checks "
         "every quote against the transcripts.", "",
         f"Paper trading: Rs 10 lakh of separate virtual capital per coded strategy on the Premium paper desk (source "
         f"youtube_traderoom), simulated orders on real prices only (Delta Exchange for gold and bitcoin, the desk's Angel One "
         f"index minutes for Nifty and Bank Nifty), from {START} flat. None of these is backtested.", ""]
    for r in R:
        if r["status"] != "coded":
            continue
        L += [f"## {r['id']} v1: {r['name']}", "",
              f"Source: https://youtu.be/{r['video']} ({r['title']}, {r['uploaded']}, {r['minutes']} min). Desk markets: "
              f"{', '.join(r['markets'])}; {', '.join(r['timeframes'])}.", "", r["summary"], ""]
        for x in r["rules"]:
            q = f' "{x["quote"]}"' if x["quote"] else ""
            L.append(f"- [{x['tag']}] {x['label']}: {x['text']} ({', '.join(_t(t) for t in x['times']) or 'our choice'}){q}")
        L += ["", "Missing or ambiguous (flagged, not guessed silently):"]
        L += [f"- '{v['term']}' ({_t(v['at'])}): {v['why']}. Coded as: {v['coded']}." for v in r["vague"]]
        L += [f"- Open question: {u}" for u in r["unclear"]]
        if r["claims"] or r["examples"]:
            L += ["", "Claims and examples (as said, not verified):"]
            L += [f"- Claim ({_t(c['at'])}): {c['value']}" for c in r["claims"]]
            L += [f"- Example ({_t(x['at'])}) {x['date']}: {x['instrument']} {x['direction']}; {x['setup']}; entry {x['entry']}, "
                  f"stop {x['stop']}, target {x['target']} -> {x['outcome']}" for x in r["examples"]]
        ck = r["checks"]
        L += ["", f"Duplicate check: {r['duplicateCheck']}",
              f"Code check: {'look-ahead and fills passed' if ck and ck['lookahead'] and ck['fills'] else 'NOT PASSED' if ck else 'not run'}"
              + (f" ({ck['signals']} signals, {ck['trades']} simulated fills on research data; a correctness check, not a result)." if ck else "."), ""]
    L += ["## Not coded", ""]
    L += [f"- {r['id']} {r['name']} ({', '.join(_t(c) for c in r['cites'])}): {r['reason']}." for r in R if r["status"] == "blocked"]
    L += ["", "## Already in the app (skipped)", ""]
    L += [f"- {r['id']} {r['name']}: {r['reason']}." for r in R if r["status"] == "duplicate"]
    L += ["", "## Every video read", "", "| Video | Kind | Date | Min | What it gave |", "|---|---|---|---|---|"]
    L += [f"| [{v['id']}](https://youtu.be/{v['id']}) {v['title'][:70]} | {v['kind']} | {v['uploaded']} | {v['minutes']} | {v['gave']} |"
          for v in V]
    OUT_MD.parent.mkdir(exist_ok=True)
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print("wrote", OUT_MD)


def main():
    cp = HERE / "results" / "checks.json"
    checks = json.loads(cp.read_text())["results"] if cp.exists() else {}
    R, V = rows(checks), videos()
    write_ts(R, V)
    write_md(R, V)


if __name__ == "__main__":
    main()
