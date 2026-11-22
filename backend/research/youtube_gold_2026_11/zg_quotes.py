"""Quotes of the gold channels 21-40 study against the saved transcripts (Trading Video Lab evidence; Hindi captions in
their Latin-letter form). A quote must appear word for word (case, punctuation and spacing ignored) and its time must
be the caption where its first word is spoken, within 2 seconds.

    python -I zg_quotes.py                      check every quote of zg_spec.py (exit 1 on a miss)
    python -I zg_quotes.py find <video> "<words>"   print where the words start
"""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LAB = HERE.parents[2] / "youtube-video-explainer-reviewed" / "evidence"
_W = re.compile(r"[a-z0-9]+")


def _folder(video: str) -> Path | None:
    best = None
    for p in LAB.glob(video + "-*"):
        m = re.fullmatch(re.escape(video) + r"-(\d{10,})", p.name)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p)
    return best[1] if best else None


@lru_cache(maxsize=None)
def words(video: str) -> tuple[list[str], list[int]]:
    """The transcript as (words, caption start second of each word)."""
    f = _folder(video)
    if f is None:
        raise FileNotFoundError(f"no evidence for {video}")
    man = json.loads((f / "manifest.json").read_text(encoding="utf-8"))
    src = f / ("transcript.roman.txt" if man.get("transcript", {}).get("hindi_script") and (f / "transcript.roman.txt").exists()
               else "transcript.txt")
    ws, ts = [], []
    for line in src.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\[(\d\d):(\d\d):(\d\d)\]\s*(.*)$", line)
        if not m:
            continue
        sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        for w in _W.findall(m.group(4).lower()):
            ws.append(w)
            ts.append(sec)
    return ws, ts


def locate(video: str, quote: str) -> list[int]:
    """Caption seconds at which the quote's word sequence starts (every match)."""
    q = _W.findall(quote.lower())
    ws, ts = words(video)
    n = len(q)
    return [ts[i] for i in range(len(ws) - n + 1) if ws[i:i + n] == q] if n else []


def hms(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}"


def sec_of(t: str) -> int:
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def check() -> int:
    import zg_spec as Z
    bad = n = 0
    for s in Z.STRATEGIES:
        for r in s["rules"]:
            if r["tag"] == "A" or not r.get("quote"):
                continue
            n += 1
            v, t = r["times"][0]
            at = locate(v, r["quote"])
            if not at:
                bad += 1
                print(f"MISSING {s['id']} {v}: {r['quote'][:90]!r}")
            elif min(abs(x - sec_of(t)) for x in at) > 2:
                bad += 1
                print(f"TIME    {s['id']} {v}: listed {t}, spoken at {', '.join(hms(x) for x in at[:4])}: {r['quote'][:70]!r}")
    print(f"{n} quotes checked, {bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "find":
        hits = locate(sys.argv[2], sys.argv[3])
        print(", ".join(hms(x) for x in hits) or "not found")
    else:
        sys.exit(check())
