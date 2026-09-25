"""Does the Rs 2,00,000 paper book behave like ONE book rather than 504 of them?

The desk it sits under gives every strategy its own Rs 2,00,000, so nothing there ever
runs out of money and nothing ever competes. This book is the opposite case, and every
interesting failure is a money failure: a second strategy spending cash the first has
already deployed, a slice quietly sized off the wrong divisor, a signal dropped for want
of funds with nothing said about it. None of those show up on the parent desk, and none of
them are visible in a leaderboard — which is why they are asserted here.

Runs entirely on stubs. No Mongo, no Angel, no scheduler: what is being checked is the
allocation arithmetic and the guards, and a fake is the only way to hold cash and prices
still while checking them.

What has to hold:
  * the roster resolves by TEMPLATE NAME and timeframe, so inserting a template upstream
    cannot silently repoint the picks at different rules
  * each strategy targets book/roster_size, and one lot is allowed when that slice will
    not cover a lot but the cash will
  * a strategy cannot spend cash another strategy has already deployed, and the signal it
    could not fund is REPORTED rather than dropped in silence
  * one open position per strategy, one trade per closed bar — the parent desk's two
    load-bearing guards, which a second book could otherwise bypass
  * closes charge the real Angel option round trip and book P&L net of it
  * the daily-loss breaker stops new entries and lets open ones keep being managed
  * ROI is measured against the SLICE per strategy and against the WHOLE book overall,
    never mixed up

Run: python -m tests.nifty_scalp.verify_paper_book
"""
import asyncio
import sys
import traceback
from datetime import datetime

import app.services.nifty_scalp_paper as P
from app.services.angel_fees import option_round_trip
from app.services.nifty_scalp_strategies import CATALOG_BY_ID, Series

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  - ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ── stubs ──────────────────────────────────────────────────────────────────────


def _get(doc: dict, path: str):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches(doc: dict, query: dict) -> bool:
    for key, want in query.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in want):
                return False
            continue
        got = _get(doc, key)
        if isinstance(want, dict):
            for op, val in want.items():
                if op == "$ne" and got == val:
                    return False
                if op == "$in" and got not in val:
                    return False
                if op == "$gte" and not (got is not None and got >= val):
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
    """Enough Mongo for this module, including the `$group` the desk totals run on.

    `split()` is reimplemented rather than faked away because the book's available cash is
    computed from it — stubbing it out would remove the arithmetic under test."""

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
        return dict(hits[0]) if hits else None

    def find(self, query=None, projection=None):
        return _Cursor([dict(d) for d in self.docs if _matches(d, query or {})])

    async def insert_one(self, doc):
        self.docs.append({"_id": self._next_id(), **dict(doc)})

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _matches(d, query):
                for k, v in (update.get("$set") or {}).items():
                    if "." in k:
                        head, tail = k.split(".", 1)
                        d.setdefault(head, {})[tail] = v
                    else:
                        d[k] = v
                return
        if upsert:
            fresh = {k: v for k, v in query.items() if not isinstance(v, dict)}
            for k, v in (update.get("$set") or {}).items():
                if "." in k:
                    head, tail = k.split(".", 1)
                    fresh.setdefault(head, {})[tail] = v
                else:
                    fresh[k] = v
            self.docs.append(fresh)

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))

    def aggregate(self, pipeline):
        """Only the two shapes this module uses: desk_totals.split's status $group, and
        the per-day roll-up in `daily()`.

        A SYNC method returning an async iterator, which is what motor does. Writing it as
        `async def` returns a coroutine and `async for` refuses it."""
        docs = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if _matches(d, stage["$match"])]
        group = next((s["$group"] for s in pipeline if "$group" in s), None)

        async def gen(rows):
            for r in rows:
                yield r

        if group is None:
            return gen(docs)

        spec = group["_id"]
        buckets: dict = {}
        for d in docs:
            if isinstance(spec, str):
                key = _get(d, spec.lstrip("$"))
            else:  # the {$cond: [{$eq: [$status, OPEN]}, ...]} split
                key = "OPEN" if d.get("status") == "OPEN" else "CLOSED"
            buckets.setdefault(key, []).append(d)

        out = []
        for key, rows in buckets.items():
            row = {"_id": key}
            for field, expr in group.items():
                if field == "_id":
                    continue
                if expr == {"$sum": 1}:
                    row[field] = len(rows)
                    continue
                inner = expr["$sum"]
                if isinstance(inner, dict) and "$ifNull" in inner:
                    src = inner["$ifNull"][0].lstrip("$")
                    row[field] = sum(float(r.get(src) or 0.0) for r in rows)
                elif isinstance(inner, dict) and "$cond" in inner:
                    cond = inner["$cond"][0]["$gt"][0]["$ifNull"][0].lstrip("$")
                    row[field] = sum(1 for r in rows if float(r.get(cond) or 0.0) > 0)
                else:
                    row[field] = 0
            out.append(row)
        return gen(out)


