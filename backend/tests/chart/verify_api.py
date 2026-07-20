"""End-to-end exercise of the Chart module's HTTP surface.

Runs the real FastAPI app through Starlette's TestClient with Mongo, Redis and
the Dhan client replaced by in-memory fakes. This proves routing, request
parsing, service wiring and response shapes — the parts unit tests of pure
functions cannot reach. It does NOT prove behaviour against real Dhan data.
"""

import asyncio
import os
import sys

os.environ.setdefault("BROKER_ENCRYPTION_KEY", "")
if not os.environ["BROKER_ENCRYPTION_KEY"]:
    from cryptography.fernet import Fernet
    os.environ["BROKER_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

sys.path.insert(0, r"d:\INDIAN MARKET\backend")

# ---------------------------------------------------------------- fake mongo
class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match(self, doc, query):
        for k, v in query.items():
            if k == "$or":
                if not any(self._match(doc, sub) for sub in v):
                    return False
                continue
            cur, parts = doc, k.split(".")
            for p in parts:
                cur = (cur or {}).get(p) if isinstance(cur, dict) else None
            if isinstance(v, dict):
                if "$in" in v and cur not in v["$in"]:
                    return False
                if "$gte" in v and (cur is None or cur < v["$gte"]):
                    return False
                if "$lte" in v and (cur is None or cur > v["$lte"]):
                    return False
                if "$regex" in v:
                    import re
                    if cur is None or not re.search(v["$regex"], str(cur), re.I):
                        return False
            elif cur != v:
                return False
        return True

    async def find_one(self, query, *_a, **_k):
        for d in self.docs:
            if self._match(d, query):
                return d
        return None

    def find(self, query=None, *_a, **_k):
        return FakeCursor([d for d in self.docs if self._match(d, query or {})])

    def aggregate(self, pipeline):
        docs = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if self._match(d, stage["$match"])]
            elif "$limit" in stage:
                docs = docs[: stage["$limit"]]
        return FakeCursor(docs)

    async def insert_one(self, doc):
        # Real Mongo always stamps an _id; code downstream relies on it.
        doc.setdefault("_id", f"oid{len(self.docs)}_{id(doc)}")
        self.docs.append(doc)
        class R: inserted_id = doc["_id"]
        return R()

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                class R: upserted_count, modified_count, matched_count = 0, 1, 1
                return R()
        if upsert:
            merged = {**update.get("$set", {}), **update.get("$setOnInsert", {})}
            self.docs.append(merged)
        class R: upserted_count, modified_count, matched_count = (1 if upsert else 0), 0, 0
        return R()

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if self._match(d, query):
                del self.docs[i]
                class R: deleted_count = 1
                return R()
        class R: deleted_count = 0
        return R()

    async def create_index(self, *_a, **_k):
        return "idx"

    async def bulk_write(self, ops, **_k):
        class R: upserted_count, modified_count = len(ops), 0
        return R()

    async def distinct(self, *_a, **_k):
        return []


NIFTY = {
    "_id": "i1", "symbol": "NIFTY", "name": "Nifty 50 Index", "security_id": "13",
    "exchange_segment": "IDX_I", "asset_class": "INDEX", "tick_size": 0.05,
}
NIFTY_CE = {
    "_id": "i2", "symbol": "NIFTY24AUG24500CE", "name": "NIFTY 24500 CE", "security_id": "45001",
    "exchange_segment": "NSE_FNO", "asset_class": "INDEX_OPTION", "tick_size": 0.05,
    "expiry": "2026-08-28", "strike": 24500, "option_type": "CE",
    "underlying_symbol": "NIFTY", "lot_size": 50,
}
CRUDE = {
    "_id": "i3", "symbol": "CRUDEOIL", "name": "Crude Oil Aug Fut", "security_id": "77001",
    "exchange_segment": "MCX_COMM", "asset_class": "COMMODITY_FUTURE", "tick_size": 1.0,
    "expiry": "2026-08-19", "underlying_symbol": "CRUDEOIL", "lot_size": 100,
}

import app.core.db as db_mod

