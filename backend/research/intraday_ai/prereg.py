"""Pre-registration: write a test's hypothesis, metric, sample and decision rule BEFORE running it.

Each registration is a JSON file in prereg/ with a fingerprint of its content. It is committed
to git before the test runs — the commit is the timestamp — and it can never be changed:
`register` refuses to overwrite a different registration under the same name. Results are
judged against the stored rule, by `load` (which re-checks the fingerprint).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone

DIR = pathlib.Path(__file__).with_name("prereg")


def fingerprint(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def register(name: str, doc: dict) -> str:
    DIR.mkdir(exist_ok=True)
    p = DIR / f"{name}.json"
    fp = fingerprint(doc)
    if p.exists():
        old = json.loads(p.read_text(encoding="utf-8"))
        if old["fingerprint"] != fp:
            raise SystemExit(f"{name} is already registered with a different rule ({old['fingerprint']}); "
                             f"a pre-registration is never edited — register a new name")
        return fp
    p.write_text(json.dumps({"name": name, "registered_at": datetime.now(timezone.utc).isoformat(),
                             "fingerprint": fp, "doc": doc}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return fp


def load(name: str) -> dict:
    rec = json.loads((DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert fingerprint(rec["doc"]) == rec["fingerprint"], f"{name}: the stored rule was edited"
    return rec["doc"]
