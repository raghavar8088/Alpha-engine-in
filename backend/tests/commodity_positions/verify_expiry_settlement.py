"""Can a position held THROUGH EXPIRY be closed, and at an honest price?

It could not. `exit_position` asked Angel for a live price, and Angel never quotes a token
whose contract has stopped trading — so the close was refused with "Angel returned no price
— cannot close at an invented level" and the leg stayed in the book for ever, blocking
margin and showing whatever price happened to be its last successful mark. Two legs of the
same expired straddle could therefore show marks implying two DIFFERENT futures prices,
because each leg's last quote landed at a different moment.

This runs entirely on stubs — no Mongo, no Angel, no scratch account on the shared cluster
— because what is being checked is the pricing decision, not the plumbing. Every collection
and quote below is a fake whose contents the test chooses, which is the only way to assert
what happens when Angel answers with NOTHING.

What has to hold, in the order the price is looked for:
  * an expired option closes at its INTRINSIC value against the settlement close of the
    future it was actually written on, fetched from that future's own token — the one
    source specific to the contract, and the one the exchange itself settles against
  * that close is asked for ONCE and cached, because the mark-to-market pass runs every
    twenty seconds against an endpoint that throttles at one request every three
  * the bar store is second, and only when its bar is the RIGHT contract: the poller
    re-upserts its whole history against today's front month, so a bar dated on a past
    expiry day carries October's future, not the September one that settled the option
  * a live future is third, and the fill says plainly that it is a later price on a later
    contract rather than passing it off as a settlement
  * the last mark this desk recorded is fourth, and says it is a recorded mark
  * with nothing at all, the close is REFUSED rather than priced at an invented level
  * a LIVE contract Angel merely failed to quote is still refused — the original guard is
    intact, it just no longer fires on contracts that can never be quoted again
  * closing an expired leg books the settlement P&L and releases the position

Run: python -m tests.commodity_positions.verify_expiry_settlement
"""
import asyncio
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

import app.services.commodity_bars as _bars
import app.services.commodity_positions as cp

IST = timezone(timedelta(hours=5, minutes=30))
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# --------------------------------------------------------------------------------
# Stubs
# --------------------------------------------------------------------------------


def _get(doc: dict, path: str):
    """Mongo dotted-path read — `_open_group` queries on `instrument.expiry`."""
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches(doc: dict, query: dict) -> bool:
    for key, want in query.items():
        got = _get(doc, key)
        if isinstance(want, dict):
            for op, val in want.items():
                if op == "$gte" and not (got is not None and got >= val):
                    return False
                if op == "$lt" and not (got is not None and got < val):
                    return False
                if op == "$ne" and got == val:
                    return False
                if op == "$in" and got not in val:
                    return False
        elif got != want:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        if isinstance(key, list):
            key, direction = key[0]
        self._docs = sorted(self._docs, key=lambda d: (_get(d, key) is None, _get(d, key)),
                            reverse=direction < 0)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class FakeCollection:
    """Enough of a Mongo collection for this module's queries, including the `_id` the
    service writes back through — a fake without one hides a real KeyError."""

    _seq = 0

    def __init__(self, docs=None):
        self.docs = []
        for d in docs or []:
            self.docs.append({"_id": self._next_id(), **dict(d)})

    @classmethod
    def _next_id(cls):
        cls._seq += 1
        return f"oid{cls._seq}"

    async def find_one(self, query, projection=None, sort=None):
        hits = [d for d in self.docs if _matches(d, query)]
        if sort:
            key, direction = sort[0]
            hits.sort(key=lambda d: (_get(d, key) is None, _get(d, key)), reverse=direction < 0)
        return dict(hits[0]) if hits else None

    def find(self, query, projection=None):
        return _Cursor([dict(d) for d in self.docs if _matches(d, query)])

    async def insert_one(self, doc):
        self.docs.append({"_id": self._next_id(), **dict(doc)})

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _matches(d, query):
                d.update(update.get("$set", {}))
                return
        if upsert:
            self.docs.append({**query, **update.get("$set", {})})

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))

    async def distinct(self, field, query=None):
        return sorted({_get(d, field) for d in self.docs
                       if _matches(d, query or {}) and _get(d, field) is not None})

    async def bulk_write(self, ops, ordered=False):
        return None


class FakeAngel:
    """Angel with a quote list and a candle list, kept separate on purpose.

    That separation is the whole point: the real Angel will not QUOTE a token whose contract
    has expired but will still serve its HISTORY, and every fallback below turns on which of
    the two answers. A token absent from `prices` simply does not come back in the quote
    response, which is exactly what an expired one does."""

    def __init__(self, prices: dict[str, float] | None = None,
                 candles: dict[str, list[list]] | None = None):
        self.prices = prices or {}
        self._candles = candles or {}
        self.candle_calls = 0

    async def ltp(self, payload):
        return {tok: self.prices[tok] for ex in payload for tok in payload[ex]
                if tok in self.prices}

    async def candles(self, exchange, symbol_token, resolution, from_dt, to_dt):
        self.candle_calls += 1
        return self._candles.get(str(symbol_token), [])