def install(positions=None, trades=None, state=None):
    P.nifty_scalp_paper_positions_collection = FakeCollection(positions or [])
    P.nifty_scalp_paper_trades_collection = FakeCollection(trades or [])
    P.nifty_scalp_paper_scores_collection = FakeCollection([])
    P.nifty_scalp_paper_state_collection = FakeCollection(state or [])
    P.nifty_scalp_paper_equity_collection = FakeCollection([])


# ── fixtures ───────────────────────────────────────────────────────────────────

LOT = 65                     # NIFTY, read from the master on the real desk
PREMIUM = 200.0              # Rs 13,000 a lot
TOKEN = "45001"
BAR = "2026-09-25 09:20:00"


def contract(kind="CE"):
    return {"symbol": f"NIFTY25SEP25000{kind}", "option_type": kind, "strike": 25000.0,
            "angel_token": TOKEN, "angel_exchange": "NFO", "lot_size": LOT}


def series_for(ids, bar=BAR):
    s = Series([bar], [0.0], [0.0], [0.0], [25000.0], [0.0])
    return {CATALOG_BY_ID[sid].timeframe: s for sid in ids}


def fired_for(ids, direction=1):
    return [(CATALOG_BY_ID[sid], direction) for sid in ids]


async def fire(ids, premium=PREMIUM, direction=1, bar=BAR):
    return await P.on_signals(fired_for(ids, direction), {"CE": contract("CE"), "PE": contract("PE")},
                              {TOKEN: premium}, 25000.0, "2026-09-30", series_for(ids, bar))


# ── checks ─────────────────────────────────────────────────────────────────────


async def check_roster_resolution() -> None:
    print("the roster is bound to template NAMES, not to catalogue positions")
    ids = P.default_roster_ids()
    check("all 12 default picks resolve", len(ids) == len(P.DEFAULT_ROSTER),
          f"{len(ids)} of {len(P.DEFAULT_ROSTER)}")
    names = {(CATALOG_BY_ID[i].template, CATALOG_BY_ID[i].timeframe) for i in ids}
    check("and they resolve to the templates that were asked for",
          names == set(P.DEFAULT_ROSTER))
    check("a pick that does not exist resolves to nothing rather than a wrong rule",
          P.resolve("No Such Template", "5m") is None)
    check("a real template on an unlisted timeframe also resolves to nothing",
          P.resolve("Engulfing Candle", "7m") is None)


