"""Visible text and code blocks of a saved HTML page (evidence reading; no network, no execution of page content).

    python -I ws_pagetext.py <page.html> [--find word] [--code] [--chars N]

Prints the page title, the SHA-256 of the saved bytes (the content-version reference), the visible text (scripts and
styles removed) around the first --find match, and with --code every <pre>/<code> block with its index.
"""

from __future__ import annotations

import hashlib
import html
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")


def visible(raw: str) -> str:
    t = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</tr>", "\n", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def code_blocks(raw: str) -> list[str]:
    out = []
    for m in re.finditer(r"<pre\b[^>]*>(.*?)</pre>|<code\b[^>]*>(.*?)</code>", raw, flags=re.S | re.I):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        body = html.unescape(re.sub(r"<[^>]+>", "", body))
        if len(body.strip()) > 40:
            out.append(body)
    return out


def main(argv: list[str]) -> None:
    path = argv[0]
    raw_bytes = open(path, "rb").read()
    raw = raw_bytes.decode("utf-8", errors="replace")
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.S | re.I)
    print("title:", html.unescape(title.group(1)).strip() if title else None)
    print("sha256:", hashlib.sha256(raw_bytes).hexdigest(), "bytes:", len(raw_bytes))
    chars = int(argv[argv.index("--chars") + 1]) if "--chars" in argv else 3000
    text = visible(raw)
    print("visible chars:", len(text))
    if "--find" in argv:
        w = argv[argv.index("--find") + 1]
        i = text.find(w)
        print(f"--- around '{w}' @ {i}:")
        print(text[max(0, i - 300): i + chars] if i >= 0 else "(not found)")
    elif "--code" not in argv:
        print(text[:chars])
    if "--code" in argv:
        for k, b in enumerate(code_blocks(raw)):
            print(f"=== code block {k} ({len(b)} chars)")
            print(b[:chars])


if __name__ == "__main__":
    main(sys.argv[1:])
