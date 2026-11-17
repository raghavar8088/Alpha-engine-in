"""Index Option Buying: picked-strategy paper accounts (12 Nov 2026; premium50k 16 Nov; the NIFTY BANK pair 17 Nov).

The owner asked, on the Index Option Buying page, for:

  best2L       "Best Strategies of Top 10" - Rs 2,00,000 on the two strategies that made the most in BOTH
               of this page's Top 10 paper accounts (top10_books, desk "prelive") from 27 Oct to 12 Nov
               2026: intra_ha_reversal · 15m and it_fake_breakout · 15m. ONE shared account with a slot
               for each: at most two positions at once, each up to Rs 1,00,000.
  premium50k   "Premium Option Buying Strategies" (16 Nov 2026) - the SAME two strategies on ONE Rs 50,000
               account: at most two positions at once, each up to Rs 25,000 of premium (paid in full: an
               option buyer has no leverage). Its own start; nothing earlier is copied.
  sf_top10     "Top 10 Performing Strategies" - the Strategy Factory tab's Rank 1-10 on Index Option
               Buying (factory_desks, tab "index-buying"), Rs 10,00,000 for EACH strategy.
  sf_top10_20  "Top 10-20 Performing Strategies" - the same board's Rank 11-20, Rs 10,00,000 for each.
  bn2L, bn10L  (17 Nov 2026, the NIFTY BANK tab) - the ten strategies the NIFTY BANK desk trades
               (banknifty_desk, chosen by the BANKNIFTY research on 13 Oct 2026), Rs 2,00,000 for EACH strategy
               in one set and Rs 10,00,000 for each in the other.

WHAT THEY COPY. Each book copies its desk's own trades of its picks - entry and exit at the desk's own
prices - and never re-scans or calls a broker:
  - best2L: the NIFTY 50 tournament (prelive_positions / prelive_trades), priced as its Top 10 books are:
    bought at the ask, sold at the bid (the tournament's real-money estimate);
  - the Factory books: the Strategy Factory tab's NIFTY option buys (factory_desk_positions, in that
    tab's own MongoDB): its ATM option bought at the ask and sold at the bid from Angel's quote, an
    unquoted expired option at intrinsic, as the tab itself books them;
  - the NIFTY BANK books: the NIFTY BANK desk's BANKNIFTY monthly option buys (bn_desk_positions) at
    its real-money prices - bought at the ask, sold at the bid - marked at the bid while open.
Whole lots; never two positions in one contract inside one account; Angel One's option charges on the
book's own lots. A book starts at its first cycle and never backfills. The replay - slots, cash, one
contract, and the rewind that keeps them honest on the trades' own clock - is plan_book's
(live_intraday_mirror), as for the Top-10 and the rank-band books.

THE SHAPES. best2L is ONE account, as the Top 10 books are. The Factory books give every strategy its
OWN Rs 10 lakh (a book is Rs 1 crore), as the Commodity rank-band books do: one position at a time, as on
the desk, in whole lots up to that strategy's free cash, so a strategy's losses never shrink another's
money. The tab buys 1 lot a signal; at Rs 1,900-16,400 a lot these accounts buy roughly 60-520, priced
at the tab's 1-lot fill - an upper bound on what an order that size would have got. The NIFTY BANK books
have the same shape at Rs 2 lakh and Rs 10 lakh a strategy (Rs 20 lakh and Rs 1 crore a book); the desk
buys 1 lot (30) a signal, and at Rs 21,000-45,000 a lot these buy roughly 4-9 and 22-47.

THE PICKS ARE FROZEN as they stood at each book's picked_at (PICKED_AT unless the book says otherwise);
they are not re-picked as the boards move. Never re-pick them without the owner: a changed roster is a
new book.

MORE STRATEGY FACTORY ACCOUNTS (17 Nov 2026). The owner asked, on the same tab, for:
  sfb1_5_2L ... sfb46_50_10L   the tab's Rank in ten bands of five (1-5, 6-10 ... 46-50), each band in a
                               Rs 2 lakh and a Rs 10 lakh account (20 accounts). ONE shared account per band,
                               as the Top 10 books are: a slot for each of the five, each up to a fifth of the
                               account (Rs 40,000 / Rs 2,00,000), never two positions in one contract.
  sf_all_2L / sf_all_10L       all 546 of the tab's strategies, each with its OWN Rs 2 lakh / Rs 10 lakh and
                               one position at a time, as the Top 10 Performing books are.
The roster and the Rank they were banded by are frozen in prelive_pick_roster (20:35 IST, 17 Nov 2026). The
bands are shown together (group "sf-bands", accounts()). A book of 546 accounts is synced from one read of
each collection a cycle (_sync_book), and plan_book runs only for an account with something to do.

Paper only: nothing here places an order.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from app.core.db import db
from app.services import top10_books as t10
from app.services.book_reset import naive_utc
from app.services.live_intraday_mirror import pending_since, plan_book
from app.services.prelive_pick_roster import PICKED_AT as SF_PICKED_AT, RANKED as SF_RANKED, SF546

logger = logging.getLogger("prelive_pick_books")

POSITIONS = db["pick_book_positions"]
SCORES = db["pick_book_scores"]
STATE = db["pick_book_state"]
EQUITY = db["pick_book_equity"]
SOURCE_TAG = "pick"
ENABLED = os.getenv("PRELIVE_PICK_BOOKS_ENABLED", "1").lower() not in ("0", "false", "")
LOOKBACK = t10.LOOKBACK
SKIP_REASONS = ("full", "symbol_held", "price_above_cap", "no_cash")
SHARED = "book"                       # the account id of a book that is one account
FACTORY_TAB = "index-buying"          # factory_desks.TABS key of Index Option Buying's Strategy Factory tab
SNAPSHOT_EVERY = timedelta(minutes=15)
PICKED_AT = "2026-11-12T23:14:00+05:30"
MODULE = "Index Option Buying"


# -- the Strategy Factory tab's trades as parents --------------------------------------------------


def _factory_parent(p: dict) -> dict | None:
    """One Strategy Factory tab position (a single bought NIFTY option) as a parent the copy replays."""
    legs = p.get("legs") or []
    if p.get("kind") != "option_buy" or len(legs) != 1 or not p.get("lot_size") or not legs[0].get("entry"):
        return None
    leg = legs[0]
    closed = p.get("status") == "CLOSED"
    exits = p.get("exit_legs") or []
    marks = p.get("mark_legs") or []
    strike = t10._f(leg.get("strike"))
    return t10._option_parent(
        pid=str(p["position_id"]), key=p["strategy_id"], name=p.get("strategy_name") or p["strategy_id"],
        symbol=str(leg.get("token") or leg.get("tradingsymbol")),
        label=f"NIFTY {int(strike)} {leg.get('option_type') or ''} {leg.get('expiry') or ''}".strip(),
        lot_size=int(p["lot_size"]), entry=t10._f(leg["entry"]),
        exit_px=t10._f(exits[0]) if closed and exits else None,
        ltp=t10._f(marks[0]) if marks else None,
        opened_at=p.get("opened_at"), closed_at=p.get("closed_at"), status="CLOSED" if closed else "OPEN",
        expiry=leg.get("expiry"), opened_on=p.get("opened_on"), closed_on=p.get("closed_on"),
        exit_reason=p.get("exit_reason"))


async def _load_factory(since: datetime, keys: set, pointed: list) -> list[dict]:
    """The tab's positions of these strategies opened since `since`, plus any an open copy points at."""
    from app.services import factory_desks as fd       # its store: the tab's own MongoDB in production
    q = {"desk": FACTORY_TAB, "strategy_id": {"$in": list(keys)},
         "$or": [{"opened_at": {"$gte": since}}, {"position_id": {"$in": list(pointed)}}]}
    out = []
    async for p in fd.POSITIONS.find(q):
        x = _factory_parent(p)
        if x is not None:
            out.append(x)
    return out


