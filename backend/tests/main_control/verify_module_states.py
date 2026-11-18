"""Verify Main Control's three states (ACTIVE / STOPPING / PAUSED), the drain context, the API
gate's exit rule and the timing gauge - offline, against fake collections.

Run:  python backend/tests/main_control/verify_module_states.py

What must hold:
* ON runs the cycle normally, outside the drain context.
* OFF with open positions runs it INSIDE the drain context (entries_blocked() is True there and
  only there) and re-counts afterwards, so the first flat cycle pauses.
* OFF and flat skips the cycle entirely and returns {}.
* A failed open-position probe reads as "may still hold something" -> STOPPING, never PAUSED.
* A module with drains=False pauses at once (the old freeze), and says so.
* Two desks interleaving on one event loop never see each other's drain flag.
* While OFF the API still serves reads AND exits (close/flatten/kill...), refuses other work,
  and `reset-halt` is NOT an exit.
"""

import asyncio
import os
import sys
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200"   # never the real cluster
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "shared"))
sys.path.insert(0, str(ROOT))

from app.services import desk_switches as sw  # noqa: E402
from app.services import module_registry as reg  # noqa: E402
from app.services.module_registry import REGISTRY, is_exit, is_work, pages_for, resolve  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


class FakeColl:
    def __init__(self, open_n=0, fail=False):
        self.open_n, self.fail, self.calls = open_n, fail, 0

    async def count_documents(self, flt, **kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError("probe down")
        assert flt == {"status": "OPEN"}, flt
        return self.open_n


class FakeSwitches:
    def __init__(self):
        self.docs = {}

    def find(self, flt):
        docs = list(self.docs.values())

        async def gen():
            for d in docs:
                yield d
        return gen()

    async def update_one(self, flt, upd, upsert=False):
        self.docs[flt["_id"]] = dict(upd["$set"])


class FakeDB(dict):
    def __getitem__(self, k):
        return self.setdefault(k, FakeColl())


async def main():
    fake_db = FakeDB()
    sw.db = fake_db
    sw.desk_switches_collection = FakeSwitches()
    sw._invalidate()

    # ── registry sanity ──────────────────────────────────────────────────────────
    for key, m in REGISTRY.items():
        if m.drains and key not in ("commodity_auto", "index_auto", "intraday_focus"):
            check(bool(m.positions), f"{key}: drains=True has an open-position probe")
    gated_keys = ["intraday_lab", "live_intraday", "live_trading", "stock_desk", "stock_books",
                  "selling_books", "zero_hero", "live_paper", "morning_momentum", "swing_trading",
                  "pattern", "pattern_books", "nifty_scalp", "momentum_engine", "banknifty_desk",
                  "ath_trading", "trending_stocks", "paper_broker", "prelive"]
    for k in gated_keys:
        check(REGISTRY[k].drains, f"{k} drains on OFF")
    for k in ("screener", "strategy_factory", "long_horizon"):
        check(not REGISTRY[k].drains, f"{k} keeps pause-at-once (documented)")
    check(set(pages_for("/intraday-stocks")) >= {"intraday_lab", "live_intraday", "pattern", "pattern_books"},
          "pages_for(/intraday-stocks) finds the four intraday modules")
    check("intraday_focus" in pages_for("/intraday-stocks/focus-five"), "sub-page finds Focus Five")
    check(pages_for("/live-trading") == ["live_trading"], "/live-trading is only Live Trading")
    check("live_paper" not in pages_for("/live-trading"), "/live does not claim /live-trading")

    # ── API rule ─────────────────────────────────────────────────────────────────
    check(is_exit("POST", "/api/fno-positions/positions/abc123/exit"), "position exit is an exit")
    check(is_exit("POST", "/api/live-trading/panic-close-all"), "panic-close-all is an exit")
    check(is_exit("POST", "/api/gold-desk/close-all"), "close-all is an exit")
    check(is_exit("POST", "/api/premium-paper/live/flatten"), "flatten is an exit")
    check(not is_exit("POST", "/api/index-intraday/risk/reset-halt"), "reset-halt is NOT an exit")
    check(not is_exit("GET", "/api/gold-desk/close-all"), "a GET is never an exit")
    check(not is_exit("POST", "/api/intraday-lab/run"), "run is not an exit")
    check(is_work("POST", "/api/intraday-lab/run"), "run is work")
    check(not is_work("GET", "/api/intraday-lab/runs"), "runs is a read")

    # ── states and gated() ──────────────────────────────────────────────────────
    seen = []

    async def cycle(tag):
        seen.append((tag, sw.entries_blocked(), sw.draining_module()))
        await asyncio.sleep(0)
        return {"opened": 0 if sw.entries_blocked() else 1, "managed": 1}

    key = "swing_trading"
    fake_db["swing_positions"].open_n = 2
    fake_db["swing_signal_positions"].open_n = 0
    check(await sw.state(key) == sw.ACTIVE, "default (no record) is ACTIVE")
    r = await sw.gated(key, cycle, "on")
    check(r == {"opened": 1, "managed": 1} and seen[-1] == ("on", False, None), "ON runs normally, no drain flag")

    await sw.set_module(key, False)
    check(await sw.state(key) == sw.STOPPING, "OFF + 2 open = STOPPING")
    r = await sw.gated(key, cycle, "drain")
    check(seen[-1] == ("drain", True, key) and r["opened"] == 0, "STOPPING runs inside the drain context")
    check(not sw.entries_blocked(), "drain flag is reset after the cycle")

    fake_db["swing_positions"].open_n = 0
    n_before = len(seen)
    check(await sw.state(key) == sw.PAUSED, "flat after the drain cycle = PAUSED on the very next look (cache dropped)")
    r = await sw.gated(key, cycle, "paused")
    check(r == {} and len(seen) == n_before, "PAUSED skips the cycle and returns {}")

    await sw.set_module(key, True)
    r = await sw.gated(key, cycle, "back-on")
    check(r["opened"] == 1 and seen[-1] == ("back-on", False, None), "ON again resumes normally")

    # probe failure -> STOPPING
    await sw.set_module("pattern", False)
    fake_db["pattern_positions"].fail = True
    check(await sw.open_positions("pattern", fresh=True) is None, "failed probe reports None")
    check(await sw.state("pattern") == sw.STOPPING, "failed probe reads as STOPPING, never PAUSED")
    fake_db["pattern_positions"].fail = False

    # drains=False -> PAUSED even with positions, and gated() does not run it
    await sw.set_module("screener", False)
    fake_db["screener_paper_positions"].open_n = 5
    check(await sw.state("screener") == sw.PAUSED, "drains=False pauses at once even with open positions")
    r = await sw.gated("screener", cycle, "frozen")
    check(r == {} and seen[-1][0] != "frozen", "drains=False is not run while OFF")

    # cached probe: one count per OPEN_TTL
    await sw.set_module("momentum_engine", False)
    c = fake_db["momentum_positions"]
    c.open_n = 1
    await sw.state("momentum_engine"); await sw.state("momentum_engine"); await sw.state("momentum_engine")
    check(c.calls == 1, f"open-position probe is cached (calls={c.calls})")

    # interleaving: an ON desk running concurrently with a draining one never sees the flag
    await sw.set_module("nifty_scalp", False)
    fake_db["nifty_scalp_positions"].open_n = 1
    flags = {}

    async def slow(tag):
        for _ in range(5):
            flags.setdefault(tag, set()).add(sw.entries_blocked())
            await asyncio.sleep(0)
        return {"ok": 1}

    await asyncio.gather(sw.gated("nifty_scalp", slow, "draining"), sw.gated("zero_hero", slow, "active"))
    check(flags["draining"] == {True} and flags["active"] == {False},
          f"interleaved desks keep their own drain flag ({flags})")

    # Crypto keeps its book in its own store ("pkg:ATTR" probe). OFF and flat must skip the whole
    # tick (should_run False); OFF with something open must keep ticking to manage it.
    import types as _types
    fake_store = _types.ModuleType("app.services.crypto_trading.store")
    fake_store.POSITIONS = FakeColl(0)
    sys.modules.setdefault("app.services.crypto_trading", _types.ModuleType("app.services.crypto_trading"))
    sys.modules["app.services.crypto_trading.store"] = fake_store
    await sw.set_module("crypto_trading", False)
    check(not await sw.should_run("crypto_trading"), "Crypto OFF and flat: should_run is False, the tick is skipped")
    fake_store.POSITIONS.open_n = 2
    sw._open_cache.pop("crypto_trading", None)
    check(await sw.should_run("crypto_trading"), "Crypto OFF with 2 open: still ticks to manage them")
    await sw.set_module("crypto_trading", True)
    check(await sw.should_run("crypto_trading"), "Crypto ON: ticks")

    # snapshot / status shapes
    snap = await sw.snapshot()
    row = next(r for r in snap["modules"] if r["module"] == "nifty_scalp")
    check(row["state"] == "stopping" and row["open_positions"] == 1 and row["drains"],
          "snapshot row carries state/open/drains")
    check(snap["semantics"] == "drain" and snap["stopping"] >= 1, "snapshot summary counts stopping")
    st = await sw.status()
    check(st["modules"]["nifty_scalp"]["state"] == "stopping" and st["modules"]["live_trading"]["real_money"],
          "status() carries state + real_money flag")
    check(all(r["off_behaviour"] for r in snap["modules"]), "every module explains what OFF does")

    # ── the gate end to end ─────────────────────────────────────────────────────
    from app.services.module_gate import ModuleGateMiddleware
    from app.core import perf

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b"{}"})

    gate = ModuleGateMiddleware(app)

    async def call(method, path):
        out = {}

        async def send(m):
            if m["type"] == "http.response.start":
                out["status"] = m["status"]
                out["headers"] = dict(m.get("headers") or [])

        async def receive():
            return {"type": "http.request", "body": b""}

        await gate({"type": "http", "method": method, "path": path, "headers": []}, receive, send)
        return out

    await sw.set_module("fno_positions", False)
    check((await call("POST", "/api/fno-positions/positions/a1b2c3d4e5f6/exit"))["status"] == 200,
          "OFF module: exit still served")
    check((await call("POST", "/api/fno-positions/positions")) ["status"] == 423, "OFF module: new order refused (423)")
    check((await call("GET", "/api/fno-positions/positions"))["status"] == 200, "OFF module: plain read served")
    check((await call("POST", "/api/main-control/toggle"))["status"] == 200, "main-control never gated")
    ps = perf.summary()
    names = [e["endpoint"] for e in ps["endpoints"]]
    check("POST /api/fno-positions/positions/:id/exit" in names, f"perf normalises ids ({names[:4]})")
    check("event_loop_lag" in ps, "perf reports event-loop lag")

    print()
    print("ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return len(FAILS)


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