db_mod.instruments_collection = FakeCollection([NIFTY, NIFTY_CE, CRUDE])
db_mod.users_collection = FakeCollection([{"_id": "u1", "email": "local@tradingai.dev", "is_active": True}])
db_mod.manual_positions_collection = FakeCollection([{
    "position_id": "p1", "symbol": "NIFTY", "display_name": "Nifty 50", "side": "BUY", "quantity": 50,
    "avg_price": 24100.5, "ltp": 24250.0, "unrealized_pnl": 7475.0, "product_type": "INTRADAY",
    "status": "OPEN", "opened_at": None,
    "instrument": {"security_id": "13", "exchange_segment": "IDX_I"},
}])
db_mod.fno_positions_collection = FakeCollection([])
db_mod.trading_calls_collection = FakeCollection([{
    "call_id": "c1", "symbol": "NIFTY", "display_name": "Nifty 50", "segment": "INDEX", "side": "BUY",
    "horizon": "SWING", "entry_price": 24000.0, "target": 24800.0, "stoploss": 23700.0,
    "confidence": 0.72, "rationale": "test", "status": "OPEN", "created_at": None,
    "instrument": {"security_id": "13", "exchange_segment": "IDX_I"},
}])
db_mod.chart_drawings_collection = FakeCollection([])
db_mod.chart_layouts_collection = FakeCollection([])
db_mod.chart_alerts_collection = FakeCollection([])
db_mod.chart_bars_collection = FakeCollection([])
db_mod.live_watchlist_collection = FakeCollection([])

# Service modules bind these names at import time.
import app.services.chart_cache as cache_mod
import app.services.chart_overlays as ov_mod
import app.services.chart_workspace as ws_mod
import app.services.chart_data as cd_mod

for mod in (cache_mod, ov_mod, ws_mod, cd_mod):
    for name in ("instruments_collection", "manual_positions_collection", "fno_positions_collection",
                 "trading_calls_collection", "chart_drawings_collection", "chart_layouts_collection",
                 "chart_alerts_collection", "chart_bars_collection", "live_watchlist_collection"):
        if hasattr(mod, name):
            setattr(mod, name, getattr(db_mod, name))
ov_mod.backtests_collection = FakeCollection([])

# Redis cache: force a miss, record writes.
CACHE_WRITES = []


async def _no_cache(_key):
    return None


async def _record(key, payload, ttl):
    CACHE_WRITES.append((key, ttl))

cache_mod.get_cached = _no_cache
cache_mod.set_cached = _record

# ---------------------------------------------------------------- fake dhan
DHAN_CALLS = []


class FakeDhan:
    async def historical_daily(self, security_id, segment, itype, frm, to):
        DHAN_CALLS.append(("daily", security_id, itype))
        base = 1_700_000_000
        return {
            "timestamp": [base + i * 86400 for i in range(60)],
            "open": [100 + i for i in range(60)],
            "high": [102 + i for i in range(60)],
            "low": [99 + i for i in range(60)],
            "close": [101 + i for i in range(60)],
            "volume": [1000 + i for i in range(60)],
        }

    async def historical_intraday(self, security_id, segment, itype, interval, frm, to):
        DHAN_CALLS.append(("intraday", security_id, itype))
        base = 1_700_000_000
        return {
            "timestamp": [base + i * 300 for i in range(40)],
            "open": [100 + i * 0.5 for i in range(40)],
            "high": [101 + i * 0.5 for i in range(40)],
            "low": [99 + i * 0.5 for i in range(40)],
            "close": [100.5 + i * 0.5 for i in range(40)],
            "volume": [500 + i for i in range(40)],
        }


import app.api.routes.chart_data as routes_mod

async def _fake_dhan(_user):
    return FakeDhan()

routes_mod._dhan = _fake_dhan

from fastapi.testclient import TestClient
from app.main import app

# Startup hooks touch the real Mongo/Dhan; skip them.
app.router.on_startup.clear()

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' — ' + str(detail)[:220]) if detail else ''}")