# -- the NIFTY BANK desk's trades as parents (17 Nov 2026) -----------------------------------------

BN_POSITIONS = "bn_desk_positions"   # banknifty_desk.positions, in the backend's own database
BN_MARK_TTL = 45.0                   # seconds a quote is reused: twenty accounts read the desk each pass
_bn_marks: dict[str, tuple[float, float | None]] = {}


async def _bn_quotes(tokens: list[str]) -> dict[str, dict]:
    """Angel's quotes of these NFO tokens - the call the desk itself marks with."""
    from app.services.angel_client import angel_client
    return await angel_client.full_quote({"NFO": tokens}) if tokens else {}


async def _bn_bids(tokens: list[str]) -> dict[str, float | None]:
    """Each token's bid (its last price when the book is empty), fetched at most once a BN_MARK_TTL. A quote
    outage gives None, and an open copy then keeps its last mark."""
    now = time.monotonic()
    for t in [t for t, (at, _) in _bn_marks.items() if now - at > 3600]:
        del _bn_marks[t]
    want = [t for t in tokens if t not in _bn_marks or now - _bn_marks[t][0] > BN_MARK_TTL]
    if want:
        try:
            q = await _bn_quotes(want)
        except Exception:  # noqa: BLE001 - a quote outage must not stop the copy
            logger.warning("[prelive_pick_books] NIFTY BANK quotes unavailable", exc_info=True)
            q = {}
        for t in want:
            x = q.get(t) or {}
            v = x.get("bid") or x.get("ltp")
            _bn_marks[t] = (now, float(v) if v else None)
    return {t: _bn_marks[t][1] for t in tokens}


def _bn_parent(p: dict, bids: dict[str, float | None]) -> dict | None:
    """One NIFTY BANK desk position (one bought BANKNIFTY monthly option) as a parent the copy replays, at the
    desk's real-money prices: its ask in, its bid out, and the bid now while it is open."""
    legs = p.get("legs") or []
    # One leg: the desk can buy a straddle, but none of the ten trades one.
    if len(legs) != 1 or not legs[0].get("real_entry") or not legs[0].get("token") or not p.get("strategy"):
        return None
    leg = legs[0]
    closed = p.get("status") == "CLOSED"
    if closed and leg.get("real_exit") is None:
        return None
    token = str(leg["token"])
    return t10._option_parent(
        pid=str(p["_id"]), key=p["strategy"], name=p["strategy"], symbol=token,
        label=f"BANKNIFTY {int(t10._f(leg.get('strike')))} {leg.get('type') or p.get('kind') or ''} "
              f"{leg.get('expiry') or p.get('expiry') or ''}".strip(),
        lot_size=int(leg.get("lot_size") or 30), entry=t10._f(leg["real_entry"]),
        exit_px=t10._f(leg["real_exit"]) if closed else None,
        ltp=None if closed else bids.get(token),
        opened_at=p.get("opened_at"), closed_at=p.get("closed_at"), status="CLOSED" if closed else "OPEN",
        expiry=leg.get("expiry") or p.get("expiry"), opened_on=p.get("session"), exit_reason=p.get("exit_reason"))


async def _load_banknifty(since: datetime, keys: set, pointed: list) -> list[dict]:
    """The desk's positions of these strategies opened since `since`, plus any an open copy points at."""
    ids = []
    for x in pointed:
        try:
            ids.append(ObjectId(x))
        except (InvalidId, TypeError):
            continue
    q = {"strategy": {"$in": list(keys)}, "$or": [{"opened_at": {"$gte": since}}, {"_id": {"$in": ids}}]}
    docs = [p async for p in db[BN_POSITIONS].find(q)]
    # Only what the account holds is marked (a copy opened this pass is marked from the next), so Angel is asked
    # for the contracts the books hold and nothing else.
    held = {str(i) for i in ids}
    tokens = sorted({str(lg["token"]) for p in docs if p.get("status") == "OPEN" and str(p["_id"]) in held
                     for lg in p.get("legs") or [] if lg.get("token")})
    bids = await _bn_bids(tokens) if tokens else {}
    out = []
    for p in docs:
        x = _bn_parent(p, bids)
        if x is not None:
            out.append(x)
    return out


# -- the books and their frozen picks ---------------------------------------------------------------


@dataclass(frozen=True)
class Book:
    key: str
    label: str
    desk: t10.Desk            # the copied desk's adapters, with this book's picks as its roster
    capital: float            # each strategy's own when per_strategy, else the one account's
    slots: int                # positions at once: in each strategy's account, or in the one account
    per_strategy: bool
    pick_rule: str            # how the picks were chosen
    picked_at: str = PICKED_AT
    source: str = "the tab"   # what the page calls the copied desk
    caveat: tuple[str, str] = ("Picked on a short, lucky-prone record, and none is validated.",   # (headline, body)
                               "This account is the out-of-sample test of whether they keep earning.")
    group: str = ""           # accounts the page shows together ("sf-bands"); "" = its own tab

    @property
    def picks(self) -> tuple[t10.Pick, ...]:
        return self.desk.picks

    @property
    def total_capital(self) -> float:
        return self.capital * (len(self.picks) if self.per_strategy else 1)

    def accounts(self) -> list[tuple[str, set[str]]]:
        """(account id, the strategies it trades): one per strategy, or the one shared account."""
        if self.per_strategy:
            return [(p.key, {p.key}) for p in self.picks]
        return [(SHARED, {p.key for p in self.picks})]


