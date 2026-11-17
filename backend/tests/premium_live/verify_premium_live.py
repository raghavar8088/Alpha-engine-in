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
"""

import asyncio
import hashlib
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gold_desk"))
from _harness import Coll, check, finish, section  # noqa: E402

from app.services import delta_rest as DR  # noqa: E402
from app.services import premium_live as M  # noqa: E402
from app.services.delta_rest import Delta, DeltaError  # noqa: E402

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
         "XAUTUSD": {"id": 131253, "cv": "0.001", "tick": "0.01", "mm": "0.5", "taker": "0.0001", "spread": 0.03, "lev": 100}}
BY_ID = {v["id"]: k for k, v in SPECS.items()}


class FakeDelta(Delta):
    def __init__(self):
        super().__init__()
        self.mid = {"BTCUSD": 69000.0, "XAUTUSD": 3885.0}
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


def fresh(mode="live", btc=69000.0, gold=3885.0):
    db = SimpleNamespace(premium_trades=Coll("pt"), premium_meta=Coll("pm"), live_delta_trades=Coll("lt"),
                         live_delta_state=Coll("ls"), live_crypto_trades=Coll("ct"), live_crypto_state=Coll("cs"))
    db.premium_meta.docs.append({"_id": "status", "segments_at": datetime.fromtimestamp(CLOCK[0], UTC).isoformat()})
    M._db = lambda: db
    M.D = FakeDelta()
    M.D.mid.update(BTCUSD=btc, XAUTUSD=gold)
    if mode != "off":
        for coll in (db.live_delta_state, db.live_crypto_state):
            coll.docs.append({"_id": "state", "mode": mode, "since": CLOCK[0] - 3600, "errors_in_row": 0,
                              "pin_fails": [], "products": {}, "sizing": "risk"})   # dollar sizing; 22 tests one contract
    return db


def st_of(db, desk):
    coll = db.live_crypto_state if desk == "crypto" else db.live_delta_state
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
    return next((d for d in db.live_crypto_trades.docs + db.live_delta_trades.docs if d["_id"] == tid), None)


def heartbeat(db):
    db.premium_meta.docs[0]["segments_at"] = datetime.fromtimestamp(CLOCK[0], UTC).isoformat()


async def cyc(db):
    heartbeat(db)
    return await M.cycle()


async def main():
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
    section("6. Late or moved signals are refused, never chased")
    db = fresh()
    late = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, None, ago=700)
    await cyc(db)
    check("bitcoin seen 11+ minutes after its entry: skipped (its limit is 10)", trade(db, late)["status"] == "skipped"
          and "after its entry (limit 10)" in trade(db, late)["reason"], trade(db, late)["reason"])
    db = fresh(btc=69150.0)
    drift = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, None)
    await cyc(db)
    check("the market already 50% of the risk away: skipped", trade(db, drift)["status"] == "skipped"
          and "moved" in trade(db, drift)["reason"], trade(db, drift)["reason"])
    db = fresh(btc=68690.0)
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
    section("10. The $20 daily loss stop, and its reset the next day (IST)")
    db = fresh()
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
    await M.cycle()                                             # no heartbeat: the desk last wrote 25 minutes ago
    check("a desk silent for 20+ minutes: no new entry", trade(db, stale)["status"] == "skipped"
          and "not updated" in trade(db, stale)["reason"])
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
    check("a position the desk does not own blocks going live", not r["ok"] and "already holds BTCUSD" in r["why"], r["why"])
    M.D.pos.pop(BTC)
    r = await M.set_mode("live", PIN, "REAL MONEY", desk="crypto")
    check("then it goes live, with leverage at 10x on BTCUSD only (gold keeps Delta's default until its own desk arms)",
          r["ok"] and M.D.lev[BTC] == 10 and M.D.lev[GOLD] == 100 and st_of(db, "crypto")["mode"] == "live"
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
    check("status (gold, the original routes): mode, keys, PIN, limits, its seven gold picks, notes", s["keys"] and s["pin_set"]
          and s["desk"] == "gold" and len(s["picks"]) == 7 and {p["product"] for p in s["picks"]} == {"XAUTUSD"}
          and s["limits"]["risk_usd"] == 5 and s["limits"]["daily_stop_usd"] == 20 and s["limits"]["leverage"] == 10
          and len(s["notes"]) >= 5)
    c = await M.status("crypto")
    check("status (crypto): TH-05, TL-04, TH-01 and TD-02 on BTCUSD, $5 a trade, a $20 daily stop",
          c["desk"] == "crypto" and [p["acct"] for p in c["picks"]] == ["TH-05", "TL-04", "TH-01", "TD-02"]
          and {p["product"] for p in c["picks"]} == {"BTCUSD"} and c["limits"]["risk_usd"] == 5
          and c["limits"]["daily_stop_usd"] == 20 and c["picked_at"].startswith("2026-11-14"), [p["acct"] for p in c["picks"]])
    check("an unknown desk is refused", "error" in await M.status("nope") and not (await M.set_mode("off", desk="nope"))["ok"])
    check("the secrets never appear in what the page reads", "s\n" not in str(s) and SALT not in str(s) and "DELTA_API_SECRET" not in str(s))
    # ── 16. two desks ─────────────────────────────────────────────────────────────
    section("16. Two desks: each trades only its own picks and its own product")
    db = fresh()
    b16 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    g16 = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    old = paper(db, "RU-04", "BTCUSD", 1, 69000.0, 68650.0, None, ago=20)     # a former gold-desk bitcoin pick
    tlg = paper(db, "CP-24", "XAUUSD", 1, 3885.0, 3880.0, 3895.0, ago=20)     # a gold book that is not a pick (TL-04's
                                                                              # gold book became one on 16 Nov)
    await cyc(db)
    check("the bitcoin trade is the crypto desk's, the gold trade the gold desk's",
          [d["_id"] for d in db.live_crypto_trades.docs] == [b16] and [d["_id"] for d in db.live_delta_trades.docs] == [g16],
          ([d["_id"] for d in db.live_crypto_trades.docs], [d["_id"] for d in db.live_delta_trades.docs]))
    check("a former bitcoin pick (RU-04) and a gold book that is not a pick are ignored by both desks: no record, no order",
          trade(db, old) is None and trade(db, tlg) is None and len(M.D.orders) == 2)
    check("one position on each product", M.D.pos[BTC]["size"] > 0 and M.D.pos[GOLD]["size"] > 0)
    # ── 17. a bitcoin trade from before the split ───────────────────────────────────────
    section("17. A live bitcoin trade the gold desk opened before the split is managed by it to its close")
    db = fresh()
    leg = paper(db, "RU-04", "BTCUSD", 1, 69000.0, 68300.0, 70400.0, ago=600)
    M.D.pos[BTC] = {"size": 7, "entry": 69000.0}
    db.live_delta_trades.docs.append({"_id": leg, "acct": "RU-04", "mkt": "BTCUSD", "product": "BTCUSD", "name": "earlier pick",
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
    section("18. Each desk has its own switch and its own $20 daily stop")
    db = fresh()
    await M.set_mode("off")                                   # the gold desk only
    g18 = paper(db, "YT-14", "XAUUSD", 1, 3885.0, 3878.0, 3899.0)
    b18 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    check("gold off: its signal is not taken; crypto live: its signal is", trade(db, g18) is None
          and trade(db, b18)["status"] == "open")
    db = fresh()
    db.live_crypto_trades.docs.append({"_id": "lost-today", "acct": "TH-05", "mkt": "BTCUSD", "product": "BTCUSD", "mode": "live",
                                       "side": 1, "status": "closed", "day_closed": M._day(), "pnl_usd": -25.0})
    b18b = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68650.0, None)
    g18b = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    await cyc(db)
    check("the crypto desk's daily stop does not stop the gold desk", trade(db, b18b)["status"] == "skipped"
          and "daily loss stop" in trade(db, b18b)["reason"] and trade(db, g18b)["status"] == "open",
          (trade(db, b18b)["reason"], trade(db, g18b)["status"]))
    # ── 19. ten minutes on the bitcoin desk, five on the gold desk ─────────────────────────────────
    section("19. A late signal: both desks copy one seen up to 10 minutes late (15 Nov), never later")
    db = fresh()
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
    check("the page reads each desk's own limit, and the bitcoin notes say 10 minutes", c["limits"]["max_lag_s"] == 600
          and g["limits"]["max_lag_s"] == 600 and any("10 minutes" in n for n in c["notes"]), (c["limits"], g["limits"]))
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
    section("22. One contract a trade, the smallest order, unless the owner picks $1-$5; TD-02 and CP-06 added")
    db = fresh()
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
    db = fresh()
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
    check("the picks: TD-02 joins TH-05, TL-04 and TH-01; CP-06 then TL-04's gold book join the five gold; each new one "
          "carries its own pick time",
          [p["acct"] for p in c["picks"]] == ["TH-05", "TL-04", "TH-01", "TD-02"]
          and [p["acct"] for p in g["picks"]][-2:] == ["CP-06", "TL-04"] and len(g["picks"]) == 7
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


if __name__ == "__main__":
    asyncio.run(main())
    finish()