with TestClient(app) as client:
    # --- search: options + commodities are now chartable (Phase 4) ----------
    r = client.get("/api/chart/search", params={"q": "NIFTY"})
    check("search 200", r.status_code == 200, r.text)
    syms = {d["symbol"] for d in r.json()["results"]}
    check("search returns the index", "NIFTY" in syms, syms)
    check("search returns the option contract", "NIFTY24AUG24500CE" in syms, syms)
    opt = next(d for d in r.json()["results"] if d["symbol"] == "NIFTY24AUG24500CE")
    check("option carries strike", opt.get("strike") == 24500, opt)
    check("option carries expiry", opt.get("expiry") == "2026-08-28", opt)
    check("option carries option_type", opt.get("option_type") == "CE", opt)

    r = client.get("/api/chart/search", params={"q": "CRUDE"})
    check("MCX contract is searchable", "CRUDEOIL" in {d["symbol"] for d in r.json()["results"]}, r.text)

    # --- symbol: session hours differ by asset class (Phase 4) -------------
    r = client.get("/api/chart/symbol", params={"security_id": "13", "exchange_segment": "IDX_I"})
    check("symbol 200", r.status_code == 200, r.text)
    check("equity/index session is 0915-1530", r.json()["session"] == "0915-1530", r.json())

    r = client.get("/api/chart/symbol", params={"security_id": "77001", "exchange_segment": "MCX_COMM"})
    check("MCX session runs late", r.json()["session"] == "0900-2330", r.json())
    check("MCX flagged as commodity", r.json()["is_commodity"] is True, r.json())

    r = client.get("/api/chart/symbol", params={"security_id": "45001", "exchange_segment": "NSE_FNO"})
    body = r.json()
    check("option flagged as option", body["is_option"] is True, body)
    check("option exposes lot size", body["lot_size"] == 50, body)
    check("option exposes underlying", body["underlying_symbol"] == "NIFTY", body)

    r = client.get("/api/chart/symbol", params={"security_id": "999", "exchange_segment": "NSE_EQ"})
    check("unknown instrument 404s", r.status_code == 404, r.status_code)

    # --- history + caching (Phase 3) ---------------------------------------
    DHAN_CALLS.clear()
    CACHE_WRITES.clear()
    r = client.get("/api/chart/history", params={
        "security_id": "13", "exchange_segment": "IDX_I", "resolution": "D",
        "from": 1_700_000_000, "to": 1_705_000_000,
    })
    check("history 200", r.status_code == 200, r.text)
    h = r.json()
    check("history status ok", h["s"] == "ok", h.get("s"))
    check("history columns are equal length",
          len({len(h[k]) for k in ("t", "o", "h", "l", "c", "v")}) == 1,
          {k: len(h[k]) for k in ("t", "o", "h", "l", "c", "v")})
    check("history hit Dhan once", len(DHAN_CALLS) == 1, DHAN_CALLS)
    check("history result was cached", len(CACHE_WRITES) == 1, CACHE_WRITES)
    check("completed-history TTL is long", CACHE_WRITES[0][1] >= 86400, CACHE_WRITES)

    # An option chart must reach Dhan with instrument=OPTIDX (Phase 4).
    DHAN_CALLS.clear()
    r = client.get("/api/chart/history", params={
        "security_id": "45001", "exchange_segment": "NSE_FNO", "resolution": "5",
        "from": 1_700_000_000, "to": 1_700_400_000,
    })
    check("option history 200", r.status_code == 200, r.text)
    check("option history used OPTIDX", any(c[2] == "OPTIDX" for c in DHAN_CALLS), DHAN_CALLS)

    DHAN_CALLS.clear()
    r = client.get("/api/chart/history", params={
        "security_id": "77001", "exchange_segment": "MCX_COMM", "resolution": "D",
        "from": 1_700_000_000, "to": 1_705_000_000,
    })
    check("MCX history used FUTCOM", any(c[2] == "FUTCOM" for c in DHAN_CALLS), DHAN_CALLS)

    r = client.get("/api/chart/history", params={
        "security_id": "13", "exchange_segment": "IDX_I", "resolution": "3h",
        "from": 1, "to": 2,
    })
    check("bad resolution 422s", r.status_code == 422, r.status_code)

    # --- structure (Phase 6) -----------------------------------------------
    r = client.get("/api/chart/structure", params={
        "security_id": "13", "exchange_segment": "IDX_I", "resolution": "D", "lookback": 60,
    })
    check("structure 200", r.status_code == 200, r.text)
    s = r.json()
    check("structure available", s.get("available") is True, s)
    check("structure reports a bias", "bias" in (s.get("structure") or {}), s.get("structure"))
    check("structure reports zone lists",
          isinstance(s.get("support_zones"), list) and isinstance(s.get("resistance_zones"), list), s)
    # The fake feed is a strictly monotonic ramp, which has no interior fractal
    # pivots at all. The honest answer is "no swing structure", not a
    # confidently-invented trend — assert it refuses rather than fabricates.
    check("a trendless ramp reports no swing structure instead of inventing one",
          s["structure"]["bias"] == "unclear", s["structure"])
    check("a ramp yields no fabricated zones",
          s["support_zones"] == [] and s["resistance_zones"] == [],
          (s["support_zones"], s["resistance_zones"]))

    # --- trendline still works (no regression) ------------------------------
    r = client.get("/api/chart/trendline", params={
        "security_id": "13", "exchange_segment": "IDX_I", "resolution": "D",
    })
    check("legacy trendline still 200", r.status_code == 200, r.text)
    check("legacy trendline shape unchanged", "trend" in r.json(), r.json())

    # --- overlays (Phase 5) -------------------------------------------------
    r = client.get("/api/chart/overlays", params={"security_id": "13", "exchange_segment": "IDX_I"})
    check("overlays 200", r.status_code == 200, r.text)
    ov = r.json()
    check("open position surfaced", len(ov["positions"]) == 1, ov["positions"])
    check("position entry price is the avg fill", ov["positions"][0]["entry_price"] == 24100.5, ov["positions"][0])
    check("active call surfaced", len(ov["calls"]) == 1, ov["calls"])
    call = ov["calls"][0]
    check("call carries entry/target/SL",
          (call["entry_price"], call["target"], call["stoploss"]) == (24000.0, 24800.0, 23700.0), call)

    # A different instrument must not inherit the index's position/call.
    r = client.get("/api/chart/overlays", params={"security_id": "45001", "exchange_segment": "NSE_FNO"})
    check("overlays are instrument-scoped", r.json()["positions"] == [] and r.json()["calls"] == [], r.json())

    # --- streaming guard ----------------------------------------------------
    r = client.get("/api/chart/stream", params={
        "security_id": "13", "exchange_segment": "IDX_I", "resolution": "W",
    })
    check("weekly stream is refused with 422", r.status_code == 422, r.status_code)

    # --- workspace: drawings (Phase 7) --------------------------------------
    r = client.post("/api/chart/drawings",
                    params={"security_id": "13", "exchange_segment": "IDX_I"},
                    json={"kind": "trendline",
                          "points": [{"time": 1700000000, "price": 100}, {"time": 1700086400, "price": 120}]})
    check("create drawing 200", r.status_code == 200, r.text)
    did = r.json()["drawing_id"]
    check("drawing echoes its kind", r.json()["kind"] == "trendline", r.json())

    r = client.get("/api/chart/drawings", params={"security_id": "13", "exchange_segment": "IDX_I"})
    check("drawing persisted", len(r.json()["drawings"]) == 1, r.json())

    r = client.get("/api/chart/drawings", params={"security_id": "45001", "exchange_segment": "NSE_FNO"})
    check("drawings are per-instrument", r.json()["drawings"] == [], r.json())

    r = client.post("/api/chart/drawings",
                    params={"security_id": "13", "exchange_segment": "IDX_I"},
                    json={"kind": "spaceship", "points": [{"time": 1, "price": 2}]})
    check("unknown drawing kind 422s", r.status_code == 422, r.status_code)

    r = client.post("/api/chart/drawings",
                    params={"security_id": "13", "exchange_segment": "IDX_I"},
                    json={"kind": "trendline", "points": []})
    check("empty points 422s", r.status_code == 422, r.status_code)

    check("delete drawing 200", client.delete(f"/api/chart/drawings/{did}").status_code == 200)
    check("deleting a missing drawing 404s", client.delete("/api/chart/drawings/nope").status_code == 404)

    # --- workspace: layouts -------------------------------------------------
    r = client.post("/api/chart/layouts", json={
        "name": "My setup", "resolution": "15",
        "indicators": {"ema": {"on": True, "periods": [20]}}, "overlays": {"positions": True},
    })
    check("create layout 200", r.status_code == 200, r.text)
    lid = r.json()["layout_id"]

    r = client.post("/api/chart/layouts", json={
        "name": "My setup", "resolution": "60", "indicators": {}, "overlays": {},
    })
    check("re-saving a layout name reuses its id (no duplicate)", r.json()["layout_id"] == lid, r.json())

    r = client.get("/api/chart/layouts")
    check("only one layout stored", len(r.json()["layouts"]) == 1, r.json())

    check("nameless layout 422s", client.post("/api/chart/layouts", json={"name": "  "}).status_code == 422)
    check("delete layout 200", client.delete(f"/api/chart/layouts/{lid}").status_code == 200)

    # --- workspace: alerts --------------------------------------------------
    r = client.post("/api/chart/alerts", json={
        "security_id": "13", "exchange_segment": "IDX_I", "symbol": "NIFTY",
        "condition": "crosses_above", "price": 24500, "note": "breakout",
    })
    check("create alert 200", r.status_code == 200, r.text)
    aid = r.json()["alert_id"]
    check("alert starts ACTIVE", r.json()["status"] == "ACTIVE", r.json())
    check("alert delivery is labelled in_app", r.json()["delivery"] == "in_app", r.json())

    check("bad condition 422s", client.post("/api/chart/alerts", json={
        "security_id": "13", "exchange_segment": "IDX_I", "condition": "vibes", "price": 1,
    }).status_code == 422)
    check("non-numeric price 422s", client.post("/api/chart/alerts", json={
        "security_id": "13", "exchange_segment": "IDX_I", "condition": "crosses_above", "price": "high",
    }).status_code == 422)

    # No previous price -> cannot establish a cross -> must not fire.
    r = client.post("/api/chart/alerts/evaluate", json={
        "security_id": "13", "exchange_segment": "IDX_I", "last_price": 24600, "previous_price": None,
    })
    check("no previous price fires nothing", r.json()["triggered"] == [], r.json())

    # Price moving through the level from below -> fires.
    r = client.post("/api/chart/alerts/evaluate", json={
        "security_id": "13", "exchange_segment": "IDX_I", "last_price": 24600, "previous_price": 24400,
    })
    check("upward cross fires the alert", len(r.json()["triggered"]) == 1, r.json())
    check("fired alert records its trigger price",
          r.json()["triggered"][0]["triggered_price"] == 24600, r.json()["triggered"][0])

    # Already triggered -> must not re-fire.
    r = client.post("/api/chart/alerts/evaluate", json={
        "security_id": "13", "exchange_segment": "IDX_I", "last_price": 24700, "previous_price": 24650,
    })
    check("a triggered alert does not re-fire", r.json()["triggered"] == [], r.json())

    # A move that never reaches the level must not fire.
    client.post("/api/chart/alerts", json={
        "security_id": "13", "exchange_segment": "IDX_I", "condition": "crosses_above", "price": 30000,
    })
    r = client.post("/api/chart/alerts/evaluate", json={
        "security_id": "13", "exchange_segment": "IDX_I", "last_price": 24700, "previous_price": 24600,
    })
    check("a move short of the level does not fire", r.json()["triggered"] == [], r.json())

    # crosses_below
    client.post("/api/chart/alerts", json={
        "security_id": "13", "exchange_segment": "IDX_I", "condition": "crosses_below", "price": 24000,
    })
    r = client.post("/api/chart/alerts/evaluate", json={
        "security_id": "13", "exchange_segment": "IDX_I", "last_price": 23900, "previous_price": 24100,
    })
    check("downward cross fires crosses_below", len(r.json()["triggered"]) == 1, r.json())

    # An upward move must not fire a crosses_below alert.
    client.post("/api/chart/alerts", json={
        "security_id": "13", "exchange_segment": "IDX_I", "condition": "crosses_below", "price": 25000,
    })
    r = client.post("/api/chart/alerts/evaluate", json={
        "security_id": "13", "exchange_segment": "IDX_I", "last_price": 25500, "previous_price": 24900,
    })
    check("upward move does not fire crosses_below", r.json()["triggered"] == [], r.json())

    check("evaluate without last_price 422s", client.post("/api/chart/alerts/evaluate", json={
        "security_id": "13", "exchange_segment": "IDX_I",
    }).status_code == 422)
    check("delete alert 200", client.delete(f"/api/chart/alerts/{aid}").status_code == 200)

    # --- AI explain degrades honestly with no API key -----------------------
    r = client.post("/api/chart/explain", json={"instrument": {"symbol": "NIFTY"}, "window": {"bars": 10}})
    check("explain 200 even unconfigured", r.status_code == 200, r.text)
    check("explain reports not_configured rather than inventing a read",
          r.json().get("status") == "not_configured", r.json())

print()
print("ALL API CHECKS PASSED" if failures == 0 else f"{failures} API CHECK(S) FAILED")
raise SystemExit(0 if failures == 0 else 1)