_BEST_NOTES = (
    "Picked on 12 Nov 2026 as the two that made the most in BOTH of this page's Top 10 paper accounts since "
    "27 Oct: in the ₹2 lakh one, intra_ha_reversal · 15m made +₹79,871 on 9 trades and it_fake_breakout · 15m "
    "+₹59,580 on 7 (+₹4,22,549 and +₹3,12,818 in the ₹10 lakh one, the same trades at a bigger size).",
    "Chosen after the fact, on 9 and 7 trades. When the Top 10 was picked on 27 Oct, intra_ha_reversal stood #9 "
    "on the tournament with a loss of 128 bp a trade over 37 trades. On this desk a month's top 20 option-buying "
    "strategies lost the next month 11 times in 12 (Option Buying Top 20 study, Oct 2026).",
    "Priced as the Top 10 books are: bought at the ask, sold at the bid (the tournament's real-money estimate), "
    "not at the option's last traded price. Both trade ATM NIFTY options, so when they want the same contract at "
    "the same time the second is skipped and counted.",
)
_FACTORY_NOTES = (
    "Each strategy has its own ₹10,00,000 and holds one position at a time, as on the Strategy Factory tab; one "
    "strategy's losses never reduce another's money.",
    "The tab buys 1 lot a signal. These accounts buy whole lots up to the strategy's free cash - roughly 60 to "
    "520 lots at the premiums these strategies have paid (₹1,900-16,400 a lot) - priced at the tab's own 1-lot "
    "fill (the ask in, the bid out). A real order that size would pay more to get in and out, so read the "
    "rupee P&L as an upper bound.",
    "Ranked on 4-15 closed trades each since 28 Oct; the board itself says a rank is relative, not proof of an "
    "edge. On this desk a month's top 20 option-buying strategies lost the next month 11 times in 12 (Option "
    "Buying Top 20 study, Oct 2026).",
)

_BEST_DESK = dataclasses.replace(
    t10.DESKS["prelive"],
    board="net P&L in this page's two Top 10 paper accounts (₹2 lakh and ₹10 lakh), 27 Oct - 12 Nov 2026",
    picks=t10._picks([
        # (key, rank in the Top 10 books by net P&L, no Rank score, trades, mean net bp a trade, name, net
        #  P&L in the Rs 2 lakh Top 10 book) - both books' leaderboards at the 12 Nov close
        ("intra_ha_reversal@15m", 1, None, 9, 2390.5, "intra_ha_reversal · 15m", 79870.79),
        ("it_fake_breakout@15m", 2, None, 7, 2235.1, "it_fake_breakout · 15m", 59579.89),
    ]),
    max_open=2,
    notes=_BEST_NOTES,
)

_FACTORY_DESK = t10.Desk(
    key="factory:index-buying", label="Index Option Buying · Strategy Factory", route="/prelive",
    instrument="NIFTY options bought: the ATM CE on a BUY signal, the ATM PE on a SELL (the Strategy Factory "
               "tab's own trades)",
    cost_basis="the premium paid at the ask (premium x lot size a lot)",
    board="the Strategy Factory tab's Rank on Index Option Buying (146 strategies with closed trades, 28 Oct - "
          "12 Nov 2026)",
    picks=(), load=_load_factory, pnl=t10._bought_option_pnl, mark=t10._bought_option_mark, max_open=1,
)

# /api/strategy-rank/factory-desks?desk=index-buying at PICKED_AT: (strategy id, rank, score, closed trades,
# net bp a trade, name, net P&L of the tab's own 1-lot trades). Ranks 1-20 as on the owner's screenshot.
_SF_TOP10 = t10._picks([
    ("SF0400", 1, 60.8, 15, 2023.18, "MACD Histogram Turn · 5m", 24147.70),
    ("SF0107", 2, 60.7, 8, 4338.73, "Engulfing Candle · 15m", 26578.54),
    ("SF0474", 3, 59.2, 8, 4966.10, "Pullback + EMA + RSI + VWAP · 30m", 37694.77),
    ("SF0330", 4, 59.2, 8, 4966.10, "Trend Pullback to EMA · 30m", 37694.77),
    ("SF0329", 5, 59.0, 11, 3273.70, "Trend Pullback to EMA · 15m", 34481.93),
    ("SF0401", 6, 58.0, 8, 3916.64, "MACD Histogram Turn · 15m", 29356.84),
    ("SF0113", 7, 57.9, 10, 1964.19, "Hammer / Shooting Star · 1m", 11895.35),
    ("SF0473", 8, 57.1, 10, 3250.00, "Pullback + EMA + RSI + VWAP · 15m", 28084.21),
    ("SF0367", 9, 56.9, 6, 4172.12, "RSI Trend Regime (40/60) · 1m", 17763.29),
    ("SF0179", 10, 56.8, 11, 2434.42, "Three Soldiers / Crows · 15m", 21172.03),
])
_SF_TOP10_20 = t10._picks([
    ("SF0116", 11, 56.2, 8, 3797.42, "Hammer / Shooting Star · 30m", 18162.39),
    ("SF0416", 12, 56.1, 10, 2743.75, "Supertrend Flip · 5m", 32691.84),
    ("SF0392", 13, 56.1, 9, 3340.42, "MACD Signal Cross · 5m", 29542.72),
    ("SF0229", 14, 55.9, 6, 5220.25, "Keltner Breakout · 45m", 24717.48),
    ("SF0108", 15, 55.4, 4, 6621.32, "Engulfing Candle · 30m", 22904.01),
    ("SF0230", 16, 54.5, 4, 7678.34, "Keltner Breakout · 1h", 27125.52),
    ("SF0533", 17, 54.5, 5, 3326.88, "Fib 61.8% + RSI + HTF Trend · 15m", 10915.92),
    ("SF0226", 18, 54.1, 11, 2376.87, "Keltner Breakout · 5m", 15410.48),
    ("SF0369", 19, 54.0, 5, 3309.59, "RSI Trend Regime (40/60) · 15m", 13828.23),
    ("SF0109", 20, 53.8, 4, 5751.71, "Engulfing Candle · 45m", 19524.14),
])

