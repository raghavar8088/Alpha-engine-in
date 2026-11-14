"""Print an algorithm file attached to a saved QuantConnect discussion, with line numbers (evidence reading only).

    python -I ws_qc_show.py <extract.json> <discussion id> [<post index: 'o' = opening, 0.. = comments>] [<file name>]

Without a post index it lists every post that carries files. Blank and comment-only lines are skipped (numbers kept).
"""

from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main(a: list[str]) -> None:
    d = json.load(open(a[0], encoding="utf-8"))[a[1]]
    posts = [("o", d["opening"])] + [(str(i), c) for i, c in enumerate(d["comments"])]
    if len(a) < 3:
        for k, p in posts:
            if p and p["files"]:
                print(k, p["author"], p["published"], [(f["name"], f["lines"], f["sha256"][:12]) for f in p["files"]])
        return
    p = dict(posts)[a[2]]
    for f in p["files"]:
        if len(a) > 3 and f["name"] != a[3]:
            continue
        if f["name"].endswith(".ipynb"):
            continue
        print(f"=== {a[1]} post {a[2]} by {p['author']} {p['published']} :: {f['name']} ({f['lines']} lines, sha256 {f['sha256']})")
        for i, line in enumerate(f["content"].splitlines(), start=1):
            s = line.rstrip()
            if s.strip() and not s.strip().startswith(("#", "//")):
                print(f"L{i:<4}{s[:150]}")


if __name__ == "__main__":
    main(sys.argv[1:])
