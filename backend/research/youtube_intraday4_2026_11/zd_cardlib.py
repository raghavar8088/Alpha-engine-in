"""Reads the study's strategy cards (cards/<video id>.txt, the format zd_cards.mjs documents) for the registry, the
rules file and the app export. Pure text parsing: no network, no Lab."""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[2] / "youtube-video-explainer-reviewed"
KINDS_ORDER = ["market", "timeframe", "session", "indicator", "setup", "entry", "stop", "target", "exit", "management",
               "sizing", "filter", "no_trade"]
KIND_LABEL = {"market": "Market and instruments", "timeframe": "Timeframe", "session": "Session",
              "indicator": "Indicators and settings", "setup": "Setup", "entry": "Entry and confirmation",
              "stop": "Stop-loss", "target": "Target", "exit": "Exit", "management": "Trade management",
              "sizing": "Position sizing and risk", "filter": "Filters", "no_trade": "When not to trade"}


def _ts(s: str) -> str:
    s = s.strip()
    if not s or s == "-":
        return ""
    p = [int(x) for x in s.split(":")]
    sec = p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]
    return f"{sec // 60:02d}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}"


def _split(s: str, n: int) -> list[str]:
    a = [x.strip() for x in s.split(" | ")]
    return a + [""] * (n - len(a))


def parse(vid: str) -> dict:
    text = (HERE / "cards" / f"{vid}.txt").read_text(encoding="utf-8")
    c = {"video": vid, "topic": "", "summary": "", "instruments": [], "timeframes": [], "style": "", "strategies": [],
         "vague": [], "claims": [], "examples": [], "promotions": [], "screen": [], "unclear": []}
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(video|topic|summary|instruments|timeframes|style):\s*(.*)$", line)
        if m:
            k, v = m.groups()
            if k == "instruments":
                c[k] = [x.strip().rstrip("*").strip() for x in v.split(";") if x.strip()]
            elif k == "timeframes":
                c[k] = [x.strip() for x in v.split(",") if x.strip()]
            elif k != "video":
                c[k] = v
            continue
        tag, rest = line[0], line[1:].strip()
        if tag == "=":
            sid, name = _split(rest, 2)
            cur = {"sid": sid, "name": name, "rules": [], "status": "", "reasons": [], "duplicate": None}
            c["strategies"].append(cur)
        elif tag == "R":
            m = re.match(r"^(\w+)\s+([EIA])\s+(\S+)\s*\|\s*(.*)$", rest)
            kind, t, times, body = m.groups()
            txt, quote = _split(body, 2)
            cur["rules"].append({"kind": kind, "tag": t, "times": [] if times == "-" else [_ts(x) for x in times.split(",")],
                                 "text": txt, "quote": quote.strip('"')})
        elif tag == "T":
            st, why = _split(rest, 2)
            cur["status"], cur["reasons"] = st, [x.strip() for x in why.split(";") if x.strip()]
        elif tag == "D":
            of, why = _split(rest, 2)
            cur["duplicate"] = {"of": of, "why": why}
        elif tag == "V":
            term, rule, at, why, sug = _split(rest, 5)
            c["vague"].append({"term": term, "rule": rule, "at": _ts(at), "why": why, "suggestion": sug})
        elif tag == "C":
            kind, at, value, period, quote = _split(rest, 5)
            c["claims"].append({"kind": kind, "at": _ts(at), "value": value, "period": period, "quote": quote.strip('"')})
        elif tag == "X":
            f = _split(rest, 10)
            c["examples"].append({"date": "" if f[0] == "-" else f[0], "at": _ts(f[1]), "instrument": f[2], "direction": f[3],
                                  "setup": f[4], "entry": f[5], "stop": f[6], "target": f[7], "outcome": f[8], "note": f[9]})
        elif tag == "P":
            a, b, what = _split(rest, 3)
            c["promotions"].append({"from": _ts(a), "to": _ts(b), "what": what})
        elif tag == "O":
            at, what = _split(rest, 2)
            c["screen"].append({"at": _ts(at), "what": what})
        elif tag == "U":
            c["unclear"].append(rest)
    return c


def all_cards() -> list[dict]:
    return [parse(p.stem) for p in sorted((HERE / "cards").glob("*.txt"))]


def video_meta(vid: str) -> dict:
    """Title, channel, upload date and length from the Lab's newest evidence folder of the video."""
    folders = sorted((LAB / "evidence").glob(f"{vid}-*"), key=lambda p: p.name)
    for f in reversed(folders):
        mf = f / "manifest.json"
        if mf.exists():
            j = json.loads(mf.read_text(encoding="utf-8"))
            meta = j.get("meta") or {}
            up = meta.get("upload_date") or ""
            if len(up) == 8 and up.isdigit():
                up = f"{up[:4]}-{up[4:6]}-{up[6:]}"
            return {"title": j.get("title") or meta.get("title") or "", "channel": meta.get("channel") or "",
                    "channel_id": meta.get("channel_id") or "", "uploaded": up,
                    "minutes": round(float(j.get("duration") or 0) / 60), "words": (j.get("transcript") or {}).get("clean_words"),
                    "captions": (j.get("transcript") or {}).get("source") or ""}
    return {"title": "", "channel": "", "channel_id": "", "uploaded": "", "minutes": 0, "words": None, "captions": ""}