# PREMIUM OPTION BUYING STRATEGIES (16 Nov 2026). The owner asked, on the Best Strategies of Top 10 tab, for one more
# paper account on these two strategies with Rs 50,000 in all. The same picks and the same copy; only the money
# differs, so beside best2L it shows what account size does to the same trades (Angel's Rs 20 an order is a bigger
# share of a 1-3 lot position).
_PREMIUM50K_NOTES = _BEST_NOTES + (
    "₹50,000 in one account: two positions at most, each up to ₹25,000 of premium, paid in full (an option buyer "
    "has no leverage). A NIFTY lot is 65: the five trades the ₹2 lakh account took paid ₹84.60-163.30 an option "
    "(₹5,500-10,600 a lot), which here is 2-4 lots a position. An option above about ₹384 cannot buy one lot within "
    "₹25,000 and is skipped (price above the cap). Angel's ₹20 an order is a larger share of a position this size.",
)

# NIFTY BANK STRATEGIES · Rs 2 LAKH EACH / Rs 10 LAKH EACH (17 Nov 2026). The owner asked, on the NIFTY BANK tab, for
# a paper account for each of its ten strategies, in two sets: Rs 2 lakh each and Rs 10 lakh each. They copy the
# NIFTY BANK desk (banknifty_desk) - the ten the BANKNIFTY research chose (app/data/banknifty_research.json,
# committed 13 Oct 2026 23:06 IST), in its order. (strategy key, research rank, no Rank score, trades over 2016-2026,
# no bp figure, name, net P&L of 1 lot over 2016-2026 after spread and charges.)
BN_PICKED_AT = "2026-10-13T23:06:00+05:30"
_BN_PICKS = t10._picks([
    ("livermore_pivotal_point@1d", 1, None, 126, None, "Jesse Livermore: Pivotal Point Breakout", 259202.0),
    ("swing_fractal@1d", 2, None, 252, None, "Swing: Fractal Break", 413908.0),
    ("wt_btst@1d", 3, None, 1145, None, "Wizard Trader: BTST Trade (H5)", 375575.0),
    ("swing_gap_trend@1d", 4, None, 186, None, "Swing: Gap With Trend", 242513.0),
    ("bn_d_donchian_10@1d", 5, None, 178, None, "10-day high/low breakout, out on the 5-day opposite break", 362469.0),
    ("bn_d_donchian_20@1d", 6, None, 134, None, "20-day high/low breakout, out on the 10-day opposite break", 293998.0),
    ("swing_3day_momo@1d", 7, None, 270, None, "Swing: Three-Day Momentum", 217720.0),
    ("qullamaggie_flag@1d", 8, None, 253, None, "Kristjan Kullamägi (Qullamaggie): EMA Flag Breakout", 163844.0),
    ("swing_cci@1d", 9, None, 272, None, "Swing: CCI ±100", 135585.0),
    ("bn_gap_go_80bp_1515@5m", 10, None, 197, None, "Gap of 0.8%+ continuing in the first 15 minutes, out 15:15",
     21595.0),
])
_BN_DESK = t10.Desk(
    key="banknifty", label="Index Option Buying · NIFTY BANK desk", route="/prelive?index=banknifty",
    instrument="BANKNIFTY monthly options bought at the strike nearest the index: a CE when the strategy is long, a PE "
               "when it is short (the NIFTY BANK desk's own trades)",
    cost_basis="the premium paid at the ask (premium × 30 a lot)",
    board="the BANKNIFTY option-buying research: 297 strategies tested on 2016-2026, these ten kept as positive in both "
          "2016-2021 and 2022-2026 (tier C), none statistically significant",
    picks=_BN_PICKS, load=_load_banknifty, pnl=t10._bought_option_pnl, mark=t10._bought_option_mark, max_open=1,
)


def _bn_notes(each: str, lots: str) -> tuple[str, ...]:
    return (
        f"Each strategy has its own {each} and holds one position at a time, as on the desk; one strategy's losses "
        "never reduce another's money.",
        "The desk buys 1 lot (30) a signal. These accounts buy whole lots up to the strategy's free cash: at the "
        f"₹697-1,485 an option the desk has paid so far (₹21,000-45,000 a lot) that is {lots} lots, priced at the "
        "desk's own 1-lot fill (the ask in, the bid out). A real order that size would pay more to get in and out, "
        "so read the rupee P&L as an upper bound.",
        "Almost the whole account rides on each trade. The desk's stops on 23 and 30 Oct sold at about half the "
        "premium paid, and a trade like that takes about half of the strategy's money.",
        "Nine of the ten hold overnight for 1-7 sessions in the monthly contract (rolled to the next monthly near "
        "expiry); the gap strategy is in and out the same day. They often take the SAME trade on the same day - on "
        "5 Nov five bought the same call - so the accounts move together.",
        "Started empty: the positions the desk opened before this account's start are not copied. A strategy's "
        "account takes its first trade at that strategy's next entry on the desk.",
    )


_BN_CAVEAT = ("Chosen by research, and none is proven.",
              "Of 297 strategies tested, 11 made money in both 2016-2021 and 2022-2026 and none significantly - "
              "chance alone would have made about 70 look that good. This account is the forward test.")

BOOKS: dict[str, Book] = {
    "best2L": Book(
        key="best2L", label="Best Strategies of Top 10 · ₹2 lakh", desk=_BEST_DESK,
        capital=200000.0, slots=2, per_strategy=False,
        pick_rule="the two that made the most in both of this page's Top 10 Paper Trade accounts (₹2 lakh and ₹10 "
                  "lakh) from 27 Oct to 12 Nov 2026"),
    "premium50k": Book(
        key="premium50k", label="Premium Option Buying Strategies · ₹50k",
        desk=dataclasses.replace(_BEST_DESK, notes=_PREMIUM50K_NOTES),
        capital=50000.0, slots=2, per_strategy=False,
        pick_rule="the same two as the Best Strategies of Top 10 account - the two that made the most in both of this "
                  "page's Top 10 Paper Trade accounts (₹2 lakh and ₹10 lakh) from 27 Oct to 12 Nov 2026"),
    "sf_top10": Book(
        key="sf_top10", label="Top 10 Performing Strategies · ₹10 lakh each",
        desk=dataclasses.replace(_FACTORY_DESK, picks=_SF_TOP10, notes=_FACTORY_NOTES + (
            "SF0474 and SF0330 have taken the same 8 trades so far, and SF0329 and SF0473 share 8 of theirs, so "
            "this book often holds one trade twice.",
            "SF0113 and SF0367 are 1-minute strategies. The tab took no 1-minute entries on 12 Nov (it reported "
            "its 1-minute NIFTY bars behind), and they trade only while that feed is current.")),
        capital=1000000.0, slots=1, per_strategy=True,
        pick_rule="ranks 1-10 on the Strategy Factory tab's Rank (146 strategies with closed trades, 28 Oct - 12 Nov "
                  "2026)"),
    "sf_top10_20": Book(
        key="sf_top10_20", label="Top 10-20 Performing Strategies · ₹10 lakh each",
        desk=dataclasses.replace(_FACTORY_DESK, picks=_SF_TOP10_20, notes=_FACTORY_NOTES),
        capital=1000000.0, slots=1, per_strategy=True,
        pick_rule="ranks 11-20 on the Strategy Factory tab's Rank (146 strategies with closed trades, 28 Oct - 12 Nov "
                  "2026)"),
    "bn2L": Book(
        key="bn2L", label="NIFTY BANK Strategies · ₹2 lakh each",
        desk=dataclasses.replace(_BN_DESK, notes=_bn_notes("₹2,00,000", "about 4-9")),
        capital=200000.0, slots=1, per_strategy=True, picked_at=BN_PICKED_AT, source="the NIFTY BANK desk",
        caveat=_BN_CAVEAT,
        pick_rule="the ten the NIFTY BANK desk trades, chosen by the BANKNIFTY research's pre-registered protocol "
                  "(297 tested on 2016-2026)"),
    "bn10L": Book(
        key="bn10L", label="NIFTY BANK Strategies · ₹10 lakh each",
        desk=dataclasses.replace(_BN_DESK, notes=_bn_notes("₹10,00,000", "about 22-47")),
        capital=1000000.0, slots=1, per_strategy=True, picked_at=BN_PICKED_AT, source="the NIFTY BANK desk",
        caveat=_BN_CAVEAT,
        pick_rule="the ten the NIFTY BANK desk trades, chosen by the BANKNIFTY research's pre-registered protocol "
                  "(297 tested on 2016-2026)"),
}


