"""Verify the Delta real-money desk (app.services.premium_live) against a simulated Delta Exchange. No network.

Run:  python backend/tests/premium_live/verify_premium_live.py

The exchange is FAKED AT THE HTTP LAYER: FakeDelta overrides only `Delta.request`, so the real client code builds
every order body, formats every price to the tick and parses every answer (numbers sent as strings, as Delta does).
The fake keeps positions, fills, bracket legs that trigger as the price moves, a wallet and per-product leverage.
The paper desk is the harness's in-memory Mongo, and the clock is controlled.

What this pins down: sizing by $5 of risk under the $2,500 notional cap; brackets at the paper's own stop and target,
the stop's limit past its trigger; closes when the paper closes, when the venue's bracket closes it and when the paper
trade disappears; one position per product; late and drifted signals refused; a refused bracket closing the position
at once and switching the desk off; a lost order answer adopted from the account; the $20 daily stop and its reset;
a stale paper desk; shadow mode sending nothing; flatten; the PIN, its lockout and the REAL MONEY confirmation;
leverage set to 10x before going live; three venue errors switching the desk off. Then (15 Nov): the owner's risk a
trade, $1 to $5 with the PIN; each desk's lag limit, 10 minutes on bitcoin and 5 on gold; the books named to the paper
desk so it runs them first. Later on 15 Nov: every strategy may hold a trade at the same time, each with its OWN
stop and target orders on Delta (sections 1-5, 8, 9 and 25-29 test them); one contract a trade by default on both desks (a dollar risk is the
owner's other choice), TD-02 and CP-06 added, and gold also 10 minutes.

Two desks since 14 Nov 2026: the bitcoin scenarios run on the crypto desk (the Delta Exchange Live Trading module: TH-05,
TL-04, TH-01) and the gold ones on the gold desk. Sections 16-18 pin the split down: each desk trades only its own picks
and product; former bitcoin picks and TL-04's gold book are ignored; a bitcoin trade the gold desk opened before the
split is managed by it to its close and blocks the crypto desk from going live; each desk has its own switch and stop.

18 Nov 2026 (section 31): five more bitcoin and thirteen more gold Premium picks, and six Gold Desk H1 templates on the
gold desk, read from the Gold Desk's own positions (faked here as an in-memory collection, stored as the database does:
naive UTC times). Pinned: what is copied and what is not; a Gold Desk that cannot be read leaves its trades waiting,
never closed; each source's own clock (a silent Gold Desk stops H1 entries only, a silent paper desk Premium ones);
a voided or closed position closes the real trade; the paper desk is told only its own books.

22 Nov 2026 (section 36): the owner's third list, 49 more gold picks (Premium, H1, Factory) and 9 on the bitcoin desk,
two of them ether books on ETHUSD, the first second product on a desk. Pinned: the lists and their records; ether
copied, closed and checked against the account like bitcoin; a product that joins a desk already live has its
leverage confirmed at 10x (read, set only if needed, read back) before its first entry, its signals waiting meanwhile
and never sent at another leverage; shadow sends nothing. The harness's desks start as going live leaves them: every
product's leverage confirmed in their state.

25 Nov 2026 (section 41): Delta's 100 open orders a product. A refusal for that limit skips the signal ("Delta's
100-order limit full") and the desk stays on; gold trades keep only their stop on Delta and the app closes them at
their target. Sections 1-40 run with APP_TARGET_PRODUCTS empty: they pin the stop-and-target-on-Delta mechanism
that bitcoin and ether keep (and gold had until then); section 41 runs the server's own setting, gold only.
"""

import asyncio
import hashlib
import math
import os
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200"   # Main Control's store: never the real one
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gold_desk"))
from _harness import Coll, check, finish, section  # noqa: E402

from app.services import delta_rest as DR  # noqa: E402
from app.services import premium_live as M  # noqa: E402
from app.services.delta_rest import Delta, DeltaError  # noqa: E402

PROD_APP_TARGET = M.APP_TARGET_PRODUCTS     # as the server reads it (25 Nov 2026): gold only; section 41

UTC = timezone.utc
T0 = datetime(2026, 11, 16, 9, 0, tzinfo=UTC).timestamp()      # a Monday, 14:30 IST
CLOCK = [T0]
M._now = lambda: CLOCK[0]
PIN = "4711"
SALT = "test-salt"
_tmp = Path(tempfile.mkdtemp(prefix="plive_"))
(_tmp / "secrets").write_text(f"DELTA_API_KEY=k\nDELTA_API_SECRET=s\nLIVE_ARM_SALT={SALT}\n"
                              f"LIVE_ARM_PIN_SHA256={hashlib.sha256((SALT + PIN).encode()).hexdigest()}\n", encoding="utf-8")
DR.SECRETS_FILE = _tmp / "secrets"
for k in ("DELTA_API_KEY", "DELTA_API_SECRET"):
    os.environ.pop(k, None)


def advance(s):
    CLOCK[0] += s


# ── the fake exchange ─────────────────────────────────────────────────────────────────────────────

SPECS = {"BTCUSD": {"id": 27, "cv": "0.001", "tick": "0.5", "mm": "0.25", "taker": "0.0005", "spread": 0.5, "lev": 200},
         "XAUTUSD": {"id": 131253, "cv": "0.001", "tick": "0.01", "mm": "0.5", "taker": "0.0001", "spread": 0.03, "lev": 100},
         # Delta India's ETHUSD as read on 22 Nov 2026 (the bitcoin desk's second product); its default leverage here is
         # one nobody set, so section 36 can show the desk setting it
         "ETHUSD": {"id": 3136, "cv": "0.01", "tick": "0.05", "mm": "0.25", "taker": "0.0005", "spread": 0.1, "lev": 100}}
BY_ID = {v["id"]: k for k, v in SPECS.items()}


class FakeDelta(Delta):
    def __init__(self):
        super().__init__()
        self.mid = {"BTCUSD": 69000.0, "XAUTUSD": 3885.0, "ETHUSD": 1690.0}
        self.pos = {}                 # product id -> {"size": signed int, "entry": float}
        self.legs = {}                # product id -> {"stop": (trigger, limit) | None, "tp": (trigger, limit) | None}
        self.fills_ = []
        self.orders = []
        self.lev = {v["id"]: v["lev"] for v in SPECS.values()}
        self.balance = 400.0
        self.fail = {}                # path key -> "definite" | "ambiguous" | ("ambiguous_after", ...)
        self.calls = []
        self.oid = 1000
        self.stops = {}               # order id -> a trade's own leg (a standalone stop order), as Delta reports it
        self.book = {}                # order id -> every order placed, as Delta reports it (by id or client id)
        self.stop_orders = []         # the bodies of the legs placed

    # quotes
    def bid(self, sym):
        return self.mid[sym] - SPECS[sym]["spread"] / 2

    def ask(self, sym):
        return self.mid[sym] + SPECS[sym]["spread"] / 2

    def _fail(self, key):
        f = self.fail.get(key)
        if f == "definite":
            raise DeltaError(f"{key}: HTTP 400 {{\"code\":\"test_refusal\"}}")
        if f == "ambiguous":
            raise DeltaError(f"{key}: no answer (ReadTimeout)", ambiguous=True)

    def _fill(self, pid, side, size, price, reduce_only=False, kind="market", order_id=None):
        sym = BY_ID[pid]
        cv = float(SPECS[sym]["cv"])
        comm = abs(size * cv * price) * float(SPECS[sym]["taker"]) * 1.18
        if order_id is None:
            self.oid += 1
        oid = str(order_id) if order_id is not None else str(self.oid)
        p = self.pos.get(pid, {"size": 0, "entry": 0.0})
        signed = size if side == "buy" else -size
        new = p["size"] + signed
        if p["size"] == 0 or (p["size"] > 0) == (signed > 0):
            entry = (p["entry"] * abs(p["size"]) + price * size) / abs(new) if new else 0.0
        else:
            entry = p["entry"] if new and (new > 0) == (p["size"] > 0) else (price if new else 0.0)
            self.balance += (price - p["entry"]) * (1 if p["size"] > 0 else -1) * min(size, abs(p["size"])) * cv
        self.balance -= comm
        if new:
            self.pos[pid] = {"size": new, "entry": entry}
        else:
            self.pos.pop(pid, None)
        self.fills_.append({"id": f"f-{oid}", "order_id": oid, "side": side, "size": size, "price": f"{price}",
                            "commission": f"{comm}", "created_at": datetime.fromtimestamp(CLOCK[0], UTC).isoformat(),
                            "product_id": pid, "kind": kind})
        return oid, comm

    def set_price(self, sym, px):
        """Move the market: every trade's own leg the move crosses fills (in the order placed); a resting bracket leg
        (trades from before 15 Nov) fills and the other is cancelled."""
        self.mid[sym] = px
        pid = SPECS[sym]["id"]
        for oid, o in sorted(self.stops.items(), key=lambda kv: int(kv[0])):
            if o["product_id"] != pid or o["state"] != "pending":
                continue
            trig, lim, sell = float(o["stop_price"]), float(o["limit_price"]), o["side"] == "sell"
            loss = o["stop_order_type"] == "stop_loss_order"
            hit = (px <= trig if sell else px >= trig) if loss else (px >= trig if sell else px <= trig)
            if not hit:
                continue
            fill = (max(self.bid(sym), lim) if sell else min(self.ask(sym), lim)) if loss else lim
            _, comm = self._fill(pid, o["side"], int(o["size"]), fill, False, "leg", order_id=oid)
            o.update(state="closed", unfilled_size=0, average_fill_price=f"{fill}", paid_commission=f"{comm}")
        p, lg = self.pos.get(pid), self.legs.get(pid)
        if not p or not lg:
            return
        long_ = p["size"] > 0
        close_side = "sell" if long_ else "buy"
        st, tp = lg.get("stop"), lg.get("tp")
        if st and ((long_ and px <= st[0]) or (not long_ and px >= st[0])):
            fill = max(self.bid(sym), st[1]) if long_ else min(self.ask(sym), st[1])
            self._fill(pid, close_side, abs(p["size"]), fill, True, "stop")
            self.legs.pop(pid, None)
        elif tp and ((long_ and px >= tp[0]) or (not long_ and px <= tp[0])):
            self._fill(pid, close_side, abs(p["size"]), tp[1], True, "target")
            self.legs.pop(pid, None)

    # the HTTP surface the client uses
    async def request(self, method, path, body=None, signed=True):
        self.calls.append((method, path.split("?")[0]))
        base = path.split("?")[0]
        if method == "GET" and base.startswith("/v2/products/") and base.count("/") == 3:
            sym = base.rsplit("/", 1)[1]
            s = SPECS[sym]
            return {"id": s["id"], "symbol": sym, "contract_type": "perpetual_futures", "contract_value": s["cv"],
                    "tick_size": s["tick"], "maintenance_margin": s["mm"], "taker_commission_rate": s["taker"]}
        if method == "GET" and base.startswith("/v2/tickers/"):
            sym = base.rsplit("/", 1)[1]
            self._fail("ticker")
            return {"symbol": sym, "mark_price": f"{self.mid[sym]}", "close": self.mid[sym],
                    "quotes": {"best_bid": f"{self.bid(sym)}", "best_ask": f"{self.ask(sym)}"}}
        if method == "GET" and base == "/v2/positions/margined":
            self._fail("positions")
            return [{"product_id": pid, "product_symbol": BY_ID[pid], "size": p["size"], "entry_price": f"{p['entry']}",
                     "mark_price": f"{self.mid[BY_ID[pid]]}", "unrealised_pnl": "0", "margin": "1"}
                    for pid, p in self.pos.items()]
        if method == "GET" and base == "/v2/wallet/balances":
            self._fail("wallet")
            blocked = sum(abs(p["size"]) * float(SPECS[BY_ID[pid]]["cv"]) * p["entry"] / self.lev[pid] for pid, p in self.pos.items())
            return [{"asset_symbol": "USD", "balance": f"{self.balance}", "available_balance": f"{self.balance - blocked}",
                     "blocked_margin": f"{blocked}"}]
        if base.endswith("/orders/leverage"):
            pid = int(base.split("/")[3])
            if method == "POST":
                self._fail("leverage")
                self.lev[pid] = int(body["leverage"])
            return {"leverage": f"{self.lev[pid]}"}
        if method == "GET" and base == "/v2/fills":
            q = dict(kv.split("=") for kv in path.split("?")[1].split("&"))
            since = int(q["start_time"]) / 1e6
            pid = int(q["product_ids"])
            return [f for f in self.fills_ if f["product_id"] == pid
                    and datetime.fromisoformat(f["created_at"]).timestamp() >= since]
        if method == "GET" and base == "/v2/orders":
            self._fail("open_orders")
            q = dict(kv.split("=") for kv in path.split("?")[1].split("&"))
            pid, states = int(q["product_ids"]), q["states"].split(",")
            return [dict(o) for o in self.stops.values() if o["product_id"] == pid and o["state"] in states]
        if method == "GET" and base.startswith("/v2/orders/client_order_id/"):
            self._fail("order_lookup")
            cid = base.rsplit("/", 1)[1]
            for o in self.book.values():
                if o.get("client_order_id") == cid:
                    return dict(o)
            raise DeltaError(f"GET {base}: HTTP 404 {{\"code\":\"not_found\"}}")
        if method == "GET" and base.startswith("/v2/orders/") and base.count("/") == 3:
            self._fail("order_lookup")
            o = self.book.get(base.rsplit("/", 1)[1])
            if o is None:
                raise DeltaError(f"GET {base}: HTTP 404 {{\"code\":\"not_found\"}}")
            return dict(o)
        if method == "DELETE" and base == "/v2/orders":
            self._fail("cancel")
            o = self.stops.get(str(body["id"]))
            if o is None or o["state"] != "pending":
                raise DeltaError("DELETE /v2/orders: HTTP 400 {\"code\": \"open_order_not_found\"}")
            o["state"] = "cancelled"
            return dict(o)
        if method == "POST" and base == "/v2/orders" and body.get("stop_order_type"):
            self._fail("stop_order")
            left = self.fail.get("stop_order_after")          # this many legs go through, then they are refused
            if left is not None:
                if left <= 0:
                    raise DeltaError("POST /v2/orders: HTTP 400 {\"code\":\"test_refusal\"}")
                self.fail["stop_order_after"] = left - 1
            pid, tick = body["product_id"], float(SPECS[BY_ID[body["product_id"]]]["tick"])
            for k in ("stop_price", "limit_price"):
                v = body[k]
                assert isinstance(v, str) and abs(round(float(v) / tick) * tick - float(v)) < 1e-9, f"off tick: {v}"
            assert body["order_type"] == "limit_order" and body.get("reduce_only") is False
            assert body.get("stop_trigger_method") == "last_traded_price"
            self.oid += 1
            o = {"id": self.oid, "product_id": pid, "side": body["side"], "size": body["size"], "unfilled_size": body["size"],
                 "state": "pending", "stop_order_type": body["stop_order_type"], "stop_price": body["stop_price"],
                 "limit_price": body["limit_price"], "client_order_id": body.get("client_order_id"),
                 "average_fill_price": None, "paid_commission": "0"}
            self.stops[str(self.oid)] = o
            self.book[str(self.oid)] = o
            self.stop_orders.append(dict(body))
            return dict(o)
        if method == "POST" and base == "/v2/orders":
            assert body["order_type"] == "market_order"
            self.orders.append(dict(body))
            pid, size, side = body["product_id"], body["size"], body["side"]
            sym = BY_ID[pid]
            f = self.fail.get("market")
            if f == "definite":
                raise DeltaError("POST /v2/orders: HTTP 400 {\"code\":\"insufficient_margin\"}")
            if body.get("reduce_only"):
                p = self.pos.get(pid)
                size = min(size, abs(p["size"])) if p else 0
            px = self.ask(sym) if side == "buy" else self.bid(sym)
            oid, comm = self._fill(pid, side, size, px, body.get("reduce_only", False)) if size else ("0", 0.0)
            o = {"id": int(oid), "size": size, "unfilled_size": "0", "average_fill_price": f"{px}",
                 "paid_commission": f"{comm}", "state": "closed", "client_order_id": body.get("client_order_id"),
                 "product_id": pid, "side": side}
            self.book[str(oid)] = o
            if f == "ambiguous":            # the order went through; the answer did not come back
                raise DeltaError("POST /v2/orders: no answer (ReadTimeout)", ambiguous=True)
            return dict(o)
        if method == "POST" and base == "/v2/orders/bracket":
            self._fail("bracket")
            pid = body["product_id"]
            if pid not in self.pos:
                raise DeltaError("POST /v2/orders/bracket: HTTP 400 {\"code\":\"no_position\"}")
            for leg in ("stop_loss_order", "take_profit_order"):
                if leg in body:
                    for k in ("stop_price", "limit_price"):
                        v = body[leg][k]
                        tick = float(SPECS[BY_ID[pid]]["tick"])
                        assert isinstance(v, str) and abs(round(float(v) / tick) * tick - float(v)) < 1e-9, f"off tick: {v}"
            sl, tp = body.get("stop_loss_order"), body.get("take_profit_order")
            self.legs[pid] = {"stop": (float(sl["stop_price"]), float(sl["limit_price"])) if sl else None,
                              "tp": (float(tp["stop_price"]), float(tp["limit_price"])) if tp else None,
                              "trigger": body.get("bracket_stop_trigger_method")}
            return {}
        if method == "DELETE" and base == "/v2/orders/all":
            self.legs.pop(body["product_id"], None)
            for o in self.stops.values():
                if o["product_id"] == body["product_id"] and o["state"] == "pending":
                    o["state"] = "cancelled"
            return {}
        raise AssertionError(f"unexpected call {method} {path}")


_REAL_DESKS = dict(M.DESKS)          # production: both desks follow every paper trade (19 Nov)


def fresh(mode="live", btc=69000.0, gold=3885.0, follow=True):
    """A fresh scenario. follow=False runs it on the rules before 19 Nov (lag, drift, daily stop, $5 cap): the code
    path every desk without follow_all still takes."""
    M.DESKS.clear()
    M.DESKS.update(_REAL_DESKS if follow else {k: replace(v, follow_all=False) for k, v in _REAL_DESKS.items()})
    db = SimpleNamespace(premium_trades=Coll("pt"), premium_meta=Coll("pm"), live_delta_trades=Coll("lt"),
                         live_delta_state=Coll("ls"), live_crypto_trades=Coll("ct"), live_crypto_state=Coll("cs"),
                         live_pgold_state=Coll("gs2"), live_pgold_trades=Coll("gt2"))   # the Premium Gold book (24 Nov)
    db.premium_meta.docs.append({"_id": "status", "segments_at": datetime.fromtimestamp(CLOCK[0], UTC).isoformat()})
    M._db = lambda: db
    # the Gold Desk (the gold desk's second source, 18 Nov): empty and running, unless section 31 says otherwise
    gpos, gstate = Coll("gpos"), Coll("gstate")
    gstate.docs.append({"_id": "delta", "last_run_at": datetime.fromtimestamp(CLOCK[0], UTC).replace(tzinfo=None)})
    M._h1_coll, M._h1_state_coll = (lambda: gpos), (lambda: gstate)
    # the Gold Desk's Strategy Factory tab (the third source, 19 Nov): empty and running, unless section 34 says otherwise
    sfpos, sfstate = Coll("sfpos"), Coll("sfstate")
    sfstate.docs.append({"_id": "cycle:gold", "at": datetime.fromtimestamp(CLOCK[0], UTC).replace(tzinfo=None)})
    M._sf_coll, M._sf_state_coll = (lambda: sfpos), (lambda: sfstate)
    M._PAPER_CACHE.clear()                  # the page's paper view is cached 30 s a desk: never across scenarios
    M._WAITING.clear()                      # copies a follow_all desk is waiting on (memory only): never across scenarios
    M._FULL.clear()                         # Delta's 100-order limit seen full (25 Nov; memory only)
    M._TQ.clear()                           # the target check's quotes (memory only)
    M._CONVERTED.clear()
    M.D = FakeDelta()
    M.D.mid.update(BTCUSD=btc, XAUTUSD=gold)
    if mode != "off":
        # a desk already on, as going live leaves it: its products' leverage confirmed at 10x in its state (going live
        # sets it; section 36 takes ETHUSD's away to show a product that joins a live desk being confirmed first)
        for coll in (db.live_delta_state, db.live_crypto_state):
            coll.docs.append({"_id": "state", "mode": mode, "since": CLOCK[0] - 3600, "errors_in_row": 0,
                              "pin_fails": [], "products": {s: {"leverage": 10} for s in SPECS},
                              "sizing": "risk"})   # dollar sizing; 22 tests one contract
    return db


def st_of(db, desk):
    coll = {"crypto": db.live_crypto_state, "premium_gold": db.live_pgold_state}.get(desk, db.live_delta_state)
    return coll.docs[0] if coll.docs else {}


def paper(db, acct, mkt, side, entry, stop, target, ago=30, **kw):
    tid = f"{acct}|{mkt}|{mkt}|{int(CLOCK[0] - ago)}|{side}"
    db.premium_trades.docs.append({"_id": tid, "acct": acct, "mkt": mkt, "sym": mkt, "side": side,
                                   "entry_t": int(CLOCK[0] - ago), "entry": entry, "stop": stop, "target": target,
                                   "open": True, "qty": 1.0, "reason": None, "exit": None, **kw})
    return tid


def close_paper(db, tid, reason, exit_px):
    for d in db.premium_trades.docs:
        if d["_id"] == tid:
            d.update(open=False, reason=reason, exit=exit_px, exit_t=int(CLOCK[0]))


def own_leg(t, k):
    """A trade's own leg ("stop" or "target") as the fake exchange holds it."""
    oid = ((t or {}).get("legs") or {}).get(f"{k}_id")
    return M.D.stops.get(str(oid)) if oid else None


def trade(db, tid):
    return next((d for d in db.live_crypto_trades.docs + db.live_delta_trades.docs + db.live_pgold_trades.docs
                 if d["_id"] == tid), None)


def heartbeat(db):
    db.premium_meta.docs[0]["segments_at"] = datetime.fromtimestamp(CLOCK[0], UTC).isoformat()


async def cyc(db):
    heartbeat(db)
    return await M.cycle()


async def _fake_fx():                      # the page's USD/INR (24 Nov 2026): never the network in a test
    M._FX.update(rate=90.0, asof="test", at=M._now())


