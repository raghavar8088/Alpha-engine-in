"""Read-only reader for the app's bar files (/data/intraday/<tf>/<SYMBOL>.ibar, written by
backend/app/services/intraday_store.py). Same layout: zlib( b"IBAR1\\n" + json header + "\\n" + column bytes ).

This module only READS. The desk never writes to the shared bar volume (it is mounted read-only in the container)."""
from __future__ import annotations

import json
import os
import zlib
from array import array

MAGIC = b"IBAR1\n"
COLS = (("t", "q"), ("o", "d"), ("h", "d"), ("l", "d"), ("c", "d"), ("v", "q"), ("src", "b"))


def path(root: str, symbol: str, tf: str = "5m") -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_&" else "_" for ch in symbol.upper())
    return os.path.join(root, tf, f"{safe}.ibar")


def read(root: str, symbol: str, tf: str = "5m") -> dict:
    """{'t','o','h','l','c','v','src'} arrays, oldest first; empty arrays when the file is missing."""
    p = path(root, symbol, tf)
    out = {name: array(code) for name, code in COLS}
    if not os.path.exists(p):
        return out
    with open(p, "rb") as f:
        raw = zlib.decompress(f.read())
    if not raw.startswith(MAGIC):
        raise ValueError(f"{p}: not an intraday bar file")
    he = raw.index(b"\n", len(MAGIC))
    head = json.loads(raw[len(MAGIC):he])
    n = int(head["n"])
    pos = he + 1
    for name, code in COLS:
        a = out[name]
        size = n * a.itemsize
        a.frombytes(raw[pos:pos + size])
        pos += size
    return out


def symbols(root: str, tf: str = "5m") -> list[str]:
    d = os.path.join(root, tf)
    if not os.path.isdir(d):
        return []
    return sorted(fn[:-5] for fn in os.listdir(d) if fn.endswith(".ibar"))