# -- the Rank-band and all-546 accounts (17 Nov 2026) ------------------------------------------------
# Picks: prelive_pick_roster.SF546, frozen at 20:35 IST on 17 Nov 2026. Never re-pick them without the owner.

SF_GROUP = "sf-bands"
SF_SIZES = (("2L", 200000.0, "₹2 lakh"), ("10L", 1000000.0, "₹10 lakh"))
_SF_ALL = t10._picks(list(SF546))
_SF_TOP50 = tuple(p for p in _SF_ALL if p.rank is not None and p.rank <= 50)
_SF_BOARD_1711 = (f"the Strategy Factory tab's Rank on Index Option Buying ({SF_RANKED} strategies with closed "
                  "trades, 28 Oct - 17 Nov 2026)")
_SF_DESK_1711 = dataclasses.replace(_FACTORY_DESK, board=_SF_BOARD_1711)
_UPPER_BOUND = ("The tab buys 1 lot a signal. These accounts buy whole lots up to {room}, priced at the tab's own "
                "1-lot fill (the ask in, the bid out) - roughly {lots} lots at the premiums these strategies have paid "
                "(₹1,900-16,400 a lot). A real order that size would pay more to get in and out, so read the rupee "
                "P&L as an upper bound.")
_LUCK = ("Picked after the fact off a board of {ranked} on 1 to 31 closed trades each ({few} of the 50 have fewer "
         "than 5). The Rank shrinks a short record toward the middle, but luck still collects at the top. On this "
         "desk a month's top 20 option-buying strategies lost the next month 11 times in 12 (Option Buying Top 20 "
         "study, Oct 2026).")


def _inr(v: float) -> str:
    """Rs in the Indian grouping: 200000 -> '₹2,00,000'."""
    s = f"{int(round(v)):d}"
    head, tail = s[:-3], s[-3:]
    while len(head) > 2:
        tail = f"{head[-2:]},{tail}"
        head = head[:-2]
    return f"₹{head},{tail}" if head else f"₹{tail}"


def _lots(room: float) -> str:
    return f"{max(int(room // 16400), 1)} to {int(room // 1900)}"


def _twins(picks: tuple[t10.Pick, ...]) -> list[str]:
    """Pairs in one band with the same record on the tab to the paisa: in practice the same trades."""
    out, seen = [], set()
    for i, a in enumerate(picks):
        for b in picks[i + 1:]:
            if (a.key not in seen and a.trades == b.trades and a.bp == b.bp and a.net == b.net):
                seen.add(b.key)
                out.append(f"#{a.rank} {a.name} and #{b.rank} {b.name} have the same record on the tab ({a.trades} "
                           "trades, the same net to the paisa): they take the same trades, so this account usually "
                           "holds the first and skips the second as already holding that contract.")
    return out


def _sf_more_books() -> dict[str, Book]:
    """20 Rank-band accounts (ten bands of five x Rs 2 lakh / Rs 10 lakh) + the two all-546 books."""
    out: dict[str, Book] = {}
    few = sum(1 for p in _SF_TOP50 if p.trades < 5)
    for lo in range(1, 51, 5):
        hi = lo + 4
        picks = tuple(p for p in _SF_TOP50 if lo <= p.rank <= hi)
        rule = (f"ranks {lo}-{hi} on the Strategy Factory tab's Rank ({SF_RANKED} strategies with closed trades, "
                "28 Oct - 17 Nov 2026), frozen at 20:35 IST on 17 Nov 2026: "
                + "; ".join(f"#{p.rank} {p.name}" for p in picks))
        for suffix, capital, cap_label in SF_SIZES:
            key = f"sfb{lo}_{hi}_{suffix}"
            slot = capital / 5
            notes = (
                f"One account with a slot for each of its five strategies: at most five positions at once, each up "
                f"to a fifth of the account ({_inr(slot)}), in whole lots. Never two positions in one contract: when "
                "two of the five want the same option at once, the second is skipped and counted.",
                _UPPER_BOUND.format(room=f"the slot's {_inr(slot)}", lots=_lots(slot)),
                _LUCK.format(ranked=SF_RANKED, few=few),
                *_twins(picks),
            )
            out[key] = Book(
                key=key, label=f"Strategy Factory Rank {lo}-{hi} · {cap_label}",
                desk=dataclasses.replace(_SF_DESK_1711, picks=picks, notes=notes),
                capital=capital, slots=5, per_strategy=False, pick_rule=rule,
                picked_at=SF_PICKED_AT, group=SF_GROUP)
    for suffix, capital, cap_label in SF_SIZES:
        key = f"sf_all_{suffix}"
        notes = (
            f"Each of the {len(_SF_ALL)} strategies has its own {_inr(capital)} ({_inr(capital * len(_SF_ALL))} in "
            "all) and holds one position at a time, as on the Strategy Factory tab; one strategy's losses never "
            "reduce another's money.",
            _UPPER_BOUND.format(room="the strategy's free cash", lots=_lots(capital)),
            f"All {len(_SF_ALL)}, not a pick: {len(_SF_ALL) - SF_RANKED} had not closed a trade on the tab when this "
            "account was made (1-minute strategies trade only while that feed is current; 4-hour and daily ones "
            "signal rarely). The book's return is over every account, most of them idle, so it stays small "
            "whichever way it goes - read each strategy's own return.",
            "On the tab itself, 28 Oct - 17 Nov 2026 (1 lot a signal): 161 strategies closed 1,205 trades for "
            "+₹13.35 lakh net. That is the record before this account; it starts empty.",
        )
        out[key] = Book(
            key=key, label=f"All {len(_SF_ALL)} Factory Strategies · {cap_label} each",
            desk=dataclasses.replace(_SF_DESK_1711, picks=_SF_ALL, notes=notes),
            capital=capital, slots=1, per_strategy=True,
            pick_rule=(f"all {len(_SF_ALL)} strategies of the Strategy Factory tab, as listed at 20:35 IST on 17 Nov "
                       f"2026 ({SF_RANKED} of them ranked then), in Rank order"),
            picked_at=SF_PICKED_AT)
    return out