async def main():
    M._read_fx = _fake_fx
    M.APP_TARGET_PRODUCTS = frozenset()   # sections 1-40: both orders on Delta (bitcoin and ether still); 41: gold
    BTC, GOLD = 27, 131253
    M.REQUIRE_PIN = True          # sections 1-23 test the PIN when the server requires one; 24 the owner's choice: none
    # ── 1. a live bitcoin entry, sized by risk, with the stop on the venue ─────────────────────────
    section("1. A live entry: $5 of risk, the paper's stop on Delta, no target when the paper has none")
    db = fresh()
    t1 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    r = await cyc(db)
    t = trade(db, t1)
    ask = M.D.ask("BTCUSD")
    want = min(math.floor(5 / ((ask - 68650.0) * 0.001)), math.floor(2500 / (ask * 0.001)))
    check("a market buy of the risk-sized contracts went in", t and t["status"] == "open" and t["contracts"] == want
          and M.D.orders[-1]["side"] == "buy" and M.D.pos[BTC]["size"] == want, f"{r['crypto']['entered']} / {want} contracts")
    check("its risk at the stop is at most $5", t["plan"]["risk_usd"] <= 5.0 + 1e-9, t["plan"])
    sl = own_leg(t, "stop")
    check("its own stop is on Delta: a sell of its size at the paper's stop, the limit 20% of the risk past it, not "
          "reduce-only, last-traded trigger; no target leg", sl is not None and sl["state"] == "pending" and sl["side"] == "sell"
          and sl["size"] == want and float(sl["stop_price"]) == 68650.0
          and abs(float(sl["limit_price"]) - (68650.0 - (ask - 68650.0) * 0.2)) <= 0.5 and t["legs"]["target_id"] is None
          and M.D.stop_orders[-1]["reduce_only"] is False and M.D.stop_orders[-1]["stop_trigger_method"] == "last_traded_price",
          sl)
    check("the order carried a client id derived from the paper trade", M.D.orders[-1].get("client_order_id", "").startswith("p5"))

    # ── 2. the venue's stop closes it ───────────────────────────────────────────────────────────────
    section("2. The price hits the stop on Delta: recorded from Delta's fills, legs cleared")
    advance(600)
    M.D.set_price("BTCUSD", 68600.0)
    await cyc(db)
    t = trade(db, t1)
    check("closed as a venue stop, from the fills", t["status"] == "closed" and t["close_reason"] == "venue stop"
          and t["exit_basis"] == "fills", (t.get("close_reason"), t.get("exit_basis")))
    risk = t["plan"]["risk_usd"]
    fees = t["fees"]
    check("the loss is the planned risk, at most 1.2x it on a gap through the stop, plus Delta's fees",
          -(1.2 * risk + fees) - 0.01 <= t["pnl_usd"] <= -risk * 0.9, (t["pnl_usd"], round(risk, 2), round(fees, 2)))
    check("no leg is left on the product", BTC not in M.D.pos and not any(o["state"] == "pending" for o in M.D.stops.values()))

    # ── 3. the paper's own exit closes it ───────────────────────────────────────────────────────────
    section("3. The paper trade exits on its signal: the real one is closed at the market")
    db = fresh()
    t3 = paper(db, "TH-05", "BTCUSD", -1, 69000.0, 69300.0, None)
    await cyc(db)
    advance(1800)
    M.D.set_price("BTCUSD", 68800.0)
    close_paper(db, t3, "exit_signal", 68800.0)
    await cyc(db)
    t = trade(db, t3)
    calls = M.D.calls
    i_cancel = max((i for i, c in enumerate(calls) if c == ("DELETE", "/v2/orders")), default=-1)
    i_close = max((i for i, c in enumerate(calls) if c == ("POST", "/v2/orders")), default=-1)
    check("its stop was cancelled first, then a buy of its own size closed it (not reduce-only: trades share the position)",
          0 <= i_cancel < i_close and M.D.orders[-1].get("reduce_only") is None and M.D.orders[-1]["side"] == "buy"
          and M.D.orders[-1]["size"] == trade(db, t3)["contracts"] and BTC not in M.D.pos, (i_cancel, i_close))
    check("recorded with the paper's reason and a profit (short from 69,000 to 68,800)",
          t["status"] == "closed" and t["close_reason"] == "paper exit: exit_signal" and t["pnl_usd"] > 0, t.get("pnl_usd"))
    check("its stop ended cancelled, never filled", own_leg(trade(db, t3), "stop")["state"] == "cancelled")

    # ── 4. a gold trade reaches its target on Delta ─────────────────────────────────────────────────
    section("4. Gold: target and stop both on Delta; the target fills")
    db = fresh(gold=3885.0)
    t4 = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    await cyc(db)
    t = trade(db, t4)
    sl, tp = own_leg(t, "stop"), own_leg(t, "target")
    check("both of its own legs on Delta, on the 0.01 tick", sl is not None and tp is not None
          and float(sl["stop_price"]) == 3880.0 and float(tp["stop_price"]) == 3895.0 and float(tp["limit_price"]) == 3895.0
          and sl["state"] == tp["state"] == "pending", (sl, tp))
    advance(900)
    M.D.set_price("XAUTUSD", 3895.5)
    await cyc(db)
    t = trade(db, t4)
    rr = (3895.0 - t["fill"]) / (t["fill"] - 3880.0)
    want = t["plan"]["risk_usd"] * rr - t["fees"]
    check("closed as a venue target: the trade's risk x its reward ratio, less fees (the $2,500 cap bound its size)",
          t["status"] == "closed" and t["close_reason"] == "venue target" and abs(t["pnl_usd"] - want) < 0.02
          and t["plan"]["capped"], (t["pnl_usd"], round(want, 2), t["plan"]["risk_usd"]))
    check("its stop was cancelled once the target filled; nothing else was sent", own_leg(t, "stop")["state"] == "cancelled"
          and len(M.D.orders) == 1 and GOLD not in M.D.pos)

    # ── 5. one position per product, and the account's own positions ───────────────────────────────
    section("5. Every strategy on one product at once (15 Nov); a position no trade accounts for makes entries wait")
    db = fresh()
    a = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    b = paper(db, "TL-04", "BTCUSD", -1, 69000.0, 69400.0, 68400.0, ago=20)
    await cyc(db)
    ta, tb = trade(db, a), trade(db, b)
    check("both bitcoin signals opened, each with its own stop (TL-04 its target too)", ta["status"] == "open"
          and tb["status"] == "open" and own_leg(ta, "stop")["state"] == "pending" and own_leg(tb, "stop")["state"] == "pending"
          and own_leg(tb, "target")["state"] == "pending", (ta.get("reason"), tb.get("reason")))
    check("Delta holds their sum as one position (the long and the short net out)",
          M.D.pos.get(BTC, {}).get("size", 0) == ta["contracts"] - tb["contracts"], (M.D.pos.get(BTC), ta["contracts"], tb["contracts"]))
    M.D.pos[GOLD] = {"size": 50, "entry": 3880.0}          # the owner's own gold position
    g = paper(db, "YT-14", "XAUUSD", 1, 3885.0, 3878.0, 3899.0)
    await cyc(db)
    check("a gold signal waits, undecided, while the account holds gold no trade accounts for",
          trade(db, g) is None and st_of(db, "gold")["mismatch_checks"] == 1, st_of(db, "gold").get("mismatch"))
    await cyc(db)
    await cyc(db)
    sg = st_of(db, "gold")
    check("seen on three checks: the gold desk switches off and says why", sg["mode"] == "off"
          and "has not matched" in (sg.get("switched_off") or ""), sg.get("switched_off"))
    check("the owner's position was not touched, and the bitcoin desk carries on", M.D.pos[GOLD]["size"] == 50
          and st_of(db, "crypto")["mode"] == "live" and trade(db, g) is None)

    # ── 6. late, drifted and outside the levels ─────────────────────────────────────────────────────
    section("6. Late or moved signals are refused, never chased [a desk without follow_all: the rules before 19 Nov]")
    db = fresh(follow=False)
    late = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, None, ago=700)
    await cyc(db)
    check("bitcoin seen 11+ minutes after its entry: skipped (its limit is 10)", trade(db, late)["status"] == "skipped"
          and "after its entry (limit 10)" in trade(db, late)["reason"], trade(db, late)["reason"])
    db = fresh(follow=False, btc=69150.0)
    drift = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, None)
    await cyc(db)
    check("the market already 50% of the risk away: skipped", trade(db, drift)["status"] == "skipped"
          and "moved" in trade(db, drift)["reason"], trade(db, drift)["reason"])
    db = fresh(follow=False, btc=68690.0)
    past = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, None)
    await cyc(db)
    check("the market already past the stop: skipped", trade(db, past)["status"] == "skipped"
          and "between the stop" in trade(db, past)["reason"], trade(db, past)["reason"])
    check("none of them sent an order", not M.D.orders)

    # ── 7. the notional cap ─────────────────────────────────────────────────────────────────────────
    section("7. A very tight stop: the $2,500 notional cap binds, so less than $5 is risked")
    db = fresh(gold=3885.0)
    tight = paper(db, "CP-23", "XAUUSD", -1, 3885.0, 3886.6, 3881.0)
    await cyc(db)
    t = trade(db, tight)
    cap = math.floor(2500 / (M.D.bid("XAUTUSD") * 0.001))
    check("capped at the notional limit", t["status"] == "open" and t["contracts"] == cap and t["plan"]["capped"]
          and t["plan"]["risk_usd"] < 5, (t["contracts"], cap, t["plan"]["risk_usd"]))

    # ── 8. a refused bracket ────────────────────────────────────────────────────────────────────────
    section("8. Delta refuses a trade's stop or target: the trade is closed at once and the desk switches off")
    db = fresh()
    M.D.fail["stop_order"] = "definite"
    t8 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    t, st = trade(db, t8), st_of(db, "crypto")
    check("the trade was closed in the same pass", BTC not in M.D.pos and t["status"] == "closed"
          and "stop or target refused" in t["close_reason"], t.get("close_reason"))
    check("the desk switched itself off and says why", st["mode"] == "off"
          and "stop or target was refused" in (st.get("switched_off") or ""), st.get("switched_off"))
    db = fresh(gold=3885.0)
    M.D.fail["stop_order_after"] = 1                       # the stop goes through, the target is refused
    t8b = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    await cyc(db)
    t = trade(db, t8b)
    check("the target refused after the stop went in: the stop is cancelled and the trade closed at once",
          t["status"] == "closed" and own_leg(t, "stop")["state"] == "cancelled" and GOLD not in M.D.pos
          and st_of(db, "gold")["mode"] == "off", (t.get("status"), t.get("legs")))

    # ── 9. a lost order answer ──────────────────────────────────────────────────────────────────────
    section("9. The entry's answer is lost: the position is found on the account and protected")
    db = fresh()
    M.D.fail["market"] = "ambiguous"
    t9 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    check("left 'entering' (it may have filled), not written off", trade(db, t9)["status"] == "entering" and BTC in M.D.pos)
    M.D.fail.pop("market")
    advance(100)
    await cyc(db)
    t = trade(db, t9)
    check("found on Delta by its client id, adopted and given its own stop", t["status"] == "open" and t.get("recovered")
          and own_leg(t, "stop") is not None and float(own_leg(t, "stop")["stop_price"]) == 68650.0, (t["status"], t.get("legs")))
    db = fresh()
    M.D.fail["market"] = "definite"
    t9b = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    check("a plain refusal is an error, with nothing on the account", trade(db, t9b)["status"] == "error" and BTC not in M.D.pos)

    # ── 10. the daily loss stop ─────────────────────────────────────────────────────────────────────
    section("10. The $20 daily loss stop, and its reset the next day (IST) [a desk without follow_all]")
    db = fresh(follow=False)
    for i in range(4):
        tid = paper(db, "TH-01", "BTCUSD", 1, M.D.mid["BTCUSD"], M.D.mid["BTCUSD"] - 350.0, None, ago=10)
        await cyc(db)
        advance(60)
        M.D.set_price("BTCUSD", M.D.mid["BTCUSD"] - 400.0)
        await cyc(db)
        advance(60)
    day_loss = sum(t.get("pnl_usd") or 0 for t in db.live_crypto_trades.docs if t["status"] == "closed")
    nxt = paper(db, "TH-01", "BTCUSD", 1, M.D.mid["BTCUSD"], M.D.mid["BTCUSD"] - 350.0, None, ago=10)
    await cyc(db)
    check("four stopped trades lose about $20, and the next is refused", day_loss <= -20 and trade(db, nxt)["status"] == "skipped"
          and "daily loss stop" in trade(db, nxt)["reason"], round(day_loss, 2))
    CLOCK[0] = datetime(2026, 11, 17, 3, 30, tzinfo=UTC).timestamp()     # 09:00 IST the next day
    tomorrow = paper(db, "TH-01", "BTCUSD", 1, M.D.mid["BTCUSD"], M.D.mid["BTCUSD"] - 350.0, None, ago=10)
    await cyc(db)
    check("the next IST day trades again", trade(db, tomorrow)["status"] == "open")

    # ── 11. the paper trade disappears; the paper desk goes quiet ───────────────────────────────────
    section("11. A paper trade that disappears, and a paper desk that stops updating")
    db = fresh()
    t11 = paper(db, "TL-04", "BTCUSD", 1, 69000.0, 68300.0, 70400.0)
    await cyc(db)
    db.premium_trades.docs = [d for d in db.premium_trades.docs if d["_id"] != t11]
    await cyc(db)
    check("first noticed, not closed at once", trade(db, t11)["status"] == "open" and trade(db, t11).get("paper_missing_since"))
    advance(301)
    await cyc(db)
    check("closed after five minutes gone", trade(db, t11)["status"] == "closed"
          and trade(db, t11)["close_reason"] == "the paper trade disappeared" and BTC not in M.D.pos)
    db = fresh()
    t11b = paper(db, "TL-04", "BTCUSD", 1, 69000.0, 68300.0, 70400.0)
    await cyc(db)
    advance(1500)
    stale = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0, ago=10)
    stale_b = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68650.0, None, ago=10)
    n_orders = len(M.D.orders)
    r11 = await M.cycle()                                       # no heartbeat: the desk last wrote 25 minutes ago
    check("a desk silent for 20+ minutes: no new entry, no order sent", len(M.D.orders) == n_orders)
    check("... each copy WAITS (19 Nov: both desks follow every paper trade): nothing recorded, the reason kept for the "
          "page", trade(db, stale) is None and trade(db, stale_b) is None and r11["gold"].get("waiting") == 1
          and r11["crypto"].get("waiting") == 1 and "not updated" in M._WAITING["gold"][stale]["why"]
          and "not updated" in M._WAITING["crypto"][stale_b]["why"], (r11["gold"], r11["crypto"], M._WAITING))
    close_paper(db, stale, "exit_signal", 3885.0)
    close_paper(db, stale_b, "exit_signal", 69000.0)
    advance(2200)
    await M.cycle()
    check("silent for an hour: the open position is closed", trade(db, t11b)["status"] == "closed"
          and trade(db, t11b)["close_reason"] == "the paper desk stopped updating")

    # ── 12. shadow mode ─────────────────────────────────────────────────────────────────────────────
    section("12. Shadow: every decision, simulated fills, no order sent")
    db = fresh(mode="shadow", gold=3885.0)
    s12 = paper(db, "YT-14", "XAUUSD", 1, 3885.0, 3878.0, 3899.0)
    await cyc(db)
    advance(900)
    close_paper(db, s12, "target", 3899.0)
    await cyc(db)
    t = trade(db, s12)
    check("opened and closed in shadow at the paper's target", t["mode"] == "shadow" and t["status"] == "closed"
          and t["exit_price"] == 3899.0 and t["pnl_usd"] > 0, (t["status"], t.get("exit_price"), t.get("pnl_usd")))
    check("no order and no signed call reached the exchange",
          not M.D.orders and not any(p in ("/v2/positions/margined", "/v2/wallet/balances") for _m, p in M.D.calls))

    # ── 13. the owner's controls ────────────────────────────────────────────────────────────────────
    section("13. Going live needs the PIN and the words REAL MONEY; leverage is set to 10x first")
    db = fresh(mode="off")
    r = await M.set_mode("live", "0000", "REAL MONEY", desk="crypto")
    check("a wrong PIN is refused and counted", not r["ok"] and "wrong PIN" in r["why"], r["why"])
    r = await M.set_mode("live", PIN, "yes", desk="crypto")
    check("the right PIN without the words is refused", not r["ok"] and "REAL MONEY" in r["why"], r["why"])
    M.D.pos[BTC] = {"size": 3, "entry": 69000.0}
    r = await M.set_mode("live", PIN, "real money", desk="crypto")
    check("a position the desk does not own blocks going live", not r["ok"] and "BTCUSD: the account holds +3 contracts "
          "and the desks' trades none: close those 3 on Delta" in r["why"], r["why"])
    M.D.pos.pop(BTC)
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="crypto")
    check("then it goes live, with leverage at 10x on its own products, BTCUSD and ETHUSD (gold keeps Delta's default "
          "until its own desk arms)",
          r["ok"] and M.D.lev[BTC] == 10 and M.D.lev[SPECS["ETHUSD"]["id"]] == 10 and M.D.lev[GOLD] == 100
          and r["leverage"] == {"BTCUSD": 10, "ETHUSD": 10} and st_of(db, "crypto")["mode"] == "live"
          and not db.live_delta_state.docs, r)
    for _ in range(5):
        await M.set_mode("live", "0000", "REAL MONEY", desk="crypto")
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="crypto")
    check("five wrong PINs lock going live for an hour, even with the right one", not r["ok"] and "locked" in r["why"], r["why"])
    advance(3601)
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="crypto")
    check("an hour later it works again", r["ok"], r)
    r = await M.set_mode("live", PIN, "REAL MONEY")
    check("the gold desk arms on its own, setting 10x on XAUTUSD only", r["ok"] and M.D.lev[GOLD] == 10
          and st_of(db, "gold")["mode"] == "live", r)
    r = await M.set_mode("off", desk="crypto")
    check("switching off needs no PIN, and switches only that desk", r["ok"] and st_of(db, "crypto")["mode"] == "off"
          and st_of(db, "gold")["mode"] == "live")
    db = fresh()
    f = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    r = await M.flatten("0000", desk="crypto")
    check("flatten with a wrong PIN does nothing", not r["ok"] and BTC in M.D.pos)
    heartbeat(db)
    r = await M.flatten(PIN, desk="crypto")
    check("flatten closes every open position and switches off", r["ok"] and BTC not in M.D.pos
          and trade(db, f)["status"] == "closed" and st_of(db, "crypto")["mode"] == "off")

    # ── 14. off still manages; errors switch off ────────────────────────────────────────────────────
    section("14. Off still manages what is open; three venue errors in a row switch the desk off")
    db = fresh()
    o14 = paper(db, "TL-04", "BTCUSD", 1, 69000.0, 68300.0, 70400.0)
    await cyc(db)
    await M.set_mode("off", desk="crypto")
    advance(600)
    close_paper(db, o14, "time", 69100.0)
    await cyc(db)
    check("switched off, the open trade still closed with its paper exit", trade(db, o14)["status"] == "closed" and BTC not in M.D.pos)
    db = fresh()
    M.D.fail["positions"] = "definite"
    for _ in range(3):
        await cyc(db)
    st, sg = st_of(db, "crypto"), st_of(db, "gold")
    check("three failed position reads in a row: off (each desk counts its own)", st["mode"] == "off" and st["errors_in_row"] >= 3
          and sg["mode"] == "off" and sg["errors_in_row"] >= 3, st.get("switched_off"))

    # ── 15. the read model ──────────────────────────────────────────────────────────────────────────
    section("15. What the page reads")
    s = await M.status()
    check("status (gold, the original routes): mode, keys, PIN, limits, its 102 gold picks (18-24 Nov), notes", s["keys"] and s["pin_set"]
          and s["desk"] == "gold" and len(s["picks"]) == 102 and {p["product"] for p in s["picks"]} == {"XAUTUSD"}
          and s["limits"]["risk_usd"] == 5 and s["limits"]["daily_stop_usd"] == 20 and s["limits"]["leverage"] == 10
          and len(s["notes"]) >= 5)
    c = await M.status("crypto")
    check("status (crypto): TH-05, TL-04, TH-01, TD-02, the eleven of 18 Nov, the seven of 22 Nov and the six of 24 Nov "
          "on BTCUSD, four ether books on ETHUSD, $5 a trade, a $20 daily stop",
          c["desk"] == "crypto" and [p["acct"] for p in c["picks"]] == ["TH-05", "TL-04", "TH-01", "TD-02", "TH-06", "DT-02",
                                                                        "RU-06", "NJ-47", "RU-03", "TH-04", "DT-01", "TH-07",
                                                                        "NJ-27", "PT-04", "SB-04", "DT-05", "TL-03", "RU-04",
                                                                        "KA-01", "DD-01", "TD-04", "TC-04", "DD-04", "BX-02",
                                                                        "NJ-43", "TD-03", "NJ-28", "SC-02", "NJ-37", "DD-04",
                                                                        "DD-03", "BX-01"]
          and {p["product"] for p in c["picks"]} == {"BTCUSD", "ETHUSD"} and c["desk_products"] == ["BTCUSD", "ETHUSD"]
          and [p["acct"] for p in c["picks"] if p["product"] == "ETHUSD"] == ["DD-04", "BX-02", "DD-03", "BX-01"]
          and all(p["mkt"] == p["product"] for p in c["picks"]) and c["limits"]["risk_usd"] == 5
          and c["limits"]["daily_stop_usd"] == 20 and c["picked_at"].startswith("2026-11-14"), [p["acct"] for p in c["picks"]])
    check("an unknown desk is refused", "error" in await M.status("nope") and not (await M.set_mode("off", desk="nope"))["ok"])
    check("the secrets never appear in what the page reads", "s\n" not in str(s) and SALT not in str(s) and "DELTA_API_SECRET" not in str(s))
    # ── 16. two desks ─────────────────────────────────────────────────────────────
    section("16. Two desks: each trades only its own picks and its own product")
    db = fresh()
    b16 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    g16 = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    old = paper(db, "XX-03", "BTCUSD", 1, 69000.0, 68650.0, None, ago=20)     # a book neither desk picks (the gold
    #   desk's former bitcoin picks - TH-01, TH-05, TD-02, RU-04, TD-03 - are all bitcoin-desk picks again by 24 Nov)
    tlg = paper(db, "CP-24", "XAUUSD", 1, 3885.0, 3880.0, 3895.0, ago=20)     # a gold book that is not a pick (TL-04's
                                                                              # gold book became one on 16 Nov)
    await cyc(db)
    check("the bitcoin trade is the crypto desk's, the gold trade the gold desk's",
          [d["_id"] for d in db.live_crypto_trades.docs] == [b16] and [d["_id"] for d in db.live_delta_trades.docs] == [g16],
          ([d["_id"] for d in db.live_crypto_trades.docs], [d["_id"] for d in db.live_delta_trades.docs]))
    check("a bitcoin book that is not a pick (XX-03) and a gold book that is not one are ignored by both desks: no record, "
          "no order",
          trade(db, old) is None and trade(db, tlg) is None and len(M.D.orders) == 2)
    check("one position on each product", M.D.pos[BTC]["size"] > 0 and M.D.pos[GOLD]["size"] > 0)
    # ── 17. a bitcoin trade from before the split ───────────────────────────────────────
    section("17. A live bitcoin trade the gold desk opened before the split is managed by it to its close [without follow_all]")
    db = fresh(follow=False)
    leg = paper(db, "XX-03", "BTCUSD", 1, 69000.0, 68300.0, 70400.0, ago=600)   # a book neither desk picks now
    M.D.pos[BTC] = {"size": 7, "entry": 69000.0}
    db.live_delta_trades.docs.append({"_id": leg, "acct": "XX-03", "mkt": "BTCUSD", "product": "BTCUSD", "name": "earlier pick",
                                      "mode": "live", "side": 1, "status": "open", "contracts": 7, "fill": 69000.0,
                                      "stop": 68300.0, "target": 70400.0, "entry_fee": 0.2, "opened_at": CLOCK[0] - 600,
                                      "created_at": CLOCK[0] - 600, "day": "2026-11-16", "legs": {"stop": "68300"}})
    new = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    check("still open and marked by the gold desk: not closed early, no error", trade(db, leg)["status"] == "open"
          and trade(db, leg).get("mark") and not st_of(db, "gold").get("switched_off"), trade(db, leg))
    check("the crypto desk's bitcoin signal is skipped while that older trade (one bracket on the whole position) is open",
          trade(db, new)["status"] == "skipped" and "older trade" in trade(db, new)["reason"], trade(db, new)["reason"])
    await M.set_mode("off", desk="crypto")
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="crypto")
    check("the crypto desk can go live (the account's BTCUSD is the gold desk's known trade), entering nothing beside it",
          r["ok"], r.get("why"))
    advance(1200)
    M.D.set_price("BTCUSD", 69500.0)
    close_paper(db, leg, "exit_signal", 69500.0)
    await cyc(db)
    check("closed by the gold desk with its paper exit; the account is flat", trade(db, leg)["status"] == "closed"
          and trade(db, leg)["close_reason"] == "paper exit: exit_signal" and BTC not in M.D.pos, trade(db, leg).get("close_reason"))
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="crypto")
    check("then the crypto desk can go live", r["ok"], r.get("why"))
    # ── 18. separate switches and stops ─────────────────────────────────────────────────
    section("18. Each desk has its own switch and its own $20 daily stop [without follow_all]")
    db = fresh(follow=False)
    await M.set_mode("off")                                   # the gold desk only
    g18 = paper(db, "YT-14", "XAUUSD", 1, 3885.0, 3878.0, 3899.0)
    b18 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    check("gold off: its signal is not taken; crypto live: its signal is", trade(db, g18) is None
          and trade(db, b18)["status"] == "open")
    db = fresh(follow=False)
    db.live_crypto_trades.docs.append({"_id": "lost-today", "acct": "TH-05", "mkt": "BTCUSD", "product": "BTCUSD", "mode": "live",
                                       "side": 1, "status": "closed", "day_closed": M._day(), "pnl_usd": -25.0})
    b18b = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68650.0, None)
    g18b = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    await cyc(db)
    check("the crypto desk's daily stop does not stop the gold desk", trade(db, b18b)["status"] == "skipped"
          and "daily loss stop" in trade(db, b18b)["reason"] and trade(db, g18b)["status"] == "open",
          (trade(db, b18b)["reason"], trade(db, g18b)["status"]))
    # ── 19. ten minutes on the bitcoin desk, five on the gold desk ─────────────────────────────────
    section("19. A late signal: both desks copy one seen up to 10 minutes late (15 Nov), never later [without follow_all]")
    db = fresh(follow=False)
    b19 = paper(db, "TL-04", "BTCUSD", -1, 69000.0, 69400.0, 68200.0, ago=406)    # as 03:30 IST on 15 Nov: 6.8 min late
    g19 = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0, ago=406)
    b19x = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68650.0, None, ago=700)
    g19x = paper(db, "YT-14", "XAUUSD", 1, 3885.0, 3878.0, 3899.0, ago=700)
    await cyc(db)
    check("bitcoin seen 6.8 minutes late: copied", trade(db, b19)["status"] == "open", trade(db, b19).get("reason"))
    check("gold seen 6.8 minutes late: copied too (its limit is also 10 minutes from 15 Nov)", trade(db, g19)["status"] == "open",
          trade(db, g19).get("reason"))
    check("seen 11+ minutes late on either desk: skipped (limit 10)", trade(db, b19x)["status"] == "skipped"
          and trade(db, g19x)["status"] == "skipped" and "(limit 10)" in trade(db, b19x)["reason"]
          and "(limit 10)" in trade(db, g19x)["reason"], (trade(db, b19x).get("reason"), trade(db, g19x).get("reason")))
    c, g = await M.status("crypto"), await M.status()
    check("the page reads each desk's own limit", c["limits"]["max_lag_s"] == 600 and g["limits"]["max_lag_s"] == 600
          and c["limits"]["follow_all"] is False and g["limits"]["follow_all"] is False, (c["limits"], g["limits"]))
    # ── 20. the owner's risk a trade ───────────────────────────────────────────────────────────────
    section("20. The risk a trade, $1 to $5, set by the owner with the PIN")
    db = fresh()
    r = await M.set_risk(2, "000000", desk="crypto")
    check("a wrong PIN is refused and counted; the risk stays $5", not r["ok"] and "wrong PIN" in r["why"]
          and (await M.status("crypto"))["limits"]["risk_usd"] == 5 and len(st_of(db, "crypto")["pin_fails"]) == 1, r)
    bad = [await M.set_risk(v, PIN, desk="crypto") for v in (0.5, 5.01, 6, "two", None, float("nan"))]
    check("below $1, above $5 or not a number: refused, before the PIN is even checked", not any(x["ok"] for x in bad)
          and len(st_of(db, "crypto")["pin_fails"]) == 1, [x["why"] for x in bad])
    r = await M.set_risk(2, PIN, desk="crypto")
    c, g = await M.status("crypto"), await M.status()
    check("$2 with the PIN: set on the bitcoin desk only", r["ok"] and c["limits"]["risk_usd"] == 2
          and c["limits"]["risk_cap_usd"] == 5 and c["limits"]["risk_min_usd"] == 1 and g["limits"]["risk_usd"] == 5,
          (r, c["limits"]))
    t20 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    t = trade(db, t20)
    want = math.floor(2 / ((M.D.ask("BTCUSD") - 68650.0) * 0.001))
    check("the next trade is sized for $2: its stop loses at most $2", t["status"] == "open" and t["contracts"] == want
          and t["plan"]["risk_usd"] <= 2 + 1e-9 and t["plan"]["risk_set_usd"] == 2, (t["contracts"], want, t["plan"]))
    advance(60)
    M.D.set_price("BTCUSD", 69350.0)
    close_paper(db, t20, "exit_signal", 69350.0)
    await cyc(db)
    t = trade(db, t20)
    check("its R is counted against the $2 it was sized for", t["status"] == "closed"
          and abs(t["r"] - t["pnl_usd"] / 2) < 0.002, (t.get("r"), t.get("pnl_usd")))
    db = fresh()
    await M.set_risk(1, PIN, desk="crypto")
    w20 = paper(db, "TL-04", "BTCUSD", 1, 69000.0, 67500.0, 72000.0)
    await cyc(db)
    check("$1 and a stop so wide that one contract would lose $1.50: skipped, and the reason says so",
          trade(db, w20)["status"] == "skipped" and "one contract would lose $1.50 at its stop" in trade(db, w20)["reason"]
          and "more than the $1.00 a trade you set" in trade(db, w20)["reason"] and not M.D.orders, trade(db, w20)["reason"])
    # ── 21. the books named to the paper desk ──────────────────────────────────────────────────────
    section("21. The paper desk is told which of its books feed a real-money desk")
    db = fresh()
    M._PRIORITY_SENT = None
    await cyc(db)
    doc = next((d for d in db.premium_meta.docs if d["_id"] == "live_priority"), None)
    check("premium_meta 'live_priority' names every pick of both desks", doc is not None and {
        "TH-05|BTCUSD", "TL-04|BTCUSD", "TH-01|BTCUSD", "TD-02|BTCUSD", "RU-02|XAUTUSD", "CP-23|XAUUSD", "CP-06|XAUUSD",
        "TL-04|XAUTUSD"}
        <= set(doc["books"]), doc)
    db.premium_meta.docs[:] = [d for d in db.premium_meta.docs if d["_id"] != "live_priority"]
    await cyc(db)
    gone = not any(d["_id"] == "live_priority" for d in db.premium_meta.docs)
    advance(601)
    await cyc(db)
    check("not re-written every cycle, but again within 10 minutes if it went missing", gone
          and any(d["_id"] == "live_priority" for d in db.premium_meta.docs))
    # ── 22. one contract a trade (the default from 15 Nov), and the new picks ───────────────────────────
    section("22. One contract a trade, the smallest order, unless the owner picks $1-$5; TD-02 and CP-06 added [without follow_all]")
    db = fresh(follow=False)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)                       # nothing chosen: the default
    c, g = await M.status("crypto"), await M.status()
    check("nothing chosen: both desks trade one contract", c["limits"]["sizing"] == "min" and g["limits"]["sizing"] == "min",
          (c["limits"], g["limits"]))
    b22 = paper(db, "TD-02", "BTCUSD", 1, 69000.0, 68810.0, None)        # TD-02's typical 190-point stop
    g22 = paper(db, "CP-06", "XAUUSD", -1, 3885.0, 3888.6, 3878.0)       # CP-06's typical $3.60 stop
    await cyc(db)
    tb, tg = trade(db, b22), trade(db, g22)
    check("TD-02 (new on the bitcoin desk) goes in as one BTCUSD contract", tb is not None and tb["status"] == "open"
          and tb["contracts"] == 1 and tb["product"] == "BTCUSD" and tb["plan"]["sizing"] == "min"
          and M.D.pos[BTC]["size"] == 1, tb and (tb["status"], tb.get("contracts"), tb.get("reason")))
    check("CP-06 (new on the gold desk) goes in as one XAUTUSD contract", tg is not None and tg["status"] == "open"
          and tg["contracts"] == 1 and tg["product"] == "XAUTUSD" and M.D.pos[GOLD]["size"] == -1,
          tg and (tg["status"], tg.get("contracts"), tg.get("reason")))
    check("a one-contract trade's risk is what that contract loses at its stop: cents on bitcoin, a fraction of a cent on gold",
          abs(tb["plan"]["risk_usd"] - (M.D.ask("BTCUSD") - 68810.0) * 0.001) < 1e-6 and tb["plan"]["risk_set_usd"] == tb["plan"]["risk_usd"]
          and tb["plan"]["risk_usd"] < 0.25 and tg["plan"]["risk_usd"] < 0.01, (tb["plan"], tg["plan"]))
    db = fresh(follow=False)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)
    wide = paper(db, "TL-04", "BTCUSD", 1, 69000.0, 62500.0, 82000.0)    # 6,500 points: one contract would lose $6.50
    await cyc(db)
    check("one contract that would lose more than the $5 cap: skipped, never sent", trade(db, wide)["status"] == "skipped"
          and "more than the $5.00 cap" in trade(db, wide)["reason"] and not M.D.orders, trade(db, wide)["reason"])
    r1 = await M.set_risk("min", "000000", desk="crypto")
    r2 = await M.set_risk(3, PIN, desk="crypto")
    c3 = (await M.status("crypto"))["limits"]
    r3 = await M.set_risk("MIN", PIN, desk="crypto")
    c4 = (await M.status("crypto"))["limits"]
    check("one contract is picked with the PIN like an amount: $3, then back to one contract", not r1["ok"] and r2["ok"]
          and c3["sizing"] == "risk" and c3["risk_usd"] == 3 and r3["ok"] and c4["sizing"] == "min", (r1, r2, c3, r3, c4))
    c, g = await M.status("crypto"), await M.status()
    late = {("TD-02", "BTCUSD"): "2026-11-15", ("CP-06", "XAUUSD"): "2026-11-15", ("TL-04", "XAUTUSD"): "2026-11-16"}
    late.update({(p["acct"], p["mkt"]): "2026-11-18" for p in c["picks"][4:15] + g["picks"][7:30]})   # section 31
    late.update({(p["acct"], p["mkt"]): "2026-11-19" for p in g["picks"][30:50]})                    # section 34
    late.update({(p["acct"], p["mkt"]): "2026-11-22" for p in c["picks"][15:24] + g["picks"][50:99]})  # section 36
    late.update({(p["acct"], p["mkt"]): "2026-11-24" for p in c["picks"][24:] + g["picks"][99:]})     # section 39
    check("the picks: TD-02 joins TH-05, TL-04 and TH-01; CP-06 then TL-04's gold book join the five gold; each new one "
          "carries its own pick time",
          [p["acct"] for p in c["picks"]][:4] == ["TH-05", "TL-04", "TH-01", "TD-02"]
          and [p["acct"] for p in g["picks"]][5:7] == ["CP-06", "TL-04"] and len(g["picks"]) == 102
          and all((p.get("picked_at") or "").startswith(late[(p["acct"], p["mkt"])])
                  for p in c["picks"] + g["picks"] if (p["acct"], p["mkt"]) in late)
          and all(p.get("picked_at") is None for p in c["picks"] + g["picks"] if (p["acct"], p["mkt"]) not in late),
          ([p["acct"] for p in c["picks"]], [p["acct"] for p in g["picks"]]))
    # ── 25. every strategy at once ─────────────────────────────────────────────────────────────────
    section("25. All four bitcoin strategies at once (15 Nov): each its own trade, stop and target; each ends on its own")
    db = fresh()
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)                       # one contract a trade
    t5 = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68650.0, None)
    tl = paper(db, "TL-04", "BTCUSD", -1, 69000.0, 69400.0, 68200.0, ago=25)
    th = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68700.0, None, ago=20)
    td = paper(db, "TD-02", "BTCUSD", 1, 69000.0, 68810.0, None, ago=15)
    await cyc(db)
    ts = [trade(db, x) for x in (t5, tl, th, td)]
    check("four open trades of one contract, each with its own stop on Delta (TL-04 its target too)",
          all(x is not None and x["status"] == "open" and x["contracts"] == 1 and own_leg(x, "stop")["state"] == "pending"
              for x in ts) and own_leg(ts[1], "target")["state"] == "pending", [(x or {}).get("reason") for x in ts])
    check("Delta holds their sum: three longs and a short make +2 contracts", M.D.pos[BTC]["size"] == 2, M.D.pos.get(BTC))
    advance(60)
    M.D.set_price("BTCUSD", 68800.0)                          # through TD-02's stop (68,810) only
    await cyc(db)
    ts = [trade(db, x) for x in (t5, tl, th, td)]
    check("TD-02's own stop filled: it alone closed, the other three stay open with their legs",
          ts[3]["status"] == "closed" and ts[3]["close_reason"] == "venue stop" and all(x["status"] == "open" for x in ts[:3])
          and M.D.pos[BTC]["size"] == 1, [x["status"] for x in ts])
    advance(60)
    close_paper(db, tl, "exit_signal", 68800.0)
    await cyc(db)
    ts = [trade(db, x) for x in (t5, tl, th, td)]
    check("TL-04's paper exit: its stop and target cancelled, one contract bought back, the longs untouched",
          ts[1]["status"] == "closed" and own_leg(ts[1], "stop")["state"] == own_leg(ts[1], "target")["state"] == "cancelled"
          and M.D.pos[BTC]["size"] == 2 and ts[1]["pnl_usd"] > 0 and ts[0]["status"] == ts[2]["status"] == "open",
          (ts[1].get("pnl_usd"), M.D.pos.get(BTC)))
    check("the account matched the trades throughout", not st_of(db, "crypto").get("mismatch_checks"))
    # ── 26. both legs fill in a very fast move ─────────────────────────────────────────────────────
    section("26. Both legs fill before the desk looks (a very fast move): the extra contract is offset at once")
    db = fresh(gold=3885.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)
    g26 = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    await cyc(db)
    advance(60)
    M.D.set_price("XAUTUSD", 3895.5)                          # the target fills ...
    M.D.set_price("XAUTUSD", 3879.0)                          # ... and the stop too, before the next cycle
    held = M.D.pos.get(GOLD, {}).get("size", 0)
    await cyc(db)
    t = trade(db, g26)
    flows = sum((1 if f["side"] == "sell" else -1) * float(f["price"]) * f["size"] * 0.001 - float(f["commission"])
                for f in M.D.fills_ if f["product_id"] == GOLD)
    check("both legs had filled: the account was short one extra contract", held == -1, held)
    check("the desk bought it back at once: flat, the trade closed as 'venue stop and target'", GOLD not in M.D.pos
          and t["status"] == "closed" and t["close_reason"] == "venue stop and target" and "extra_pnl" in t
          and M.D.orders[-1]["side"] == "buy" and M.D.orders[-1]["size"] == 1, (M.D.pos.get(GOLD), t.get("close_reason")))
    check("its result is every fill it caused: entry, both legs and the offset", abs(t["pnl_usd"] - flows) < 1e-3,
          (t["pnl_usd"], round(flows, 6)))
    # ── 27. Delta's positions lag ──────────────────────────────────────────────────────────────────
    section("27. Delta's positions can lag a few seconds: one mismatched check only makes entries wait")
    db = fresh()
    M.D.pos[BTC] = {"size": 1, "entry": 69000.0}             # e.g. a close Delta has not reported yet
    w27 = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    check("one mismatched check: the signal waits, undecided", trade(db, w27) is None
          and st_of(db, "crypto")["mismatch_checks"] == 1)
    M.D.pos.pop(BTC)                                          # Delta catches up
    await cyc(db)
    check("matched again: the count resets and the waiting signal is taken", trade(db, w27)["status"] == "open"
          and st_of(db, "crypto")["mismatch_checks"] == 0, st_of(db, "crypto").get("mismatch"))
    # ── 28. a leg cancelled on Delta by someone else ───────────────────────────────────────────────
    section("28. A leg cancelled on Delta by someone else is put back once; cancelled again, the trade is closed")
    db = fresh()
    x = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    own_leg(trade(db, x), "stop")["state"] = "cancelled"      # cancelled on Delta's own site
    await cyc(db)
    t = trade(db, x)
    check("put back: a new stop at the same level", t["status"] == "open" and t["legs"].get("stop_replaced")
          and own_leg(t, "stop")["state"] == "pending" and float(own_leg(t, "stop")["stop_price"]) == 68650.0, t.get("legs"))
    own_leg(t, "stop")["state"] = "cancelled"
    await cyc(db)
    t = trade(db, x)
    check("cancelled again: the trade is closed at the market, never left unprotected", t["status"] == "closed"
          and "cancelled on Delta again" in t["close_reason"] and BTC not in M.D.pos, t.get("close_reason"))
    # ── 29. a leg that cannot be settled ───────────────────────────────────────────────────────────
    section("29. A leg that cannot be cancelled or read: nothing else is sent; tried again next cycle")
    db = fresh()
    y = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    n_orders = len(M.D.orders)
    M.D.fail.update(cancel="ambiguous", order_lookup="ambiguous")
    advance(60)
    close_paper(db, y, "exit_signal", 69100.0)
    await cyc(db)
    t = trade(db, y)
    check("closing, but no market order sent while its stop is unsettled", t["status"] == "closing"
          and len(M.D.orders) == n_orders and BTC in M.D.pos, (t["status"], len(M.D.orders)))
    M.D.fail.pop("cancel")
    M.D.fail.pop("order_lookup")
    await cyc(db)
    t = trade(db, y)
    check("next cycle: its stop cancelled, then the trade closed at the market", t["status"] == "closed"
          and own_leg(t, "stop")["state"] == "cancelled" and BTC not in M.D.pos, t.get("status"))
    # ── 23. venue errors count only in a row ───────────────────────────────────────────────────────
    section("23. Venue errors count only in a row: a good answer from Delta starts the count again")
    db = fresh()
    M.D.fail["positions"] = "definite"
    for _ in range(2):
        await cyc(db)
    two = st_of(db, "crypto")["errors_in_row"]
    M.D.fail.pop("positions")
    await cyc(db)
    reset = (st_of(db, "crypto")["errors_in_row"], st_of(db, "gold")["errors_in_row"])
    M.D.fail["positions"] = "definite"
    for _ in range(2):
        await cyc(db)
    M.D.fail.pop("positions")
    st, sg = st_of(db, "crypto"), st_of(db, "gold")
    check("two errors, a good read, two more errors: both desks still live (the count is 2, not 4)", two == 2
          and reset == (0, 0) and st["mode"] == "live" and sg["mode"] == "live" and st["errors_in_row"] == 2,
          (two, reset, st["errors_in_row"], st["mode"], sg["mode"]))
    M.D.fail["positions"] = "definite"
    await cyc(db)
    M.D.fail.pop("positions")
    check("a third error in a row still switches the desk off", st_of(db, "crypto")["mode"] == "off"
          and "3 venue errors in a row" in (st_of(db, "crypto").get("switched_off") or ""), st_of(db, "crypto").get("switched_off"))
    # ── 24. no PIN: the owner's choice on 15 Nov ───────────────────────────────────────────────────
    section("24. No PIN (the owner's choice, 15 Nov): the switch, the trade size and flatten work without one")
    M.REQUIRE_PIN = False
    db = fresh(mode="off")
    s = await M.status("crypto")
    check("the page is told no PIN is needed", s["pin_required"] is False and s["keys"], s.get("pin_required"))
    r = await M.set_mode("live", None, None, desk="crypto")
    check("a request without the words REAL MONEY still does not arm a desk", not r["ok"] and "REAL MONEY" in r["why"], r)
    r = await M.set_mode("live", None, "REAL MONEY", desk="crypto")
    check("ON without a PIN, with the words the page sends", r["ok"] and st_of(db, "crypto")["mode"] == "live", r)
    r = await M.set_risk(2, None, desk="crypto")
    check("the trade size without a PIN", r["ok"] and (await M.status("crypto"))["limits"]["risk_usd"] == 2, r)
    advance(60)                                               # a signal after the desk went live (earlier ones are ignored)
    f24 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    held = BTC in M.D.pos
    heartbeat(db)
    r = await M.flatten(None, desk="crypto")
    check("flatten without a PIN: closed, and switched off", held and r["ok"] and BTC not in M.D.pos
          and trade(db, f24)["status"] == "closed" and st_of(db, "crypto")["mode"] == "off",
          (held, r.get("ok"), (trade(db, f24) or {}).get("status")))
    M.REQUIRE_PIN = True
    # ── 26. TL-04's gold book joins the gold desk (16 Nov) ─────────────────────────────────────────
    section("26. TL-04's gold book on the gold desk, its bitcoin book still on the bitcoin desk (16 Nov)")
    db = fresh()
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)                       # one contract a trade
    tg26 = paper(db, "TL-04", "XAUTUSD", -1, 3885.0, 3888.0, 3879.0)      # a $3 gold stop, 2R target
    tb26 = paper(db, "TL-04", "BTCUSD", 1, 69000.0, 68600.0, 69800.0, ago=20)
    await cyc(db)
    g26, b26 = trade(db, tg26), trade(db, tb26)
    check("TL-04's gold signal is a real XAUTUSD order of one contract on the GOLD desk, with its own stop and target",
          g26 is not None and g26["status"] == "open" and g26["product"] == "XAUTUSD" and g26["contracts"] == 1
          and any(d["_id"] == tg26 for d in db.live_delta_trades.docs) and own_leg(g26, "stop") is not None
          and own_leg(g26, "target") is not None, g26 and (g26["status"], g26.get("reason")))
    check("its bitcoin signal stays on the BITCOIN desk, as before", b26 is not None and b26["status"] == "open"
          and b26["product"] == "BTCUSD" and any(d["_id"] == tb26 for d in db.live_crypto_trades.docs),
          b26 and (b26["status"], b26.get("reason")))
    g, c = await M.status(), await M.status("crypto")
    gp = next(p for p in g["picks"] if p["acct"] == "TL-04")
    check("the gold desk lists TL-04's gold book with its own record; the bitcoin desk still lists TL-04 on BTCUSD",
          gp["mkt"] == "XAUTUSD" and gp["product"] == "XAUTUSD" and gp["trades"] == 14 and gp["live"]["open"] == 1
          and [p["mkt"] for p in c["picks"] if p["acct"] == "TL-04"] == ["BTCUSD"], (gp, [p["mkt"] for p in c["picks"]]))
    close_paper(db, tg26, "exit_signal", 3882.0)
    advance(60)
    await cyc(db)
    g26 = trade(db, tg26)
    check("its paper exit closes the real gold trade (legs cancelled first); the bitcoin trade is untouched",
          g26["status"] == "closed" and own_leg(g26, "stop")["state"] == own_leg(g26, "target")["state"] == "cancelled"
          and trade(db, tb26)["status"] == "open", (g26["status"], g26.get("close_reason")))

    # ── 30. Main Control's switch (17 Nov) ──────────────────────────────────────────────────────────
    section("30. Main Control OFF: no new entry on either desk, open trades still managed; flat = the loop skips")
    from app.services import desk_switches as SW

    class Switches:                     # the switch store, in memory (never the real database)
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

    SW.desk_switches_collection = Switches()
    SW._invalidate()
    db = fresh()
    check("the probe counts no open trade on a fresh desk, and ON is ACTIVE",
          await M.open_count() == 0 and await SW.state(M.MODULE) == SW.ACTIVE)
    heartbeat(db)
    r = await SW.gated(M.MODULE, M.cycle)
    check("ON: the gated loop runs every desk as before (the Premium Gold book too, from 24 Nov)",
          set(r) == {"gold", "crypto", "premium_gold"}, r)
    held = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    heartbeat(db)
    await SW.gated(M.MODULE, M.cycle)
    check("ON: a bitcoin signal opens a real trade", (trade(db, held) or {}).get("status") == "open")

    await SW.set_module(M.MODULE, False)
    check("OFF with a trade open: one open trade, STOPPING",
          await M.open_count() == 1 and await SW.state(M.MODULE) == SW.STOPPING)
    advance(60)
    late_btc = paper(db, "TL-04", "BTCUSD", -1, 69000.0, 69400.0, 68400.0, ago=20)
    late_gold = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0, ago=20)
    n_orders = len(M.D.orders)
    heartbeat(db)
    r = await SW.gated(M.MODULE, M.cycle)
    check("OFF: no new entry on either desk, no order sent", trade(db, late_btc) is None and trade(db, late_gold) is None
          and len(M.D.orders) == n_orders and not r["crypto"]["entered"] and not r["gold"]["entered"], r)
    check("OFF: the open bitcoin trade is still managed, and the pass says why it opened nothing",
          held in r["crypto"]["managed"] and "managing" in r["crypto"].get("main_control", ""), r["crypto"])
    check("OFF leaves each desk's own mode as it was", st_of(db, "crypto")["mode"] == st_of(db, "gold")["mode"] == "live")
    check("the drain flag is gone after the pass", not SW.entries_blocked())

    advance(600)
    M.D.set_price("BTCUSD", 69200.0)
    close_paper(db, held, "exit_signal", 69200.0)
    heartbeat(db)
    await SW.gated(M.MODULE, M.cycle)
    t = trade(db, held)
    check("OFF: the paper exit still closes the real trade (its stop cancelled first)",
          t["status"] == "closed" and t["close_reason"] == "paper exit: exit_signal"
          and own_leg(t, "stop")["state"] == "cancelled" and 27 not in M.D.pos, (t["status"], t.get("close_reason")))
    check("flat and OFF: PAUSED", await M.open_count() == 0 and await SW.state(M.MODULE) == SW.PAUSED)
    n_calls = len(M.D.calls)
    r = await SW.gated(M.MODULE, M.cycle)
    check("PAUSED: the pass is skipped, nothing is asked of Delta", r == {} and len(M.D.calls) == n_calls, r)

    await SW.set_module(M.MODULE, True)
    advance(60)
    again = paper(db, "TH-05", "BTCUSD", -1, 69200.0, 69500.0, None)
    heartbeat(db)
    await SW.gated(M.MODULE, M.cycle)
    check("back ON: the desk carries on in its mode and a new signal opens", (trade(db, again) or {}).get("status") == "open")
    check("signals from the OFF stretch still open on paper are copied once back ON, on both desks (19 Nov: they "
          "follow every paper trade)", (trade(db, late_btc) or {}).get("status") == "open"
          and (trade(db, late_gold) or {}).get("status") == "open",
          ((trade(db, late_btc) or {}).get("status"), (trade(db, late_gold) or {}).get("status")))

    async def _down():
        raise RuntimeError("database down")
    real_db = M._db
    M._db = lambda: SimpleNamespace(live_delta_trades=SimpleNamespace(count_documents=lambda q: _down()),
                                    live_crypto_trades=db.live_crypto_trades)
    await SW.set_module(M.MODULE, False)
    check("a probe that cannot answer reads STOPPING (keep managing), never PAUSED", await SW.state(M.MODULE) == SW.STOPPING)
    M._db = real_db
    await SW.set_module(M.MODULE, True)

    # ── 31. 18 Nov: more Premium picks, and the Gold Desk's H1 templates as a second source ─────────
    section("31. 18 Nov: more Premium picks on both desks; six Gold Desk H1 templates on the gold desk")
    gp, cp = M.DESKS["gold"].picks, M.DESKS["crypto"].picks
    gk, ck = {(p.acct, p.mkt) for p in gp}, {(p.acct, p.mkt) for p in cp}
    check("the gold desk: the 7 before, 13 + 4 Premium gold books, 6 H1 templates and the Factory top 20 (50, then 49 "
          "more on 22 Nov: section 36, and 3 on 24 Nov: section 39); the bitcoin desk: 4 + 5 + 6 (15, then 9, then 8)",
          len(gp) == len(gk) == 102 and len(cp) == len(ck) == 32
          and [p.acct for p in gp if p.src == M.GOLD_SF][:20] == ["SF0181", "SF0020", "SF0245", "SF0013", "SF0182", "SF0331",
                                                                  "SF0346", "SF0213", "SF0324", "SF0022", "SF0219", "SF0497",
                                                                  "SF0021", "SF0251", "SF0370", "SF0542", "SF0205", "SF0228",
                                                                  "SF0426", "SF0243"]
          and {("BB-11", "XAUUSD"), ("PT-04", "XAUTUSD"), ("RU-03", "XAUTUSD"), ("SB-06", "XAUUSD"), ("RU-04", "XAUTUSD"),
               ("PR-12", "XAUTUSD"), ("TP-05", "XAUTUSD"), ("DT-01", "XAUTUSD"), ("DT-03", "XAUTUSD"), ("CD-02", "XAUTUSD"),
               ("CP-02", "XAUUSD"), ("RU-05", "XAUTUSD"), ("FZ-02", "XAUTUSD"), ("BG-01", "XAUUSD"), ("JR-04", "XAUTUSD"),
               ("TD-04", "XAUTUSD"), ("TC-11", "XAUTUSD")} <= gk
          and {("TH-06", "BTCUSD"), ("DT-02", "BTCUSD"), ("RU-06", "BTCUSD"), ("NJ-47", "BTCUSD"), ("RU-03", "BTCUSD"),
               ("TH-04", "BTCUSD"), ("DT-01", "BTCUSD"), ("TH-07", "BTCUSD"), ("NJ-27", "BTCUSD"), ("PT-04", "BTCUSD"),
               ("SB-04", "BTCUSD")} <= ck
          and sorted(p.template for p in gp[:50] if p.src == M.GOLD_H1) == sorted(
              ["ema_ribbon", "round_number_break", "donchian_fast", "pivot_break", "donchian_slow", "keltner_break"])
          and not any(p.src == M.GOLD_H1 for p in cp)
          and [(p.acct, p.mkt) for p in gp + cp if p.acct == "DD-03"] == [("DD-03", "ETHUSD")]    # its ether book, 24 Nov
          and [(p.acct, p.mkt) for p in gp + cp if p.acct == "DD-04"] == [("DD-04", "ETHUSD"),
                                                                          ("DD-04", "BTCUSD")],  # 22 Nov, 24 Nov
          (len(gp), len(cp)))
    check("every 18 Nov pick's record is as of its batch (22:00 or 23:50 IST); the earlier picks keep theirs, untouched",
          all(p.picked_at == M.NEW_PICKED_AT for p in gp[7:20] + gp[24:30] + cp[4:9])
          and all(p.picked_at == M.NEW_PICKED_AT_3 and p.template == p.acct for p in gp[30:50])
          and all(p.picked_at == M.NEW_PICKED_AT_2 for p in gp[20:24] + cp[9:15])
          and [p.acct for p in gp[20:24]] == ["BG-01", "JR-04", "TD-04", "TC-11"]
          and [p.picked_at for p in cp[:4]] == [None, None, None, "2026-11-15T13:40:00+05:30"]
          and gp[6].picked_at == "2026-11-16T23:33:00+05:30" and (gp[0].trades, gp[0].sum_r) == (5, 2.73)
          and next(p for p in gp if p.acct == "H1-RIB").trades == 12 and next(p for p in cp if p.acct == "TH-06").trades == 9)
    naive = datetime(2026, 11, 18, 16, 3, 18)
    one = M._h1_as_paper({"position_id": "x", "strategy_template": "ema_ribbon", "side": "SELL", "entry_price": 3750.48,
                          "stoploss": 3815.35, "target": 3620.75, "status": "CLOSED", "opened_at": naive,
                          "exit_price": 3815.35, "exit_reason": "stoploss", "qty": 0.296},
                         next(p for p in gp if p.acct == "H1-RIB"))
    check("an H1 position read as a paper trade: id H1|<position>, SELL = -1, a naive time is UTC, 'stoploss' = 'stop'",
          one["_id"] == "H1|x" and one["side"] == -1 and one["entry_t"] == naive.replace(tzinfo=UTC).timestamp()
          and one["reason"] == "stop" and not one["open"] and one["acct"] == "H1-RIB" and one["mkt"] == "XAUTUSD", one)

    db = fresh(gold=3885.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)                       # one contract a trade
    gpos, gstate = Coll("gpos"), Coll("gstate")
    utc_naive = lambda s: datetime.fromtimestamp(s, UTC).replace(tzinfo=None)   # noqa: E731 - how the db stores it
    gstate.docs.append({"_id": "delta", "last_run_at": utc_naive(CLOCK[0])})
    reads = []

    class _Positions:
        def find(self, q=None, projection=None):
            reads.append(M._CUR.get())
            return gpos.find(q, projection)
    M._h1_coll, M._h1_state_coll = (lambda: _Positions()), (lambda: gstate)

    def h1pos(pid, template, side, entry, stop, target, ago=30, h1=True):
        gpos.docs.append({"position_id": pid, "venue": "delta", "h1": h1, "symbol": "XAUTUSD", "strategy_template": template,
                          "side": side, "entry_price": entry, "stoploss": stop, "target": target, "qty": 0.296,
                          "status": "OPEN", "opened_at": utc_naive(CLOCK[0] - ago), "exit_price": None, "exit_reason": None})
        return "H1|" + pid

    def h1_end(pid, status, reason, px):
        for d in gpos.docs:
            if d["position_id"] == pid:
                d.update(status=status, exit_reason=reason, exit_price=px, closed_at=utc_naive(CLOCK[0]))
                if status == "VOID":
                    d["void"] = True

    h_old = h1pos("p0", "ema_ribbon", "BUY", 3885.0, 3882.0, 3891.0, ago=7200)   # before the desk's start
    h_rib = h1pos("p1", "ema_ribbon", "SELL", 3885.0, 3888.0, 3879.0)
    h_atr = h1pos("p2", "atr_thrust", "BUY", 3885.0, 3882.0, 3891.0)              # an H1 template not picked
    h_rec = h1pos("p3", "pivot_break", "BUY", 3885.0, 3882.0, 3891.0, h1=False)   # not the H1 record
    bb = paper(db, "BB-11", "XAUUSD", 1, 3885.0, 3882.0, 3891.0, ago=20)
    ru6 = paper(db, "RU-06", "BTCUSD", -1, 69000.0, 69400.0, 68400.0, ago=25)
    M._PRIORITY_SENT = None
    r = await cyc(db)
    t = trade(db, h_rib)
    check("an H1 template's new position is a real XAUTUSD order of one contract on the gold desk, with its own stop and "
          "target at the Gold Desk's levels", t is not None and t["status"] == "open" and t["product"] == "XAUTUSD"
          and t["side"] == -1 and t["contracts"] == 1 and t["acct"] == "H1-RIB"
          and any(d["_id"] == h_rib for d in db.live_delta_trades.docs)
          and float(own_leg(t, "stop")["stop_price"]) == 3888.0 and float(own_leg(t, "target")["stop_price"]) == 3879.0,
          t and (t["status"], t.get("reason")))
    check("not copied: an H1 template not picked, a position outside the H1 record",
          trade(db, h_atr) is None and trade(db, h_rec) is None)
    check("copied: an H1 position still open from before the desk's start (19 Nov: every open one)",
          (trade(db, h_old) or {}).get("status") == "open", (trade(db, h_old) or {}).get("reason"))
    check("the new Premium picks trade too: BB-11's gold book on the gold desk, RU-06 on the bitcoin desk",
          (trade(db, bb) or {}).get("product") == "XAUTUSD" and trade(db, bb)["status"] == "open"
          and (trade(db, ru6) or {}).get("product") == "BTCUSD" and trade(db, ru6)["status"] == "open"
          and any(d["_id"] == ru6 for d in db.live_crypto_trades.docs))
    check("only the gold desk asks the Gold Desk; the bitcoin desk never does", reads and set(reads) == {"gold"}, reads)
    doc = next((d for d in db.premium_meta.docs if d["_id"] == "live_priority"), None)
    check("the paper desk is told the new Premium books, never the H1 ones (they are not its books)", doc is not None
          and {"BB-11|XAUUSD", "PR-12|XAUTUSD", "TH-06|BTCUSD", "RU-03|BTCUSD", "RU-03|XAUTUSD"} <= set(doc["books"])
          and not any(b.startswith("H1-") for b in doc["books"]), doc)

    class _Down:
        def find(self, *a, **k):
            raise RuntimeError("main database down")
    M._h1_coll = lambda: _Down()
    advance(400)
    fz = paper(db, "FZ-02", "XAUTUSD", 1, 3885.0, 3882.0, 3891.0, ago=10)
    r1 = await cyc(db)
    advance(400)
    r2 = await cyc(db)
    t = trade(db, h_rib)
    check("the Gold Desk cannot be read: its H1 trade waits, open, never counted as disappeared (two passes, 13 minutes)",
          t["status"] == "open" and not t.get("paper_missing_since") and "could not be read" in r1["gold"].get("gold_desk", "")
          and "could not be read" in r2["gold"].get("gold_desk", ""), (t["status"], t.get("paper_missing_since"), r1["gold"]))
    check("... while the gold desk's Premium books still trade, and the bitcoin desk is untouched",
          (trade(db, fz) or {}).get("status") == "open" and "gold_desk" not in r1["crypto"], (trade(db, fz) or {}).get("reason"))
    M._h1_coll = lambda: _Positions()
    h1_end("p1", "CLOSED", "max_hold", 3884.0)
    advance(60)
    gstate.docs[0]["last_run_at"] = utc_naive(CLOCK[0])
    await cyc(db)
    t = trade(db, h_rib)
    check("read again, the closed H1 position closes the real trade (legs cancelled first)", t["status"] == "closed"
          and t["close_reason"] == "paper exit: max_hold" and own_leg(t, "stop")["state"] == "cancelled"
          and own_leg(t, "target")["state"] == "cancelled", (t["status"], t.get("close_reason")))

    gstate.docs[0]["last_run_at"] = utc_naive(CLOCK[0] - 1500)           # the Gold Desk silent for 25 minutes
    h_dcf = h1pos("p4", "donchian_fast", "BUY", 3885.0, 3882.0, 3891.0, ago=10)
    cp2 = paper(db, "CP-02", "XAUUSD", 1, 3885.0, 3882.0, 3891.0, ago=10)
    await cyc(db)                                                       # the paper desk itself is fresh
    check("each source has its own clock: a silent Gold Desk holds H1 entries only (they wait)",
          trade(db, h_dcf) is None and "the Gold Desk has not updated" in M._WAITING["gold"][h_dcf]["why"]
          and (trade(db, cp2) or {}).get("status") == "open", (M._WAITING["gold"].get(h_dcf), (trade(db, cp2) or {}).get("reason")))
    advance(1500)
    gstate.docs[0]["last_run_at"] = utc_naive(CLOCK[0])
    h_piv = h1pos("p5", "pivot_break", "BUY", 3885.0, 3882.0, 3891.0, ago=10)
    dt1 = paper(db, "DT-01", "XAUTUSD", 1, 3885.0, 3882.0, 3891.0, ago=10)
    await M.cycle()                                                     # no paper-desk heartbeat: it is 25 minutes old
    check("... and a silent paper desk holds Premium entries only; the waiting H1 copy goes in once its desk is back",
          (trade(db, h_piv) or {}).get("status") == "open" and (trade(db, h_dcf) or {}).get("status") == "open"
          and trade(db, dt1) is None and "the paper desk has not updated" in M._WAITING["gold"][dt1]["why"],
          ((trade(db, h_piv) or {}).get("reason"), M._WAITING["gold"].get(dt1)))
    h1_end("p5", "VOID", None, None)
    advance(60)
    gstate.docs[0]["last_run_at"] = utc_naive(CLOCK[0])
    await cyc(db)
    check("a position the Gold Desk voids closes its real trade", trade(db, h_piv)["status"] == "closed"
          and trade(db, h_piv)["close_reason"] == "paper exit: void", trade(db, h_piv).get("close_reason"))
    g = await M.status()
    pr = next(p for p in g["picks"] if p["acct"] == "H1-RIB")
    check("the page lists the H1 template with its source, its own record and its real trades",
          pr["src"] == "gold_h1" and pr["template"] == "ema_ribbon" and pr["trades"] == 12 and pr["live"]["trades"] == 1
          and pr["backtest"].startswith("pooled only") and len(g["picks"]) == 102, pr)

    # ── 32. the page's paper view: each strategy's own paper trades beside what the desk did with them ─────
    section("32. The paper view: each strategy's paper record and open trade now, its latest signals and the desk's decision")
    db = fresh(gold=3885.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)
    gpos, gstate = Coll("gpos32"), Coll("gstate32")
    gstate.docs.append({"_id": "delta", "last_run_at": utc_naive(CLOCK[0])})
    M._h1_coll, M._h1_state_coll = (lambda: gpos), (lambda: gstate)

    def closed_paper(acct, mkt, side, r, ago, qty=1.0):
        tid = paper(db, acct, mkt, side, 3885.0, 3882.0 if side > 0 else 3888.0, 3891.0 if side > 0 else 3879.0, ago=ago,
                    qty=qty)
        close_paper(db, tid, "target" if r > 0 else "stop", 3891.0 if r > 0 else 3882.0)
        for d in db.premium_trades.docs:
            if d["_id"] == tid:
                d["r_net"] = r
        return tid
    c_win = closed_paper("CP-23", "XAUUSD", 1, 1.5, ago=7200)              # before the desk's start (since = 1 h ago)
    c_loss = closed_paper("CP-23", "XAUUSD", 1, -1.0, ago=6000)
    c_unsized = closed_paper("CP-23", "XAUUSD", 1, 5.0, ago=5000, qty=0.0)  # not sized on paper: not a trade of the record
    c_other = closed_paper("ZZ-99", "XAUUSD", 1, 3.0, ago=4000)             # not a pick
    tl = paper(db, "TL-04", "XAUTUSD", -1, 3885.0, 3888.0, 3879.0, ago=30, last=3884.0, unit=3.0)   # open, after the start
    gpos.docs.append({"position_id": "r1", "venue": "delta", "h1": True, "symbol": "XAUTUSD", "strategy_template": "ema_ribbon",
                      "side": "BUY", "entry_price": 3885.0, "stoploss": 3882.0, "target": 3891.0, "qty": 0.296,
                      "status": "CLOSED", "opened_at": utc_naive(CLOCK[0] - 9000), "closed_at": utc_naive(CLOCK[0] - 8000),
                      "exit_price": 3891.0, "exit_reason": "target", "realized_pnl": 1.776})
    gpos.docs.append({"position_id": "d1", "venue": "delta", "h1": True, "symbol": "XAUTUSD",
                      "strategy_template": "donchian_fast", "side": "SELL", "entry_price": 3890.0, "stoploss": 3896.0,
                      "target": 3878.0, "qty": 0.296, "status": "OPEN", "opened_at": utc_naive(CLOCK[0] - 9500),
                      "ltp": 3887.0, "exit_price": None, "exit_reason": None})
    await cyc(db)
    g = await M.status()
    by = {f"{p['acct']}|{p['mkt']}": p for p in g["picks"]}
    cp23, tlp = by["CP-23|XAUUSD"]["paper"], by["TL-04|XAUTUSD"]["paper"]
    check("a pick's paper record now: its sized closed trades (wins, net R); unsized and other books' trades left out",
          cp23["trades"] == 2 and cp23["wins"] == 1 and cp23["sum_r"] == 0.5 and cp23["open"] == [], cp23)
    check("... and its open paper trade, marked: TL-04 short from 3,885, last 3,884, risk 3 a unit = +0.33R",
          len(tlp["open"]) == 1 and tlp["open"][0]["side"] == -1 and tlp["open"][0]["r_now"] == 0.33 and tlp["trades"] == 0, tlp)
    rib, dcf = by["H1-RIB|XAUTUSD"]["paper"], by["H1-DCF|XAUTUSD"]["paper"]
    check("the H1 templates from the Gold Desk: closed in R (1.776 / (3 x 0.296) = 2R), open marked at its ltp (+0.5R)",
          rib["trades"] == 1 and rib["wins"] == 1 and abs(rib["sum_r"] - 2.0) < 1e-9 and len(dcf["open"]) == 1
          and dcf["open"][0]["r_now"] == 0.5, (rib, dcf))
    check("a pick with no paper trade yet reads an empty record, not a missing one",
          by["PR-12|XAUTUSD"]["paper"] == {"trades": 0, "wins": 0, "sum_r": 0.0, "open": [], "last_t": None})
    sig = {x["id"]: x for x in g["signals"]}
    order = [x["entry_t"] for x in g["signals"]]
    check("the latest signals, newest first: TL-04's copied (open on the desk), CP-23's before the desk was switched on",
          order == sorted(order, reverse=True) and sig[tl]["desk"]["status"] == "open" and sig[tl]["open"]
          and sig[c_win]["desk"]["status"] == "before" and sig[c_win]["r"] == 1.5 and sig[c_loss]["r"] == -1.0
          and c_unsized not in sig and c_other not in sig and "H1|r1" in sig and sig["H1|r1"]["src"] == "gold_h1",
          [(x["acct"], x["desk"]["status"]) for x in g["signals"]])
    check("the view says how fresh both sources are", g["paper_view"]["paper_age_s"] is not None
          and g["paper_view"]["gold_desk_age_s"] is not None and g["paper_view"]["gold_desk_age_s"] < 60, g["paper_view"])
    closed_paper("CP-23", "XAUUSD", 1, 2.0, ago=3000)
    advance(10)
    again = next(p for p in (await M.status())["picks"] if p["acct"] == "CP-23")["paper"]["trades"]
    advance(31)
    later = next(p for p in (await M.status())["picks"] if p["acct"] == "CP-23")["paper"]["trades"]
    check("read at most every 30 s a desk (the page polls every 15 s): the new trade shows on the next read after that",
          again == 2 and later == 3, (again, later))
    c = await M.status("crypto")
    check("the bitcoin desk's view is its own: no Gold Desk, no gold signals", "gold_desk_age_s" not in (c["paper_view"] or {"x": 1})
          and all(x["mkt"] == "BTCUSD" for x in c["signals"]), c["paper_view"])

    class _Broken:
        def find(self, *a, **k):
            raise RuntimeError("paper database down")
    good = db.premium_trades
    db.premium_trades = _Broken()
    advance(31)
    g = await M.status()
    check("the paper side unreadable: the page still gets the desk, its picks without a paper record, no signals",
          g.get("mode") == "live" and len(g["picks"]) == 102 and all(p["paper"] is None for p in g["picks"])
          and g["signals"] is None and g["paper_view"] is None)
    db.premium_trades = good
    db2 = fresh(mode="off")
    paper(db2, "TH-05", "BTCUSD", 1, 69000.0, 68650.0, None, ago=30)
    c = await M.status("crypto")
    check("a desk that is off: its strategies' new paper trades read 'this desk is off'",
          c["signals"] and c["signals"][0]["desk"]["status"] == "off", c["signals"] and c["signals"][0]["desk"])


    # ── 33. 19 Nov: the gold desk follows EVERY paper trade ─────────────────────────────────────────
    section("33. 19 Nov: the desks copy every open paper trade, however late or far; a copy waits, never given up")
    db = fresh(gold=3885.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)                       # one contract a trade, as on the real desks
    old = paper(db, "RU-02", "XAUTUSD", -1, 3900.0, 3920.0, 3870.0, ago=7200)   # 2 h old, before the switch-on, 75% away
    old_shut = paper(db, "YT-14", "XAUUSD", 1, 3880.0, 3875.0, 3890.0, ago=7000)
    close_paper(db, old_shut, "target", 3890.0)                 # closed before the switch-on: nothing to copy
    beyond = paper(db, "CP-05", "XAUUSD", -1, 3895.0, 3900.0, 3886.0, ago=20)    # short; the price is already past its target
    tight = paper(db, "DR-01", "XAUTUSD", 1, 3885.5, 3884.99, 3890.0, ago=20)   # long; the price 2.5 ticks over its stop
    ladder = paper(db, "PR-12", "XAUTUSD", 1, 3921.15, None, None, ago=7 * 86400, unit=392.1)   # PR-12: no stop, no target
    b_old = paper(db, "TL-04", "BTCUSD", -1, 69000.0, 69400.0, 68400.0, ago=7200)
    b_nostop = paper(db, "TH-05", "BTCUSD", 1, 69000.0, None, None, ago=20)
    r = await cyc(db)
    t = trade(db, old)
    bid = M.D.bid("XAUTUSD")
    check("a 2-hour-old paper trade from before the switch-on, 75% of its risk away: copied at today's price, one "
          "contract, with the paper's own stop and target on Delta", t is not None and t["status"] == "open"
          and t["contracts"] == 1 and abs(t["fill"] - bid) < 1e-6 and float(own_leg(t, "stop")["stop_price"]) == 3920.0
          and float(own_leg(t, "target")["stop_price"]) == 3870.0 and t.get("late_s", 0) >= 7200,
          t and (t.get("status"), t.get("reason"), t.get("fill")))
    check("a paper trade that closed before the switch-on is not copied", trade(db, old_shut) is None)
    wb, wt = M._WAITING["gold"].get(beyond), M._WAITING["gold"].get(tight)
    check("the price past a target, or within reach of a stop: the copy WAITS (no record, no order), with the reason",
          trade(db, beyond) is None and trade(db, tight) is None and wb and "not inside the stop and the target" in wb["why"]
          and wt and "not inside" in wt["why"] and r["gold"].get("waiting") == 2, (wb, wt, r["gold"]))
    check("waiting copies are counted, not listed as decisions (the loop logs only real ones)",
          not any(str(x["result"]).startswith("waiting") for x in r["gold"]["entered"]), r["gold"]["entered"])
    t = trade(db, ladder)
    sl = own_leg(t, "stop")
    want_stop = round(M.D.ask("XAUTUSD") * (1 - M.GUARD_STOP_FRAC), 2)
    check("PR-12 (no stop on paper): copied with a protective stop 3% under the price on Delta, no target",
          t is not None and t["status"] == "open" and t.get("guard_stop") and t.get("paper_stop", 1) is None
          and sl is not None and abs(float(sl["stop_price"]) - want_stop) <= 0.01 and t["legs"]["target_id"] is None,
          t and (t.get("status"), t.get("reason"), sl))
    tb, tn = trade(db, b_old), trade(db, b_nostop)
    check("the bitcoin desk follows every paper trade too: its 2-hour-old one is copied with the paper's levels; one "
          "without a stop gets the protective stop 3% away", tb is not None and tb["status"] == "open"
          and float(own_leg(tb, "stop")["stop_price"]) == 69400.0 and tn is not None and tn["status"] == "open"
          and tn.get("guard_stop") and abs(float(own_leg(tn, "stop")["stop_price"]) - M.D.ask("BTCUSD") * 0.97) <= 0.5,
          ((tb or {}).get("reason"), (tn or {}).get("reason")))
    check("Delta's gold position is the sum of the copies (a short and a long: flat)", GOLD not in M.D.pos
          and trade(db, old)["side"] + trade(db, ladder)["side"] == 0, M.D.pos.get(GOLD))
    g, c = await M.status(), await M.status("crypto")
    sig = {x["id"]: x for x in g["signals"]}
    check("the page: a waiting copy reads 'waiting' with its reason; the old closed one 'before'; the limits say "
          "follow_all on gold only", sig[beyond]["desk"]["status"] == "waiting" and "not inside" in sig[beyond]["desk"]["why"]
          and sig[old_shut]["desk"]["status"] == "before" and sig[old]["desk"]["status"] == "open"
          and g["limits"]["follow_all"] is True and c["limits"]["follow_all"] is True and g["limits"]["waiting"] == 2
          and g["limits"]["daily_stop_on"] is False and c["limits"]["contract_cap_on"] is False
          and all(any("EVERY signal becomes a real position" in n for n in x["notes"]) for x in (g, c)),
          [(x["acct"], x["desk"]["status"]) for x in g["signals"]])

    advance(60)
    M.D.set_price("XAUTUSD", 3890.0)                            # back inside CP-05's levels; DR-01's paper hits its target
    close_paper(db, tight, "target", 3890.0)
    await cyc(db)
    t = trade(db, beyond)
    check("the price back inside: the waiting copy goes in at once, with the paper's stop and target",
          t is not None and t["status"] == "open" and float(own_leg(t, "target")["stop_price"]) == 3886.0, t and t.get("reason"))
    check("a waiting copy whose paper trade closes is recorded as closed on paper before it could be copied, and stops "
          "waiting", trade(db, tight)["status"] == "skipped" and trade(db, tight)["reason"]
          == "closed on paper before it could be copied" and not M._WAITING["gold"], (trade(db, tight), M._WAITING["gold"]))

    real_day = M._day_pnl

    async def _lost(db_, mode, positions):
        return -25.0
    M._day_pnl = _lost
    advance(60)
    g_day = paper(db, "TL-04", "XAUTUSD", 1, 3890.0, 3886.0, 3898.0, ago=10)
    b_day = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None, ago=10)
    await cyc(db)
    check("$25 down on the day: no daily stop on either desk (the owner, 19 Nov), both copies go in at once",
          (trade(db, g_day) or {}).get("status") == "open" and (trade(db, b_day) or {}).get("status") == "open",
          ((trade(db, g_day) or {}).get("reason"), (trade(db, b_day) or {}).get("reason")))
    M._day_pnl = real_day

    advance(60)
    many = [paper(db, a, m, 1, 3890.0, 3886.0, 3898.0, ago=10) for a, m in (("RU-03", "XAUTUSD"), ("FZ-02", "XAUTUSD"),
                                                                             ("DT-03", "XAUTUSD"))]
    M.D.fail["wallet"] = "definite"
    r = await cyc(db)
    sg = st_of(db, "gold")
    check("the wallet unreadable: three copies wait, ONE venue error is counted for the pass, the desk stays live",
          all(trade(db, x) is None for x in many) and r["gold"].get("waiting") == 3 and sg["errors_in_row"] == 1
          and sg["mode"] == "live", (r["gold"], sg.get("errors_in_row"), sg.get("mode")))
    M.D.fail.pop("wallet")
    advance(30)
    await cyc(db)
    check("... and all three go in on the next good pass", all((trade(db, x) or {}).get("status") == "open" for x in many)
          and st_of(db, "gold")["errors_in_row"] == 0)


    # ── 34. 19 Nov (later): every signal on both desks at one contract; the Gold Desk Strategy Factory top 20 ─────────
    section("34. Both desks: every signal at one contract, no cap, margin waits; the Factory top 20 as a third source")
    db = fresh(gold=3885.0, btc=69150.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)                       # one contract a trade
        coll.docs[0]["wallet_at"] = CLOCK[0]                   # the desk's own 5-minute wallet refresh is not due
    sfp, sfs = Coll("sfp34"), Coll("sfs34")
    sfs.docs.append({"_id": "cycle:gold", "at": utc_naive(CLOCK[0])})
    M._sf_coll, M._sf_state_coll = (lambda: sfp), (lambda: sfs)

    def sf_pos(pid, sid, side, entry, stop, target, ago=30, status="OPEN", **kw):
        sfp.docs.append({"position_id": pid, "desk": "gold", "strategy_id": sid, "strategy_name": f"{sid} name",
                         "symbol": "XAUTUSD", "signal_side": side, "side": side, "kind": "perp", "entry_px": entry,
                         "under_entry": entry, "stop": stop, "target": target, "capital_deployed": 1111.11,
                         "status": status, "opened_at": utc_naive(CLOCK[0] - ago), "closed_at": None, "exit_px": None,
                         "exit_reason": None, "realized_pnl": None, "under_ltp": entry, "pattern": "p", **kw})
        return "SF|" + pid

    def sf_end(pid, reason, px, pnl):
        for d in sfp.docs:
            if d["position_id"] == pid:
                d.update(status="CLOSED", exit_reason=reason, exit_px=px, realized_pnl=pnl, closed_at=utc_naive(CLOCK[0]))

    late_far = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, None, ago=700)   # 11+ min late, 50% of its risk away
    wide = paper(db, "TL-04", "BTCUSD", 1, 69000.0, 62000.0, None, ago=20)        # a stop 10% away: past liquidation
    s1 = sf_pos("a1", "SF0181", "SELL", 3885.0, 3890.0, 3875.0)                    # a new Factory position
    s_old = sf_pos("a2", "SF0020", "BUY", 3880.0, 3870.0, 3900.0, ago=7200)        # open since before the switch-on
    s_shut = sf_pos("a3", "SF0245", "BUY", 3880.0, 3875.0, 3890.0, ago=6000, status="CLOSED", exit_px=3890.0,
                    exit_reason="target", realized_pnl=2.86, closed_at=utc_naive(CLOCK[0] - 5000))
    s_other = sf_pos("a4", "SF0999", "BUY", 3885.0, 3880.0, 3895.0)                # not one of the 20
    r = await cyc(db)
    t = trade(db, late_far)
    check("bitcoin seen 11+ minutes late and 50% of its risk away: copied at today's price with the paper's stop",
          t is not None and t["status"] == "open" and abs(t["fill"] - M.D.ask("BTCUSD")) < 1e-6
          and float(own_leg(t, "stop")["stop_price"]) == 68700.0, t and (t.get("status"), t.get("reason")))
    t = trade(db, wide)
    ask = M.D.ask("BTCUSD")
    check("a paper stop 10% away (past the ~9.5% at which Delta liquidates at 10x): copied, its stop pulled in to 7% on "
          "Delta, the paper's kept on the trade", t is not None and t["status"] == "open" and t.get("stop_capped")
          and t.get("paper_stop") == 62000.0 and abs(float(own_leg(t, "stop")["stop_price"]) - ask * 0.93) <= 0.5,
          t and (t.get("status"), t.get("reason"), t.get("stop")))
    t = trade(db, s1)
    check("a Strategy Factory position of a picked strategy: one real XAUTUSD contract, short, with the tab's own stop "
          "and target on Delta", t is not None and t["status"] == "open" and t["acct"] == "SF0181" and t["side"] == -1
          and t["contracts"] == 1 and t["product"] == "XAUTUSD" and float(own_leg(t, "stop")["stop_price"]) == 3890.0
          and float(own_leg(t, "target")["stop_price"]) == 3875.0, t and (t.get("status"), t.get("reason")))
    check("... one open since before the switch-on is copied too; a closed one and a strategy outside the 20 are not",
          (trade(db, s_old) or {}).get("status") == "open" and trade(db, s_shut) is None and trade(db, s_other) is None,
          (trade(db, s_old) or {}).get("reason"))
    g = await M.status()
    by = {p["acct"]: p for p in g["picks"]}
    sfr = by["SF0181"]
    check("the page: the Factory pick with its source, strategy, record and real trade; its paper side from the tab",
          sfr["src"] == M.GOLD_SF and sfr["template"] == "SF0181" and sfr["trades"] == 42
          and sfr["backtest"].startswith("factory only") and sfr["live"]["open"] == 1
          and len(sfr["paper"]["open"]) == 1 and by["SF0245"]["paper"]["trades"] == 1
          and abs(by["SF0245"]["paper"]["sum_r"] - 2.86 / (5.0 * 1111.11 / 3880.0)) < 0.01
          and g["paper_view"].get("factory_age_s") is not None
          and any(x["src"] == M.GOLD_SF and x["id"] == s1 and x["desk"]["status"] == "open" for x in g["signals"]),
          (sfr["paper"], by["SF0245"]["paper"], g["paper_view"]))

    advance(60)
    sfs.docs[0]["at"] = utc_naive(CLOCK[0])
    M.D.set_price("XAUTUSD", 3880.0)
    sf_end("a1", "max_hold", 3880.0, 1.20)                     # the tab's hold limit closes it
    await cyc(db)
    t = trade(db, s1)
    check("the tab closes its position (hold limit): the real trade is closed, its legs cancelled first",
          t["status"] == "closed" and t["close_reason"] == "paper exit: max_hold" and own_leg(t, "stop")["state"] == "cancelled"
          and own_leg(t, "target")["state"] == "cancelled", (t["status"], t.get("close_reason")))

    class _SfDown:
        def find(self, *a, **k):
            raise RuntimeError("factory store down")
    M._sf_coll = lambda: _SfDown()
    advance(60)
    pr = paper(db, "DT-01", "XAUTUSD", 1, 3880.0, 3876.0, 3888.0, ago=10)
    r = await cyc(db)
    check("the Factory's store unreadable: its open copy waits, never closed; Premium copies still go in",
          trade(db, s_old)["status"] == "open" and "could not be read" in r["gold"].get("factory", "")
          and (trade(db, pr) or {}).get("status") == "open", (r["gold"].get("factory"), (trade(db, pr) or {}).get("reason")))
    M._sf_coll = lambda: sfp
    advance(60)
    sfs.docs[0]["at"] = utc_naive(CLOCK[0] - 1500)            # the tab silent for 25 minutes
    s_new = sf_pos("a5", "SF0013", "BUY", 3880.0, 3876.0, 3888.0, ago=10)
    pr2 = paper(db, "DT-03", "XAUTUSD", 1, 3880.0, 3876.0, 3888.0, ago=10)
    await cyc(db)
    check("a silent Factory tab holds its own copies only (they wait); the paper desk's go in",
          trade(db, s_new) is None and "Strategy Factory tab has not updated" in M._WAITING["gold"][s_new]["why"]
          and (trade(db, pr2) or {}).get("status") == "open", (M._WAITING["gold"].get(s_new), (trade(db, pr2) or {}).get("reason")))
    sfs.docs[0]["at"] = utc_naive(CLOCK[0])
    advance(30)
    sfs.docs[0]["at"] = utc_naive(CLOCK[0])
    await cyc(db)
    check("... and goes in once the tab is back", (trade(db, s_new) or {}).get("status") == "open")

    advance(60)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0]["wallet_at"] = CLOCK[0]
    M.D.balance = 5.0                                          # $5 left: one bitcoin contract needs about $8.6 free
    blocked_now = [paper(db, a, "BTCUSD", -1, 69150.0, 69500.0, 68400.0, ago=10) for a in ("RU-06", "NJ-47", "DT-02")]
    n_wallet = sum(1 for c in M.D.calls if c == ("GET", "/v2/wallet/balances"))
    r = await cyc(db)
    reads = sum(1 for c in M.D.calls if c == ("GET", "/v2/wallet/balances")) - n_wallet
    check("too little free margin: the three bitcoin copies wait (never skipped), the wallet read once for the pass",
          all(trade(db, x) is None for x in blocked_now) and r["crypto"].get("waiting") == 3 and reads == 1
          and all("not enough free balance" in M._WAITING["crypto"][x]["why"] for x in blocked_now), (r["crypto"], reads))
    M.D.balance = 400.0
    advance(30)
    await cyc(db)
    check("... and all three go in once the margin is there", all((trade(db, x) or {}).get("status") == "open"
                                                                  for x in blocked_now))
    sc, sg = st_of(db, "crypto"), st_of(db, "gold")
    check("both desks still live, no venue errors", sc["mode"] == sg["mode"] == "live"
          and sc["errors_in_row"] == sg["errors_in_row"] == 0, (sc.get("switched_off"), sg.get("switched_off")))
    db = fresh(btc=100000.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)
    big = paper(db, "TH-05", "BTCUSD", 1, 100000.0, 93500.0, None, ago=20)        # 6.5% away: about $6.50 a contract
    await cyc(db)
    t = trade(db, big)
    check("bitcoin at 100,000 and a stop 6.5% away, one contract losing about $6.50: copied, no $5 cap at one contract",
          t is not None and t["status"] == "open" and t["contracts"] == 1 and t["plan"]["risk_usd"] > 5.0
          and float(own_leg(t, "stop")["stop_price"]) == 93500.0 and not t.get("stop_capped"),
          t and (t.get("status"), t.get("reason")))

    # ── 35. results (21 Nov) ──────────────────────────────────────────────────────
    section("35. Results: trades, % won, PF, t, net, return % on the peak margin, trading days, the average a day")
    pr = {"BTCUSD": {"contract_value": 0.001, "leverage": 10}}

    def row(acct, status, contracts, fill, opened, closed=None, pnl=None, day=None, mode="live", **kw):
        return {"_id": f"{acct}|{opened}", "acct": acct, "mkt": "BTCUSD", "product": "BTCUSD", "mode": mode,
                "status": status, "contracts": contracts, "fill": fill, "opened_at": opened, "created_at": opened,
                **({"closed_at": closed, "pnl_usd": pnl, "day_closed": day, "fees": 0.1} if status == "closed" else {}), **kw}
    rows = [row("X", "closed", 4, 60000.0, 1000.0, 2000.0, 6.0, "2026-11-15"),     # $24 of margin
            row("Y", "closed", 1, 50000.0, 1500.0, 2500.0, -2.0, "2026-11-15"),    # $5, held while X's $24 is
            row("X", "closed", 1, 50000.0, 3000.0, 4000.0, -1.0, "2026-11-16"),    # $5
            row("Y", "open", 1, 50000.0, 5000.0, unrealised_usd=0.5),             # $5, held until now
            row("X", "skipped", 1, 50000.0, 6000.0), row("X", "closed", 9, 50000.0, 500.0, 900.0, 99.0, "2026-11-14",
                                                           mode="shadow")]
    r = M._results(rows, pr, 9000.0)
    k, x, y = r["desk"], r["per"]["X|BTCUSD"], r["per"]["Y|BTCUSD"]
    check("the desk: 3 closed (skipped and shadow rows left out), 1 won, 1 open, net +$3, PF 6/3 = 2.0",
          (k["trades"], k["wins"], k["open"], k["net_usd"], k["pf"], k["win_pct"]) == (3, 1, 1, 3.0, 2.0, 33.3), k)
    check("the desk's peak margin is the $29 held at once (X's 4 contracts + Y's 1), so +$3 is +10.34%",
          k["peak_margin_usd"] == 29.0 and k["return_pct"] == 10.34, (k["peak_margin_usd"], k["return_pct"]))
    check("2 trading days (IST days a trade closed): +5.172% and +$1.50 a trading day; 1 green day",
          (k["days"], k["avg_day_pct"], k["avg_day_usd"], k["green_days"]) == (2, 5.172, 1.5, 1), k)
    check("by day: 15 Nov 2 trades 1 won +$4 (+13.79%), 16 Nov 1 trade -$1 (-3.45%)",
          k["by_day"] == [{"day": "2026-11-15", "trades": 2, "wins": 1, "pnl_usd": 4.0, "return_pct": 13.79},
                          {"day": "2026-11-16", "trades": 1, "wins": 0, "pnl_usd": -1.0, "return_pct": -3.45}], k["by_day"])
    check("the desk's worst run from a peak is -$3 (+6, then -2, -1); fees summed; the open trade's +$0.50",
          (k["max_dd_usd"], k["fees_usd"], k["open_usd"], k["best_usd"], k["worst_usd"]) == (-3.0, 0.3, 0.5, 6.0, -2.0), k)
    check("strategy X: 2 trades, net +$5 on its $24 peak (one trade at a time) = +20.83%, 2 days, PF 6.0, t 0.71",
          (x["trades"], x["net_usd"], x["peak_margin_usd"], x["return_pct"], x["days"], x["avg_day_pct"], x["pf"], x["t"])
          == (2, 5.0, 24.0, 20.83, 2, 10.417, 6.0, 0.71), x)
    check("strategy Y: 1 trade -$2 and one open: -40% of its $5, PF 0, no t from one trade",
          (y["trades"], y["open"], y["return_pct"], y["pf"], y["t"], y["win_pct"]) == (1, 1, -40.0, 0.0, None, 0.0), y)
    same = M._results([row("A", "closed", 1, 50000.0, 1000.0, 2000.0, 1.0, "2026-11-15"),
                       row("B", "closed", 1, 50000.0, 2000.0, 3000.0, 1.0, "2026-11-15")], pr, 9000.0)["desk"]
    check("a close and an open in the same second never count both margins", same["peak_margin_usd"] == 5.0, same)
    none = M._results([], pr, 9000.0)["desk"]
    check("no trade at all: zeros and blanks, never a division by zero",
          none["trades"] == 0 and none["return_pct"] is None and none["avg_day_pct"] is None and none["by_day"] == [], none)
    plan = M._results([{**row("P", "closed", 1, None, 1000.0, 2000.0, 0.5, "2026-11-15"), "plan": {"margin_usd": 2.5}}],
                      {}, 9000.0)["desk"]
    check("no product read yet: the plan's margin is used", plan["peak_margin_usd"] == 2.5 and plan["return_pct"] == 20.0, plan)

    db = fresh()
    tid = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None, ago=20)
    await cyc(db)
    advance(120)
    M.D.mid.update(BTCUSD=69300.0)
    close_paper(db, tid, "signal", 69300.0)
    await cyc(db)
    c = await M.status("crypto")
    t = trade(db, tid)
    kr, pk = c.get("results") or {}, next(p for p in c["picks"] if p["acct"] == "TH-01").get("results") or {}
    check("status: the closed real trade is in the desk's results and TH-01's, its return % = net / its margin",
          t and t["status"] == "closed" and kr.get("trades") == 1 and pk.get("trades") == 1 and kr.get("days") == 1
          and abs(pk["return_pct"] - round(100 * t["pnl_usd"] / pk["peak_margin_usd"], 2)) < 0.01
          and pk["peak_margin_usd"] > 0 and len(kr.get("by_day") or []) == 1, (t and t.get("status"), kr, pk))
    check("... strategies without a real trade read null, and the gold desk has none",
          next(p for p in c["picks"] if p["acct"] == "TH-05")["results"] is None
          and (await M.status("gold"))["results"]["trades"] == 0)
    real = M._results
    M._results = lambda *a: 1 / 0
    c = await M.status("crypto")
    M._results = real
    check("results that fail to count never break the page: they read null, the rest is there",
          c.get("results") is None and all(p["results"] is None for p in c["picks"]) and c["totals"]["live"]["trades"] == 1)

    # ── 36. 22 Nov: the owner's third list; ether on the bitcoin desk; a new product's leverage confirmed first ─────
    section("36. 22 Nov: 49 gold and 9 bitcoin-desk picks (two on ETHUSD); a product new to a live desk is confirmed at 10x first")
    from collections import Counter
    ETH = SPECS["ETHUSD"]["id"]
    LEV = lambda pid: f"/v2/products/{pid}/orders/leverage"   # noqa: E731
    gp, cp = M.DESKS["gold"].picks, M.DESKS["crypto"].picks
    g22 = [p for p in gp if p.picked_at == M.NEW_PICKED_AT_4]
    c22 = [p for p in cp if p.picked_at == M.NEW_PICKED_AT_4]
    sf22 = ["SF0345", "SF0298", "SF0541", "SF0315", "SF0347", "SF0337", "SF0220", "SF0466", "SF0221", "SF0332", "SF0244",
            "SF0325", "SF0449", "SF0488", "SF0465", "SF0230", "SF0467", "SF0474", "SF0246", "SF0498", "SF0476", "SF0314",
            "SF0402", "SF0487", "SF0229", "SF0090", "SF0316", "SF0212", "SF0014", "SF0543", "SF0004", "SF0222", "SF0344",
            "SF0451", "SF0119", "SF0395", "SF0268", "SF0475"]
    check("the gold desk's 49, after its 50: ten Premium gold books, the H1 Prior Session High/Low Break and 38 of the "
          "Factory board's top 56 in board order (the other 18 of the 56 were already here)",
          tuple(gp[50:99]) == tuple(g22) and len(g22) == 49
          and [(p.acct, p.mkt) for p in g22[:10]] == [("CP-21", "XAUUSD"), ("YT-18", "XAUUSD"), ("TF-01", "XAUTUSD"),
                                                      ("CP-01", "XAUUSD"), ("FL-02", "XAUTUSD"), ("MH-01", "XAUTUSD"),
                                                      ("DT-02", "XAUTUSD"), ("BG-08", "XAUUSD"), ("RU-06", "XAUTUSD"),
                                                      ("JR-03", "XAUTUSD")]
          and all(p.src == M.PREMIUM and p.product == "XAUTUSD" for p in g22[:10])
          and (g22[10].acct, g22[10].src, g22[10].template) == ("H1-PSB", M.GOLD_H1, "prior_session_break")
          and [p.acct for p in g22[11:]] == sf22 and all(p.src == M.GOLD_SF and p.template == p.acct for p in g22[11:])
          and len({p.acct for p in gp if p.src == M.GOLD_SF}) == 58, [p.acct for p in g22])
    check("the bitcoin desk's 9, after its 15: seven bitcoin books and the ether books of DD-04 and BX-02 (their bitcoin "
          "books were not picks on 22 Nov; DD-04's joined on 24 Nov: section 39)",
          tuple(cp[15:24]) == tuple(c22) and [(p.acct, p.mkt, p.product) for p in c22] == [
              ("DT-05", "BTCUSD", "BTCUSD"), ("TL-03", "BTCUSD", "BTCUSD"), ("RU-04", "BTCUSD", "BTCUSD"),
              ("KA-01", "BTCUSD", "BTCUSD"), ("DD-01", "BTCUSD", "BTCUSD"), ("TD-04", "BTCUSD", "BTCUSD"),
              ("TC-04", "BTCUSD", "BTCUSD"), ("DD-04", "ETHUSD", "ETHUSD"), ("BX-02", "ETHUSD", "ETHUSD")]
          and M.DESKS["crypto"].pick[("DD-04", "BTCUSD")].picked_at == M.NEW_PICKED_AT_5
          and ("BX-02", "BTCUSD") not in M.DESKS["crypto"].pick,
          [(p.acct, p.mkt) for p in c22])
    both = {p.acct for p in gp} & {p.acct for p in cp}
    check("a strategy on both desks has a different book on each (RU-04, TD-04, DT-02, RU-06 from 22 Nov); no product "
          "is on both desks",
          {"RU-04", "TD-04", "DT-02", "RU-06", "TL-04", "PT-04", "RU-03", "DT-01"} <= both
          and all({p.product for p in gp if p.acct == a} == {"XAUTUSD"} and {p.product for p in cp if p.acct == a} == {"BTCUSD"}
                  for a in both)
          and not set(M.DESKS["gold"].products) & set(M.DESKS["crypto"].products)
          and M.DESKS["crypto"].products == ["BTCUSD", "ETHUSD"] and M.DESKS["gold"].products == ["XAUTUSD"], sorted(both))
    by = {p.acct: p for p in g22 + c22}
    rec = lambda a: (by[a].trades, by[a].sum_r, by[a].t, by[a].win)   # noqa: E731
    check("records as of 14:30 IST 22 Nov, by each source's own method (re-proven on frozen records before they were read)",
          rec("DT-05") == (24, 4.44, 0.76, 54) and rec("BX-02") == (10, 2.04, 0.35, 30) and rec("BG-08")[:2] == (110, 13.01)
          and rec("H1-PSB") == (26, 0.68, 0.09, 35) and rec("SF0315") == (30, 9.10, 0.84, 40)
          and rec("SF0474")[0] == 51 and rec("SF0344")[:2] == (154, -4.11))
    verdict = lambda ps: Counter(p.backtest.split(":")[0].split(" ")[0] for p in ps)   # noqa: E731 - as the page counts
    check("what each one's own backtest said, counted the way the page counts it, is what the desks' notes say "
          "(from 24 Nov with section 39's picks)",
          verdict(gp) == {"loses": 16, "earns": 5, "never": 16, "pooled": 7, "factory": 58}
          and verdict(cp) == {"loses": 11, "never": 21}
          and "102 unproven gold strategies" in M.GOLD_NOTES[0] and M.GOLD_NOTES[1].startswith("Sixteen lose")
          and "five earn" in M.GOLD_NOTES[1] and "sixteen were" in M.GOLD_NOTES[1] and "the 58 Factory" in M.GOLD_NOTES[1]
          and "32 strategies" in M.CRYPTO_NOTES[0] and "eleven lose" in M.CRYPTO_NOTES[1]
          and "twenty-one" in M.CRYPTO_NOTES[1],
          (verdict(gp), verdict(cp)))

    # ether trades on the bitcoin desk
    db = fresh(btc=69000.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)                       # one contract a trade
        coll.docs[0]["wallet_at"] = CLOCK[0]
    M.D.mid.update(ETHUSD=1689.0)
    e1 = paper(db, "BX-02", "ETHUSD", -1, 1675.0, 1715.8, None, ago=6 * 3600)   # open since before the switch-on;
    #                                                                             it stops and reverses: no target
    nb = paper(db, "BX-02", "BTCUSD", -1, 69000.0, 69500.0, None, ago=20)        # its bitcoin book: not a pick
    ne = paper(db, "DD-01", "ETHUSD", 1, 1689.0, 1670.0, 1720.0, ago=20)         # DD-01's ether book: not a pick
    n0 = len(M.D.calls)
    await cyc(db)
    t = trade(db, e1)
    check("BX-02's ether paper trade, open since before the switch-on, is one real ETHUSD contract on the bitcoin desk: "
          "short, its stop on Delta on ETHUSD's tick, no target (it stops and reverses)",
          t is not None and t["status"] == "open" and t["product"] == "ETHUSD" and t["contracts"] == 1 and t["side"] == -1
          and any(d["_id"] == e1 for d in db.live_crypto_trades.docs) and M.D.pos[ETH]["size"] == -1
          and float(own_leg(t, "stop")["stop_price"]) == 1715.8 and own_leg(t, "target") is None
          and t["plan"]["margin_usd"] == round(0.01 * M.D.bid("ETHUSD") / 10, 2) and t["plan"]["risk_usd"] < 0.5,
          t and (t.get("status"), t.get("reason"), t.get("plan")))
    check("not copied: BX-02's bitcoin book and DD-01's ether book (a pick is one book: strategy and market)",
          trade(db, nb) is None and trade(db, ne) is None and BTC not in M.D.pos)
    check("ETHUSD confirmed at 10x already (as going live leaves a desk): no leverage call",
          not any(c[1].endswith("/orders/leverage") for c in M.D.calls[n0:]))
    advance(300)
    M.D.set_price("ETHUSD", 1680.0)
    close_paper(db, e1, "exit_signal", 1680.0)
    await cyc(db)
    t = trade(db, e1)
    check("its paper exit closes it at the market, its stop cancelled first; the account's ether is flat, the trade won",
          t["status"] == "closed" and t["close_reason"] == "paper exit: exit_signal" and ETH not in M.D.pos
          and own_leg(t, "stop")["state"] == "cancelled" and t["pnl_usd"] > 0, (t["status"], t.get("close_reason"), t.get("pnl_usd")))
    M.D.pos[ETH] = {"size": 2, "entry": 1680.0}                 # an ether position no trade accounts for
    e2 = paper(db, "DD-04", "ETHUSD", 1, 1680.0, 1660.0, 1710.0, ago=10)
    b2 = paper(db, "DT-05", "BTCUSD", 1, 69000.0, 68700.0, 69450.0, ago=10)
    advance(30)
    await cyc(db)
    check("the books check covers ETHUSD: an ether position no trade accounts for makes the ether copy wait, while a "
          "bitcoin one (DT-05, new on 22 Nov) goes in",
          trade(db, e2) is None and (trade(db, b2) or {}).get("status") == "open"
          and "ETHUSD" in (st_of(db, "crypto").get("mismatch") or ""),
          (st_of(db, "crypto").get("mismatch"), (trade(db, b2) or {}).get("reason")))
    M.D.pos.pop(ETH)
    advance(30)
    await cyc(db)
    check("... and goes in once the account matches", (trade(db, e2) or {}).get("status") == "open"
          and M.D.pos[ETH]["size"] == 1 and not st_of(db, "crypto").get("mismatch"))

    # a product that joins a desk already live (the 22 Nov deploy): its leverage is confirmed before its first entry
    db = fresh(btc=69000.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)
        coll.docs[0]["wallet_at"] = CLOCK[0]
    db.live_crypto_state.docs[0]["products"].pop("ETHUSD")      # never armed with the desk: no confirmed leverage
    M.D.mid.update(ETHUSD=1689.0)
    M.D.fail["leverage"] = "definite"                            # Delta refuses the change at first
    e3 = paper(db, "DD-04", "ETHUSD", 1, 1689.0, 1670.0, 1720.0, ago=20)
    b3 = paper(db, "KA-01", "BTCUSD", 1, 69000.0, 68700.0, 69300.0, ago=20)
    n0 = len(M.D.calls)
    await cyc(db)
    lev_calls = [c for c in M.D.calls[n0:] if c[1].endswith("/orders/leverage")]
    sc = st_of(db, "crypto")
    check("leverage on the new product refused: its signal waits (no ether order), the bitcoin one goes in, the desk stays "
          "live and says why; bitcoin's leverage is never asked",
          trade(db, e3) is None and ETH not in M.D.pos and "leverage" in M._WAITING["crypto"][e3]["why"]
          and (trade(db, b3) or {}).get("status") == "open" and sc["mode"] == "live"
          and "ETHUSD: its leverage could not be confirmed" in (sc.get("last_error") or "")
          and lev_calls == [("GET", LEV(ETH)), ("POST", LEV(ETH))] and M.D.lev[ETH] == 100,
          (M._WAITING["crypto"].get(e3), sc.get("last_error"), lev_calls))
    M.D.fail.pop("leverage")
    advance(30)
    n1 = len(M.D.calls)
    await cyc(db)
    lev_calls = [c for c in M.D.calls[n1:] if c[1].endswith("/orders/leverage")]
    t = trade(db, e3)
    check("the next pass: read (100x), set to 10x, read back and kept in the desk's state; then the ether copy goes in",
          lev_calls == [("GET", LEV(ETH)), ("POST", LEV(ETH)), ("GET", LEV(ETH))] and M.D.lev[ETH] == 10
          and st_of(db, "crypto")["products"]["ETHUSD"]["leverage"] == 10
          and t is not None and t["status"] == "open" and t["product"] == "ETHUSD" and M.D.pos[ETH]["size"] == 1,
          (lev_calls, t and (t.get("status"), t.get("reason"))))
    advance(30)
    n2 = len(M.D.calls)
    await cyc(db)
    check("confirmed once: later passes make no leverage call; bitcoin's own leverage was never touched",
          not any(c[1].endswith("/orders/leverage") for c in M.D.calls[n2:]) and M.D.lev[BTC] == 200
          and st_of(db, "crypto")["mode"] == "live")
    db = fresh(btc=69000.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)
        coll.docs[0]["wallet_at"] = CLOCK[0]
    db.live_crypto_state.docs[0]["products"].pop("ETHUSD")
    M.D.mid.update(ETHUSD=1689.0)
    M.D.lev[ETH] = 10                                            # as the real account read on 22 Nov
    e4 = paper(db, "BX-02", "ETHUSD", -1, 1689.0, 1715.8, None, ago=20)
    n0 = len(M.D.calls)
    await cyc(db)
    lev_calls = [c for c in M.D.calls[n0:] if c[1].endswith("/orders/leverage")]
    check("Delta already says 10x (the real account on 22 Nov): one read, no change sent, and the copy goes in",
          lev_calls == [("GET", LEV(ETH))] and (trade(db, e4) or {}).get("status") == "open"
          and st_of(db, "crypto")["products"]["ETHUSD"]["leverage"] == 10, lev_calls)
    db = fresh(btc=69000.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)
        coll.docs[0]["wallet_at"] = CLOCK[0]
    db.live_crypto_state.docs[0]["products"].pop("ETHUSD")
    M.D.mid.update(ETHUSD=1689.0)

    async def _kept(pid, lev):                                   # Delta answers but keeps its old leverage
        return 100.0
    M.D.set_leverage = _kept
    e5 = paper(db, "DD-04", "ETHUSD", 1, 1689.0, 1670.0, 1720.0, ago=20)
    await cyc(db)
    del M.D.set_leverage
    check("a change that does not take (it still reads 100x): no ether order, the signal waits, the desk says why",
          trade(db, e5) is None and ETH not in M.D.pos and "not yet confirmed" in M._WAITING["crypto"][e5]["why"]
          and "reads 100.0x, not 10x" in (st_of(db, "crypto").get("last_error") or "")
          and "ETHUSD" not in {k for k, v in (st_of(db, "crypto").get("products") or {}).items() if v.get("leverage")},
          (M._WAITING["crypto"].get(e5), st_of(db, "crypto").get("last_error")))
    db = fresh(mode="shadow")
    db.live_crypto_state.docs[0]["products"].pop("ETHUSD")
    M.D.mid.update(ETHUSD=1689.0)
    e6 = paper(db, "BX-02", "ETHUSD", -1, 1689.0, 1715.8, None, ago=20)
    n0 = len(M.D.calls)
    await cyc(db)
    check("shadow sends nothing, leverage included: the ether trade is simulated",
          not any(c[1].endswith("/orders/leverage") for c in M.D.calls[n0:]) and not M.D.orders
          and (trade(db, e6) or {}).get("status") == "open" and trade(db, e6)["mode"] == "shadow")

    # the gold desk's new books, from all three sources
    db = fresh(gold=3885.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)
        coll.docs[0]["wallet_at"] = CLOCK[0]
    M._h1_coll().docs.append({"position_id": "q1", "venue": "delta", "h1": True, "symbol": "XAUTUSD",
                              "strategy_template": "prior_session_break", "side": "BUY", "entry_price": 3885.0,
                              "stoploss": 3870.0, "target": 3915.0, "qty": 0.296, "status": "OPEN",
                              "opened_at": utc_naive(CLOCK[0] - 30), "exit_price": None, "exit_reason": None})

    def sf36(pid, sid, side, entry, stop, target):
        M._sf_coll().docs.append({"position_id": pid, "desk": "gold", "strategy_id": sid, "strategy_name": f"{sid} name",
                                  "symbol": "XAUTUSD", "signal_side": side, "side": side, "kind": "perp",
                                  "entry_px": entry, "under_entry": entry, "stop": stop, "target": target,
                                  "capital_deployed": 1111.11, "status": "OPEN", "opened_at": utc_naive(CLOCK[0] - 30),
                                  "closed_at": None, "exit_px": None, "exit_reason": None, "realized_pnl": None,
                                  "under_ltp": entry, "pattern": "p"})
        return "SF|" + pid
    s315 = sf36("z1", "SF0315", "SELL", 3885.0, 3892.0, 3871.0)          # rank 17, under the board's header
    s520 = sf36("z2", "SF0520", "BUY", 3885.0, 3878.0, 3899.0)           # rank 57: outside the 56
    cp21 = paper(db, "CP-21", "XAUUSD", 1, 3885.0, 3880.0, 3895.0, ago=20)
    tf01 = paper(db, "TF-01", "XAUTUSD", -1, 3885.0, 3890.0, 3875.0, ago=20)
    tfb = paper(db, "TF-01", "BTCUSD", -1, 69000.0, 69500.0, 68000.0, ago=20)   # TF-01's bitcoin book: not a pick
    M._PRIORITY_SENT = None
    await cyc(db)
    got = {k: trade(db, k) for k in ("H1|q1", s315, cp21, tf01)}
    check("the gold desk copies its new books from all three sources, one XAUTUSD contract each: CP-21's and TF-01's "
          "paper trades, the H1 Prior Session Break position, SF0315's Factory position",
          all(t is not None and t["status"] == "open" and t["product"] == "XAUTUSD" and t["contracts"] == 1
              and any(d["_id"] == t["_id"] for d in db.live_delta_trades.docs) for t in got.values())
          and got["H1|q1"]["acct"] == "H1-PSB" and got[s315]["acct"] == "SF0315" and got[tf01]["side"] == -1,
          {k: v and (v.get("status"), v.get("reason")) for k, v in got.items()})
    check("not copied: a Factory strategy outside the 56 (SF0520) and TF-01's bitcoin book",
          trade(db, s520) is None and trade(db, tfb) is None and BTC not in M.D.pos)
    doc = next((d for d in db.premium_meta.docs if d["_id"] == "live_priority"), None)
    check("the paper desk is told the new Premium books (bitcoin, gold, ether), never the H1 or Factory ones",
          doc is not None and {"DT-05|BTCUSD", "TC-04|BTCUSD", "CP-21|XAUUSD", "TF-01|XAUTUSD", "JR-03|XAUTUSD",
                               "DD-04|ETHUSD", "BX-02|ETHUSD"} <= set(doc["books"])
          and not any(b.startswith(("H1-", "SF")) for b in doc["books"]) and len(doc["books"]) == 69, doc)
    g = await M.status()
    check("the page: 102 gold picks, each new one with its pick time; the notes name 102",
          len(g["picks"]) == 102 and sum(1 for p in g["picks"] if p["picked_at"] == M.NEW_PICKED_AT_4) == 49
          and "102" in g["notes"][0], len(g["picks"]))

    # ── 37. 23 Nov: each strategy's own lot size and ON/OFF ────────────────────────────────────────────
    section("37. Each strategy's own lots (default one contract) and ON/OFF (default ON), set from the page")
    M.REQUIRE_PIN = False                                    # the owner's choice (15 Nov); the PIN case is at the end
    db = fresh(btc=69000.0, gold=3885.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)                     # contract sizing, as both desks trade now
        coll.docs[0]["wallet_at"] = CLOCK[0]
    c = await M.status("crypto")
    th5 = next(p for p in c["picks"] if p["acct"] == "TH-05")
    check("defaults: every strategy 1 contract and ON, with its product's cap; the server says it takes the settings",
          all(p["cfg"]["contracts"] == 1 and p["cfg"]["on"] for p in c["picks"]) and th5["cfg"]["max"] == 10
          and c["limits"]["pick_cfg"] is True and c["limits"]["lots_max"] == {"BTCUSD": 10, "ETHUSD": 30, "XAUTUSD": 250}
          and c["limits"]["lots_default"] == 1, th5["cfg"])
    bad = [await M.set_pick("XX-99|BTCUSD", contracts=2, confirm="REAL MONEY", desk="crypto"),
           await M.set_pick("TH-05|BTCUSD", contracts=0, desk="crypto"),
           await M.set_pick("TH-05|BTCUSD", contracts=11, confirm="REAL MONEY", desk="crypto"),
           await M.set_pick("TH-05|BTCUSD", contracts=2.5, confirm="REAL MONEY", desk="crypto"),
           await M.set_pick("TH-05|BTCUSD", contracts="two", confirm="REAL MONEY", desk="crypto"),
           await M.set_pick("TH-05|BTCUSD", on="maybe", desk="crypto"),
           await M.set_pick("RU-02|XAUTUSD", contracts=2, confirm="REAL MONEY", desk="crypto"),
           await M.set_pick("TH-05|BTCUSD", contracts=2, confirm="REAL MONEY", desk="nope")]
    check("refused: an unknown strategy, 0 or 11 bitcoin contracts (1-10), 2.5 or 'two' contracts, on='maybe', the gold "
          "desk's strategy asked of the bitcoin desk, an unknown desk; nothing stored",
          all(not r["ok"] for r in bad) and not st_of(db, "crypto").get("pick_cfg"), [r.get("why") for r in bad])
    r = await M.set_pick("TH-05|BTCUSD", contracts=3, desk="crypto")
    check("raising the lots without the words REAL MONEY is refused, nothing stored",
          not r["ok"] and "REAL MONEY" in r["why"] and not st_of(db, "crypto").get("pick_cfg"), r)
    r = await M.set_pick("TH-05|BTCUSD", contracts=3, confirm="REAL MONEY", desk="crypto")
    r2 = await M.set_pick("TH-05|BTCUSD", contracts=2, desk="crypto")
    s = st_of(db, "crypto")
    check("raised to 3 with REAL MONEY, then lowered to 2 with no confirmation: stored, both changes logged",
          r["ok"] and r2["ok"] and s["pick_cfg"]["TH-05|BTCUSD"]["contracts"] == 2 and s["pick_cfg"]["TH-05|BTCUSD"]["on"]
          and [x["to"]["contracts"] for x in s["pick_log"]] == [3, 2] and s["pick_log"][1]["from"]["contracts"] == 3,
          (r, r2, s.get("pick_cfg"), s.get("pick_log")))
    r3 = await M.set_pick("TH-05|BTCUSD", contracts=2, desk="crypto")
    check("the same size again changes nothing and logs nothing",
          r3["ok"] and r3["changed"] is False and len(st_of(db, "crypto")["pick_log"]) == 2, r3)
    check("the gold desk's own cap: 250 XAUTUSD contracts allowed, 251 refused",
          (await M.set_pick("RU-02|XAUTUSD", contracts=250, confirm="REAL MONEY"))["ok"]
          and not (await M.set_pick("RU-02|XAUTUSD", contracts=251, confirm="REAL MONEY"))["ok"]
          and (await M.set_pick("RU-02|XAUTUSD", contracts=1))["ok"])
    a = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, 69600.0, ago=20)
    b = paper(db, "TL-04", "BTCUSD", -1, 69000.0, 69300.0, 68400.0, ago=20)
    await cyc(db)
    ta, tb = trade(db, a), trade(db, b)
    check("a new TH-05 signal goes in at its own 2 contracts, its stop and target orders 2 as well; TL-04 at the default 1",
          ta is not None and ta["status"] == "open" and ta["contracts"] == 2 and ta["plan"]["lots"] == 2
          and int(own_leg(ta, "stop")["size"]) == 2 and int(own_leg(ta, "target")["size"]) == 2
          and tb is not None and tb["status"] == "open" and tb["contracts"] == 1,
          (ta and (ta.get("status"), ta.get("contracts"), ta.get("reason")), tb and (tb.get("status"), tb.get("contracts"))))
    check("... its plan's risk is the two contracts' (its R counts against it); the account nets +2 - 1 = +1 and the "
          "books check agrees",
          abs(ta["plan"]["risk_usd"] - 2 * abs(ta["plan"]["price"] - 68700.0) * 0.001) < 1e-6
          and M.D.pos[BTC]["size"] == 1 and not st_of(db, "crypto").get("mismatch"), (ta["plan"], M.D.pos.get(BTC)))
    r = await M.set_pick("TH-05|BTCUSD", on=False, desk="crypto")
    c2 = paper(db, "TH-05", "BTCUSD", -1, 69000.0, 69300.0, 68400.0, ago=15)
    shut = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, 69600.0, ago=10)
    n_orders = len(M.D.orders)
    await cyc(db)
    w = M._WAITING.get("crypto", {})
    check("switched OFF with no confirmation: TH-05's new signals take no real trade and wait, saying why",
          r["ok"] and trade(db, c2) is None and trade(db, shut) is None and len(M.D.orders) == n_orders
          and "switched off" in w.get(c2, {}).get("why", ""), (r, w.get(c2)))
    close_paper(db, a, "exit_signal", 69050.0)
    close_paper(db, shut, "stop", 68700.0)
    await cyc(db)
    check("... its real trade from before stays managed: its paper exit closes it on Delta, at its 2 contracts",
          trade(db, a)["status"] == "closed" and M.D.pos[BTC]["size"] == -1, (trade(db, a).get("status"), M.D.pos.get(BTC)))
    check("... a paper trade that closed while it was off is recorded as skipped, saying so",
          (trade(db, shut) or {}).get("status") == "skipped" and "switched off" in (trade(db, shut) or {}).get("reason", ""),
          trade(db, shut))
    M._PAPER_CACHE.clear()                                   # the page's paper view is cached 30 s; the clock stood still
    g = await M.status("crypto")
    pc = next(p for p in g["picks"] if p["acct"] == "TH-05")["cfg"]
    sig = next((x for x in g["signals"] if x["id"] == c2), {})
    check("the page: TH-05 shows OFF at 2 lots, and its waiting signal says why",
          pc["contracts"] == 2 and pc["on"] is False and pc["max"] == 10 and sig.get("desk", {}).get("status") == "waiting"
          and "switched off" in sig.get("desk", {}).get("why", ""), (pc, sig.get("desk")))
    r = await M.set_pick("TH-05|BTCUSD", on=True, desk="crypto")
    r2 = await M.set_pick("TH-05|BTCUSD", on=True, confirm="REAL MONEY", desk="crypto")
    await cyc(db)
    t2 = trade(db, c2)
    check("switching it back ON needs REAL MONEY; then its paper trade still open is copied, at its 2 contracts",
          not r["ok"] and r2["ok"] and t2 is not None and t2["status"] == "open" and t2["contracts"] == 2
          and M.D.pos[BTC]["size"] == -3, (r, t2 and (t2.get("status"), t2.get("contracts")), M.D.pos.get(BTC)))
    # a dollar risk picked for the desk sizes by risk: the lots are not used
    db = fresh(btc=69000.0)                                  # dollar sizing, $5 a trade
    await M.set_pick("TH-05|BTCUSD", contracts=7, confirm="REAL MONEY", desk="crypto")
    a = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, 69600.0, ago=20)
    await cyc(db)
    t = trade(db, a)
    want = math.floor(5.0 / (abs(t["plan"]["price"] - 68700.0) * 0.001)) if t else None
    check("with a dollar risk chosen for the desk, the risk sizes the trade and the strategy's 7 lots are not used",
          t is not None and t["contracts"] == want and t["plan"]["lots"] is None and t["contracts"] != 7,
          t and (t.get("contracts"), want, t["plan"]))
    # shadow: the lots size the simulated trade
    db = fresh(mode="shadow", btc=69000.0)
    db.live_crypto_state.docs[0].pop("sizing", None)
    await M.set_pick("TH-05|BTCUSD", contracts=3, confirm="REAL MONEY", desk="crypto")
    a = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, 69600.0, ago=20)
    await cyc(db)
    t = trade(db, a)
    check("shadow: the simulated trade takes the strategy's 3 contracts, and no order is sent",
          t is not None and t["mode"] == "shadow" and t["contracts"] == 3 and not M.D.orders, t and t.get("contracts"))
    # the PIN, when the server requires one (PREMIUM_LIVE_REQUIRE_PIN=1): asked only for more risk, as going live
    M.REQUIRE_PIN = True
    db = fresh()
    no = await M.set_pick("TH-05|BTCUSD", contracts=2, confirm="REAL MONEY", desk="crypto")
    yes = await M.set_pick("TH-05|BTCUSD", contracts=2, confirm="REAL MONEY", pin=PIN, desk="crypto")
    down = await M.set_pick("TH-05|BTCUSD", contracts=1, desk="crypto")
    off = await M.set_pick("TH-05|BTCUSD", on=False, desk="crypto")
    on_no = await M.set_pick("TH-05|BTCUSD", on=True, confirm="REAL MONEY", desk="crypto")
    on_yes = await M.set_pick("TH-05|BTCUSD", on=True, confirm=" real money ", pin=PIN, desk="crypto")
    M.REQUIRE_PIN = False
    pc = st_of(db, "crypto")["pick_cfg"]["TH-05|BTCUSD"]
    check("with a PIN required: raising the lots or switching ON needs it (the words in any case); lowering and OFF "
          "never do, as switching the desk off never does",
          not no["ok"] and "PIN" in no["why"] and yes["ok"] and down["ok"] and off["ok"] and not on_no["ok"]
          and on_yes["ok"] and pc["contracts"] == 1 and pc["on"] is True, (no, yes, down, off, on_no, on_yes, pc))

    # ── 38. 23 Nov: the rank ───────────────────────────────────────────────────────────────────────────
    section("38. The rank: expected net R a trade from the backtest, the paper record and the real copies")
    AT = "2026-11-20T00:00:00+05:30"
    TP = M._iso_ts(AT)

    def pk(acct, bt, src=M.PREMIUM):
        return M.Pick(acct, "BTCUSD", "BTCUSD", acct, 0, 0.0, 0.0, 0, bt, AT, src, None if src == M.PREMIUM else "t")

    def recs(acct, rs_, before=False):
        t0 = TP - 86400 if before else TP + 3600
        return [(t0 + i * 60, float(x), f"{acct}-{i}") for i, x in enumerate(rs_)]

    A_ = pk("A", "loses: -0.20R a trade over 1,000 trades (t -4.0)")
    B_ = pk("B", "never backtested")
    C_ = pk("C", "earns: +0.10R a trade over 400 trades (t 1.5), not significant")
    D_ = pk("D", "never backtested")
    E_ = pk("E", "factory only: graded by the Strategy Factory's own backtest", src=M.GOLD_SF)
    H_ = pk("H", "pooled only: the nine H1 templates together", src=M.GOLD_H1)
    good = [2.0, -1.0] * 20                                  # +0.5R a trade over 40 trades
    rs = {"A|BTCUSD": recs("A", [1.0, -1.0] * 10), "C|BTCUSD": recs("C", [2.0, -1.0, 0.0] * 10),
          "D|BTCUSD": recs("D", good, before=True), "E|BTCUSD": recs("E", good)}
    with M._use("crypto"):
        rk = M._rank([A_, B_, C_, D_, E_, H_], rs, [])
    tau_a = math.sqrt(1.3 ** 2 / 1000 + 0.1 ** 2)
    sd_a = M._sd([1.0, -1.0] * 10)
    mean_a = (-0.20 / tau_a ** 2) / (1 / tau_a ** 2 + 20 / sd_a ** 2)
    check("a backtest of 1,000 trades at -0.20R and a flat 20-trade paper record: about -0.16R, as the formula says",
          abs(rk["A|BTCUSD"]["edge_r"] - mean_a) < 1e-3 and rk["A|BTCUSD"]["prior"] == "backtest"
          and rk["A|BTCUSD"]["post_n"] == 20, (rk["A|BTCUSD"], mean_a))
    check("no trades and no backtest: its desk's average backtest, (-0.20 + 0.10) / 2, about 40% likely positive",
          abs(rk["B|BTCUSD"]["edge_r"] + 0.05) < 1e-9 and rk["B|BTCUSD"]["prior"] == "untested"
          and 0.39 < rk["B|BTCUSD"]["p_pos"] < 0.41, rk["B|BTCUSD"])
    check("an H1 template with no record: 0, 50% likely positive", rk["H|BTCUSD"]["edge_r"] == 0 and
          rk["H|BTCUSD"]["p_pos"] == 0.5 and rk["H|BTCUSD"]["prior"] == "pooled", rk["H|BTCUSD"])
    check("the same 40 winning trades count more after the pick (E) than before it (D): E ranks above D",
          rk["E|BTCUSD"]["edge_r"] > rk["D|BTCUSD"]["edge_r"] > rk["B|BTCUSD"]["edge_r"] and rk["D|BTCUSD"]["pre_n"] == 40
          and rk["E|BTCUSD"]["post_n"] == 40 and rk["E|BTCUSD"]["pos"] < rk["D|BTCUSD"]["pos"],
          (rk["E|BTCUSD"]["edge_r"], rk["D|BTCUSD"]["edge_r"]))
    check("ranked 1..6 by expected R, best first; C (a positive backtest and a positive record) above A",
          sorted(v["pos"] for v in rk.values()) == list(range(1, 7)) and all(v["of"] == 6 for v in rk.values())
          and rk["C|BTCUSD"]["pos"] < rk["A|BTCUSD"]["pos"]
          and [k for k, _ in sorted(rk.items(), key=lambda kv: kv[1]["pos"])]
          == sorted(rk, key=lambda k: -rk[k]["edge_r"]), {k: (v["pos"], v["edge_r"]) for k, v in rk.items()})
    # the real copies against their paper twins: F's real trades made 1R less than paper, K's the same, G has none
    F_, G_, K_ = pk("F", "never backtested"), pk("G", "never backtested"), pk("K", "never backtested")
    same = [1.0, -0.5] * 5
    rs2 = {"F|BTCUSD": recs("F", same), "G|BTCUSD": recs("G", same), "K|BTCUSD": recs("K", same)}
    rows2 = []
    for acct, worse in (("F", 1.0), ("K", 0.0)):
        for _, rr_, i in rs2[f"{acct}|BTCUSD"]:
            rows2.append({"_id": i, "mode": "live", "status": "closed", "acct": acct, "mkt": "BTCUSD",
                          "pnl_usd": (rr_ - worse) * 0.30, "plan": {"risk_usd": 0.30}})
    with M._use("crypto"):
        rk2 = M._rank([F_, G_, K_], rs2, rows2)
    check("identical paper records: the strategy whose real copies lost 1R against paper (F) ranks below one with no "
          "copies (G), below one whose copies matched paper (K); gaps -0.75, -0.5, -0.25 (each pulled toward the desk's)",
          rk2["F|BTCUSD"]["pos"] == 3 and rk2["G|BTCUSD"]["pos"] == 2 and rk2["K|BTCUSD"]["pos"] == 1
          and abs(rk2["F|BTCUSD"]["gap_r"] + 0.75) < 1e-9 and abs(rk2["G|BTCUSD"]["gap_r"] + 0.5) < 1e-9
          and abs(rk2["K|BTCUSD"]["gap_r"] + 0.25) < 1e-9 and rk2["F|BTCUSD"]["gap_n"] == 10 and rk2["G|BTCUSD"]["gap_n"] == 0,
          {k: (v["pos"], v["gap_r"]) for k, v in rk2.items()})
    # on the page
    db = fresh(btc=69000.0)
    paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, 69600.0, ago=40000, open=False, r_net=1.5, exit_t=int(CLOCK[0] - 30000))
    for k in ("crypto", "gold"):
        g = await M.status(k)
        poss = sorted(p["rank"]["pos"] for p in g["picks"] if p.get("rank"))
        check(f"the {k} desk's page: every strategy ranked 1..{len(g['picks'])} once, with how it was ranked",
              poss == list(range(1, len(g["picks"]) + 1)) and all(0 <= p["rank"]["p_pos"] <= 1 for p in g["picks"])
              and "expected net R a trade" in g["rank_method"], (len(poss), len(g["picks"])))
    old_rows = M._paper_rows

    async def broken(_db):
        raise RuntimeError("paper store down")
    M._paper_rows = broken
    M._PAPER_CACHE.clear()
    g = await M.status("crypto")
    M._paper_rows = old_rows
    check("the paper side unreadable: no rank (nothing to rank on), and the page still reads",
          all(p["rank"] is None for p in g["picks"]) and g["configured_db"] and len(g["picks"]) == 32)


    # ── 39. 24 Nov: the owner's fourth list ───────────────────────────────────────────────────────────────────────────
    section("39. 24 Nov: 8 more on the bitcoin desk (DD-04's bitcoin book beside its ether book; DD-03 and BX-01 on ETHUSD), "
            "3 more gold; the rest skipped")
    import json as _json
    gp, cp = M.DESKS["gold"].picks, M.DESKS["crypto"].picks
    g24 = [p for p in gp if p.picked_at == M.NEW_PICKED_AT_5]
    c24 = [p for p in cp if p.picked_at == M.NEW_PICKED_AT_5]
    check("the gold desk's 3, after its 99: JR-05, BG-05 and JR-01, Premium books traded on XAUTUSD",
          tuple(gp[99:]) == tuple(g24) and [(p.acct, p.mkt, p.product) for p in g24] == [
              ("JR-05", "XAUTUSD", "XAUTUSD"), ("BG-05", "XAUUSD", "XAUTUSD"), ("JR-01", "XAUTUSD", "XAUTUSD")]
          and all(p.src == M.PREMIUM for p in g24), [(p.acct, p.mkt) for p in g24])
    check("the bitcoin desk's 8, after its 24: six bitcoin books (DD-04's among them) and the ether books of DD-03 and BX-01",
          tuple(cp[24:]) == tuple(c24) and [(p.acct, p.mkt, p.product) for p in c24] == [
              ("NJ-43", "BTCUSD", "BTCUSD"), ("TD-03", "BTCUSD", "BTCUSD"), ("NJ-28", "BTCUSD", "BTCUSD"),
              ("SC-02", "BTCUSD", "BTCUSD"), ("NJ-37", "BTCUSD", "BTCUSD"), ("DD-04", "BTCUSD", "BTCUSD"),
              ("DD-03", "ETHUSD", "ETHUSD"), ("BX-01", "ETHUSD", "ETHUSD")]
          and all(p.src == M.PREMIUM for p in c24), [(p.acct, p.mkt) for p in c24])
    # the owner's screenshots, row by row (Premium Crypto tab: 28 rows; Gold tab: 31 rows)
    asked_c = [("DT-05", "BTCUSD"), ("TL-03", "BTCUSD"), ("TH-01", "BTCUSD"), ("NJ-43", "BTCUSD"), ("DT-02", "BTCUSD"),
               ("TH-05", "BTCUSD"), ("TD-02", "BTCUSD"), ("TH-06", "BTCUSD"), ("RU-04", "BTCUSD"), ("NJ-47", "BTCUSD"),
               ("KA-01", "BTCUSD"), ("DD-03", "ETHUSD"), ("TD-03", "BTCUSD"), ("RU-06", "BTCUSD"), ("NJ-28", "BTCUSD"),
               ("DD-01", "BTCUSD"), ("TH-07", "BTCUSD"), ("DD-04", "ETHUSD"), ("SC-02", "BTCUSD"), ("NJ-37", "BTCUSD"),
               ("TD-04", "BTCUSD"), ("DT-01", "BTCUSD"), ("SB-04", "BTCUSD"), ("RU-03", "BTCUSD"), ("TC-04", "BTCUSD"),
               ("BX-01", "ETHUSD"), ("PT-04", "BTCUSD"), ("DD-04", "BTCUSD")]
    asked_g = [("CP-23", "XAUUSD"), ("TL-04", "XAUTUSD"), ("YT-18", "XAUUSD"), ("BG-01", "XAUUSD"), ("CP-21", "XAUUSD"),
               ("RU-04", "XAUTUSD"), ("TF-01", "XAUTUSD"), ("CP-05", "XAUUSD"), ("CP-01", "XAUUSD"), ("FZ-02", "XAUTUSD"),
               ("CP-06", "XAUUSD"), ("FL-02", "XAUTUSD"), ("MH-01", "XAUTUSD"), ("RU-02", "XAUTUSD"), ("SB-06", "XAUUSD"),
               ("RU-03", "XAUTUSD"), ("DT-02", "XAUTUSD"), ("DT-03", "XAUTUSD"), ("BB-11", "XAUUSD"), ("PT-04", "XAUTUSD"),
               ("RU-06", "XAUTUSD"), ("JR-05", "XAUTUSD"), ("JR-03", "XAUTUSD"), ("DT-01", "XAUTUSD"), ("JR-04", "XAUTUSD"),
               ("RU-05", "XAUTUSD"), ("TD-04", "XAUTUSD"), ("BG-05", "XAUUSD"), ("TP-05", "XAUTUSD"), ("JR-01", "XAUTUSD"),
               ("BG-08", "XAUUSD")]
    for desk, asked, new in (("crypto", asked_c, c24), ("gold", asked_g, g24)):
        pk = M.DESKS[desk].pick
        missing = [k for k in asked if k not in pk]
        joined = sorted(k for k in asked if k in pk and pk[k].picked_at == M.NEW_PICKED_AT_5)
        kept = [k for k in asked if k in pk and pk[k].picked_at != M.NEW_PICKED_AT_5]
        check(f"{desk}: all {len(asked)} of the owner's rows are on the desk; the {len(new)} new ones are exactly those that "
              f"were not there, and the other {len(asked) - len(new)} were skipped (their picks and records unchanged)",
              not missing and len(set(asked)) == len(asked) and joined == sorted((p.acct, p.mkt) for p in new)
              and len(kept) == len(asked) - len(new), (missing, joined))
    check("BX-02 is still the only BX book of the bitcoin desk on BTCUSD's side: BX-01's and BX-02's bitcoin books are not "
          "picks, nor are DD-03's or TD-03's other books",
          all(k not in M.DESKS["crypto"].pick for k in (("BX-01", "BTCUSD"), ("BX-02", "BTCUSD"), ("DD-03", "BTCUSD")))
          and ("TD-03", "XAUTUSD") not in M.DESKS["gold"].pick)
    by = {(p.acct, p.mkt): p for p in g24 + c24}
    rec = lambda a, m: (by[(a, m)].trades, by[(a, m)].sum_r, by[(a, m)].t, by[(a, m)].win)   # noqa: E731
    check("records as of 00:30 IST 24 Nov, by the Premium method (re-proven on five frozen records before they were read)",
          rec("NJ-43", "BTCUSD") == (11, 2.69, 0.58, 55) and rec("TD-03", "BTCUSD") == (21, 1.38, 0.24, 48)
          and rec("NJ-28", "BTCUSD") == (8, 0.57, 0.13, 50) and rec("SC-02", "BTCUSD") == (3, 4.01, 3.76, 100)
          and rec("NJ-37", "BTCUSD") == (3, 2.49, 0.85, 67) and rec("DD-04", "BTCUSD") == (8, 1.03, 0.31, 50)
          and rec("DD-03", "ETHUSD") == (27, 1.04, 0.26, 37) and rec("BX-01", "ETHUSD") == (5, 3.97, 0.83, 60)
          and rec("JR-05", "XAUTUSD") == (8, 1.98, 0.33, 38) and rec("BG-05", "XAUUSD") == (1, 0.79, 0.0, 100)
          and rec("JR-01", "XAUTUSD") == (5, 0.44, 0.12, 40))
    bt = Path(__file__).resolve().parents[2] / "research" / "youtube_channels20_2026_11" / "results" / "backtest.json"
    if bt.exists():
        src = _json.loads(bt.read_text(encoding="utf-8"))

        def said(acct, mkt):
            r = src[acct][mkt]
            m = r["mean_r"]
            return f"loses: {m:.{2 if abs(m) >= 0.1 else 3}f}R a trade over {r['n']:,} trades (t {r['t_stat']:.1f})"
        check("TD-03, JR-05 and JR-01 say what their own 2-year books say (bitcoin; gold on its XAUUSD book, as JR-03's "
              "frozen one), and the rank reads each as its prior",
              by[("TD-03", "BTCUSD")].backtest == said("TD-03", "BTCUSD")
              and by[("JR-05", "XAUTUSD")].backtest == said("JR-05", "XAUUSD")
              and by[("JR-01", "XAUTUSD")].backtest == said("JR-01", "XAUUSD")
              and M.DESKS["gold"].pick[("JR-03", "XAUTUSD")].backtest == said("JR-03", "XAUUSD")
              and M._bt_edge(by[("TD-03", "BTCUSD")].backtest) == (-0.20, 1092)
              and M._bt_edge(by[("JR-05", "XAUTUSD")].backtest) == (-0.30, 197),
              (by[("TD-03", "BTCUSD")].backtest, said("TD-03", "BTCUSD")))
    else:
        print("  (backend/research is not in this tree: the backtest-source check is skipped)")
    check("the other eight were never backtested (the 11-channel and shortlist families have no backtest of their own)",
          sorted(k for k, p in by.items() if p.backtest == "never backtested") == sorted(
              [("NJ-43", "BTCUSD"), ("NJ-28", "BTCUSD"), ("SC-02", "BTCUSD"), ("NJ-37", "BTCUSD"), ("DD-04", "BTCUSD"),
               ("DD-03", "ETHUSD"), ("BX-01", "ETHUSD"), ("BG-05", "XAUUSD")]))

    # end to end: the new picks under the desks' existing rules (every signal copied, one contract, own stops)
    db = fresh(btc=69000.0)
    for coll in (db.live_delta_state, db.live_crypto_state):
        coll.docs[0].pop("sizing", None)                       # one contract a trade, the desks' size
        coll.docs[0]["wallet_at"] = CLOCK[0]
    M.D.balance = 400.0
    M.D.mid.update(ETHUSD=1689.0)
    d_btc = paper(db, "DD-04", "BTCUSD", 1, 69000.0, 68600.0, 69800.0, ago=20)
    d_eth = paper(db, "DD-04", "ETHUSD", -1, 1689.0, 1712.0, 1655.0, ago=20)
    n43 = paper(db, "NJ-43", "BTCUSD", 1, 69000.0, 68700.0, 69600.0, ago=3 * 3600)   # open since before the switch-on
    b01 = paper(db, "BX-01", "ETHUSD", 1, 1689.0, 1670.0, 1720.0, ago=20)
    nb = paper(db, "BX-01", "BTCUSD", 1, 69000.0, 68700.0, 69600.0, ago=20)          # its bitcoin book: not a pick
    j05 = paper(db, "JR-05", "XAUTUSD", 1, 3885.0, 3880.0, 3900.0, ago=20)
    await cyc(db)
    tb, te, tn, tx, tj = (trade(db, x) for x in (d_btc, d_eth, n43, b01, j05))
    check("DD-04's two books each become one real contract on their OWN product: long BTCUSD and short ETHUSD, each "
          "with its own stop and target on Delta",
          tb is not None and te is not None and tb["status"] == te["status"] == "open"
          and (tb["product"], tb["side"], tb["contracts"]) == ("BTCUSD", 1, 1)
          and (te["product"], te["side"], te["contracts"]) == ("ETHUSD", -1, 1)
          and float(own_leg(tb, "stop")["stop_price"]) == 68600.0 and float(own_leg(te, "stop")["stop_price"]) == 1712.0
          and own_leg(tb, "target") is not None and own_leg(te, "target") is not None,
          (tb and (tb.get("status"), tb.get("reason")), te and (te.get("status"), te.get("reason"))))
    check("NJ-43's paper trade, open since before the switch-on, and BX-01's ether trade are copied at one contract",
          tn is not None and tx is not None and tn["status"] == tx["status"] == "open"
          and (tn["product"], tn["contracts"]) == ("BTCUSD", 1) and (tx["product"], tx["contracts"]) == ("ETHUSD", 1),
          (tn and (tn.get("status"), tn.get("reason")), tx and (tx.get("status"), tx.get("reason"))))
    check("BX-01's bitcoin book is not a pick: not copied", trade(db, nb) is None)
    check("JR-05 on the gold desk: one XAUTUSD contract",
          tj is not None and tj["status"] == "open" and (tj["product"], tj["contracts"]) == ("XAUTUSD", 1)
          and any(d["_id"] == j05 for d in db.live_delta_trades.docs), tj and (tj.get("status"), tj.get("reason")))
    sc, sg = st_of(db, "crypto"), st_of(db, "gold")
    check("both desks still live, no venue errors, no position the trades do not account for",
          sc["mode"] == sg["mode"] == "live" and sc["errors_in_row"] == sg["errors_in_row"] == 0
          and not sc.get("mismatch") and not sg.get("mismatch"), (sc.get("switched_off"), sg.get("switched_off")))
    c, g = await M.status("crypto"), await M.status("gold")
    new = [p for p in c["picks"] + g["picks"] if p["picked_at"] == M.NEW_PICKED_AT_5]
    check("on the page: the 11 with their pick time, each at the desks' default (one contract, ON), each ranked; the "
          "bitcoin desk shows DD-04 twice, one row a book",
          len(new) == 11 and all(p["cfg"]["contracts"] == 1 and p["cfg"]["on"] for p in new)
          and all(p.get("rank") for p in new) and len(c["picks"]) == 32 and len(g["picks"]) == 102
          and sorted(p["mkt"] for p in c["picks"] if p["acct"] == "DD-04") == ["BTCUSD", "ETHUSD"]
          and len({f"{p['acct']}|{p['mkt']}" for p in c["picks"]}) == 32,
          [(p["acct"], p["mkt"], p["cfg"], bool(p.get("rank"))) for p in new])


    # ── 40. 24 Nov evening: the Premium Gold book ─────────────────────────────────────────────────────────────────────
    section("40. 24 Nov evening: the Premium Gold book - the H1 test's six best beside the gold desk, each signal a second "
            "real position at the book's own lots")
    pg = M.DESKS["premium_gold"]
    check("the book: six H1 templates in the Gold Desk's ranking order on XAUTUSD, every signal copied, its own "
          "collections, an order-id salt (the gold and bitcoin desks have none), three desks in all",
          [p.template for p in pg.picks] == ["ema_ribbon", "pivot_break", "donchian_fast", "round_number_break",
                                             "donchian_slow", "keltner_break"]
          and all(p.src == M.GOLD_H1 and p.product == "XAUTUSD" and p.picked_at == M.NEW_PICKED_AT_6 for p in pg.picks)
          and pg.products == ["XAUTUSD"] and pg.follow_all and (pg.state_coll, pg.trades_coll) == ("live_pgold_state",
                                                                                                   "live_pgold_trades")
          and pg.cid_salt != "" and M.DESKS["gold"].cid_salt == M.DESKS["crypto"].cid_salt == "" and len(M.DESKS) == 3,
          [p.template for p in pg.picks])
    rec40 = {p.acct: (p.trades, p.sum_r, p.t, p.win) for p in pg.picks}
    check("records at 20:30 IST 24 Nov by the H1 method (re-proven on three frozen H1 records before they were read)",
          rec40 == {"H1-RIB": (12, 5.57, 1.0, 50), "H1-PIV": (23, 7.22, 0.95, 43), "H1-DCF": (20, 7.02, 1.03, 45),
                    "H1-RND": (22, 3.99, 0.56, 41), "H1-DCS": (7, 2.34, 0.54, 43), "H1-KLT": (17, 3.98, 0.64, 41)}, rec40)
    check("the gold desk keeps its seven H1 picks untouched; Prior Session High/Low is not in the new book",
          [p.acct for p in M.DESKS["gold"].picks if p.src == M.GOLD_H1] == ["H1-RIB", "H1-RND", "H1-DCF", "H1-PIV",
                                                                             "H1-DCS", "H1-KLT", "H1-PSB"]
          and "H1-PSB" not in {p.acct for p in pg.picks} and len(M.DESKS["gold"].picks) == 102)
    ids = {}
    for k in ("gold", "crypto", "premium_gold"):
        with M._use(k):
            ids[k] = (M._cid("H1|abc"), M._cid("H1|abc", "s"))
    before = (("p5" + hashlib.sha1(b"H1|abc").hexdigest())[:30], ("p5" + hashlib.sha1(b"H1|abc").hexdigest())[:29] + "s")
    check("order ids: the gold and bitcoin desks' exactly as before this change; the new book's differ for the same "
          "paper trade, at the same length", ids["gold"] == ids["crypto"] == before
          and all(a != b for a, b in zip(ids["premium_gold"], before)) and [len(x) for x in ids["premium_gold"]] == [30, 30],
          ids)

    # end to end, beside a live gold desk
    db = fresh(gold=3885.0)
    db.live_delta_state.docs[0].pop("sizing", None)          # the gold desk at its lots (one contract), as it trades
    db.live_delta_state.docs[0]["wallet_at"] = CLOCK[0]
    M.D.balance = 400.0
    un = lambda s: datetime.fromtimestamp(s, UTC).replace(tzinfo=None)   # noqa: E731 - as the Gold Desk stores times

    def h1p(pid, tpl, side, entry, stop, target, ago=30):
        M._h1_coll().docs.append({"position_id": pid, "venue": "delta", "h1": True, "symbol": "XAUTUSD",
                                  "strategy_template": tpl, "side": side, "entry_price": entry, "stoploss": stop,
                                  "target": target, "qty": 0.296, "status": "OPEN", "opened_at": un(CLOCK[0] - ago),
                                  "exit_price": None, "exit_reason": None})
        return "H1|" + pid

    def h1x(pid, px):
        for d in M._h1_coll().docs:
            if d["position_id"] == pid:
                d.update(status="CLOSED", exit_reason="exit_signal", exit_price=px, closed_at=un(CLOCK[0]))

    def ptrade(tid):
        return next((d for d in db.live_pgold_trades.docs if d["_id"] == tid), None)

    def gtrade(tid):
        return next((d for d in db.live_delta_trades.docs if d["_id"] == tid), None)

    rib = h1p("x1", "ema_ribbon", "BUY", 3885.0, 3870.0, 3915.0)
    await cyc(db)
    check("the book starts OFF: the gold desk copies the H1 trade at one contract, the new book places nothing",
          gtrade(rib) is not None and gtrade(rib)["status"] == "open" and gtrade(rib)["contracts"] == 1
          and not db.live_pgold_trades.docs and st_of(db, "premium_gold").get("mode") in (None, "off")
          and M.D.pos[GOLD]["size"] == 1, (gtrade(rib), db.live_pgold_trades.docs))
    r = await M.set_pick("H1-RIB|XAUTUSD", contracts=10, confirm="REAL MONEY", desk="premium_gold")
    check("its own lots: 10 on the new book's EMA Ribbon; the gold desk's EMA Ribbon still 1",
          r["ok"] and st_of(db, "premium_gold")["pick_cfg"]["H1-RIB|XAUTUSD"]["contracts"] == 10
          and "H1-RIB|XAUTUSD" not in (st_of(db, "gold").get("pick_cfg") or {}), r)
    n0 = len(M.D.calls)
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="premium_gold")
    lev = [c for c in M.D.calls[n0:] if c[1].endswith("/orders/leverage")]
    check("it arms on its own beside the gold desk's open XAUTUSD trade (the account matches the two books' sum), "
          "reading XAUTUSD's leverage first and setting 10x only because it was not 10x",
          r["ok"] and st_of(db, "premium_gold")["mode"] == "live" and M.D.lev[GOLD] == 10
          and lev[0] == ("GET", f"/v2/products/{GOLD}/orders/leverage") and ("POST", f"/v2/products/{GOLD}/orders/leverage") in lev,
          (r, lev))
    st_of(db, "premium_gold")["wallet_at"] = CLOCK[0]
    advance(30)
    M._h1_state_coll().docs[0]["last_run_at"] = un(CLOCK[0])
    await cyc(db)
    p1, g1 = ptrade(rib), gtrade(rib)
    check("the same H1 trade is now a SECOND real position: 10 contracts on the new book, the gold desk's one beside it; "
          "the account holds 11; each has its own stop and target on Delta, with different order ids",
          p1 is not None and p1["status"] == "open" and p1["contracts"] == 10 and g1["status"] == "open"
          and M.D.pos[GOLD]["size"] == 11 and own_leg(p1, "stop") is not None and own_leg(p1, "target") is not None
          and own_leg(p1, "stop")["client_order_id"] != own_leg(g1, "stop")["client_order_id"]
          and own_leg(p1, "target")["client_order_id"] != own_leg(g1, "target")["client_order_id"]
          and float(own_leg(p1, "stop")["stop_price"]) == 3870.0, p1 and (p1.get("status"), p1.get("reason")))
    sg, sp = st_of(db, "gold"), st_of(db, "premium_gold")
    check("both books reconcile with the account (each counts both): live, no mismatch, no venue error",
          sg["mode"] == sp["mode"] == "live" and not sg.get("mismatch_checks") and not sp.get("mismatch_checks")
          and sg["errors_in_row"] == sp["errors_in_row"] == 0, (sg.get("mismatch"), sp.get("mismatch")))
    check("Main Control's open-position probe counts the new book's trade too", await M.open_count() == 2)
    advance(600)
    M.D.set_price("XAUTUSD", 3900.0)
    h1x("x1", 3900.0)
    M._h1_state_coll().docs[0]["last_run_at"] = un(CLOCK[0])
    await cyc(db)
    p1, g1 = ptrade(rib), gtrade(rib)
    check("its paper exit closes both, each only its own contracts (10 and 1); the account is flat; both won",
          p1["status"] == g1["status"] == "closed" and GOLD not in M.D.pos and p1["pnl_usd"] > 0 and g1["pnl_usd"] > 0
          and p1["close_reason"] == g1["close_reason"] == "paper exit: exit_signal",
          (p1.get("status"), g1.get("status"), M.D.pos.get(GOLD)))
    # flattening the new book leaves the gold desk alone
    advance(60)
    rib2 = h1p("x2", "ema_ribbon", "SELL", 3900.0, 3915.0, 3870.0)
    M._h1_state_coll().docs[0]["last_run_at"] = un(CLOCK[0])
    await cyc(db)
    check("a short: -1 on the gold desk and -10 on the new book, -11 on the account",
          gtrade(rib2)["status"] == ptrade(rib2)["status"] == "open" and M.D.pos[GOLD]["size"] == -11,
          (gtrade(rib2) and gtrade(rib2).get("status"), ptrade(rib2) and ptrade(rib2).get("reason")))
    r = await M.flatten(PIN, desk="premium_gold")
    check("flattening the new book closes only its 10 and switches only it off: the gold desk's trade stays open and live",
          r["ok"] and ptrade(rib2)["status"] == "closed" and gtrade(rib2)["status"] == "open" and M.D.pos[GOLD]["size"] == -1
          and st_of(db, "premium_gold")["mode"] == "off" and st_of(db, "gold")["mode"] == "live", (r, M.D.pos.get(GOLD)))
    # one book's lost order answer never switches the other off; an unexplained position still does
    db.live_pgold_trades.docs.append({"_id": "H1|lost", "acct": "H1-PIV", "mkt": "XAUTUSD", "product": "XAUTUSD",
                                      "mode": "live", "side": 1, "status": "entering", "contracts": 5,
                                      "created_at": CLOCK[0], "plan": {"contracts": 5}})
    M.D.pos[GOLD]["size"] += 5                                  # it filled; its answer was lost
    for _ in range(4):
        advance(20)
        M._h1_state_coll().docs[0]["last_run_at"] = un(CLOCK[0])
        await M.cycle("gold")
    check("the new book's entry in flight (+5 the gold desk's records cannot see): the gold desk only waits, four checks "
          "on, still live, no mismatch counted", st_of(db, "gold")["mode"] == "live" and not st_of(db, "gold").get("mismatch_checks"),
          (st_of(db, "gold").get("switched_off"), st_of(db, "gold").get("mismatch")))
    db.live_pgold_trades.docs = [d for d in db.live_pgold_trades.docs if d["_id"] != "H1|lost"]
    for _ in range(3):
        advance(20)
        M._h1_state_coll().docs[0]["last_run_at"] = un(CLOCK[0])
        await M.cycle("gold")
    check("... the same +5 with no desk accounting for it: the gold desk switches off after three checks, as always",
          st_of(db, "gold")["mode"] == "off" and "has not matched" in (st_of(db, "gold").get("switched_off") or ""),
          st_of(db, "gold").get("switched_off"))
    # what the page reads
    c = await M.status("premium_gold")
    g = await M.status("gold")
    cc = await M.status("crypto")
    pr = next(p for p in c["picks"] if p["acct"] == "H1-RIB")
    check("what the page reads: the book's six, EMA Ribbon at 10 lots, XAUTUSD's price for the lots' money (from the "
          "gold desk's open trade's mark), USD/INR; the bitcoin desk's prices from Delta's ticker",
          c["desk"] == "premium_gold" and len(c["picks"]) == 6 and pr["cfg"]["contracts"] == 10
          and c["quotes"]["XAUTUSD"]["price"] > 0 and g["quotes"]["XAUTUSD"]["price"] == c["quotes"]["XAUTUSD"]["price"]
          and c["usd_inr"]["rate"] == 90.0 and set(cc["quotes"]) == {"BTCUSD", "ETHUSD"}
          and all(q["price"] > 0 for q in cc["quotes"].values()) and c["products"] is not None,
          (c.get("quotes"), c.get("usd_inr"), cc.get("quotes")))
    old_fx, old_q = dict(M._FX), dict(M._QUOTES)
    M._FX.update(rate=None, at=0.0)

    async def no_fx():                          # Yahoo gives nothing
        return None
    M._read_fx = no_fx
    M._QUOTES.clear()
    M.D.fail["ticker"] = "definite"
    cc = await M.status("crypto")
    M.D.fail.pop("ticker")
    check("no price and no rupee rate to be had: the page still reads, just without them",
          cc["configured_db"] and cc["usd_inr"] is None and "BTCUSD" not in cc["quotes"], (cc.get("quotes"), cc.get("usd_inr")))
    M._read_fx = _fake_fx
    M._FX.update(old_fx)
    M._QUOTES.update(old_q)

    # ── 41. 25 Nov: Delta's 100 open orders a product ──────────────────────────────────────────────────────────────────
    section("41. 25 Nov: Delta's 100 open orders a product - a refusal for it skips the signal and the desk stays on; "
            "gold trades keep only their stop on Delta and the app closes them at their target")
    check("as the server reads it: only gold (XAUTUSD) hands its targets to the app; bitcoin and ether keep both orders",
          PROD_APP_TARGET == frozenset({"XAUTUSD"}), PROD_APP_TARGET)
    CAPMSG = 'POST /v2/orders: HTTP 400 {"code": "max_orders_count_exceeded", "context": {"limit": 100}}'
    un = lambda s: datetime.fromtimestamp(s, UTC).replace(tzinfo=None)   # noqa: E731 - as the Gold Desk stores times

    def resting_on(sym):
        pid = SPECS[sym]["id"]
        return sum(1 for o in M.D.stops.values() if o["product_id"] == pid and o["state"] == "pending")

    def cap_at(n, only=None):
        """Delta's limit, scaled down to n: an order on a product is refused while the account holds n resting orders
        there (`only` "market" or "stop" refuses just that kind, whatever the count, as a race would)."""
        real = M.D.request

        async def req(method, path, body=None, signed=True):
            if method == "POST" and path.split("?")[0] == "/v2/orders" and body:
                kind = "stop" if body.get("stop_order_type") else "market"
                if (only == kind) or (only is None and resting_on(BY_ID[body["product_id"]]) >= n):
                    M.D.calls.append(("REFUSED", kind, BY_ID[body["product_id"]]))
                    raise DeltaError(CAPMSG)
            return await real(method, path, body, signed)
        M.D.request = req

    def refused():
        return [c for c in M.D.calls if c[0] == "REFUSED"]

    def gold_book(db_):
        db_.live_delta_state.docs[0].pop("sizing", None)      # one contract a trade, as the gold desk trades
        db_.live_delta_state.docs[0]["wallet_at"] = CLOCK[0]

    gpk = [p for p in M.DESKS["gold"].picks if p.src == M.PREMIUM]
    tp_gold = lambda: [o for o in M.D.stop_orders if o["product_id"] == GOLD and o["stop_order_type"] == "take_profit_order"]  # noqa: E731

    # a gold trade: only its stop; a bitcoin trade: both, as before
    M.APP_TARGET_PRODUCTS = PROD_APP_TARGET
    db = fresh(gold=3885.0)
    gold_book(db)
    a = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    b = paper(db, "TL-04", "BTCUSD", -1, 69000.0, 69400.0, 68400.0, ago=20)
    await cyc(db)
    ta, tb = trade(db, a), trade(db, b)
    check("a new gold trade: only its stop goes on Delta; its target is kept for the app to watch, on the tick; no "
          "take-profit order is sent", ta["status"] == "open" and own_leg(ta, "stop")["state"] == "pending"
          and ta["legs"]["target_id"] is None and ta["legs"]["target_app"] == DR.fmt_tick(3895.0, 0.01) == "3895.00"
          and not tp_gold() and resting_on("XAUTUSD") == 1, ta["legs"])
    check("a new bitcoin trade: its stop AND its target on Delta, exactly as before", tb["status"] == "open"
          and own_leg(tb, "stop")["state"] == "pending" and own_leg(tb, "target")["state"] == "pending"
          and "target_app" not in tb["legs"], tb["legs"])
    advance(20)
    M.D.set_price("XAUTUSD", 3894.99)                      # bid 3894.975: a whisker under the target
    n0 = len(M.D.orders)
    await cyc(db)
    check("the bid under its target: it stays open and nothing is sent", trade(db, a)["status"] == "open"
          and len(M.D.orders) == n0, trade(db, a).get("close_reason"))
    advance(20)
    M.D.set_price("XAUTUSD", 3895.2)                       # bid 3895.185: at its target
    await cyc(db)
    t = trade(db, a)
    want = round((M.D.bid("XAUTUSD") - t["fill"]) * 0.001 * t["contracts"] - t["fees"], 4)
    check("the bid at its target: the app closed it at the market, its stop cancelled FIRST, the result read from the "
          "fill", t["status"] == "closed" and t["close_reason"] == M.APP_TARGET_WHY == "target reached, closed by the app"
          and own_leg(t, "stop")["state"] == "cancelled" and M.D.orders[-1]["side"] == "sell" and GOLD not in M.D.pos
          and abs(t["pnl_usd"] - want) < 1e-6 and t["pnl_usd"] > 0, (t.get("close_reason"), t.get("pnl_usd"), want))
    check("... and the bitcoin trade beside it carries on, its two orders resting", trade(db, b)["status"] == "open"
          and own_leg(trade(db, b), "target")["state"] == "pending")

    # a short: its target is reached when the ask is at or under it
    s1 = paper(db, "CP-23", "XAUUSD", -1, 3895.0, 3900.0, 3885.0, ago=10)
    advance(20)
    await cyc(db)
    ts = trade(db, s1)
    check("a gold short opened with only its stop on Delta", ts["status"] == "open" and ts["legs"]["target_app"] == "3885.00"
          and own_leg(ts, "stop")["side"] == "buy" and own_leg(ts, "target") is None, ts["legs"])
    advance(20)
    M.D.set_price("XAUTUSD", 3885.0)                       # ask 3885.015: not yet
    await cyc(db)
    check("the ask a tick over the short's target: still open", trade(db, s1)["status"] == "open")
    advance(20)
    M.D.set_price("XAUTUSD", 3884.98)                      # ask 3884.995: there
    await cyc(db)
    ts = trade(db, s1)
    check("the ask at the short's target: closed by the app with a market BUY at the ask", ts["status"] == "closed"
          and ts["close_reason"] == M.APP_TARGET_WHY and M.D.orders[-1]["side"] == "buy" and GOLD not in M.D.pos
          and ts["pnl_usd"] > 0, (ts.get("close_reason"), ts.get("pnl_usd")))

    # trades already open before the change hand their target over, ten a pass
    db = fresh(gold=3885.0)
    gold_book(db)
    M.APP_TARGET_PRODUCTS = frozenset()                    # before the change: both orders on Delta
    ids = [paper(db, p.acct, p.mkt, 1, 3885.0, 3880.0, 3895.0 + i, ago=60 - i) for i, p in enumerate(gpk[:12])]
    await cyc(db)
    check("before: twelve gold trades hold 24 orders on Delta (a stop and a target each)",
          all(trade(db, i)["status"] == "open" for i in ids) and resting_on("XAUTUSD") == 24, resting_on("XAUTUSD"))
    M.APP_TARGET_PRODUCTS = PROD_APP_TARGET                # the change, deployed
    n_mkt = len(M.D.orders)
    advance(20)
    await cyc(db)
    moved = [i for i in ids if trade(db, i)["legs"].get("target_app")]
    check("the first pass hands ten targets to the app (cancelled on Delta), the other two the next pass",
          len(moved) == 10 and resting_on("XAUTUSD") == 14, (len(moved), resting_on("XAUTUSD")))
    advance(20)
    await cyc(db)
    tt = [trade(db, i) for i in ids]
    check("then twelve trades hold twelve orders (their stops); each target kept at its own level; no position "
          "touched, nothing sent at the market", resting_on("XAUTUSD") == 12 and M.D.pos[GOLD]["size"] == 12
          and all(t["status"] == "open" and t["legs"]["target_id"] is None
                  and t["legs"]["target_app"] == DR.fmt_tick(3895.0 + k, 0.01) for k, t in enumerate(tt))
          and len(M.D.orders) == n_mkt and not tp_gold()[12:], [t["legs"].get("target_app") for t in tt])
    advance(20)
    M.D.set_price("XAUTUSD", 3896.5)                       # bid 3896.485: past the first two targets only
    await cyc(db)
    done = [i for i in ids if trade(db, i)["status"] == "closed"]
    check("price through two of the handed-over targets: exactly those two closed by the app",
          done == ids[:2] and all(trade(db, i)["close_reason"] == M.APP_TARGET_WHY for i in done)
          and M.D.pos[GOLD]["size"] == 10 and resting_on("XAUTUSD") == 10, done)

    # the handover races a fill, and a target cancelled on Delta by someone else
    db = fresh(gold=3885.0)
    gold_book(db)
    M.APP_TARGET_PRODUCTS = frozenset()
    r1 = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0, ago=40)
    r2 = paper(db, "YT-14", "XAUUSD", 1, 3885.0, 3878.0, 3899.0, ago=30)
    rb = paper(db, "TL-04", "BTCUSD", -1, 69000.0, 69400.0, 68400.0, ago=20)
    await cyc(db)
    t1 = trade(db, r1)
    tid1 = t1["legs"]["target_id"]
    real = M.D.request

    async def fills_first(method, path, body=None, signed=True):
        if method == "DELETE" and path.split("?")[0] == "/v2/orders" and str(body.get("id")) == str(tid1):
            o = M.D.stops[str(tid1)]
            if o["state"] == "pending":                    # it triggers and fills just before the cancel arrives
                px = float(o["limit_price"])
                _, comm = M.D._fill(o["product_id"], o["side"], int(o["size"]), px, False, "leg", order_id=tid1)
                o.update(state="closed", unfilled_size=0, average_fill_price=f"{px}", paid_commission=f"{comm}")
            raise DeltaError("DELETE /v2/orders: HTTP 400 {\"code\": \"open_order_not_found\"}")
        return await real(method, path, body, signed)
    M.D.request = fills_first
    M.D.stops[str(trade(db, r2)["legs"]["target_id"])]["state"] = "cancelled"     # someone cancels YT-14's target
    M.D.stops[str(trade(db, rb)["legs"]["target_id"])]["state"] = "cancelled"     # ... and TL-04's bitcoin target
    M.APP_TARGET_PRODUCTS = PROD_APP_TARGET
    n_tp = len([o for o in M.D.stop_orders if o["stop_order_type"] == "take_profit_order"])
    advance(20)
    await cyc(db)
    M.D.request = real
    t1, t2, tb = trade(db, r1), trade(db, r2), trade(db, rb)
    check("a target that filled as its handover began: recorded as the venue target at its own fill, the stop "
          "cancelled, nothing sent at the market", t1["status"] == "closed" and t1["close_reason"] == "venue target"
          and abs(t1["exit_price"] - 3895.0) < 1e-9 and own_leg(t1, "stop")["state"] == "cancelled"
          and len(M.D.orders) == 3, (t1.get("close_reason"), t1.get("exit_price"), len(M.D.orders)))
    check("a gold target cancelled on Delta by someone else: handed to the app, never put back",
          t2["status"] == "open" and t2["legs"]["target_id"] is None and t2["legs"]["target_app"] == "3899.00"
          and not t2["legs"].get("target_replaced"), t2["legs"])
    check("a bitcoin target cancelled the same way: put back on Delta, as before",
          tb["status"] == "open" and tb["legs"].get("target_replaced") and own_leg(tb, "target")["state"] == "pending"
          and len([o for o in M.D.stop_orders if o["stop_order_type"] == "take_profit_order"]) == n_tp + 1, tb["legs"])

    # Delta's limit, scaled down to 4 resting orders a product
    db = fresh(gold=3885.0)
    gold_book(db)
    M.APP_TARGET_PRODUCTS = frozenset()
    cap_at(4)
    two = [paper(db, p.acct, p.mkt, 1, 3885.0, 3880.0, 3895.0, ago=60 - i) for i, p in enumerate(gpk[:3])]
    await cyc(db)
    check("with a stop AND a target on Delta, a limit of 4 holds two trades (the third is refused)",
          [trade(db, i)["status"] for i in two] == ["open", "open", "skipped"], [trade(db, i)["status"] for i in two])
    db = fresh(gold=3885.0)
    gold_book(db)
    M.APP_TARGET_PRODUCTS = PROD_APP_TARGET
    cap_at(4)
    ids = [paper(db, p.acct, p.mkt, 1, 3885.0, 3880.0, 3895.0, ago=60 - i) for i, p in enumerate(gpk[:7])]
    await cyc(db)
    sts = [trade(db, i)["status"] for i in ids]
    sg = st_of(db, "gold")
    check("with only its stop on Delta, the same limit holds four", sts[:4] == ["open"] * 4 and resting_on("XAUTUSD") == 4,
          sts)
    check("the fifth signal: Delta refuses its entry for the limit; it is skipped and recorded as \"Delta's 100-order "
          "limit full\"", sts[4] == "skipped" and trade(db, ids[4])["reason"] == "Delta's 100-order limit full on XAUTUSD"
          and len(refused()) == 1, (trade(db, ids[4]).get("reason"), refused()))
    check("the sixth and seventh in the same pass: skipped the same way WITHOUT being sent", sts[5:] == ["skipped"] * 2
          and all(trade(db, i)["reason"] == "Delta's 100-order limit full on XAUTUSD" for i in ids[5:])
          and len(refused()) == 1, refused())
    check("the desk stays LIVE: not a venue error (no count, no last error); the account matches the four trades",
          sg["mode"] == "live" and not sg.get("errors_in_row") and "max_orders" not in str(sg.get("last_error") or "")
          and not sg.get("switched_off") and M.D.pos[GOLD]["size"] == 4, (sg.get("mode"), sg.get("errors_in_row"),
                                                                           sg.get("last_error")))
    nxt = paper(db, gpk[7].acct, gpk[7].mkt, 1, 3885.0, 3880.0, 3895.0, ago=5)
    advance(20)
    await cyc(db)
    check("a new signal while nothing has closed: skipped unsent", trade(db, nxt)["status"] == "skipped"
          and len(refused()) == 1, trade(db, nxt).get("reason"))
    close_paper(db, ids[0], "exit_signal", 3886.0)
    nx2 = paper(db, gpk[8].acct, gpk[8].mkt, 1, 3885.0, 3880.0, 3895.0, ago=5)
    advance(20)
    await cyc(db)
    check("a trade closes (its stop cancelled first, so its market close fits under the limit): room again, and the "
          "next signal goes in in the same pass", trade(db, ids[0])["status"] == "closed"
          and trade(db, nx2)["status"] == "open" and resting_on("XAUTUSD") == 4 and st_of(db, "gold")["mode"] == "live"
          and len(refused()) == 1, (trade(db, ids[0]).get("close_reason"), trade(db, nx2).get("reason"), refused()))
    nx3 = paper(db, gpk[9].acct, gpk[9].mkt, 1, 3885.0, 3880.0, 3895.0, ago=5)
    advance(20)
    await cyc(db)
    check("full again: the next signal is sent, refused, skipped; the desk stays on", trade(db, nx3)["status"] == "skipped"
          and len(refused()) == 2 and st_of(db, "gold")["mode"] == "live", refused())
    nx4 = paper(db, gpk[10].acct, gpk[10].mkt, 1, 3885.0, 3880.0, 3895.0, ago=5)
    advance(M.VENUE_FULL_RETRY_S + 1)
    await cyc(db)
    check("two minutes on with nothing closed: the next signal is tried again (refused, skipped)",
          trade(db, nx4)["status"] == "skipped" and len(refused()) == 3 and st_of(db, "gold")["mode"] == "live", refused())

    # a stop refused for the limit after the fill (a race): out at once, the desk stays on; any other refusal as before
    db = fresh(gold=3885.0)
    gold_book(db)
    cap_at(0, only="stop")
    rs = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    await cyc(db)
    t, sg = trade(db, rs), st_of(db, "gold")
    check("its stop refused for the limit: the trade is closed at once (never unprotected) and says why; the desk "
          "stays LIVE", t["status"] == "closed" and t["close_reason"] == "closed at once: Delta's 100-order limit full "
          "on XAUTUSD, no room for its stop" and GOLD not in M.D.pos and sg["mode"] == "live" and not sg.get("switched_off"),
          (t.get("close_reason"), sg.get("mode"), sg.get("switched_off")))
    rs2 = paper(db, "YT-14", "XAUUSD", 1, 3885.0, 3878.0, 3899.0, ago=5)
    advance(20)
    await cyc(db)
    check("... and the next gold signal is skipped unsent until room frees", trade(db, rs2)["status"] == "skipped"
          and trade(db, rs2)["reason"] == "Delta's 100-order limit full on XAUTUSD", trade(db, rs2).get("reason"))
    db = fresh(gold=3885.0)
    gold_book(db)
    M.D.fail["stop_order"] = "definite"
    ro = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    await cyc(db)
    t, sg = trade(db, ro), st_of(db, "gold")
    check("any other refusal of its stop: closed at once and the desk switches off, exactly as before",
          t["status"] == "closed" and "stop or target refused" in t["close_reason"] and sg["mode"] == "off"
          and "stop or target was refused" in (sg.get("switched_off") or ""), (t.get("close_reason"), sg.get("switched_off")))
    M.D.fail.pop("stop_order")
    db = fresh()
    cap_at(0, only="market")
    cb = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    sc = st_of(db, "crypto")
    check("the bitcoin desk too: an entry refused for the limit is skipped and the desk stays on",
          trade(db, cb)["status"] == "skipped" and trade(db, cb)["reason"] == "Delta's 100-order limit full on BTCUSD"
          and sc["mode"] == "live" and not sc.get("errors_in_row"), (trade(db, cb).get("reason"), sc.get("mode")))

    # a Gold Desk that cannot be read: its trade's target is still watched
    db = fresh(gold=3885.0)
    gold_book(db)

    def h1p(pid, tpl, side, entry, stop, target, ago=30):
        M._h1_coll().docs.append({"position_id": pid, "venue": "delta", "h1": True, "symbol": "XAUTUSD",
                                  "strategy_template": tpl, "side": side, "entry_price": entry, "stoploss": stop,
                                  "target": target, "qty": 0.296, "status": "OPEN", "opened_at": un(CLOCK[0] - ago),
                                  "exit_price": None, "exit_reason": None})
        return "H1|" + pid
    h = h1p("u1", "keltner_break", "BUY", 3885.0, 3880.0, 3895.0)
    await cyc(db)
    check("an H1 trade on the gold desk: only its stop on Delta", trade(db, h)["status"] == "open"
          and trade(db, h)["legs"]["target_app"] == "3895.00" and resting_on("XAUTUSD") == 1, trade(db, h).get("legs"))
    keep = M._h1_coll

    class _Down41:
        def find(self, *a, **k):
            raise RuntimeError("main database down")
    M._h1_coll = lambda: _Down41()
    advance(20)
    M.D.set_price("XAUTUSD", 3895.3)
    r = await cyc(db)
    t = trade(db, h)
    check("the Gold Desk unreadable when the price reaches the target: the app still closes it at the target (the "
          "stop alone would have waited)", "could not be read" in r["gold"].get("gold_desk", "") and t["status"] == "closed"
          and t["close_reason"] == M.APP_TARGET_WHY and GOLD not in M.D.pos, (t.get("status"), r["gold"].get("gold_desk")))
    M._h1_coll = keep

    # both gold books on XAUTUSD
    db = fresh(gold=3885.0)
    gold_book(db)
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="premium_gold")
    st_of(db, "premium_gold")["wallet_at"] = CLOCK[0]
    hb = h1p("u2", "ema_ribbon", "BUY", 3885.0, 3880.0, 3895.0)
    advance(30)
    M._h1_state_coll().docs[0]["last_run_at"] = un(CLOCK[0])
    await cyc(db)
    g2, p2 = trade(db, hb), next((d for d in db.live_pgold_trades.docs if d["_id"] == hb), None)
    check("the gold desk and the Premium Gold book each copy the H1 signal with only their own stop on Delta: two "
          "trades, two orders", r["ok"] and g2 and p2 and g2["status"] == p2["status"] == "open"
          and g2["legs"]["target_app"] == p2["legs"]["target_app"] == "3895.00" and resting_on("XAUTUSD") == 2
          and M.D.pos[GOLD]["size"] == 2, (r, g2 and g2.get("legs"), p2 and p2.get("legs")))
    advance(20)
    M._h1_state_coll().docs[0]["last_run_at"] = un(CLOCK[0])
    M.D.set_price("XAUTUSD", 3895.2)
    await cyc(db)
    g2, p2 = trade(db, hb), next((d for d in db.live_pgold_trades.docs if d["_id"] == hb), None)
    check("the price at the target: the app closes both, each its own contract; the account is flat and both desks "
          "stay live", g2["status"] == p2["status"] == "closed" and g2["close_reason"] == p2["close_reason"] == M.APP_TARGET_WHY
          and GOLD not in M.D.pos and resting_on("XAUTUSD") == 0 and st_of(db, "gold")["mode"] == "live"
          and st_of(db, "premium_gold")["mode"] == "live", (g2.get("close_reason"), p2.get("close_reason")))

    # what the page tells the owner
    gn, pn, cn = M.DESKS["gold"].notes, M.DESKS["premium_gold"].notes, M.DESKS["crypto"].notes
    check("the page's notes: the gold desk and the Premium Gold book say the target is the app's and name Delta's "
          "100-order limit; the bitcoin desk's notes are unchanged",
          any("Delta's 100-order limit full" in n for n in gn) and any("Delta's 100-order limit full" in n for n in pn)
          and not any("stop and target live on Delta" in n for n in gn + pn)
          and any("Each trade's stop and target live on Delta itself" in n for n in cn)
          and not any("100-order" in n for n in cn))
    M.APP_TARGET_PRODUCTS = frozenset()

    # ── 42. 26 Nov: the refusal names the numbers and the order that makes them match ─────────────────
    section("42. 26 Nov: a refused switch-on says what the account holds, what the trades hold, and what order fixes it")
    db = fresh(mode="off")
    db.live_crypto_trades.docs.append({"_id": "nj47", "acct": "NJ-47", "mkt": "BTCUSD", "product": "BTCUSD", "mode": "live",
                                       "side": -1, "contracts": 1, "status": "open", "protect": "own"})
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="crypto")      # the account flat, the desk short 1
    check("the account flat under the desk's short: refused, naming the trade and the sell that puts it back",
          not r["ok"] and "BTCUSD: the account holds none, the desks' open trades -1 (NJ-47 short 1): sell 1 BTCUSD on "
          "Delta to put them back" in r["why"] and "close" not in r["why"] and st_of(db, "crypto")["mode"] == "off", r["why"])
    db.live_crypto_trades.docs[-1]["side"] = 1
    M.D.pos[BTC] = {"size": 14, "entry": 69000.0}                       # 13 bought by hand beside the desk's long 1
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="crypto")
    check("13 bought by hand beside the desk's long 1: sell 13, and closing the whole position is ruled out",
          not r["ok"] and "the account holds +14 contracts, the desks' open trades +1 (NJ-47 long 1): sell 13 BTCUSD on "
          "Delta to make them match (closing the whole position would close the trades' own contracts too)" in r["why"]
          and "ETHUSD" not in r["why"], r["why"])
    M.D.pos[BTC] = {"size": 1, "entry": 69000.0}
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="crypto")
    check("once the account matches, it goes live", r["ok"] and st_of(db, "crypto")["mode"] == "live", r)
    check("no order was sent by any refusal", not M.D.orders, M.D.orders)


if __name__ == "__main__":
    asyncio.run(main())
    finish()
