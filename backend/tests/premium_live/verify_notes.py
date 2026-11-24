"""Each strategy's own note on the Delta real-money desks (24 Nov 2026): the routes GET/POST
/api/premium-paper/live/notes/{desk} in app/api/routes/premium_paper.py, against a fake collection.

Run:  python backend/tests/premium_live/verify_notes.py
FastAPI is stubbed when it is not installed (the local env), so the route functions are called as plain async
functions; the box's production image imports the real module before any deploy.
"""

import asyncio
import os
import sys
import types
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200"   # never a real store
BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests" / "gold_desk"))
from _harness import check, finish, section  # noqa: E402

try:
    import fastapi  # noqa: F401
except ImportError:                                   # a stand-in: decorators return the function unchanged
    fa = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code=500, detail=None):
            super().__init__(detail)
            self.status_code, self.detail = status_code, detail

    class APIRouter:
        def __init__(self, *a, **k):
            self.routes, self.prefix = [], k.get("prefix", "")

        def _deco(self, method, path, *a, **k):
            def wrap(fn):
                self.routes.append(types.SimpleNamespace(path=self.prefix + path, methods={method}, endpoint=fn))
                return fn
            return wrap

        def get(self, path, *a, **k):
            return self._deco("GET", path)

        def post(self, path, *a, **k):
            return self._deco("POST", path)

        def on_event(self, *a, **k):
            return lambda fn: fn

    fa.APIRouter, fa.HTTPException = APIRouter, HTTPException
    fa.Body = fa.Depends = fa.Query = lambda *a, **k: None
    fa.Response = object
    sys.modules["fastapi"] = fa
    deps = types.ModuleType("app.api.deps")
    deps.get_current_user = lambda: {}
    sys.modules["app.api.deps"] = deps

from fastapi import HTTPException  # noqa: E402
from app.api.routes import premium_paper as R  # noqa: E402
from app.services import premium_live as M  # noqa: E402


class Notes:
    """The calls the routes make on live_strategy_notes, nothing more."""
    def __init__(self):
        self.docs = {}
        self.calls = []

    def find(self, q, projection=None):
        rows = [dict(d) for d in self.docs.values() if all(d.get(k) == v for k, v in q.items())]

        class Cur:
            async def to_list(self_inner, n):
                return rows[:n]
        return Cur()

    async def update_one(self, q, upd, upsert=False):
        self.calls.append(("update", q, upd, upsert))
        d = self.docs.get(q["_id"])
        if d is None:
            if not upsert:
                return
            d = self.docs[q["_id"]] = {"_id": q["_id"]}
        d.update(upd["$set"])

    async def delete_one(self, q):
        self.calls.append(("delete", q))
        self.docs.pop(q["_id"], None)


class DB:
    def __init__(self):
        self.live_strategy_notes = Notes()

    def __getattr__(self, name):                    # any other collection: the routes must not touch one
        raise AssertionError(f"the notes routes touched {name}")