BOOKS.update(_sf_more_books())
BOOK_KEYS = list(BOOKS)
BOOK_LABEL = {k: b.label for k, b in BOOKS.items()}


def normalize_book(book: str | None) -> str:
    return book if book in BOOKS else BOOK_KEYS[0]


# -- state ------------------------------------------------------------------------------------------


async def _start(book: str) -> datetime:
    """When the book began copying: set once, on its first cycle. Nothing earlier is copied."""
    key = f"start:{book}"
    doc = await STATE.find_one({"_id": key})
    if doc and doc.get("started_at"):
        return naive_utc(doc["started_at"])
    await STATE.update_one({"_id": key}, {"$setOnInsert": {"started_at": t10._now(), "book": book}}, upsert=True)
    doc = await STATE.find_one({"_id": key})
    return naive_utc(doc["started_at"])


def _skip_doc(book: str, acct: str, day: str) -> str:
    return f"skipped:{book}:{acct}:{day}"


async def _decided(book: str, parents_by: dict[str, list[dict]]) -> set[str]:
    """Parents the book's accounts have already taken or skipped. A parent belongs to one account (its
    strategy's), so one set serves them all."""
    ids = [p["position_id"] for ps in parents_by.values() for p in ps]
    out: set[str] = set()
    if not ids:
        return out
    async for r in POSITIONS.find({"book": book, "parent_position_id": {"$in": ids}}, {"parent_position_id": 1}):
        out.add(r["parent_position_id"])
    skip_ids = [_skip_doc(book, acct, day) for acct, ps in parents_by.items()
                for day in sorted({p.get("opened_on") for p in ps if p.get("opened_on")})]
    if skip_ids:
        async for s in STATE.find({"_id": {"$in": skip_ids}}, {"ids": 1}):
            out.update(s.get("ids") or [])
    return out


async def _totals(book: str, accts: list[str]) -> dict[str, tuple[float, float]]:
    """Each account's realised P&L and the capital its open positions tie up."""
    out: dict[str, list[float]] = {a: [0.0, 0.0] for a in accts}
    async for r in POSITIONS.find({"book": book, "account": {"$in": accts}},
                                  {"account": 1, "status": 1, "realized_pnl": 1, "capital_deployed": 1}):
        x = out.get(r.get("account"))
        if x is None:
            continue
        if r.get("status") == "OPEN":
            x[1] += r.get("capital_deployed") or 0.0
        else:
            x[0] += r.get("realized_pnl") or 0.0
    return {a: (v[0], v[1]) for a, v in out.items()}


async def _closed_after(book: str, acct: str, t0: datetime | None) -> list[dict]:
    if t0 is None:
        return []
    return [r async for r in POSITIONS.find(
        {"book": book, "account": acct, "status": "CLOSED", "closed_at": {"$gt": t0}},
        {"symbol": 1, "capital_deployed": 1, "realized_pnl": 1, "opened_at": 1, "closed_at": 1})]


# -- the copy ---------------------------------------------------------------------------------------


async def _sync_book(b: Book, entries: bool) -> dict:
    """Every account of one book, from one read of each collection: the book's open rows, the desk's trades
    of its strategies, what was already decided, and the totals of the accounts with something to do. An
    account runs plan_book only when it has a trade to decide or a position to close or mark, so a book of
    546 accounts costs a few reads a cycle, not thousands."""
    d = b.desk
    floor = max(await _start(b.key), naive_utc(t10._now()) - LOOKBACK)
    accts = b.accounts()
    owner = {k: acct for acct, keys in accts for k in keys}
    open_by: dict[str, list[dict]] = {}
    async for r in POSITIONS.find({"book": b.key, "status": "OPEN"}):
        open_by.setdefault(r.get("account") or SHARED, []).append(r)
    pointed = {r["parent_position_id"] for rows in open_by.values() for r in rows if r.get("parent_position_id")}
    parents_by: dict[str, list[dict]] = {}
    for p in await d.load(floor, set(owner), list(pointed)):
        acct = owner.get(p.get("key"))
        if acct is None or p.get("opened_at") is None:
            continue
        if p["opened_at"] >= floor or p["position_id"] in pointed:
            parents_by.setdefault(acct, []).append(p)
    for ps in parents_by.values():
        ps.sort(key=lambda p: (p["opened_at"], p["position_id"]))
    decided = await _decided(b.key, parents_by) if entries else set()

    def busy(acct: str) -> bool:
        if open_by.get(acct):
            return True
        return entries and any(p["position_id"] not in decided for p in parents_by.get(acct, ()))

    work = [acct for acct, _ in accts if busy(acct)]
    totals = await _totals(b.key, work) if work else {}
    out = {"accounts": len(accts), "active": len(work), "opened": 0, "closed": 0, "skipped": 0, "marked": 0,
           "errors": {}}
    for acct in work:
        try:
            n = await _apply_account(b, acct, parents_by.get(acct, []), open_by.get(acct, []),
                                     *totals.get(acct, (0.0, 0.0)), decided, entries)
        except Exception as exc:  # noqa: BLE001 - one account's bad row must not stop the rest
            logger.warning("[prelive_pick_books] %s %s failed: %s", b.key, acct, exc, exc_info=True)
            out["errors"][acct] = str(exc)[:200]
            continue
        for k, v in n.items():
            out[k] += v
    return out


