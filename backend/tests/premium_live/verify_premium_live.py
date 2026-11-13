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
leverage set to 10x before going live; three venue errors switching the desk off.
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

    def _fill(self, pid, side, size, price, reduce_only=False, kind="market"):
        sym = BY_ID[pid]
        cv = float(SPECS[sym]["cv"])
        comm = abs(size * cv * price) * float(SPECS[sym]["taker"]) * 1.18
        self.oid += 1
        oid = str(self.oid)
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
        """Move the market; a resting bracket leg that the move crosses fills and the other is cancelled."""
        self.mid[sym] = px
        pid = SPECS[sym]["id"]
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
            if f == "ambiguous":            # the order went through; the answer did not come back
                raise DeltaError("POST /v2/orders: no answer (ReadTimeout)", ambiguous=True)
            return {"id": int(oid), "size": size, "unfilled_size": "0", "average_fill_price": f"{px}",
                    "paid_commission": f"{comm}", "state": "closed"}
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
            return {}
        raise AssertionError(f"unexpected call {method} {path}")


def fresh(mode="live", btc=69000.0, gold=3885.0):
    db = SimpleNamespace(premium_trades=Coll("pt"), premium_meta=Coll("pm"), live_delta_trades=Coll("lt"),
                         live_delta_state=Coll("ls"))
    db.premium_meta.docs.append({"_id": "status", "segments_at": datetime.fromtimestamp(CLOCK[0], UTC).isoformat()})
    M._db = lambda: db
    M.D = FakeDelta()
    M.D.mid.update(BTCUSD=btc, XAUTUSD=gold)
    if mode != "off":
        db.live_delta_state.docs.append({"_id": "state", "mode": mode, "since": CLOCK[0] - 3600, "errors_in_row": 0,
                                         "pin_fails": [], "products": {}})
    return db


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


def trade(db, tid):
    return next((d for d in db.live_delta_trades.docs if d["_id"] == tid), None)


def heartbeat(db):
    db.premium_meta.docs[0]["segments_at"] = datetime.fromtimestamp(CLOCK[0], UTC).isoformat()


async def cyc(db):
    heartbeat(db)
    return await M.cycle()