async def check_slice_and_sizing() -> None:
    print("\nsizing - an equal slice of ONE book, with a one-lot floor")
    install()
    roster = await P.get_roster()
    s = await P.summary()
    expect = P.BOOK_CAPITAL / len(roster)
    check("the slice is the book divided by the roster",
          abs(s["slice_per_strategy"] - expect) < 0.01, f"{s['slice_per_strategy']}")
    check("the book is Rs 2,00,000, not Rs 2,00,000 each",
          s["book_capital"] == 200000.0, f"{s['book_capital']}")

    # Slice 16,666 / lot 13,000 -> 1 lot.
    r = await fire([roster[0]])
    check("a signal opens one lot inside its slice", r["opened"] == 1, str(r))
    pos = await P.nifty_scalp_paper_positions_collection.find_one({"status": "OPEN"})
    check("sized at 1 lot", pos["lots"] == 1, f"{pos['lots']}")
    check("deploying premium x lot size", pos["capital_deployed"] == PREMIUM * LOT,
          f"{pos['capital_deployed']}")

    # A premium whose single lot costs MORE than the slice: the floor lets it through.
    install()
    fat = 300.0  # Rs 19,500 a lot against a Rs 16,666 slice
    r = await fire([roster[1]], premium=fat)
    check("a lot dearer than the slice is still allowed, because a book buys whole lots",
          r["opened"] == 1, str(r))


async def check_shared_cash() -> None:
    print("\nshared cash - the thing the parent desk never has to deal with")
    install()
    roster = await P.get_roster()
    # Rs 2 lakh, lots at Rs 65,000 each: three fit, the fourth cannot.
    r = await fire(roster[:4], premium=1000.0)
    check("only what the book can afford is opened", r["opened"] == 3, str(r["opened"]))
    check("the unaffordable one is counted as skipped", r["skipped"] == 1, str(r["skipped"]))
    check("and it is SAID, not silently dropped",
          any("fully deployed" in n for n in r["notes"]), str(r["notes"]))

    cash = await P.available_cash()
    check("cash left is the book minus what went out", abs(cash - (200000 - 3 * 65000)) < 1,
          f"{cash}")
    s = await P.summary()
    check("summary agrees on deployed capital", s["deployed_capital"] == 3 * 65000.0,
          f"{s['deployed_capital']}")


async def check_guards() -> None:
    print("\nthe parent desk's two guards, which a second book could have bypassed")
    install()
    roster = await P.get_roster()
    sid = roster[0]

    await fire([sid])
    r = await fire([sid], bar="2026-09-25 09:25:00")   # new bar, position still open
    check("a strategy holding a position does not open a second", r["opened"] == 0, str(r))

    install()
    await fire([sid])
    pos = await P.nifty_scalp_paper_positions_collection.find_one({"status": "OPEN"})
    await P.nifty_scalp_paper_positions_collection.update_one(
        {"position_id": pos["position_id"]}, {"$set": {"status": "CLOSED", "realized_pnl": 0.0,
                                                       "capital_deployed": 0.0}})
    r = await fire([sid])                              # SAME bar as the first fire
    check("and it does not re-enter on a bar it has already acted on", r["opened"] == 0, str(r))

    r = await fire([sid], bar="2026-09-25 09:30:00")
    check("but a genuinely new bar may trade again", r["opened"] == 1, str(r))


async def check_exit_and_fees() -> None:
    print("\nexits charge the real Angel option round trip")
    install()
    roster = await P.get_roster()
    await fire([roster[0]])
    pos = await P.nifty_scalp_paper_positions_collection.find_one({"status": "OPEN"})
    target = pos["target_premium"]

    closed = await P.manage({TOKEN: target})
    check("a position at its target closes", closed == 1, str(closed))

    done = await P.nifty_scalp_paper_positions_collection.find_one({"status": "CLOSED"})
    gross = round((target - PREMIUM) * LOT, 2)
    fb = option_round_trip(PREMIUM, target, 1, LOT)
    check("gross is the premium move on the quantity", done["gross_pnl"] == gross,
          f"{done['gross_pnl']} vs {gross}")
    check("fees are charged", done["fees"] == fb.total, f"{done['fees']} vs {fb.total}")
    check("net is gross MINUS fees", done["realized_pnl"] == round(gross - fb.total, 2),
          f"{done['realized_pnl']}")
    check("the exit reason is recorded", done["exit_reason"] == "target", done["exit_reason"])

    cash = await P.available_cash()
    check("the closed position releases its capital back to the book",
          abs(cash - (200000 + done["realized_pnl"])) < 0.01, f"{cash}")