async def _apply_account(b: Book, acct: str, parents: list[dict], open_rows: list[dict], realized: float,
                         deployed: float, decided: set[str], entries: bool) -> dict:
    """One account of the book: the desk's trades of its strategies, replayed in time order."""
    d = b.desk
    t0 = pending_since(parents, decided, open_rows, SOURCE_TAG) if entries else None
    closed_rows = await _closed_after(b.key, acct, t0) if entries else []
    plan = plan_book(capital=b.capital, realized=realized, deployed=deployed, open_rows=open_rows,
                     parents=parents, decided=decided, breaker_tripped=False, entries=entries,
                     max_open=b.slots, net_fn=t10._net_fn(d), source_tag=SOURCE_TAG, closed_rows=closed_rows)

    n = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0}
    for c in plan["closes"]:
        res = await POSITIONS.update_one({"_id": c["row"]["_id"], "status": "OPEN"},
                                         {"$set": t10._close_fields(c["parent"], c)})
        n["closed"] += res.modified_count
    for o in plan["opens"]:
        p = o["parent"]
        doc = t10._row(d, b.key, p, o["qty"], o["spend"])
        doc.update({"source": SOURCE_TAG, "account": acct,
                    "allocation": b.capital if b.per_strategy else None})
        if o["close"] is not None:
            doc.update(t10._close_fields(p, o["close"]))
        try:
            await POSITIONS.insert_one(doc)
        except DuplicateKeyError:
            continue
        n["opened"] += 1
        n["closed"] += 1 if o["close"] is not None else 0
    per: dict[str, dict[str, int]] = {}
    ids_by_day: dict[str, list[str]] = {}
    for s in plan["skips"]:
        p = s["parent"]
        k = per.setdefault(p["key"], {})
        k[s["reason"]] = k.get(s["reason"], 0) + 1
        ids_by_day.setdefault(p.get("opened_on") or "", []).append(p["position_id"])
        n["skipped"] += 1
    for day, ids in ids_by_day.items():
        await STATE.update_one({"_id": _skip_doc(b.key, acct, day)},
                               {"$addToSet": {"ids": {"$each": ids}},
                                "$set": {"book": b.key, "account": acct, "day": day}}, upsert=True)
    for key, counts in per.items():
        await SCORES.update_one({"book": b.key, "key": key},
                                {"$inc": {f"skipped.{r}": v for r, v in counts.items()},
                                 "$set": {"updated_at": t10._now()}}, upsert=True)

    by_id = {p["position_id"]: p for p in parents}
    closed_now = {c["row"]["_id"] for c in plan["closes"]}
    for r in open_rows:
        if r["_id"] in closed_now:
            continue
        p = by_id.get(r.get("parent_position_id"))
        if not p or p.get("status") != "OPEN":
            continue
        u = d.mark(p, int(r["qty"]))
        if u is None:
            continue
        await POSITIONS.update_one({"_id": r["_id"], "status": "OPEN"},
                                   {"$set": {"ltp": p.get("px_ltp"), "unrealized_pnl": u, "updated_at": t10._now()}})
        n["marked"] += 1
    return n


_lock = asyncio.Lock()
_indexed = False


async def sync(entries: bool = True, only: str | None = None) -> dict:
    """Copy every book's desk once."""
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    out: dict = {}
    async with _lock:
        for key, b in BOOKS.items():
            if only and key != only:
                continue
            try:
                out[key] = await _sync_book(b, entries)
            except Exception as exc:  # noqa: BLE001 - one book's failure must not stop the rest
                logger.warning("[prelive_pick_books] %s failed: %s", key, exc, exc_info=True)
                out[key] = {"error": str(exc)[:200]}
            try:
                await _snapshot(b)
            except Exception:  # noqa: BLE001
                logger.warning("[prelive_pick_books] snapshot %s failed", key, exc_info=True)
    return out


async def _snapshot(b: Book) -> None:
    """An equity point at most every 15 minutes in the NSE session, or whenever realised P&L moves. Outside
    the session nothing is marked, so a point then would only repeat the last one."""
    s = await summary(b.key)
    last = await EQUITY.find_one({"book": b.key}, sort=[("ts", -1)])
    stale = last is None or (_nse_minutes()
                             and (naive_utc(t10._now()) - naive_utc(last["ts"])) > SNAPSHOT_EVERY)
    if stale or abs((last or {}).get("realized", 0.0) - s["realized_pnl"]) > 0.005:
        await EQUITY.insert_one({"ts": t10._now(), "book": b.key, "equity": s["equity"],
                                 "realized": s["realized_pnl"], "unrealized": s["unrealized_pnl"],
                                 "open_positions": s["open_positions"]})


def _nse_minutes() -> bool:
    t = datetime.now(t10.IST)
    if t.weekday() >= 5:
        return False
    hm = t.hour * 60 + t.minute
    return 9 * 60 + 10 <= hm <= 15 * 60 + 45


async def loop() -> None:
    """Every minute through the NSE session, every ten minutes otherwise (late closes still land)."""
    await asyncio.sleep(45)
    while True:
        if ENABLED:
            try:
                await sync(entries=True)
            except Exception:  # noqa: BLE001
                logger.warning("[prelive_pick_books] cycle failed", exc_info=True)
        await asyncio.sleep(60 if _nse_minutes() else 600)


# -- read models: the Top-10 / rank-band shapes ------------------------------------------------------