async def main():
    BTC, GOLD = 27, 131253
    # ── 1. a live bitcoin entry, sized by risk, with the stop on the venue ─────────────────────────
    section("1. A live entry: $5 of risk, the paper's stop on Delta, no target when the paper has none")
    db = fresh()
    t1 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    r = await cyc(db)
    t = trade(db, t1)
    ask = M.D.ask("BTCUSD")
    want = min(math.floor(5 / ((ask - 68650.0) * 0.001)), math.floor(2500 / (ask * 0.001)))
    check("a market buy of the risk-sized contracts went in", t and t["status"] == "open" and t["contracts"] == want
          and M.D.orders[-1]["side"] == "buy" and M.D.pos[BTC]["size"] == want, f"{r['entered']} / {want} contracts")
    check("its risk at the stop is at most $5", t["plan"]["risk_usd"] <= 5.0 + 1e-9, t["plan"])
    lg = M.D.legs.get(BTC)
    check("the venue holds the paper's stop, its limit 20% of the risk past it, no target leg, last-traded trigger",
          lg and lg["stop"][0] == 68650.0 and abs(lg["stop"][1] - (68650.0 - (ask - 68650.0) * 0.2)) <= 0.5
          and lg["tp"] is None and lg["trigger"] == "last_traded_price", lg)
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
    check("no leg is left on the product", BTC not in M.D.legs and BTC not in M.D.pos)

    # ── 3. the paper's own exit closes it ───────────────────────────────────────────────────────────
    section("3. The paper trade exits on its signal: the real one is closed at the market")
    db = fresh()
    t3 = paper(db, "TD-02", "BTCUSD", -1, 69000.0, 69300.0, None)
    await cyc(db)
    advance(1800)
    M.D.set_price("BTCUSD", 68800.0)
    close_paper(db, t3, "exit_signal", 68800.0)
    await cyc(db)
    t = trade(db, t3)
    check("a reduce-only buy closed the short", M.D.orders[-1].get("reduce_only") is True and M.D.orders[-1]["side"] == "buy"
          and BTC not in M.D.pos)
    check("recorded with the paper's reason and a profit (short from 69,000 to 68,800)",
          t["status"] == "closed" and t["close_reason"] == "paper exit: exit_signal" and t["pnl_usd"] > 0, t.get("pnl_usd"))
    check("the stop leg was cancelled after the close", BTC not in M.D.legs)

    # ── 4. a gold trade reaches its target on Delta ─────────────────────────────────────────────────
    section("4. Gold: target and stop both on Delta; the target fills")
    db = fresh(gold=3885.0)
    t4 = paper(db, "DR-01", "XAUTUSD", 1, 3885.0, 3880.0, 3895.0)
    await cyc(db)
    t = trade(db, t4)
    lg = M.D.legs.get(GOLD)
    check("both legs on the venue, on the 0.01 tick", lg and lg["stop"][0] == 3880.0 and lg["tp"] == (3895.0, 3895.0), lg)
    advance(900)
    M.D.set_price("XAUTUSD", 3895.5)
    await cyc(db)
    t = trade(db, t4)
    rr = (3895.0 - t["fill"]) / (t["fill"] - 3880.0)
    want = t["plan"]["risk_usd"] * rr - t["fees"]
    check("closed as a venue target: the trade's risk x its reward ratio, less fees (the $2,500 cap bound its size)",
          t["status"] == "closed" and t["close_reason"] == "venue target" and abs(t["pnl_usd"] - want) < 0.02
          and t["plan"]["capped"], (t["pnl_usd"], round(want, 2), t["plan"]["risk_usd"]))

    # ── 5. one position per product, and the account's own positions ───────────────────────────────
    section("5. One position per product; a position the desk does not own blocks the product")
    db = fresh()
    a = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    b = paper(db, "RU-04", "BTCUSD", -1, 69000.0, 69400.0, 68400.0, ago=20)
    await cyc(db)
    check("the first bitcoin signal opened, the second was skipped (Delta nets by product)",
          trade(db, a)["status"] == "open" and trade(db, b)["status"] == "skipped" and "already holds" in trade(db, b)["reason"],
          trade(db, b)["reason"])
    M.D.pos[GOLD] = {"size": 50, "entry": 3880.0}          # the owner's own gold position
    g = paper(db, "YT-14", "XAUUSD", 1, 3885.0, 3878.0, 3899.0)
    await cyc(db)
    check("a gold signal is skipped while the account holds gold it did not open",
          trade(db, g)["status"] == "skipped" and "account already holds" in trade(db, g)["reason"], trade(db, g)["reason"])
    check("the owner's position was not touched", M.D.pos[GOLD]["size"] == 50)

    # ── 6. late, drifted and outside the levels ─────────────────────────────────────────────────────
    section("6. Late or moved signals are refused, never chased")
    db = fresh()
    late = paper(db, "TH-05", "BTCUSD", 1, 69000.0, 68700.0, None, ago=400)
    await cyc(db)
    check("seen 6+ minutes after its entry: skipped", trade(db, late)["status"] == "skipped" and "after its entry" in trade(db, late)["reason"])
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
    section("8. Delta refuses the bracket: the position is closed at once and the desk switches off")
    db = fresh()
    M.D.fail["bracket"] = "definite"
    t8 = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    t, st = trade(db, t8), db.live_delta_state.docs[0]
    check("the position was closed in the same pass", BTC not in M.D.pos and t["status"] == "closed"
          and "bracket refused" in t["close_reason"], t.get("close_reason"))
    check("the desk switched itself off and says why", st["mode"] == "off" and "bracket refused" in (st.get("switched_off") or ""))

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
    check("adopted from the account and given its stop", t["status"] == "open" and t.get("recovered")
          and M.D.legs.get(BTC, {}).get("stop", (0,))[0] == 68650.0, (t["status"], M.D.legs.get(BTC)))
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
    day_loss = sum(t.get("pnl_usd") or 0 for t in db.live_delta_trades.docs if t["status"] == "closed")
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
    t11 = paper(db, "RU-04", "BTCUSD", 1, 69000.0, 68300.0, 70400.0)
    await cyc(db)
    db.premium_trades.docs = [d for d in db.premium_trades.docs if d["_id"] != t11]
    await cyc(db)
    check("first noticed, not closed at once", trade(db, t11)["status"] == "open" and trade(db, t11).get("paper_missing_since"))
    advance(301)
    await cyc(db)
    check("closed after five minutes gone", trade(db, t11)["status"] == "closed"
          and trade(db, t11)["close_reason"] == "the paper trade disappeared" and BTC not in M.D.pos)
    db = fresh()
    t11b = paper(db, "RU-04", "BTCUSD", 1, 69000.0, 68300.0, 70400.0)
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
    r = await M.set_mode("live", "0000", "REAL MONEY")
    check("a wrong PIN is refused and counted", not r["ok"] and "wrong PIN" in r["why"], r["why"])
    r = await M.set_mode("live", PIN, "yes")
    check("the right PIN without the words is refused", not r["ok"] and "REAL MONEY" in r["why"], r["why"])
    M.D.pos[BTC] = {"size": 3, "entry": 69000.0}
    r = await M.set_mode("live", PIN, "real money")
    check("a position the desk does not own blocks going live", not r["ok"] and "already holds BTCUSD" in r["why"], r["why"])
    M.D.pos.pop(BTC)
    r = await M.set_mode("live", PIN, "REAL MONEY")
    check("then it goes live, with leverage at 10x on both products (Delta's defaults were 200x and 100x)",
          r["ok"] and M.D.lev[BTC] == 10 and M.D.lev[GOLD] == 10 and db.live_delta_state.docs[0]["mode"] == "live", r)
    for _ in range(5):
        await M.set_mode("live", "0000", "REAL MONEY")
    r = await M.set_mode("live", PIN, "REAL MONEY")
    check("five wrong PINs lock going live for an hour, even with the right one", not r["ok"] and "locked" in r["why"], r["why"])
    advance(3601)
    r = await M.set_mode("live", PIN, "REAL MONEY")
    check("an hour later it works again", r["ok"], r)
    r = await M.set_mode("off")
    check("switching off needs no PIN", r["ok"] and db.live_delta_state.docs[0]["mode"] == "off")
    db = fresh()
    f = paper(db, "TH-01", "BTCUSD", 1, 69000.0, 68650.0, None)
    await cyc(db)
    r = await M.flatten("0000")
    check("flatten with a wrong PIN does nothing", not r["ok"] and BTC in M.D.pos)
    heartbeat(db)
    r = await M.flatten(PIN)
    check("flatten closes every open position and switches off", r["ok"] and BTC not in M.D.pos
          and trade(db, f)["status"] == "closed" and db.live_delta_state.docs[0]["mode"] == "off")

    # ── 14. off still manages; errors switch off ────────────────────────────────────────────────────
    section("14. Off still manages what is open; three venue errors in a row switch the desk off")
    db = fresh()
    o14 = paper(db, "RU-04", "BTCUSD", 1, 69000.0, 68300.0, 70400.0)
    await cyc(db)
    await M.set_mode("off")
    advance(600)
    close_paper(db, o14, "time", 69100.0)
    await cyc(db)
    check("switched off, the open trade still closed with its paper exit", trade(db, o14)["status"] == "closed" and BTC not in M.D.pos)
    db = fresh()
    M.D.fail["positions"] = "definite"
    for _ in range(3):
        await cyc(db)
    st = db.live_delta_state.docs[0]
    check("three failed position reads in a row: off", st["mode"] == "off" and st["errors_in_row"] >= 3, st.get("switched_off"))

    # ── 15. the read model ──────────────────────────────────────────────────────────────────────────
    section("15. What the page reads")
    s = await M.status()
    check("status: mode, keys, PIN, limits, the ten picks, notes", s["keys"] and s["pin_set"] and len(s["picks"]) == 10
          and s["limits"]["risk_usd"] == 5 and s["limits"]["daily_stop_usd"] == 20 and s["limits"]["leverage"] == 10
          and len(s["notes"]) >= 5)
    check("the secrets never appear in what the page reads", "s\n" not in str(s) and SALT not in str(s) and "DELTA_API_SECRET" not in str(s))


if __name__ == "__main__":
    asyncio.run(main())
    finish()