# --------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------

SYMBOL = "CRUDEOILM"
MULT = cp.multiplier(SYMBOL)          # 10 barrels per lot
TODAY = date.today()
OPT_EXPIRY = (TODAY - timedelta(days=6)).isoformat()      # expired last week
FUT_EXPIRY = (TODAY - timedelta(days=4)).isoformat()      # the future it was written on
LIVE_FUT_EXPIRY = (TODAY + timedelta(days=25)).isoformat()
LIVE_OPT_EXPIRY = (TODAY + timedelta(days=20)).isoformat()
STRIKE = 8350.0
SETTLE_CLOSE = 8214.0                 # the future's close on the option's expiry day
LIVE_FUT_PX = 8600.0                  # a different, later price


def option_inst(expiry=OPT_EXPIRY, option_type="PE", token="990001"):
    return {"symbol": f"{SYMBOL}{expiry}{STRIKE:g}{option_type}",
            "underlying_symbol": SYMBOL, "expiry": expiry, "strike": STRIKE,
            "option_type": option_type, "asset_class": cp.OPTION_CLASS,
            "angel_token": token, "tick_size": 100}


def future_inst(expiry, token):
    return {"symbol": f"{SYMBOL}{expiry}FUT", "underlying_symbol": SYMBOL,
            "expiry": expiry, "asset_class": cp.FUTURE_CLASS,
            "angel_token": token, "tick_size": 100}


def daily_bar(day: str, close: float, expiry: str, symbol: str = SYMBOL):
    ts = datetime.strptime(day, "%Y-%m-%d").replace(hour=9, tzinfo=IST)
    return {"symbol": symbol, "timeframe": "1d", "ts": ts.astimezone(timezone.utc),
            "open": close, "high": close, "low": close, "close": close,
            "volume": 1, "expiry": expiry}


def daily_candle(day: str, close: float):
    """One row shaped like Angel's — [timestamp, o, h, l, c, v]."""
    return [f"{day}T09:00:00+05:30", close, close, close, close, 1]


def install(*, bars=None, instruments=None, prices=None, positions=None, candles=None):
    cp.commodity_bars_collection = FakeCollection(bars or [])
    cp.instruments_collection = FakeCollection(instruments or [])
    cp.commodity_pos_positions_collection = FakeCollection(positions or [])
    cp.commodity_pos_orders_collection = FakeCollection([])
    cp.angel_client = FakeAngel(prices or {}, candles or {})
    # A settlement close never changes, so the service caches it for the life of the
    # process. Each scenario below installs a DIFFERENT world, so the cache has to go with
    # it — otherwise the second scenario silently asserts against the first one's answer.
    cp._SETTLE_CACHE.clear()
    cp._SETTLE_MISSES.clear()
    # The candle pacer is shared with the bar poller and waits 3s between calls. Real and
    # necessary against Angel; pure dead time against a fake.
    _bars.CANDLE_MIN_INTERVAL_S = 0.0
    return cp.angel_client


BARS = [daily_bar(OPT_EXPIRY, SETTLE_CLOSE, FUT_EXPIRY)]
CANDLES = {"880001": [daily_candle(OPT_EXPIRY, SETTLE_CLOSE)]}
INSTRUMENTS = [option_inst(), option_inst(option_type="CE", token="990002"),
               future_inst(FUT_EXPIRY, "880001"), future_inst(LIVE_FUT_EXPIRY, "880002")]


# --------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------


async def check_is_expired() -> None:
    print("is_expired — the expiry day itself still trades")
    check("yesterday is expired", cp.is_expired((TODAY - timedelta(days=1)).isoformat()))
    check("today is NOT expired", not cp.is_expired(TODAY.isoformat()))
    check("tomorrow is NOT expired", not cp.is_expired((TODAY + timedelta(days=1)).isoformat()))
    check("a contract with no expiry is not treated as expired", not cp.is_expired(None))


async def check_intrinsic() -> None:
    print("\nsettlement — intrinsic against the expiry-day close of the OWN underlying future")
    install(bars=[], instruments=INSTRUMENTS, prices={"880002": LIVE_FUT_PX}, candles=CANDLES)

    px, basis = await cp.settlement_price(option_inst(option_type="PE"), last_mark=126.35)
    want = STRIKE - SETTLE_CLOSE                       # 8350 - 8214 = 136 in the money
    check("an ITM put settles at strike - future", px == want, f"{px} vs {want}")
    check("the basis names the close it used", str(SETTLE_CLOSE) in basis.replace(",", ""),
          basis)
    check("the settlement close beats the live future, which is 386 higher",
          "8,600" not in basis, basis)

    px, _ = await cp.settlement_price(option_inst(option_type="CE"), last_mark=500.0)
    check("the matching OTM call settles at ZERO, not at its stale 500 mark", px == 0.0,
          f"{px}")

    px, _ = await cp.settlement_price(
        {**option_inst(option_type="CE"), "strike": 8000.0}, last_mark=1.0)
    check("an ITM call settles at future - strike", px == SETTLE_CLOSE - 8000.0, f"{px}")