async def summary(book: str) -> dict:
    b = BOOKS[normalize_book(book)]
    d = b.desk
    cap = b.total_capital
    realized = unrealized = deployed = fees = gross = 0.0
    open_n = closed_n = wins = 0
    traded: set[str] = set()
    async for r in POSITIONS.find({"book": b.key}, {"status": 1, "capital_deployed": 1, "unrealized_pnl": 1,
                                                    "realized_pnl": 1, "fees": 1, "gross_pnl": 1, "key": 1}):
        traded.add(r.get("key"))
        if r.get("status") == "OPEN":
            open_n += 1
            deployed += r.get("capital_deployed") or 0.0
            unrealized += r.get("unrealized_pnl") or 0.0
        else:
            closed_n += 1
            v = r.get("realized_pnl") or 0.0
            realized += v
            wins += 1 if v > 0 else 0
            fees += r.get("fees") or 0.0
            gross += r.get("gross_pnl") or 0.0
    skipped = {k: 0 for k in SKIP_REASONS}
    async for s in SCORES.find({"book": b.key}, {"skipped": 1}):
        for k, v in (s.get("skipped") or {}).items():
            if k in skipped:
                skipped[k] += int(v or 0)
    start = await STATE.find_one({"_id": f"start:{b.key}"})
    started = start.get("started_at") if start else None
    equity = cap + realized + unrealized
    n = len(b.picks)
    return {
        "book": b.key, "books": BOOK_KEYS, "label": b.label, "book_labels": BOOK_LABEL, "module": MODULE,
        "desk": d.key, "desk_label": d.label, "mode": "paper", "enabled": ENABLED,
        "instrument": d.instrument, "cost_basis": d.cost_basis, "board": d.board, "pick_rule": b.pick_rule,
        "notes": list(d.notes), "picked_at": b.picked_at, "group": b.group or None, "strategies": n,
        "source_label": b.source, "route": d.route, "caveat_title": b.caveat[0], "caveat": b.caveat[1],
        # the roster in full only where it is short; the all-546 books list theirs in the leaderboard
        "roster": list(d.roster) if n <= 50 else None, "pick_names": [p.name for p in b.picks] if n <= 50 else None,
        "board_ranks": [p.rank for p in b.picks] if n <= 50 else None,
        "strategies_traded": len(traded - {None}), "per_strategy": b.per_strategy,
        "per_strategy_capital": b.capital if b.per_strategy else None,
        "positions_per_strategy": b.slots if b.per_strategy else None,
        "max_open_positions": b.slots * (n if b.per_strategy else 1),
        "position_cap": round(b.capital / max(b.slots, 1), 2),
        "desk_capital": cap, "equity": round(equity, 2), "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2), "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "deployed": round(deployed, 2), "available_cash": round(cap + realized - deployed, 2),
        "open_positions": open_n, "closed_positions": closed_n, "wins": wins,
        "roi_pct": round((equity - cap) / cap * 100, 4) if cap else 0.0, "skipped": skipped,
        "copying_since": (naive_utc(started).replace(tzinfo=timezone.utc).isoformat() if started else None),
    }


async def leaderboard(book: str) -> list[dict]:
    """The picks in rank order: each one's record in this book (and its own account where it has one)."""
    b = BOOKS[normalize_book(book)]
    rec: dict[str, dict] = {p.key: {"trades": 0, "wins": 0, "net": 0.0, "gross": 0.0, "fees": 0.0, "open": 0,
                                    "unrealized": 0.0, "deployed": 0.0} for p in b.picks}
    async for r in POSITIONS.find({"book": b.key}, {"key": 1, "status": 1, "unrealized_pnl": 1, "capital_deployed": 1,
                                                    "realized_pnl": 1, "gross_pnl": 1, "fees": 1}):
        x = rec.get(r.get("key"))
        if x is None:
            continue
        if r.get("status") == "OPEN":
            x["open"] += 1
            x["unrealized"] += r.get("unrealized_pnl") or 0.0
            x["deployed"] += r.get("capital_deployed") or 0.0
            continue
        v = r.get("realized_pnl") or 0.0
        x["trades"] += 1
        x["wins"] += 1 if v > 0 else 0
        x["net"] += v
        x["gross"] += r.get("gross_pnl") or 0.0
        x["fees"] += r.get("fees") or 0.0
    sk: dict[str, dict] = {}
    async for s in SCORES.find({"book": b.key}, {"key": 1, "skipped": 1}):
        sk[s["key"]] = {k: int((s.get("skipped") or {}).get(k, 0)) for k in SKIP_REASONS}
    base = b.capital if b.per_strategy else b.total_capital
    rows = []
    for p in b.picks:
        x = rec[p.key]
        skipped = sk.get(p.key) or {k: 0 for k in SKIP_REASONS}
        rows.append({
            "key": p.key, "strategy_id": p.key, "name": p.name,
            "picked_rank": p.rank, "picked_score": p.score, "picked_trades": p.trades,
            "picked_bp": p.bp, "picked_net_pnl": p.net,
            "trades": x["trades"], "wins": x["wins"],
            "win_rate": round(x["wins"] / x["trades"], 4) if x["trades"] else 0.0,
            "net_pnl": round(x["net"], 2), "gross_pnl": round(x["gross"], 2), "fees": round(x["fees"], 2),
            "unrealized_pnl": round(x["unrealized"], 2), "deployed": round(x["deployed"], 2),
            "allocation": b.capital if b.per_strategy else None,
            "equity": round(b.capital + x["net"] + x["unrealized"], 2) if b.per_strategy else None,
            # its own account's return, or (one shared account) its share of the book
            "roi_pct": round((x["net"] + x["unrealized"]) / base * 100, 4) if base else 0.0,
            "open_positions": x["open"], "skipped": skipped, "skipped_total": sum(skipped.values()),
        })
    return rows


async def positions(book: str, status: str = "OPEN", limit: int = 200) -> list[dict]:
    b = normalize_book(book)
    q: dict = {"book": b}
    if status.upper() != "ALL":
        q["status"] = status.upper()
    sort_key = "opened_at" if status.upper() == "OPEN" else "closed_at"
    return [t10._jsonable(r) async for r in POSITIONS.find(q).sort(sort_key, -1).limit(limit)]


def books() -> list[dict]:
    """Every book and its picks (an all-546 book gives its count; its leaderboard lists them)."""
    return [{"book": b.key, "label": b.label, "capital": b.total_capital, "per_strategy": b.per_strategy,
             "per_strategy_capital": b.capital if b.per_strategy else None, "slots": b.slots,
             "desk": b.desk.key, "pick_rule": b.pick_rule, "picked_at": b.picked_at, "group": b.group or None,
             "strategies": len(b.picks),
             "picks": [{"key": p.key, "rank": p.rank, "score": p.score, "trades": p.trades, "bp": p.bp,
                        "name": p.name, "net": p.net} for p in b.picks] if len(b.picks) <= 50 else None}
            for b in BOOKS.values()]


def groups() -> dict[str, list[str]]:
    """Books the page shows together, by group, in their defined order."""
    out: dict[str, list[str]] = {}
    for key, b in BOOKS.items():
        if b.group:
            out.setdefault(b.group, []).append(key)
    return out


async def accounts(group: str) -> list[dict]:
    """Every account of one group, each with its summary: one call for an overview table."""
    return list(await asyncio.gather(*(summary(k) for k in groups().get(group, []))))


async def ensure_indexes() -> None:
    """Best effort: an index failure must never stop the books."""
    try:
        await POSITIONS.create_index([("book", 1), ("parent_position_id", 1)], name="pb_parent_unique", unique=True)
        await POSITIONS.create_index([("book", 1), ("account", 1), ("status", 1)], name="pb_book_account_status")
        await SCORES.create_index([("book", 1), ("key", 1)], name="pb_score_key", unique=True)
        await EQUITY.create_index([("book", 1), ("ts", -1)], name="pb_equity_ts")
    except Exception:  # noqa: BLE001
        logger.warning("[prelive_pick_books] index creation skipped", exc_info=True)
