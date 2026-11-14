"""QuantConnect forum evidence: reads saved discussion pages (fetched politely from the public forum; robots.txt allows
/forum and disallows /api, which this never touches) and writes, per discussion, the opening post and every reply with
author, date, text, the attached algorithm files (name, SHA-256, content) and backtest links. No code is executed.

    python -I ws_qc_extract.py <pages dir> <out json>

The discussion JSON is embedded in the page itself (<script type="application/json" id=...>).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def text_of(h: str | None) -> str:
    if not h:
        return ""
    t = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", h, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def blocks(raw: str) -> dict:
    out = {}
    for m in re.finditer(r'<script type="application/json" id="([^"]+)">(.*?)</script>', raw, flags=re.S):
        try:
            out[m.group(1)] = json.loads(m.group(2))
        except json.JSONDecodeError:
            out[m.group(1)] = None
    return out


def post(o: dict) -> dict:
    files = []
    for f in o.get("files") or []:
        c = f.get("content") or ""
        files.append({"name": f.get("name"), "sha256": hashlib.sha256(c.encode()).hexdigest(), "lines": c.count("\n") + 1,
                      "content": c})
    return {"id": o.get("id"), "author": o.get("sUserName") or o.get("name") or o.get("uid"), "published": o.get("published"),
            "text": text_of(o.get("content") or o.get("content_old") or o.get("message") or o.get("description")),
            "files": files, "backtestUrl": o.get("backtestUrl"), "votes": o.get("votes")}


def main(pages: Path, out: Path) -> None:
    res = {}
    for p in sorted(pages.glob("*.html")):
        raw_b = p.read_bytes()
        raw = raw_b.decode("utf-8", errors="replace")
        b = blocks(raw)
        title = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.S | re.I)
        disc = None
        for k, v in b.items():
            if isinstance(v, dict) and k != "jsonCommentsResult" and ("title" in v or "discussion" in v):
                disc = v.get("discussion", v)
                break
        comments = (b.get("jsonCommentsResult") or {}).get("comments") or []
        flat = []
        for c in comments:
            flat.append(post(c))
            for r in c.get("replies") or []:
                flat.append(post(r))
        res[p.stem] = {"title": html.unescape(title.group(1)).replace(" - QuantConnect.com", "").strip() if title else None,
                       "page_sha256": hashlib.sha256(raw_b).hexdigest(), "json_blocks": sorted(b),
                       "opening": post(disc) if isinstance(disc, dict) else None, "comments": flat}
        n_files = sum(len(x["files"]) for x in flat) + (len(res[p.stem]["opening"]["files"]) if res[p.stem]["opening"] else 0)
        print(f"{p.stem}: {res[p.stem]['title'][:70] if res[p.stem]['title'] else '?':70} blocks={len(b)} comments={len(flat)} files={n_files}")
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