async def check_cached() -> None:
    print("\nsettlement — the close is asked for ONCE, not on every mark")
    angel = install(bars=[], instruments=INSTRUMENTS, prices={"880002": LIVE_FUT_PX},
                    candles=CANDLES)
    for _ in range(5):
        await cp.settlement_price(option_inst(option_type="PE"), last_mark=126.35)
    check("five settlements cost one candle request", angel.candle_calls == 1,
          f"{angel.candle_calls} calls")


async def check_wrong_contract_ignored() -> None:
    print("\nsettlement — the bar store holds TODAY's front month, not that day's")
    # Angel is silent, so the store is next. Its bar is dated on the option's expiry day but
    # carries the LIVE (October) future, because the poller re-upserts its whole history
    # against whatever is front month now. Settling a September option against it would be
    # settling against the wrong contract.
    install(bars=[daily_bar(OPT_EXPIRY, 9999.0, LIVE_FUT_EXPIRY)],
            instruments=INSTRUMENTS, prices={"880002": LIVE_FUT_PX}, candles={})
    px, basis = await cp.settlement_price(option_inst(option_type="PE"), last_mark=126.35)
    check("the 9999 close on the wrong contract is not used", px != STRIKE - 9999.0, basis)
    check("it falls through to the live future instead",
          px == max(0.0, STRIKE - LIVE_FUT_PX), f"{px}")


async def check_store_used_when_right() -> None:
    print("\nsettlement — the store IS used when its bar is the right contract")
    install(bars=BARS, instruments=INSTRUMENTS, prices={"880002": LIVE_FUT_PX}, candles={})
    px, basis = await cp.settlement_price(option_inst(option_type="PE"), last_mark=126.35)
    check("it settles off the stored close", px == STRIKE - SETTLE_CLOSE, f"{px}")
    check("and the basis says the number came from the bar store",
          "bar store" in basis, basis)


async def check_live_future_fallback() -> None:
    print("\nsettlement — no close at all, so the live future, said plainly")
    install(bars=[], instruments=INSTRUMENTS, prices={"880002": LIVE_FUT_PX}, candles={})
    px, basis = await cp.settlement_price(option_inst(option_type="CE"), last_mark=500.0)
    check("intrinsic is taken against the live future", px == LIVE_FUT_PX - STRIKE, f"{px}")
    check("the basis admits it is a later price on a LATER CONTRACT",
          "NOW" in basis and "later contract" in basis, basis)


async def check_last_mark_fallback() -> None:
    print("\nsettlement — nothing to take intrinsic against, so the recorded mark")
    install(bars=[], instruments=INSTRUMENTS, prices={}, candles={})
    px, basis = await cp.settlement_price(option_inst(option_type="PE"), last_mark=126.35)
    check("it closes at the last price the desk itself recorded", px == 126.35, f"{px}")
    check("the basis says it is a recorded mark, not an exchange number",
          "recorded mark" in basis, basis)


async def check_refuses_with_nothing() -> None:
    print("\nsettlement — with NO price anywhere, it refuses rather than invents")
    install(bars=[], instruments=INSTRUMENTS, prices={}, candles={})
    try:
        await cp.settlement_price(option_inst(option_type="PE"), last_mark=None)
        check("a price with no source is refused", False, "it returned a number")
    except cp.OrderError as exc:
        check("a price with no source is refused", True, exc.detail[:70] + "…")


async def check_future_settlement() -> None:
    print("\nsettlement — an expired FUTURE settles at its OWN close")
    install(bars=[], instruments=INSTRUMENTS, prices={}, candles=CANDLES)
    px, basis = await cp.settlement_price(future_inst(FUT_EXPIRY, "880001"), last_mark=8100.0)
    check("it settles at its own last close, not the stale mark", px == SETTLE_CLOSE, f"{px}")
    check("the basis says it is that contract's own close", "own" in basis, basis)


