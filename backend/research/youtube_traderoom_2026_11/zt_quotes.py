"""Checks every citation of zt_spec.py against the Trading Video Lab's saved transcripts: each cited time must be the
start of a caption line in that video, and each rule's quote must begin on the first cited caption (it may run on into
the next two lines). Reads the transcripts as data only.

    python -I zt_quotes.py
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding="utf-8")

import zt_spec as S  # noqa: E402

LAB = HERE.parents[2] / "youtube-video-explainer-reviewed" / "evidence"
_LINES: dict = {}


def lines(vid: str) -> list[tuple[str, str]]:
    if vid not in _LINES:
        folders = sorted(LAB.glob(f"{vid}-*"), key=lambda p: p.name)
        if not folders:
            raise SystemExit(f"no evidence for {vid}")
        f = folders[-1] / "transcript.roman.txt"
        out = []
        for ln in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\[(\d\d:\d\d:\d\d)\]\s*(.*)$", ln)
            if m:
                out.append((m.group(1), m.group(2)))
        _LINES[vid] = out
    return _LINES[vid]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s.lower().replace("...", " ")).strip()


def check_time(vid: str, t: str) -> int | None:
    for i, (tt, _) in enumerate(lines(vid)):
        if tt == t:
            return i
    return None


def main() -> int:
    bad, n = [], 0
    items = []
    for s in S.CODED:
        for k, rule in enumerate(s["rules"]):
            items.append((f"{s['id']} rule {k + 1}", rule["cites"], rule["quote"]))
        for v in s["vague"]:
            items.append((f"{s['id']} vague '{v['term']}'", [v["at"]], ""))
        for c in s["claims"] + s["examples"]:
            items.append((f"{s['id']} claim/example", [c["at"]], ""))
    for s in S.NOT_CODED:
        items.append((s["id"], s["cites"], ""))
    for label, cites, quote in items:
        for j, (vid, t) in enumerate(cites):
            n += 1
            i = check_time(vid, t)
            if i is None:
                bad.append(f"{label}: {vid} {t} is not the start of a caption line")
                continue
            if j == 0 and quote:
                L = lines(vid)
                text = norm(" ".join(x for _, x in L[i:i + 3]))
                head = norm(quote.split("...")[0])
                if head not in text:
                    bad.append(f"{label}: quote not at {vid} {t}: '{quote[:60]}' / caption '{L[i][1][:80]}'")
    print("citations", n, "problems", len(bad))
    for b in bad:
        print("  ", b)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