async def main():
    db = DB()
    R._database = lambda: db
    ck = next(f"{p.acct}|{p.mkt}" for p in M.DESKS["crypto"].picks)
    gk = next(f"{p.acct}|{p.mkt}" for p in M.DESKS["gold"].picks)
    U = {}

    section("1. Reading: a desk's notes, an unknown desk refused")
    r = await R.live_notes("crypto", U)
    check("no note yet: an empty map, the limit, configured", r == {"notes": {}, "max": 1000, "configured": True}, r)
    try:
        await R.live_notes("nope", U)
        check("an unknown desk is a 404", False)
    except HTTPException as e:
        check("an unknown desk is a 404", e.status_code == 404, e.status_code)

    section("2. Writing: set, change, refuse, remove")
    r = await R.live_note_set("crypto", {"key": ck, "text": "  watch the 07:15 range\nskip on CPI days  "}, U)
    g = await R.live_notes("crypto", U)
    check(f"set on {ck}: stored stripped, newlines kept, with its time",
          r["ok"] and r["text"] == "watch the 07:15 range\nskip on CPI days" and g["notes"][ck]["text"] == r["text"]
          and isinstance(g["notes"][ck]["at"], float), (r, g))
    r2 = await R.live_note_set("crypto", {"key": ck, "text": "only longs ₹ ✓"}, U)
    g = await R.live_notes("crypto", U)
    check("changed: one note, the new text (unicode kept)", r2["ok"] and list(g["notes"]) == [ck]
          and g["notes"][ck]["text"] == "only longs ₹ ✓" and len(db.live_strategy_notes.docs) == 1, g)
    n0 = len(db.live_strategy_notes.calls)
    bad = [await R.live_note_set("crypto", {"key": gk, "text": "x"}, U),           # the gold desk's strategy
           await R.live_note_set("crypto", {"key": "XX-99|BTCUSD", "text": "x"}, U),
           await R.live_note_set("crypto", {"key": ck, "text": "x" * 1001}, U),
           await R.live_note_set("crypto", {"key": ck, "text": 123}, U),
           await R.live_note_set("crypto", {"text": "no key"}, U)]
    check("refused, nothing written: another desk's strategy, an unknown one, 1,001 characters, not text, no key",
          all(not x["ok"] for x in bad) and len(db.live_strategy_notes.calls) == n0
          and g["notes"][ck]["text"] == (await R.live_notes("crypto", U))["notes"][ck]["text"], [x.get("why") for x in bad])
    ok1000 = await R.live_note_set("crypto", {"key": ck, "text": "y" * 1000}, U)
    check("exactly 1,000 characters is taken", ok1000["ok"] and len(ok1000["text"]) == 1000, ok1000.get("why"))
    r3 = await R.live_note_set("crypto", {"key": ck, "text": "   "}, U)
    g = await R.live_notes("crypto", U)
    check("blank (spaces only) removes the note", r3["ok"] and r3["text"] == "" and g["notes"] == {}
          and not db.live_strategy_notes.docs, (r3, g))
    r4 = await R.live_note_set("crypto", {"key": ck, "text": ""}, U)
    check("removing a note that is not there is fine", r4["ok"], r4)

    section("3. The desks keep their own notes")
    await R.live_note_set("crypto", {"key": ck, "text": "bitcoin note"}, U)
    await R.live_note_set("gold", {"key": gk, "text": "gold note"}, U)
    c, g = await R.live_notes("crypto", U), await R.live_notes("gold", U)
    check("each desk reads only its own", list(c["notes"]) == [ck] and list(g["notes"]) == [gk]
          and c["notes"][ck]["text"] == "bitcoin note" and g["notes"][gk]["text"] == "gold note", (c, g))
    check("stored apart from the desks' state, _id '<desk>|<acct>|<mkt>'",
          sorted(db.live_strategy_notes.docs) == sorted([f"crypto|{ck}", f"gold|{gk}"]), sorted(db.live_strategy_notes.docs))
    try:
        await R.live_note_set("nope", {"key": ck, "text": "x"}, U)
        check("writing to an unknown desk is a 404", False)
    except HTTPException as e:
        check("writing to an unknown desk is a 404", e.status_code == 404)

    section("4. No database configured on the server")
    R._database = lambda: None
    r = await R.live_notes("crypto", U)
    w = await R.live_note_set("crypto", {"key": ck, "text": "x"}, U)
    check("reading says not configured; writing is refused", r["configured"] is False and r["notes"] == {}
          and not w["ok"] and "not configured" in w["why"], (r, w))
    paths = sorted(p for r_ in R.router.routes for p in [r_.path] if "notes" in p)
    check("the routes are mounted under /api/premium-paper", paths == ["/api/premium-paper/live/notes/{desk}"] * 2, paths)
    finish()


if __name__ == "__main__":
    asyncio.run(main())