def open_position(inst, side="SELL", entry=319.40, ltp=126.35, lots=30):
    return {"position_id": "pos1", "account_id": "acc1", "symbol": inst["symbol"],
            "display_name": f"{SYMBOL} {inst['expiry']} {STRIKE:g}{inst['option_type']}",
            "instrument_kind": "OPTION", "instrument": inst, "underlying_symbol": SYMBOL,
            "side": side, "lots": lots, "quantity": lots * MULT,
            "entry_price": entry, "ltp": ltp, "product_type": "MARGIN",
            "margin_used": 91477.0, "capital_deployed": 91477.0,
            "contract_value": 37905.0, "unrealized_pnl": 0.0, "realized_pnl": 0.0,
            "status": "OPEN", "opened_at": cp._now(), "updated_at": cp._now(),
            "closed_at": None, "closed_on": None}


async def check_exit_expired() -> None:
    print("\nexit_position — the expired leg that could not be closed")
    inst = option_inst(option_type="PE")
    install(bars=[], instruments=INSTRUMENTS, prices={"880002": LIVE_FUT_PX},
            candles=CANDLES, positions=[open_position(inst)])

    fill = await cp.exit_position("acc1", "pos1")
    want = STRIKE - SETTLE_CLOSE
    check("the close goes through at all", fill["status"] == "FILLED")
    check("it fills at the settlement value", fill["fill_price"] == want,
          f"{fill['fill_price']} vs {want}")
    check("the fill carries the basis", "intrinsic" in (fill.get("exit_basis") or ""),
          fill.get("exit_basis", ""))

    pos = await cp.commodity_pos_positions_collection.find_one({"position_id": "pos1"})
    check("the position is CLOSED, not left open", pos["status"] == "CLOSED", pos["status"])
    # A 30-lot short at 319.40 settling at 136.00: (319.40 - 136.00) x 300 barrels.
    want_pnl = round((319.40 - want) * 30 * MULT, 2)
    check("it books the settlement P&L, not the stale mark's",
          pos["realized_pnl"] == want_pnl, f"{pos['realized_pnl']} vs {want_pnl}")


async def check_exit_live_still_refused() -> None:
    print("\nexit_position — a LIVE contract Angel merely failed to quote is still refused")
    inst = option_inst(expiry=LIVE_OPT_EXPIRY, option_type="PE", token="990003")
    install(bars=[], instruments=[*INSTRUMENTS, inst], prices={"880002": LIVE_FUT_PX},
            candles=CANDLES, positions=[open_position(inst)])
    try:
        await cp.exit_position("acc1", "pos1")
        check("an unquoted LIVE leg is refused", False, "it closed at an invented level")
    except cp.OrderError as exc:
        check("an unquoted LIVE leg is refused", True, exc.detail[:60] + "…")
        check("the refusal says it is a quote failure, not a dead contract",
              "quote failure" in exc.detail, exc.detail[:80])


async def check_roll_refuses_expired() -> None:
    print("\nRe-add ATM — a dead expiry has nothing to roll into")
    inst = option_inst(option_type="PE")
    install(bars=[], instruments=INSTRUMENTS, prices={"880002": LIVE_FUT_PX},
            candles=CANDLES, positions=[open_position(inst)])
    cp.commodity_accounts_collection = FakeCollection(
        [{"account_id": "acc1", "name": "probe", "initial_capital": 200000.0}])
    try:
        await cp.reopen_at_the_money("acc1", "pos1")
        check("rolling an expired leg is refused", False, "it rolled")
    except cp.OrderError as exc:
        check("rolling an expired leg is refused", True, exc.detail[:60] + "…")
    pos = await cp.commodity_pos_positions_collection.find_one({"position_id": "pos1"})
    check("and it was NOT closed on the way to failing", pos["status"] == "OPEN")


async def check_sync_marks_settlement() -> None:
    print("\nsync_positions — an expired leg stops showing a stale quote")
    inst = option_inst(option_type="CE", token="990002")
    install(bars=[], instruments=INSTRUMENTS, prices={"880002": LIVE_FUT_PX},
            candles=CANDLES, positions=[open_position(inst, entry=322.45, ltp=500.0)])
    await cp.sync_positions()
    pos = await cp.commodity_pos_positions_collection.find_one({"position_id": "pos1"})
    check("the 500.00 stale mark is replaced by the 0.00 settlement",
          pos["ltp"] == 0.0, f"{pos['ltp']}")
    check("the row is flagged expired", pos.get("expired") is True)
    check("and carries the basis for the number", "intrinsic" in (pos.get("price_basis") or ""),
          pos.get("price_basis", ""))


async def go() -> None:
    await check_is_expired()
    await check_intrinsic()
    await check_cached()
    await check_wrong_contract_ignored()
    await check_store_used_when_right()
    await check_live_future_fallback()
    await check_last_mark_fallback()
    await check_refuses_with_nothing()
    await check_future_settlement()
    await check_exit_expired()
    await check_exit_live_still_refused()
    await check_roll_refuses_expired()
    await check_sync_marks_settlement()


def main() -> int:
    try:
        asyncio.run(go())
    except Exception:
        traceback.print_exc()
        return 2
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