async def check_stop_side() -> None:
    print("\nand a loser exits on its stop, net of costs, without going through the book")
    install()
    roster = await P.get_roster()
    await fire([roster[0]])
    pos = await P.nifty_scalp_paper_positions_collection.find_one({"status": "OPEN"})
    closed = await P.manage({TOKEN: pos["stop_premium"]})
    check("it closes", closed == 1, str(closed))
    done = await P.nifty_scalp_paper_positions_collection.find_one({"status": "CLOSED"})
    check("the loss is booked", done["realized_pnl"] < 0, f"{done['realized_pnl']}")
    check("costs made it worse, not better", done["realized_pnl"] < done["gross_pnl"],
          f"{done['realized_pnl']} vs {done['gross_pnl']}")


async def check_breaker() -> None:
    print("\nthe daily loss breaker stops entries and leaves open positions managed")
    today = datetime.now(P.IST).date().isoformat()
    loss = -(P.BOOK_CAPITAL * P.DAILY_LOSS_BREAKER_PCT) - 1
    install(positions=[{
        "position_id": "old", "strategy_id": "ns_1m_01", "status": "CLOSED",
        "closed_on": today, "opened_on": today, "realized_pnl": loss, "unrealized_pnl": 0.0,
        "capital_deployed": 0.0, "fees": 0.0, "gross_pnl": loss,
    }])
    st = await P.breaker_state()
    check("it trips", st["breaker_tripped"] is True, str(st))
    roster = await P.get_roster()
    r = await fire([roster[0]])
    check("no new position is opened", r["opened"] == 0, str(r))
    check("and the reason is said out loud",
          any("BREAKER" in n for n in r["notes"]), str(r["notes"]))


async def check_roi_denominators() -> None:
    print("\nROI: per strategy against its SLICE, for the book against the WHOLE book")
    install()
    roster = await P.get_roster()
    await fire([roster[0]])
    pos = await P.nifty_scalp_paper_positions_collection.find_one({"status": "OPEN"})
    await P.manage({TOKEN: pos["target_premium"]})

    rows = await P.roster_rows()
    row = next(r for r in rows if r["strategy_id"] == roster[0])
    slice_size = P.BOOK_CAPITAL / len(roster)
    check("the strategy's ROI divides by its slice",
          abs(row["roi_pct"] - row["net_pnl"] / slice_size * 100) < 0.01,
          f"{row['roi_pct']}")
    check("which is NOT the same as dividing by the book",
          abs(row["roi_pct"] - row["net_pnl"] / P.BOOK_CAPITAL * 100) > 0.01)

    s = await P.summary()
    check("the book's ROI divides by the book",
          abs(s["roi_pct"] - (s["equity"] - P.BOOK_CAPITAL) / P.BOOK_CAPITAL * 100) < 0.01,
          f"{s['roi_pct']}")
    check("the roster row also carries the desk record that got it picked",
          "desk_roi_pct" in row and "desk_trades" in row)


async def check_set_roster() -> None:
    print("\nediting the roster")
    install()
    good = P.default_roster_ids()[:3]
    res = await P.set_roster(good + ["ns_not_a_real_id"])
    check("known ids are kept", res["count"] == 3, str(res["count"]))
    check("the unknown one is REPORTED, not silently dropped",
          res["unknown"] == ["ns_not_a_real_id"], str(res["unknown"]))
    s = await P.summary()
    check("a smaller roster means a bigger slice each",
          abs(s["slice_per_strategy"] - P.BOOK_CAPITAL / 3) < 0.01,
          f"{s['slice_per_strategy']}")
    try:
        await P.set_roster(["nonsense"])
        check("an all-nonsense roster is refused", False, "it was accepted")
    except ValueError as exc:
        check("an all-nonsense roster is refused", True, str(exc)[:50] + "...")


async def go() -> None:
    await check_roster_resolution()
    await check_slice_and_sizing()
    await check_shared_cash()
    await check_guards()
    await check_exit_and_fees()
    await check_stop_side()
    await check_breaker()
    await check_roi_denominators()
    await check_set_roster()


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
