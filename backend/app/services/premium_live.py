"""Real money on Delta Exchange India for Premium strategies: two desks on one engine (2026-11-13, split 2026-11-14).

DESKS. Each desk has its own picks, products, switch (off / shadow / live), daily loss stop, state and trade records;
they share the Delta account, its keys and the owner's PIN, and never trade the same product.
- gold (Premium Strategies > "Real money · Delta gold"): the five gold picks of 13 Nov, CP-06 (15 Nov), TL-04's gold
  book (16 Nov), and from 18 Nov thirteen more Premium gold books and six Gold Desk H1 templates, on XAUTUSD; the
  Gold Desk Strategy Factory's top 20 on 19 Nov; 49 more on 22 Nov; three more on 24 Nov; 152 more Factory
  strategies on 27 Nov (254 in all).
  Its records are the original ones (live_delta_state / live_delta_trades).
- crypto (the "Delta Exchange Live Trading" module, 14 Nov): the bitcoin strategies the owner picked from the Crypto
  tab - TH-05, TL-04 and TH-01 on 14 Nov, TD-02 on 15 Nov, five more on 18 Nov - on BTCUSD, a $20 daily stop
  (live_crypto_state / live_crypto_trades); seven more bitcoin books and two ether books (ETHUSD) on 22 Nov, six
  more bitcoin books and two more ether books on 24 Nov (32 in
  all). From 15 Nov both desks trade one contract a trade (the owner can pick $1
  to $5 of risk instead) and copy a signal seen up to 10 minutes late.
  On 14 Nov the owner moved bitcoin here from the gold desk; the gold desk's earlier bitcoin picks (TH-01, TH-05, RU-04,
  TD-02, TD-03) left it, and any bitcoin trade it still had open would be managed by it to its close.

THE ORIGINAL DESK (13 Nov). The owner asked for five bitcoin and five gold strategies from Premium Strategies to trade
REAL money on Delta, and chose the size: $5 of risk a trade and a $20 daily loss stop. Before choosing, the owner was shown the record:
since 8 Nov the desk's 107 bitcoin books lost -397R over 585 trades and its 90 gold books -166R; of the ten below, six
lose in their own 2-year backtests (700-2,900 trades each) and four were never backtested; every backtested bitcoin
strategy in the module loses after Delta's fee but one with 24 trades. None is proven. This desk exists because the
owner chose to trade them anyway, at a size meant to be affordable to lose.

THE TEN are frozen as picked on 13 Nov 2026 at 23:00 IST: the five bitcoin and five gold paper books with the best
record since 8 Nov among those with at least five closed trades and a net profit, ranked by the t-stat of their net
R a trade (R = what a trade risks).

WHAT IT DOES. It copies the paper desk's trades of those ten (premium-paper-service's premium_trades, in the box's
local MongoDB) into real Delta orders. The paper desk decides every entry and exit, and this desk never re-scans:
- A paper entry is copied only if it is seen within its desk's lag limit of its entry time (MAX_LAG_S; the bitcoin
  desk's CRYPTO_MAX_LAG_S), the market is still within DRIFT_FRAC of a risk distance of the paper entry, and the price
  is strictly between the paper's stop and target. The order is a market order of one contract, the smallest order
  Delta allows (the default from 15 Nov; skipped if that one contract would lose more than the desk's RISK_USD at the
  stop), or, when the owner picks a dollar risk on the page (RISK_MIN_USD up to RISK_USD), sized so the
  paper's stop loses at most that: contracts = risk / (|price - stop| x contract value), and never more than
  MAX_NOTIONAL_USD of notional; then a trade whose single contract would lose more than that risk is skipped.
- The paper's own stop and target go on the venue right after the fill as the trade's OWN two orders (from 15 Nov:
  standalone stop orders of the trade's size, not reduce-only, their ids on the trade). If either is refused, the
  trade is closed at once and the desk switches itself off: a real trade never stays unprotected.
- When the paper trade closes, for any reason, or disappears, its legs are cancelled first and then the trade is
  closed at the market by its own size. When a leg fills first, the other is cancelled and the close is recorded
  from that leg; legs that filled beyond the trade (both, in a very fast move) are offset at the market at once.
- Every strategy of a desk may hold a trade at the same time (the owner's choice, 15 Nov). Delta keeps one netted
  position per product, so every cycle the desk checks that the account's position equals the sum of the desks'
  trades: a mismatch makes new entries wait, and one seen on three checks switches the desk off, touching nothing.
  A trade from before (one bracket on the whole position) is managed the old way, and nothing new enters its product
  while it is open.
- The daily loss stop: once today's (IST) closed plus open P&L reaches -DAILY_STOP_USD, no new entry until tomorrow.
- Before going live, leverage is set to LEVERAGE on both products and read back. Delta's defaults, 200x on BTCUSD and
  100x on XAUTUSD, liquidate inside the strategies' stops.

MODES
- off: no new trade; open positions are still managed to their close.
- shadow: every decision is made and logged with simulated fills at the quote, and no order is sent.
- live: real orders.
Going live also needs the words REAL MONEY in the request (the page sends them). The owner's PIN is asked for going
live, flattening and changing the size only when PREMIUM_LIVE_REQUIRE_PIN=1; the owner chose no PIN on 15 Nov.
Three venue errors in a row switch the desk off (a good answer from Delta starts the count again).

MAIN CONTROL (17 Nov 2026). Both desks are one module there, "delta_live", with the ON/OFF switch in the header of the
Delta Exchange Live Trading page. OFF stops new entries on both desks whatever their own mode, and leaves the mode as it
is: a trade already open is still managed to its close, exactly as in mode off. Once neither desk holds a trade the loop
stops running altogether until the switch is back ON, when each desk carries on in the mode it was left in. A signal
from the OFF stretch is then taken only as any late-seen signal is: inside the desk's lag and drift limits.

18 NOV 2026: MORE PICKS, AND A SECOND SOURCE. The owner sent the Premium leaderboard's bitcoin and gold rows and asked
for them on these desks: five bitcoin books (TH-06, DT-02, RU-06, NJ-47, RU-03) and thirteen gold ones (BB-11, PT-04,
RU-03, SB-06, RU-04, PR-12, TP-05, DT-01, DT-03, CD-02, CP-02, RU-05, FZ-02) join the books already here; DD-03 was in
the screenshots too but trades Ether, which neither desk trades. Records are frozen at 22:00 IST (NEW_PICKED_AT).
A second batch that night (records at 23:50 IST, NEW_PICKED_AT_2): gold BG-01, JR-04, TD-04, TC-11; bitcoin TH-04,
DT-01, TH-07, NJ-27, PT-04, SB-04 (DD-04 is Ether again). Every gold book reads Delta's XAUTUSD candles on the paper
desk, so all gold signals come from Delta's own data, as the bitcoin ones always did.
The page also gains a paper view (_paper_view): each pick's paper record and open trades now, and the latest paper
trades with this desk's decision on each, so the strategies' own trades show beside the real ones.
The owner also asked for six templates of the Gold Desk's H1 forward test (EMA Ribbon Compression, Round Number Break,
Donchian Breakout fast and slow, Pivot R1/S1 Break, Keltner Breakout; 4h, XAUTUSD). They are not Premium books: the
gold desk reads their positions from the Gold Desk itself (gold_desk_positions, venue delta, h1) and treats each one
as a paper trade with the id "H1|<position_id>" (_paper_h1). The H1 record itself is untouched: this desk only reads
it. Its liveness is the Gold Desk's own (gold_desk_state "delta" last_run_at), and when those positions cannot be read
the H1 trades wait - managed again on the next good read, their stop and target resting on Delta meanwhile - rather
than being closed as disappeared.

FOLLOW EVERY PAPER TRADE (19 Nov 2026, the gold desk). The owner asked that all 30 gold strategies take a real position
whenever their paper trade does, with nothing stopping the copy. That desk has follow_all: it reads every open paper
trade of its picks however long ago it entered (and every open H1 position), and copies it, with the paper's own stop
and target, at whatever the price is now:
- no lag limit and no drift limit, and a trade already open on paper when the desk was switched on is copied too;
- a copy that cannot go in yet WAITS (nothing recorded, tried again next cycle, the reason in _WAITING for the page)
  instead of being skipped for good: the price not inside the paper's stop and target with FOLLOW_PAD_TICKS and
  FOLLOW_PAD_FRAC of the risk to spare (so a market fill cannot land past a level, which would close the trade and
  switch the desk off), a silent paper desk or Gold Desk, no quote, a failed wallet read, the daily loss stop
  (tomorrow it copies what is still open), an older one-bracket trade on the product;
- a paper trade with no stop (PR-12's ladder) gets a protective stop GUARD_STOP_FRAC from the price, because a real
  trade never stands on Delta without one; it otherwise closes when its paper trade closes, as every copy does.
What still ends a copy for good: the paper trade closing first, a refused or unfilled order. The switches (this desk's
mode, Main Control) are untouched.
Later that evening the owner widened it: "all the gold and btc strategies can place trades at the same time ... no
stop for signal to convert into positions, only thing is, buy or sell with least money/lot". So BOTH desks follow every
paper trade, and a follow_all desk has no daily loss stop and no cap on what one contract may lose (at one contract,
the default size; a dollar risk picked on the page still sizes and caps as before). Too little free margin waits for
the next pass (the wallet is read once a pass and each entry takes its margin off it). With no cap on what a contract
may lose, a copy's stop is pulled in to MAX_STOP_FRAC (7%) of the price when the paper's is farther: at 10x Delta
liquidates about 9.5% against a position, so a farther stop would never be reached, and the trade's own stop order (not
reduce-only) could open a position after a liquidation.

19 NOV 2026: THE GOLD DESK'S STRATEGY FACTORY TOP 20, A THIRD SOURCE. The owner sent the Gold Desk "Strategy Factory ·
546" board and asked for its top 20 on real money. They are not Premium books: the gold desk reads their positions from
the tab itself (factory_desk_positions, desk gold, in the Factory's own store) and treats each one as a paper trade with
the id "SF|<position_id>" (_paper_sf), exactly as the H1 positions: its stop and target (levels of XAUTUSD itself), its
exit (stop, target or the tab's hold limit). Liveness = the tab's own cycle (factory_desk_state "cycle:gold" at); an
unreadable store leaves its trades waiting, never closed. Records frozen at NEW_PICKED_AT_3 (21:29 IST, the owner's
screenshot), in R; they match the board.

22 NOV 2026: THE OWNER'S THIRD LIST, AND ETHER. The owner sent the Premium Crypto and Gold tabs, the Gold Desk's H1
"Strategy records" and its Strategy Factory board, and asked for every strategy on them on real money ("if it is
already there, skip it"; the live rules unchanged). The screenshots held the boards' winning rows; a row already on
its desk was skipped. New:
- bitcoin desk: DT-05, TL-03, RU-04, KA-01, DD-01, TD-04, TC-04 (BTCUSD), and the ether books of DD-04 and BX-02 on
  Delta's ETHUSD perpetual (0.01 ETH a contract), the first time a desk trades a second product;
- gold desk: ten Premium gold books (CP-21, YT-18, TF-01, CP-01, FL-02, MH-01, DT-02, BG-08, RU-06, JR-03), the H1
  test's Prior Session High/Low Break, and 38 more of the Factory board's top 56 (ranks 17 and 34, hidden under the
  board's sticky header in the screenshots, are inside the 56 the owner scrolled through).
Records at NEW_PICKED_AT_4 (14:30 IST, the screenshots), by the methods above (each re-proven on a frozen record).
A product that joins a desk already live never went through going live, where leverage is set (_set_mode_one): its
leverage is confirmed at LEVERAGE before its first entry (_confirm_leverage), and its signals wait until it is.

23 NOV 2026: EACH STRATEGY'S OWN SIZE AND SWITCH, AND A RANK. The owner asked, for both desks' strategies tables, for a
Rank column, a lot size per strategy (today's one contract the default, with increase and decrease) and an ON/OFF per
strategy (ON the default). Kept in the desk's state as pick_cfg["acct|mkt"] (set_pick; the last changes in pick_log):
- lots: the contracts a new trade of that strategy takes in the desk's contract sizing ("min"), 1 up to LOTS_MAX of its
  product (about $700-1,000 of notional; MAX_NOTIONAL_USD still caps every trade). A dollar risk picked for the desk
  sizes by risk instead and ignores lots. A trade already open keeps the size it was given.
- on / off: OFF takes no new real trade for that strategy (on a follow_all desk its open paper trades wait, so switching
  it back ON copies what is still open, as switching the desk on does; one that closes meanwhile is recorded as skipped);
  a real trade already open is still managed to its close, exactly like the desk's own switch.
Raising the lots or switching a strategy back ON needs the words REAL MONEY in the request (the page asks once), and
the PIN when the server requires one (PREMIUM_LIVE_REQUIRE_PIN=1), as going live does; lowering or switching OFF needs
neither, as switching the desk off never does.
RANK (_rank): the strategies in order of their expected net R a trade, best first, from all a strategy's evidence: its
own backtest (the prior: its R a trade, trusted by its number of trades plus RANK_DRIFT_SD of drift; an untested one
starts at its desk's typical backtest), its whole paper record (trades closed before its pick count RANK_PRE_W: a good
record is what got it picked, so they are partly luck), and how its real Delta copies did against their own paper
twins (the gap, pulled toward the desk's). Shown with how likely the edge is above zero. Read only: it trades nothing.

24 NOV 2026: THE OWNER'S FOURTH LIST. The owner sent the Premium Crypto and Gold tabs again (28 bitcoin and ether rows,
31 gold rows) and asked for those strategies on real money, skipping any already here, with the desks' configuration
unchanged (every signal copied; each new strategy one contract and ON, the pick_cfg default). New:
- bitcoin desk: NJ-43, TD-03, NJ-28, SC-02, NJ-37 and DD-04's BITCOIN book (BTCUSD; its ether book has been here
  since 22 Nov - a pick is (account, market), so one strategy may hold a book on each product), and the ether books
  of DD-03 and BX-01 on ETHUSD (BX-02's is a different strategy);
- gold desk: JR-05, BG-05 and JR-01.
Records at NEW_PICKED_AT_5 (00:30 IST 24 Nov), by the Premium method above (re-proven on five frozen records first).
Backtests: TD-03, JR-05 and JR-01 have their own 2-year books (results/backtest.json of youtube_channels20, gold
on its XAUUSD book as JR-03's); the channels-11 and shortlist strategies were never backtested.

24 NOV 2026 (EVENING): A THIRD BOOK, "PREMIUM GOLD STRATEGIES" (premium_gold). The owner asked for the Gold Desk H1
test's six best paper records (EMA Ribbon Compression, Pivot R1/S1 Break, Donchian Breakout fast and slow, Round
Number Break, Keltner Breakout; all 4-hour) to trade in a SEPARATE book beside the gold desk ("a separate second
book"), each strategy at its own size, set in lots or in dollars of gold per trade on its own tab. The gold desk
keeps its own copies of the same strategies at its own lots, so each of their signals opens two real positions.
- Same engine and rules as the gold desk (follow_all: every signal copied, the H1 position's own stop and target on
  Delta, the 7% stop cap, a copy waits rather than being given up); its own state and trades (live_pgold_*), its own
  switch (it starts OFF), its own lots per strategy (pick_cfg), its own records and page.
- Two desks on one product, for the first time. Delta nets an account's position per product, and every desk already
  checks the account against the sum of EVERY desk's trades (_expected_net), so the books reconcile; a trade never
  touches another's contracts (it closes only its own size and cancels only its own legs). Added for it:
  * order ids: both books copy the same H1 position (one paper id), so this book hashes it with its own cid_salt;
    the two original desks keep cid_salt "", their ids exactly as before;
  * a mismatch on a product where ANOTHER desk has a trade in flight (entering or closing) only makes entries wait
    and never counts toward switching this desk off (_in_flight_elsewhere): one book's lost order answer must not
    switch the other off. The bitcoin and gold desks share no product, so nothing changes for them.
- Going live reads each product's leverage first and sets it only when it is not already LEVERAGE (the gold desk may
  hold XAUTUSD positions when this book arms); the end state is the same for every desk.
- The page converts lots to money: status() carries each product's latest price (_prices: the freshest mark of any
  desk's open trade, else one public ticker read a minute) and USD/INR (gold_desk.usd_inr, Yahoo INR=X).
Records at NEW_PICKED_AT_6 (20:30 IST 24 Nov) by the H1 method above (re-proven on three frozen H1 records first).

25 NOV 2026: DELTA'S 100 OPEN ORDERS A PRODUCT. Delta refuses any new order on a product once the account holds 100
open orders there ("max_orders_count_exceeded", limit 100): every resting stop and target counts, and a market order
being placed is refused too. Each copy kept two orders on Delta, so the gold desk and the Premium Gold book together
filled XAUTUSD's 100 at about 50 trades, and on 25 Nov the refusals switched the gold desk off six times, 01:41
to 22:09 IST (three refused entries in a row, or a refused stop or target). The owner chose both of these that night:
- A refusal for that limit is not a venue error. The signal is skipped and recorded as "Delta's 100-order limit
  full", and the desk stays on. Until a trade on that product closes (or VENUE_FULL_RETRY_S passes), the product's
  new signals are skipped the same way without being sent (_FULL, shared by the desks). A copy whose stop is refused
  for it after the fill is closed at once, as ever (never unprotected), and the desk stays on. Any other refusal is
  handled as before.
- On APP_TARGET_PRODUCTS (XAUTUSD) a trade keeps only its stop on Delta. This server closes it at the market once the
  bid (a long) or the ask (a short) reaches its target (_app_target_hit, every pass, also while its paper source
  cannot be read), cancelling the stop first, so the close itself always fits under the limit. One order a trade
  instead of two: room for about 100 trades. Trades already open hand their target over: the resting target is
  cancelled (CONVERT_PER_PASS a pass a desk) and watched by this server from then on; one found filled, wholly or in
  part, closes as the venue target. A target cancelled on Delta by anyone else is handed over too, never put back.
  Bitcoin and ether keep both orders on Delta.

27 NOV 2026: THE OWNER'S FIFTH LIST, THE FACTORY BOARD'S TOP 209. The owner sent the Gold Desk's "Strategy Factory
· 546" board (ranks 34 to 209, scrolled through), its "Factory Top 1-25" table and the H1 records, and asked for them
on real money, trading as the others do ("if already present skip, add the remaining"). Asked which ranks (one
screenful, 97-113, and the board's top 33 were not in the screenshots), the owner chose ranks 1-209. 57 of the 209
were already picks (ranks have moved since 22 Nov; SF0487, a pick, is now below 209 and stays), and every H1
template shown was already here, so 152 Factory strategies join, in board order, each at one contract and ON (the
pick_cfg default). Records at NEW_PICKED_AT_7 (00:15 IST 27 Nov) by the Factory method above, re-proven first on
four frozen records (SF0181 and SF0243 of 19 Nov, SF0344 and SF0476 of 22 Nov); every one's trade count equals the
board's. 49 of the 152 held an open tab position at the pick: this follow_all desk copies them on its first pass.
With 254 strategies on one product, Delta's 100 open orders on XAUTUSD (shared with the Premium Gold book, one stop a
trade) is the binding limit: a signal past it is skipped as "Delta's 100-order limit full" (25 Nov), never queued.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import hmac
import logging
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from app.services import delta_rest as DR
from app.services.delta_rest import Delta, DeltaError, Product, fmt_tick

logger = logging.getLogger("premium_live")

IST = timezone(timedelta(hours=5, minutes=30))
RISK_USD = float(os.getenv("PREMIUM_LIVE_RISK_USD", "5"))              # the gold desk
DAILY_STOP_USD = float(os.getenv("PREMIUM_LIVE_DAILY_STOP_USD", "20"))
CRYPTO_RISK_USD = float(os.getenv("PREMIUM_CRYPTO_RISK_USD", "5"))       # the crypto desk (the owner's choice, 14 Nov)
CRYPTO_DAILY_STOP_USD = float(os.getenv("PREMIUM_CRYPTO_DAILY_STOP_USD", "20"))
MAX_NOTIONAL_USD = float(os.getenv("PREMIUM_LIVE_MAX_NOTIONAL_USD", "2500"))
LEVERAGE = int(os.getenv("PREMIUM_LIVE_LEVERAGE", "10"))
MAX_LAG_S = int(os.getenv("PREMIUM_LIVE_MAX_LAG_S", "300"))
CRYPTO_MAX_LAG_S = int(os.getenv("PREMIUM_CRYPTO_MAX_LAG_S", "600"))   # the bitcoin desk (the owner's choice, 15 Nov)
GOLD_MAX_LAG_S = int(os.getenv("PREMIUM_GOLD_MAX_LAG_S", "600"))       # the gold desk too, when it went live (15 Nov)
SIZING_DEFAULT = os.getenv("PREMIUM_LIVE_SIZING", "min")   # "min": one contract a trade, the owner's choice on 15 Nov
REQUIRE_PIN = os.getenv("PREMIUM_LIVE_REQUIRE_PIN", "0").strip() == "1"   # the owner chose no PIN on 15 Nov
RISK_MIN_USD = 1.0             # the lowest risk a trade the owner can pick on the page; the highest is the desk's own
PRIORITY_REFRESH_S = 600       # the books named to the paper desk (live_priority) are re-written at least this often
DRIFT_FRAC = float(os.getenv("PREMIUM_LIVE_DRIFT_FRAC", "0.30"))
TICK_S = int(os.getenv("PREMIUM_LIVE_TICK_S", "20"))
MISSING_GRACE_S = 300          # a paper trade gone this long is treated as closed
DESK_STALE_S = 1200            # the paper desk silent this long: no new entry
DESK_DEAD_S = 3600             # ... this long: open positions are closed (nothing can manage them)
# A desk that follows EVERY paper trade (the gold desk, the owner's ask on 19 Nov 2026; see FOLLOW EVERY PAPER TRADE)
FOLLOW_PAD_TICKS = 5           # it enters only with the price this many ticks inside the paper's stop and target ...
FOLLOW_PAD_FRAC = 0.10         # ... and this share of the paper's risk, so a market fill cannot land past a level
GUARD_STOP_FRAC = 0.03         # a paper trade with no stop at all (PR-12's ladder): its real copy's stop, 3% away
MAX_STOP_FRAC = 0.07           # a copy's stop is never farther than this from its price: at LEVERAGE 10x Delta liquidates
#                                a position about 9.5% against it, so a farther stop would never be reached (and the
#                                trade's own stop order, not reduce-only, could later open a position nobody holds)
MARGIN_BUFFER = 1.25           # free balance needed: margin x this
# Delta's 100 open orders a product (25 Nov 2026, see 25 NOV 2026 above)
APP_TARGET_PRODUCTS = frozenset(x.strip().upper() for x in os.getenv("PREMIUM_LIVE_APP_TARGET", "XAUTUSD").split(",")
                                if x.strip())   # their trades keep only the stop on Delta; this server takes the target
VENUE_FULL = "Delta's 100-order limit full"
APP_TARGET_WHY = "target reached, closed by the app"
VENUE_FULL_RETRY_S = 120       # after that refusal a product's new signals are skipped unsent until a trade on it
#                                closes, or this long has passed
CONVERT_PER_PASS = 10          # open trades whose resting target is handed to this server, at most this many a pass
TARGET_QUOTE_TTL_S = 5         # the target check's quote: one read a product per pass, shared by the desks
# Each strategy's own size (23 Nov 2026): the contracts a new trade takes in contract sizing, 1 (the default, the size
# every trade had before) up to its product's cap here - about $700-1,000 of notional at late-November prices.
LOTS_DEFAULT = 1
LOTS_MAX = {"BTCUSD": 10, "ETHUSD": 30, "XAUTUSD": 250}
PICK_LOG_N = 200               # the last changes to the strategies' sizes and switches kept in the desk's state
# The rank (23 Nov 2026, _rank): expected net R a trade from the backtest, the paper record and the real copies.
RANK_DRIFT_SD = 0.10           # how far (R a trade) a backtest's edge may drift before live trading, beyond its own noise
RANK_UNTESTED_SD = 0.20        # an untested strategy's prior spread around its desk's typical backtest
RANK_POOLED_SD = 0.15          # the H1 templates: only their pooled backtest is known
RANK_PRE_W = 0.25              # paper trades closed before the pick count this much: their record is why it was picked
RANK_SD_MIN, RANK_SD_MAX, RANK_SD_N = 0.7, 4.0, 8   # a record's own R spread once it has RANK_SD_N trades, kept in range
RANK_SD_DEFAULT = 1.3          # ... and before that, its desk's median (this when no record has enough trades)
RANK_R_CLIP = 10.0             # one trade counts at most this many R either way
RANK_GAP_K = 10.0              # real-vs-paper gap: a strategy's own pairs weigh against this many of the desk's
RANK_GAP_CLIP = 5.0
ERRORS_TO_STOP = 3
PIN_TRIES = 5                  # wrong PINs an hour before going live is locked for the hour
GST = 0.18                     # on Delta India's fees (shadow estimates only; live uses Delta's own figures)
PICKED_AT = "2026-11-13T23:00:00+05:30"        # the gold desk
CRYPTO_PICKED_AT = "2026-11-14T09:44:00+05:30"
NEW_PICKED_AT = "2026-11-18T22:00:00+05:30"   # the 18 Nov additions on both desks: their records are as of this time
NEW_PICKED_AT_2 = "2026-11-18T23:50:00+05:30"  # ... and the second batch the owner sent that night
PREMIUM, GOLD_H1 = "premium", "gold_h1"        # a pick's source: the Premium paper desk, or the Gold Desk's H1 test
H1_ID = "H1|"                                  # a Gold Desk H1 position, as a paper trade id: "H1|<position_id>"
GOLD_SF = "gold_sf"                            # ... or the Gold Desk's Strategy Factory tab (19 Nov)
SF_ID = "SF|"                                  # a Strategy Factory tab position, as a paper trade id: "SF|<position_id>"
NEW_PICKED_AT_3 = "2026-11-19T21:29:00+05:30"  # the Factory board's top 20 the owner sent: their records as of this time
NEW_PICKED_AT_4 = "2026-11-22T14:30:00+05:30"  # the owner's 22 Nov screenshots (both desks): their records as of this time
NEW_PICKED_AT_5 = "2026-11-24T00:30:00+05:30"  # the owner's 24 Nov screenshots (both desks): their records as of this time
NEW_PICKED_AT_6 = "2026-11-24T20:30:00+05:30"  # the Premium Gold book's six (24 Nov evening): their records as of this time
NEW_PICKED_AT_7 = "2026-11-27T00:15:00+05:30"  # the Factory board's top 209 (27 Nov): the 152 new ones' records as of this time
CONFIRM = "REAL MONEY"
D = Delta()


@dataclass(frozen=True)
class Pick:
    acct: str
    mkt: str            # the paper desk's market key
    product: str        # the Delta perpetual it trades
    name: str
    trades: int         # its paper record at the pick: closed trades since 8 Nov
    sum_r: float        # net R
    t: float            # t-stat of the net R a trade
    win: int            # % of trades won
    backtest: str       # what its own 2-year backtest said
    picked_at: str | None = None    # its own pick time, when it joined the desk after the others (its record's time)
    src: str = PREMIUM              # where its trades come from: PREMIUM (premium_trades), GOLD_H1 (the Gold Desk's H1
    #                                 test) or GOLD_SF (the Gold Desk's Strategy Factory tab)
    template: str | None = None     # GOLD_H1: the Gold Desk's strategy_template; GOLD_SF: the Factory's strategy_id


_H1_BACKTEST = ("pooled only: the nine H1 templates together earned +12.2 bp a trade net on Delta's 2026 data "
                "(1,045 trades), the data they were found in; no single template survives the luck correction")


def _h1(code: str, template: str, name: str, trades: int, sum_r: float, t: float, win: int,
        at: str = NEW_PICKED_AT) -> Pick:
    """A Gold Desk H1 template on the gold desk (18 Nov 2026). Record = its closed H1 positions at its pick time `at`,
    in R (realised P&L over |entry - stop| x quantity)."""
    return Pick(code, "XAUTUSD", "XAUTUSD", f"Gold Desk H1: {name}", trades, sum_r, t, win, _H1_BACKTEST,
                at, GOLD_H1, template)


_SF_BACKTEST = ("factory only: graded by the Strategy Factory's own backtest, whose replay reads future 4-hour bars; "
                "none of the 546 is validated, and its forward paper record on the Gold Desk picked it")


def _sf(sid: str, name: str, trades: int, sum_r: float, t: float, win: int, at: str = NEW_PICKED_AT_3) -> Pick:
    """A strategy of the Gold Desk's "Strategy Factory · 546" tab on the gold desk (19 Nov 2026). Record = its closed
    tab positions at its pick time `at`, in R (realised P&L over what its sleeve loses at its stop)."""
    return Pick(sid, "XAUTUSD", "XAUTUSD", f"Gold Desk Strategy Factory: {name}", trades, sum_r, t, win, _SF_BACKTEST,
                at, GOLD_SF, sid)


GOLD_PICKS: tuple[Pick, ...] = (
    Pick("RU-02", "XAUTUSD", "XAUTUSD", "Stochastic below 20, then a MACD cross, 1.5R (30-minute)", 5, 2.73, 1.47, 60,
         "loses: -0.06R a trade over 795 trades (t -1.6)"),
    Pick("CP-23", "XAUUSD", "XAUTUSD", "Inducement", 8, 5.29, 1.33, 62, "never backtested"),
    Pick("YT-14", "XAUUSD", "XAUTUSD", "MA fan + engulfing / three-line strike, RSI 50", 13, 5.19, 1.15, 62,
         "loses: -0.14R a trade over 2,317 trades"),
    Pick("DR-01", "XAUTUSD", "XAUTUSD", "EMA 200 side + counter-trend-line breakout, 1:2 (15-minute)", 15, 5.27, 0.88, 53,
         "loses: -0.26R a trade over 1,467 trades (t -7.3)"),
    Pick("CP-05", "XAUUSD", "XAUTUSD", "Turning-point zones (3 touches)", 8, 3.74, 0.86, 50, "never backtested"),
    # added by the owner on 15 Nov 2026 from the Gold tab's ranking; record = its gold paper trades at 13:40 IST
    Pick("CP-06", "XAUUSD", "XAUTUSD", "Triple top / triple bottom", 3, 1.44, 0.37, 67, "never backtested",
         "2026-11-15T13:40:00+05:30"),
    # added by the owner on 16 Nov 2026 from the Gold tab: TL-04's GOLD book (its bitcoin book stays on the crypto desk;
    # a pick is (account, market), so the two never meet). Record = its XAUTUSD paper trades at 23:33 IST.
    Pick("TL-04", "XAUTUSD", "XAUTUSD", "EMA 200 + RSI 50 + engulfing, stop two candles, 2R", 14, 3.13, 0.61, 43,
         "loses: -0.035R a trade over 1,304 trades (t -1.0)", "2026-11-16T23:33:00+05:30"),
    # added by the owner on 18 Nov 2026 from the Premium leaderboard's gold rows; records = their gold paper trades at
    # 22:00 IST (closed, by the same method as above). Backtests: each one's own 2-year gold book, where it has one.
    Pick("BB-11", "XAUUSD", "XAUTUSD", "Forex 10:00 IST range trap", 4, 4.79, 1.61, 75,
         "loses: -0.30R a trade over 582 trades (its no-void-rule variant R1, the one on paper)", NEW_PICKED_AT),
    Pick("PT-04", "XAUTUSD", "XAUTUSD", "4-hour inside-bar breakout in the trend, 2R", 4, 4.70, 1.60, 75,
         "loses: -0.19R a trade over 260 trades (t -2.3)", NEW_PICKED_AT),
    Pick("RU-03", "XAUTUSD", "XAUTUSD", "Opposite RSI: RSI through 70/30 with ADX 25 in the EMA 200 trend, 1.5R", 4, 3.99,
         3.80, 100, "earns: +0.044R a trade over 316 trades (t 0.8), not significant", NEW_PICKED_AT),
    Pick("SB-06", "XAUUSD", "XAUTUSD", "Gold liquidity sweep at a tested level, pause-candle or rejection trigger", 3, 4.57,
         1.14, 67, "never backtested", NEW_PICKED_AT),
    Pick("RU-04", "XAUTUSD", "XAUTUSD", "Williams fractal breakout in the 200 MA trend, 1.5R", 8, 2.96, 0.99, 62,
         "earns: +0.039R a trade over 832 trades (t 1.1), not significant", NEW_PICKED_AT),
    Pick("PR-12", "XAUTUSD", "XAUTUSD", "Gold: 4-hour Supertrend ladder with counter-scalps", 0, 0.0, 0.0, 0,
         "never backtested", NEW_PICKED_AT),
    Pick("TP-05", "XAUTUSD", "XAUTUSD", "9:30 displacement ORB without the session filter", 1, 1.93, 0.0, 100,
         "loses: -0.30R a trade over 265 trades (t -3.8)", NEW_PICKED_AT),
    Pick("DT-01", "XAUTUSD", "XAUTUSD", "MACD cross in the EMA 100 trend, swing stop, 1.5R (1-hour)", 3, 1.94, 0.77, 67,
         "earns: +0.12R a trade over 223 trades (t 1.4), not significant", NEW_PICKED_AT),
    Pick("DT-03", "XAUTUSD", "XAUTUSD", "Stochastic oversold, RSI 50, MACD cross, 1.5R (30-minute)", 6, 1.67, 0.53, 50,
         "loses: -0.023R a trade over 347 trades (t -0.4)", NEW_PICKED_AT),
    Pick("CD-02", "XAUTUSD", "XAUTUSD", "200 EMA side and slope, pullback touching the EMA, engulfing close, 2R (one minute, "
         "Asia session)", 6, 1.42, 0.36, 50, "never backtested", NEW_PICKED_AT),
    Pick("CP-02", "XAUUSD", "XAUTUSD", "Power-candle breakout of the last swing", 10, 1.84, 0.38, 40, "never backtested",
         NEW_PICKED_AT),
    Pick("RU-05", "XAUTUSD", "XAUTUSD", "RSI through 70 (30) with Supertrend agreeing, Supertrend stop, 1.5R", 1, 1.48, 0.0,
         100, "never backtested", NEW_PICKED_AT),
    Pick("FZ-02", "XAUTUSD", "XAUTUSD", "Gold London first FVG inversion (15-minute)", 3, 1.20, 0.56, 33,
         "loses: -0.18R a trade over 179 trades (t -2.0)", NEW_PICKED_AT),
    # the owner's second batch that night (23:50 IST): four more gold books. JR-04's t (2 trades of almost the same R)
    # is what the method gives and means nothing; the page shows no t under five trades.
    Pick("BG-01", "XAUUSD", "XAUTUSD", "Gold: 1-hour structure, 15-minute sweep at the point of interest", 7, 3.23, 0.79,
         57, "never backtested", NEW_PICKED_AT_2),
    Pick("JR-04", "XAUTUSD", "XAUTUSD", "9:30-9:35 range, retest close outside, stop at the midpoint, 2R", 2, 3.74, 1193.17,
         100, "loses: -0.13R a trade over 343 trades (t -1.8)", NEW_PICKED_AT_2),
    Pick("TD-04", "XAUTUSD", "XAUTUSD", "UT Bot + linear-regression candles trend ride (1-hour)", 7, 1.09, 0.56, 43,
         "loses: -0.014R a trade over 620 trades (t -0.6)", NEW_PICKED_AT_2),
    Pick("TC-11", "XAUTUSD", "XAUTUSD", "RSI (14) divergence at a lower low (higher high), a close beyond the high (low) "
         "between the swings, 2R", 0, 0.0, 0.0, 0, "never backtested", NEW_PICKED_AT_2),
    # and six templates of the Gold Desk's H1 forward test (its "Strategy records" table), read from the Gold Desk
    _h1("H1-RIB", "ema_ribbon", "EMA Ribbon Compression · 4h", 12, 5.57, 1.00, 50),
    _h1("H1-RND", "round_number_break", "Round Number Break · 4h", 20, 3.06, 0.45, 40),
    _h1("H1-DCF", "donchian_fast", "Donchian Breakout (fast) · 4h", 16, 5.02, 0.82, 44),
    _h1("H1-PIV", "pivot_break", "Pivot R1/S1 Break · 4h", 20, 4.08, 0.58, 40),
    _h1("H1-DCS", "donchian_slow", "Donchian Breakout (slow) · 4h", 5, 1.30, 0.34, 40),
    _h1("H1-KLT", "keltner_break", "Keltner Breakout · 4h", 14, 0.95, 0.17, 36),
    # the owner's 19 Nov pick: the Gold Desk "Strategy Factory · 546" board's Rank 1-20 at 21:29 IST, read from the tab's
    # own positions (factory_desk_positions, desk gold); the records match the board (trades, % won, net P&L)
    _sf("SF0181", "Three Soldiers / Crows · 45m", 42, 25.64, 1.94, 48),
    _sf("SF0020", "Triple Top / Bottom · 30m", 43, 21.51, 1.58, 42),
    _sf("SF0245", "Prior Session High/Low Break · 45m", 29, 23.06, 2.27, 52),
    _sf("SF0013", "Double Top / Bottom · 45m", 40, 21.41, 1.83, 45),
    _sf("SF0182", "Three Soldiers / Crows · 1h", 33, 11.51, 1.17, 42),
    _sf("SF0331", "Trend Pullback to EMA · 45m", 31, 21.96, 1.89, 42),
    _sf("SF0346", "Rectangle / Trading Range Break · 30m", 23, 7.03, 1.89, 65),
    _sf("SF0213", "Donchian Breakout (fast) · 45m", 25, 16.45, 1.73, 48),
    _sf("SF0324", "Opening Range Breakout · 45m", 47, 8.90, 0.76, 45),
    _sf("SF0022", "Triple Top / Bottom · 1h", 28, 9.58, 0.96, 39),
    _sf("SF0219", "Donchian Breakout (slow) · 15m", 41, 14.37, 1.12, 39),
    _sf("SF0497", "S/R Flip Retest + Volume · 30m", 29, 8.52, 0.74, 38),
    _sf("SF0021", "Triple Top / Bottom · 45m", 28, 19.12, 1.82, 46),
    _sf("SF0251", "Round Number Break · 30m", 20, 13.32, 1.74, 60),
    _sf("SF0370", "RSI Trend Regime (40/60) · 30m", 19, 18.89, 2.58, 63),
    _sf("SF0542", "Rectangle + Volume + ATR · 30m", 19, 7.71, 2.65, 68),
    _sf("SF0205", "Heikin Ashi Flip · 45m", 32, 7.40, 0.78, 41),
    _sf("SF0228", "Keltner Breakout · 30m", 33, 5.95, 0.59, 36),
    _sf("SF0426", "Parabolic SAR Flip · 30m", 24, 14.14, 1.77, 54),
    _sf("SF0243", "Prior Session High/Low Break · 15m", 78, 17.38, 1.14, 41),
    # the owner's 22 Nov screenshots (records at NEW_PICKED_AT_4, 14:30 IST): ten more gold books from the Premium Gold
    # tab (backtests: each one's own 2-year gold book where it has one; YT-18's is its hold-out, as YT-14's) ...
    Pick("CP-21", "XAUUSD", "XAUTUSD", "Breaker block", 15, 1.68, 0.30, 40, "never backtested", NEW_PICKED_AT_4),
    Pick("YT-18", "XAUUSD", "XAUTUSD", "Heikin-Ashi colour change + RSI 50", 16, 6.37, 0.79, 50,
         "loses: -0.14R a trade over 1,960 hold-out trades (t -3.5)", NEW_PICKED_AT_4),
    Pick("TF-01", "XAUTUSD", "XAUTUSD", "Fibonacci confluence continuation, -0.272 target (15-minute)", 29, 4.39, 0.41, 34,
         "loses: -0.21R a trade over 1,374 trades (t -4.7)", NEW_PICKED_AT_4),
    Pick("CP-01", "XAUUSD", "XAUTUSD", "Trend pullback at the 5th point", 16, 3.30, 0.60, 38, "never backtested",
         NEW_PICKED_AT_4),
    Pick("FL-02", "XAUTUSD", "XAUTUSD", "Williams Alligator: the 5-minute candle clear of all three lines and engulfing, "
         "with the 1-hour EMA 50, 1R", 11, 4.12, 1.33, 73, "never backtested", NEW_PICKED_AT_4),
    Pick("MH-01", "XAUTUSD", "XAUTUSD", "Gold 8 PM New York hourly candle: reversal or continuation", 6, 2.37, 0.57, 50,
         "earns: +0.087R a trade over 451 trades (t 1.3), not significant", NEW_PICKED_AT_4),
    Pick("DT-02", "XAUTUSD", "XAUTUSD", "MACD + Parabolic SAR + EMA 200, stop at the dot, 1:1 (30-minute)", 12, 2.20, 0.58,
         58, "earns: +0.015R a trade over 680 trades (t 0.4), not significant", NEW_PICKED_AT_4),
    Pick("BG-08", "XAUUSD", "XAUTUSD", "Candle range theory on 15 minutes", 110, 13.01, 0.47, 31, "never backtested",
         NEW_PICKED_AT_4),
    Pick("RU-06", "XAUTUSD", "XAUTUSD", "Zero-lag MACD cross below/above zero in the 200 EMA trend, pullback stop, 1.5R", 10,
         1.00, 0.27, 50, "never backtested", NEW_PICKED_AT_4),
    Pick("JR-03", "XAUTUSD", "XAUTUSD", "9:30-9:35 range, 1-minute FVG break, market entry, 2R", 8, 2.24, 0.49, 50,
         "loses: -0.13R a trade over 499 trades (t -2.1)", NEW_PICKED_AT_4),
    # ... the H1 test's Prior Session High/Low Break (its ranks 7 and 8, both losing, were not in the screenshots) ...
    _h1("H1-PSB", "prior_session_break", "Prior Session High/Low Break · 4h", 26, 0.68, 0.09, 35, NEW_PICKED_AT_4),
    # ... and the Factory board's top 56 not already here (38; the 18 others of the 56 are above), in board order
    _sf("SF0345", "Rectangle / Trading Range Break · 15m", 49, 10.45, 1.64, 65, NEW_PICKED_AT_4),
    _sf("SF0298", "Break of Structure · 15m", 28, 14.43, 1.53, 50, NEW_PICKED_AT_4),
    _sf("SF0541", "Rectangle + Volume + ATR · 15m", 38, 7.65, 1.35, 66, NEW_PICKED_AT_4),
    _sf("SF0315", "Support / Resistance Flip · 30m", 30, 9.10, 0.84, 40, NEW_PICKED_AT_4),
    _sf("SF0347", "Rectangle / Trading Range Break · 45m", 19, 8.27, 2.50, 79, NEW_PICKED_AT_4),
    _sf("SF0337", "Previous Week High/Low Break · 15m", 20, 10.66, 1.89, 65, NEW_PICKED_AT_4),
    _sf("SF0220", "Donchian Breakout (slow) · 30m", 25, 20.53, 1.78, 44, NEW_PICKED_AT_4),
    _sf("SF0466", "Breakout + Volume + HTF Trend · 30m", 28, 13.73, 1.24, 39, NEW_PICKED_AT_4),
    _sf("SF0221", "Donchian Breakout (slow) · 45m", 20, 15.46, 1.61, 45, NEW_PICKED_AT_4),
    _sf("SF0332", "Trend Pullback to EMA · 1h", 21, 19.29, 2.05, 48, NEW_PICKED_AT_4),
    _sf("SF0244", "Prior Session High/Low Break · 30m", 47, 21.84, 1.61, 43, NEW_PICKED_AT_4),
    _sf("SF0325", "Opening Range Breakout · 1h", 38, 9.67, 1.06, 45, NEW_PICKED_AT_4),
    _sf("SF0449", "CCI Breakout · 15m", 43, 2.49, 0.27, 42, NEW_PICKED_AT_4),
    _sf("SF0488", "Structure Break + Volume + HTF · 15m", 20, 12.98, 1.47, 50, NEW_PICKED_AT_4),
    _sf("SF0465", "Breakout + Volume + HTF Trend · 15m", 59, 13.34, 0.90, 36, NEW_PICKED_AT_4),
    _sf("SF0230", "Keltner Breakout · 1h", 24, 6.53, 0.82, 42, NEW_PICKED_AT_4),
    _sf("SF0467", "Breakout + Volume + HTF Trend · 45m", 16, 16.74, 2.01, 56, NEW_PICKED_AT_4),
    _sf("SF0474", "Pullback + EMA + RSI + VWAP · 30m", 51, 18.29, 1.38, 41, NEW_PICKED_AT_4),
    _sf("SF0246", "Prior Session High/Low Break · 1h", 28, 13.22, 1.39, 46, NEW_PICKED_AT_4),
    _sf("SF0498", "S/R Flip Retest + Volume · 45m", 20, 14.65, 1.52, 45, NEW_PICKED_AT_4),
    _sf("SF0476", "Pullback + EMA + RSI + VWAP · 1h", 20, 15.65, 1.74, 45, NEW_PICKED_AT_4),
    _sf("SF0314", "Support / Resistance Flip · 15m", 72, 22.72, 1.38, 40, NEW_PICKED_AT_4),
    _sf("SF0402", "MACD Histogram Turn · 30m", 33, 9.83, 1.15, 48, NEW_PICKED_AT_4),
    _sf("SF0487", "Structure Break + Volume + HTF · 5m", 51, 4.47, 0.36, 33, NEW_PICKED_AT_4),
    _sf("SF0229", "Keltner Breakout · 45m", 26, 10.09, 1.12, 42, NEW_PICKED_AT_4),
    _sf("SF0090", "Diamond · 5m", 42, 2.50, 0.16, 38, NEW_PICKED_AT_4),
    _sf("SF0316", "Support / Resistance Flip · 45m", 22, 14.85, 1.65, 45, NEW_PICKED_AT_4),
    _sf("SF0212", "Donchian Breakout (fast) · 30m", 52, 9.00, 0.67, 35, NEW_PICKED_AT_4),
    _sf("SF0014", "Double Top / Bottom · 1h", 32, 9.25, 0.99, 44, NEW_PICKED_AT_4),
    _sf("SF0543", "Rectangle + Volume + ATR · 45m", 15, 6.51, 2.07, 80, NEW_PICKED_AT_4),
    _sf("SF0004", "Head & Shoulders · 30m", 13, 12.88, 1.71, 54, NEW_PICKED_AT_4),
    _sf("SF0222", "Donchian Breakout (slow) · 1h", 12, 12.67, 1.60, 50, NEW_PICKED_AT_4),
    _sf("SF0344", "Rectangle / Trading Range Break · 5m", 154, -4.11, -0.37, 56, NEW_PICKED_AT_4),
    _sf("SF0451", "CCI Breakout · 45m", 15, 9.29, 1.38, 53, NEW_PICKED_AT_4),
    _sf("SF0119", "Hammer / Shooting Star · 4h", 10, 10.04, 2.14, 70, NEW_PICKED_AT_4),
    _sf("SF0395", "MACD Signal Cross · 45m", 13, 8.86, 1.48, 54, NEW_PICKED_AT_4),
    _sf("SF0268", "TTM Squeeze · 45m", 10, 18.45, 3.31, 80, NEW_PICKED_AT_4),
    _sf("SF0475", "Pullback + EMA + RSI + VWAP · 45m", 35, 16.57, 1.38, 37, NEW_PICKED_AT_4),
    # the owner's 24 Nov screenshots of the Gold tab (records at NEW_PICKED_AT_5, 00:30 IST): three more gold books; the
    # screenshots' other 28 were already here. Backtests: each one's own 2-year gold book (XAUUSD) where it has one.
    Pick("JR-05", "XAUTUSD", "XAUTUSD", "9:30-9:35 range, 1-minute FVG pullback + engulfing, 3R", 8, 1.98, 0.33, 38,
         "loses: -0.30R a trade over 197 trades (t -2.7)", NEW_PICKED_AT_5),
    Pick("BG-05", "XAUUSD", "XAUTUSD", "Gold supply/demand zone with an EMA 8 cross and an engulfing", 1, 0.79, 0.0, 100,
         "never backtested", NEW_PICKED_AT_5),
    Pick("JR-01", "XAUTUSD", "XAUTUSD", "First Candle Rule: 9:30-9:45 range, FVG limit, candle-1 stop, 2R", 5, 0.44, 0.12,
         40, "loses: -0.15R a trade over 341 trades (t -2.2)", NEW_PICKED_AT_5),
    # the owner's 27 Nov pick: the Gold Desk Factory board's ranks 1-209 not already above (152; records at
    # NEW_PICKED_AT_7, 00:15 IST), in board order from rank 13 (SF0520) to rank 209 (SF0234)
    _sf("SF0520", "VWAP Reclaim + Volume + HTF Â· 30m", 36, 16.41, 1.58, 44, NEW_PICKED_AT_7),
    _sf("SF0352", "EMA Crossover (fast) Â· 5m", 79, 1.42, 0.11, 44, NEW_PICKED_AT_7),
    _sf("SF0450", "CCI Breakout Â· 30m", 24, 11.89, 1.58, 50, NEW_PICKED_AT_7),
    _sf("SF0418", "Supertrend Flip Â· 30m", 17, 11.24, 1.61, 53, NEW_PICKED_AT_7),
    _sf("SF0371", "RSI Trend Regime (40/60) Â· 45m", 20, 12.25, 1.41, 45, NEW_PICKED_AT_7),
    _sf("SF0427", "Parabolic SAR Flip Â· 45m", 24, 6.11, 0.75, 42, NEW_PICKED_AT_7),
    _sf("SF0283", "ATR Expansion Thrust Â· 30m", 39, 9.19, 0.90, 44, NEW_PICKED_AT_7),
    _sf("SF0276", "EMA Ribbon Compression Â· 45m", 29, 9.30, 0.92, 38, NEW_PICKED_AT_7),
    _sf("SF0111", "Engulfing Candle Â· 4h", 12, 9.11, 1.95, 67, NEW_PICKED_AT_7),
    _sf("SF0207", "Heikin Ashi Flip Â· 4h", 12, 12.25, 1.92, 58, NEW_PICKED_AT_7),
    _sf("SF0227", "Keltner Breakout Â· 15m", 98, 13.90, 0.69, 36, NEW_PICKED_AT_7),
    _sf("SF0284", "ATR Expansion Thrust Â· 45m", 20, 3.53, 0.41, 45, NEW_PICKED_AT_7),
    _sf("SF0452", "CCI Breakout Â· 1h", 12, 5.19, 0.88, 50, NEW_PICKED_AT_7),
    _sf("SF0393", "MACD Signal Cross Â· 15m", 48, 8.41, 0.80, 46, NEW_PICKED_AT_7),
    _sf("SF0330", "Trend Pullback to EMA Â· 30m", 64, 19.75, 1.31, 38, NEW_PICKED_AT_7),
    _sf("SF0468", "Breakout + Volume + HTF Trend Â· 1h", 15, 8.36, 1.16, 47, NEW_PICKED_AT_7),
    _sf("SF0292", "HH/HL Structure Shift Â· 45m", 16, 7.48, 0.92, 38, NEW_PICKED_AT_7),
    _sf("SF0419", "Supertrend Flip Â· 45m", 11, 9.55, 1.41, 55, NEW_PICKED_AT_7),
    _sf("SF0266", "TTM Squeeze Â· 15m", 37, 5.29, 0.44, 35, NEW_PICKED_AT_7),
    _sf("SF0354", "EMA Crossover (fast) Â· 30m", 11, 8.97, 1.69, 55, NEW_PICKED_AT_7),
    _sf("SF0429", "Parabolic SAR Flip Â· 4h", 9, 11.60, 2.23, 67, NEW_PICKED_AT_7),
    _sf("SF0285", "ATR Expansion Thrust Â· 1h", 29, 2.85, 0.33, 38, NEW_PICKED_AT_7),
    _sf("SF0428", "Parabolic SAR Flip Â· 1h", 20, 5.05, 0.68, 40, NEW_PICKED_AT_7),
    _sf("SF0522", "VWAP Reclaim + Volume + HTF Â· 1h", 19, 3.83, 0.55, 42, NEW_PICKED_AT_7),
    _sf("SF0435", "Stochastic Cross Â· 45m", 21, 1.26, 0.21, 48, NEW_PICKED_AT_7),
    _sf("SF0417", "Supertrend Flip Â· 15m", 30, 1.64, 0.19, 40, NEW_PICKED_AT_7),
    _sf("SF0534", "Fib 61.8% + RSI + HTF Trend Â· 30m", 11, 4.25, 0.74, 64, NEW_PICKED_AT_7),
    _sf("SF0307", "Change of Character Â· 30m", 11, 7.15, 1.14, 45, NEW_PICKED_AT_7),
    _sf("SF0301", "Break of Structure Â· 1h", 13, 12.36, 1.78, 62, NEW_PICKED_AT_7),
    _sf("SF0361", "Golden / Death Cross Â· 15m", 15, 4.20, 0.61, 47, NEW_PICKED_AT_7),
    _sf("SF0188", "Morning / Evening Star Â· 30m", 34, 1.13, 0.12, 35, NEW_PICKED_AT_7),
    _sf("SF0293", "HH/HL Structure Shift Â· 1h", 7, 17.06, 4.02, 86, NEW_PICKED_AT_7),
    _sf("SF0308", "Change of Character Â· 45m", 8, 6.96, 1.39, 62, NEW_PICKED_AT_7),
    _sf("SF0005", "Head & Shoulders Â· 45m", 8, 11.94, 1.97, 62, NEW_PICKED_AT_7),
    _sf("SF0269", "TTM Squeeze Â· 1h", 8, 7.74, 1.22, 50, NEW_PICKED_AT_7),
    _sf("SF0300", "Break of Structure Â· 45m", 12, 5.63, 0.91, 50, NEW_PICKED_AT_7),
    _sf("SF0267", "TTM Squeeze Â· 30m", 19, 4.89, 0.56, 32, NEW_PICKED_AT_7),
    _sf("SF0002", "Head & Shoulders Â· 5m", 145, -40.78, -1.73, 29, NEW_PICKED_AT_7),
    _sf("SF0006", "Head & Shoulders Â· 1h", 8, 5.83, 1.06, 50, NEW_PICKED_AT_7),
    _sf("SF0257", "Bollinger Squeeze Release Â· 5m", 82, -25.36, -1.59, 33, NEW_PICKED_AT_7),
    _sf("SF0261", "Bollinger Squeeze Release Â· 1h", 6, 13.29, 3.38, 83, NEW_PICKED_AT_7),
    _sf("SF0496", "S/R Flip Retest + Volume Â· 15m", 86, 3.98, 0.22, 31, NEW_PICKED_AT_7),
    _sf("SF0206", "Heikin Ashi Flip Â· 1h", 43, 7.16, 0.66, 35, NEW_PICKED_AT_7),
    _sf("SF0490", "Structure Break + Volume + HTF Â· 45m", 7, 9.32, 1.83, 71, NEW_PICKED_AT_7),
    _sf("SF0376", "RSI Overbought / Oversold Reversal Â· 5m", 64, -74.89, -2.52, 39, NEW_PICKED_AT_7),
    _sf("SF0150", "Marubozu Continuation Â· 1h", 12, 3.49, 0.52, 42, NEW_PICKED_AT_7),
    _sf("SF0260", "Bollinger Squeeze Release Â· 45m", 6, 11.00, 1.94, 67, NEW_PICKED_AT_7),
    _sf("SF0388", "RSI Divergence Â· 1h", 7, 1.09, 0.19, 43, NEW_PICKED_AT_7),
    _sf("SF0108", "Engulfing Candle Â· 30m", 83, 9.68, 0.73, 42, NEW_PICKED_AT_7),
    _sf("SF0183", "Three Soldiers / Crows Â· 4h", 16, 6.84, 1.00, 44, NEW_PICKED_AT_7),
    _sf("SF0282", "ATR Expansion Thrust Â· 15m", 64, -7.77, -0.62, 39, NEW_PICKED_AT_7),
    _sf("SF0038", "Descending Triangle Â· 1h", 6, 7.93, 1.75, 67, NEW_PICKED_AT_7),
    _sf("SF0259", "Bollinger Squeeze Release Â· 30m", 16, 0.99, 0.13, 31, NEW_PICKED_AT_7),
    _sf("SF0483", "Squeeze + Momentum + Volume Â· 1h", 5, 12.55, 2.81, 80, NEW_PICKED_AT_7),
    _sf("SF0355", "EMA Crossover (fast) Â· 45m", 9, 3.23, 0.69, 56, NEW_PICKED_AT_7),
    _sf("SF0508", "Engulfing + VWAP + Volume Â· 4h", 10, 2.68, 0.50, 40, NEW_PICKED_AT_7),
    _sf("SF0442", "Williams %R Reversal Â· 30m", 14, 1.38, 0.27, 50, NEW_PICKED_AT_7),
    _sf("SF0491", "Structure Break + Volume + HTF Â· 1h", 7, 8.04, 1.47, 57, NEW_PICKED_AT_7),
    _sf("SF0444", "Williams %R Reversal Â· 1h", 5, 6.28, 9.34, 100, NEW_PICKED_AT_7),
    _sf("SF0278", "EMA Ribbon Compression Â· 4h", 5, 6.43, 1.32, 60, NEW_PICKED_AT_7),
    _sf("SF0481", "Squeeze + Momentum + Volume Â· 30m", 10, 1.92, 0.28, 30, NEW_PICKED_AT_7),
    _sf("SF0309", "Change of Character Â· 1h", 4, 4.93, 1.54, 75, NEW_PICKED_AT_7),
    _sf("SF0231", "Keltner Breakout Â· 4h", 12, 7.12, 1.22, 50, NEW_PICKED_AT_7),
    _sf("SF0482", "Squeeze + Momentum + Volume Â· 45m", 5, 9.51, 1.52, 60, NEW_PICKED_AT_7),
    _sf("SF0179", "Three Soldiers / Crows Â· 15m", 165, -14.72, -0.71, 35, NEW_PICKED_AT_7),
    _sf("SF0512", "Pin Bar + Trend + ADX Â· 30m", 5, 5.40, 1.10, 60, NEW_PICKED_AT_7),
    _sf("SF0214", "Donchian Breakout (fast) Â· 1h", 28, 2.71, 0.30, 36, NEW_PICKED_AT_7),
    _sf("SF0189", "Morning / Evening Star Â· 45m", 22, 2.05, 0.27, 36, NEW_PICKED_AT_7),
    _sf("SF0211", "Donchian Breakout (fast) Â· 15m", 121, 0.53, 0.03, 35, NEW_PICKED_AT_7),
    _sf("SF0489", "Structure Break + Volume + HTF Â· 30m", 9, 2.80, 0.54, 44, NEW_PICKED_AT_7),
    _sf("SF0523", "VWAP Reclaim + Volume + HTF Â· 4h", 9, 4.75, 0.88, 44, NEW_PICKED_AT_7),
    _sf("SF0299", "Break of Structure Â· 30m", 16, 3.67, 0.56, 38, NEW_PICKED_AT_7),
    _sf("SF0124", "Inverted Hammer Â· 30m", 7, 3.19, 0.59, 57, NEW_PICKED_AT_7),
    _sf("SF0363", "Golden / Death Cross Â· 45m", 4, 4.01, 1.16, 75, NEW_PICKED_AT_7),
    _sf("SF0037", "Descending Triangle Â· 45m", 3, 6.94, 31.30, 100, NEW_PICKED_AT_7),
    _sf("SF0410", "ADX / DI Cross Â· 30m", 17, 3.22, 0.47, 41, NEW_PICKED_AT_7),
    _sf("SF0453", "CCI Breakout Â· 4h", 3, 6.99, 9.87, 100, NEW_PICKED_AT_7),
    _sf("SF0420", "Supertrend Flip Â· 1h", 6, 2.47, 0.62, 50, NEW_PICKED_AT_7),
    _sf("SF0372", "RSI Trend Regime (40/60) Â· 1h", 11, 6.57, 1.03, 45, NEW_PICKED_AT_7),
    _sf("SF0473", "Pullback + EMA + RSI + VWAP Â· 15m", 121, -6.32, -0.30, 31, NEW_PICKED_AT_7),
    _sf("SF0500", "S/R Flip Retest + Volume Â· 4h", 6, 6.40, 1.14, 50, NEW_PICKED_AT_7),
    _sf("SF0396", "MACD Signal Cross Â· 1h", 13, 3.40, 0.56, 38, NEW_PICKED_AT_7),
    _sf("SF0076", "Cup & Handle Â· 30m", 4, 5.23, 0.95, 50, NEW_PICKED_AT_7),
    _sf("SF0091", "Diamond Â· 15m", 4, 2.54, 0.87, 75, NEW_PICKED_AT_7),
    _sf("SF0012", "Double Top / Bottom Â· 30m", 79, 2.69, 0.18, 33, NEW_PICKED_AT_7),
    _sf("SF0323", "Opening Range Breakout Â· 30m", 98, 6.26, 0.41, 40, NEW_PICKED_AT_7),
    _sf("SF0158", "Inside Bar Breakout Â· 1h", 13, 0.08, 0.01, 31, NEW_PICKED_AT_7),
    _sf("SF0397", "MACD Signal Cross Â· 4h", 3, 4.07, 1.14, 67, NEW_PICKED_AT_7),
    _sf("SF0156", "Inside Bar Breakout Â· 30m", 14, 2.14, 0.31, 36, NEW_PICKED_AT_7),
    _sf("SF0019", "Triple Top / Bottom Â· 15m", 115, -4.90, -0.26, 31, NEW_PICKED_AT_7),
    _sf("SF0036", "Descending Triangle Â· 30m", 2, 4.52, 19.66, 100, NEW_PICKED_AT_7),
    _sf("SF0254", "Round Number Break Â· 4h", 5, 3.34, 0.96, 60, NEW_PICKED_AT_7),
    _sf("SF0535", "Fib 61.8% + RSI + HTF Trend Â· 45m", 6, 0.86, 0.24, 50, NEW_PICKED_AT_7),
    _sf("SF0215", "Donchian Breakout (fast) Â· 4h", 10, 5.73, 1.06, 50, NEW_PICKED_AT_7),
    _sf("SF0338", "Previous Week High/Low Break Â· 30m", 12, 0.20, 0.06, 50, NEW_PICKED_AT_7),
    _sf("SF0015", "Double Top / Bottom Â· 4h", 12, 4.71, 0.78, 42, NEW_PICKED_AT_7),
    _sf("SF0190", "Morning / Evening Star Â· 1h", 20, 1.87, 0.23, 30, NEW_PICKED_AT_7),
    _sf("SF0394", "MACD Signal Cross Â· 30m", 22, 9.64, 1.22, 41, NEW_PICKED_AT_7),
    _sf("SF0163", "Multi Inside Bar Compression Â· 15m", 8, -0.43, -0.08, 25, NEW_PICKED_AT_7),
    _sf("SF0364", "Golden / Death Cross Â· 1h", 2, 1.79, 1.25, 100, NEW_PICKED_AT_7),
    _sf("SF0545", "Rectangle + Volume + ATR Â· 4h", 3, 1.10, 0.55, 67, NEW_PICKED_AT_7),
    _sf("SF0362", "Golden / Death Cross Â· 30m", 7, 5.48, 0.94, 43, NEW_PICKED_AT_7),
    _sf("SF0149", "Marubozu Continuation Â· 45m", 13, 0.38, 0.06, 38, NEW_PICKED_AT_7),
    _sf("SF0389", "RSI Divergence Â· 4h", 2, 1.18, 0.33, 50, NEW_PICKED_AT_7),
    _sf("SF0180", "Three Soldiers / Crows Â· 30m", 77, 3.64, 0.24, 34, NEW_PICKED_AT_7),
    _sf("SF0506", "Engulfing + VWAP + Volume Â· 45m", 24, 6.98, 0.81, 42, NEW_PICKED_AT_7),
    _sf("SF0318", "Support / Resistance Flip Â· 4h", 7, 4.68, 0.84, 43, NEW_PICKED_AT_7),
    _sf("SF0175", "Outside Bar Reversal Â· 4h", 9, -0.79, -0.18, 33, NEW_PICKED_AT_7),
    _sf("SF0291", "HH/HL Structure Shift Â· 30m", 14, -0.41, -0.06, 29, NEW_PICKED_AT_7),
    _sf("SF0413", "ADX / DI Cross Â· 4h", 4, 5.20, 1.42, 75, NEW_PICKED_AT_7),
    _sf("SF0411", "ADX / DI Cross Â· 45m", 12, 1.98, 0.34, 42, NEW_PICKED_AT_7),
    _sf("SF0191", "Morning / Evening Star Â· 4h", 4, 2.80, 0.71, 50, NEW_PICKED_AT_7),
    _sf("SF0159", "Inside Bar Breakout Â· 4h", 7, 0.75, 0.14, 29, NEW_PICKED_AT_7),
    _sf("SF0262", "Bollinger Squeeze Release Â· 4h", 2, 2.01, 0.48, 50, NEW_PICKED_AT_7),
    _sf("SF0092", "Diamond Â· 30m", 2, 1.87, 0.47, 50, NEW_PICKED_AT_7),
    _sf("SF0381", "RSI Overbought / Oversold Reversal Â· 4h", 2, -0.16, -0.07, 50, NEW_PICKED_AT_7),
    _sf("SF0421", "Supertrend Flip Â· 4h", 2, 1.73, 0.48, 50, NEW_PICKED_AT_7),
    _sf("SF0055", "Rising / Falling Wedge Â· 4h", 2, 2.09, 0.51, 50, NEW_PICKED_AT_7),
    _sf("SF0165", "Multi Inside Bar Compression Â· 45m", 4, 3.85, 0.84, 50, NEW_PICKED_AT_7),
    _sf("SF0216", "Donchian Breakout (fast) Â· 1d", 1, 2.98, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0016", "Double Top / Bottom Â· 1d", 1, 2.98, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0232", "Keltner Breakout Â· 1d", 1, 2.98, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0167", "Multi Inside Bar Compression Â· 4h", 1, 3.11, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0492", "Structure Break + Volume + HTF Â· 4h", 1, 1.32, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0302", "Break of Structure Â· 4h", 1, 1.32, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0349", "Rectangle / Trading Range Break Â· 4h", 4, 0.41, 0.16, 50, NEW_PICKED_AT_7),
    _sf("SF0116", "Hammer / Shooting Star Â· 30m", 79, 7.83, 0.54, 39, NEW_PICKED_AT_7),
    _sf("SF0501", "S/R Flip Retest + Volume Â· 1d", 1, 2.12, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0319", "Support / Resistance Flip Â· 1d", 1, 1.86, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0192", "Morning / Evening Star Â· 1d", 1, 1.61, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0120", "Hammer / Shooting Star Â· 1d", 1, 1.13, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0461", "Flag + Volume + HTF Trend Â· 4h", 1, 2.88, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0078", "Cup & Handle Â· 1h", 1, 4.49, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0077", "Cup & Handle Â· 45m", 1, 4.05, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0039", "Descending Triangle Â· 4h", 1, 2.31, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0063", "Bull / Bear Flag Â· 4h", 1, 1.91, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0199", "Pin Bar at Extreme Â· 4h", 1, 2.35, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0151", "Marubozu Continuation Â· 4h", 1, 2.06, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0537", "Fib 61.8% + RSI + HTF Trend Â· 4h", 1, 2.37, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0457", "Flag + Volume + HTF Trend Â· 15m", 1, 3.82, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0110", "Engulfing Candle Â· 1h", 42, 3.94, 0.40, 38, NEW_PICKED_AT_7),
    _sf("SF0059", "Bull / Bear Flag Â· 15m", 1, 2.58, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0067", "Pennant Â· 15m", 1, 2.58, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0093", "Diamond Â· 45m", 1, 2.37, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0164", "Multi Inside Bar Compression Â· 30m", 6, 1.54, 0.30, 33, NEW_PICKED_AT_7),
    _sf("SF0100", "Broadening Formation Â· 30m", 2, 0.35, 0.13, 50, NEW_PICKED_AT_7),
    _sf("SF0101", "Broadening Formation Â· 45m", 1, 1.47, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0533", "Fib 61.8% + RSI + HTF Trend Â· 15m", 31, -11.50, -1.25, 32, NEW_PICKED_AT_7),
    _sf("SF0123", "Inverted Hammer Â· 15m", 1, 0.93, 0.00, 100, NEW_PICKED_AT_7),
    _sf("SF0130", "Hanging Man Â· 5m", 2, 5.55, 0.93, 50, NEW_PICKED_AT_7),
    _sf("SF0317", "Support / Resistance Flip Â· 1h", 22, 8.46, 0.83, 32, NEW_PICKED_AT_7),
    _sf("SF0234", "Bollinger %B Extreme Â· 5m", 1, 1.30, 0.00, 100, NEW_PICKED_AT_7),
)
# picked by the owner on 14 Nov 2026 from the Crypto tab; records = their bitcoin paper trades at 09:44 IST
CRYPTO_PICKS: tuple[Pick, ...] = (
    Pick("TH-05", "BTCUSD", "BTCUSD", "EMA 50/200 trend, pullback to EMA 50 with RSI 40-55", 9, 8.41, 1.00, 44,
         "never backtested"),
    Pick("TL-04", "BTCUSD", "BTCUSD", "EMA 200 + RSI 50 + engulfing, stop two candles, 2R", 15, 3.58, 0.67, 47,
         "loses: -0.31R a trade over 2,134 trades (t -11.1)"),
    Pick("TH-01", "BTCUSD", "BTCUSD", "Bitcoin 6 PM session: anchored VWAP + EMA 25, the N pattern", 9, 9.55, 0.49, 11,
         "never backtested"),
    # added by the owner on 15 Nov 2026 from the Crypto tab; record = its bitcoin paper trades at 13:40 IST
    Pick("TD-02", "BTCUSD", "BTCUSD", "9/15 EMA cross filtered by the SMI (7, 2, 2)", 7, 20.0, 0.94, 43,
         "loses: -0.37R a trade over 998 trades (t -3.5)", "2026-11-15T13:40:00+05:30"),
    # added by the owner on 18 Nov 2026 from the Premium leaderboard's bitcoin rows; records = their bitcoin paper trades
    # at 22:00 IST
    Pick("TH-06", "BTCUSD", "BTCUSD", "Bitcoin 07:15-07:30 IST range breakout, stop at mid-range", 9, 5.29, 1.12, 78,
         "never backtested", NEW_PICKED_AT),
    Pick("DT-02", "BTCUSD", "BTCUSD", "MACD + Parabolic SAR + EMA 200, stop at the dot, 1:1 (30-minute)", 15, 4.36, 1.21, 73,
         "loses: -0.18R a trade over 1,170 trades (t -6.0)", NEW_PICKED_AT),
    Pick("RU-06", "BTCUSD", "BTCUSD", "Zero-lag MACD cross below/above zero in the 200 EMA trend, pullback stop, 1.5R", 9,
         5.30, 1.58, 67, "never backtested", NEW_PICKED_AT),
    Pick("NJ-47", "BTCUSD", "BTCUSD", "Smoothed Heikin Ashi retest, 1:3", 4, 3.57, 0.77, 50, "never backtested",
         NEW_PICKED_AT),
    Pick("RU-03", "BTCUSD", "BTCUSD", "Opposite RSI: RSI through 70/30 with ADX 25 in the EMA 200 trend, 1.5R", 7, 3.32,
         1.24, 57, "loses: -0.081R a trade over 417 trades (t -1.7)", NEW_PICKED_AT),
    # the second batch (23:50 IST): six more bitcoin books. DT-01's t (4 trades of almost the same R) means nothing.
    Pick("TH-04", "BTCUSD", "BTCUSD", "Renko + Ichimoku dual system, bitcoin", 0, 0.0, 0.0, 0, "never backtested",
         NEW_PICKED_AT_2),
    Pick("DT-01", "BTCUSD", "BTCUSD", "MACD cross in the EMA 100 trend, swing stop, 1.5R (1-hour)", 4, 5.68, 65.44, 100,
         "loses: -0.11R a trade over 281 trades (t -1.5)", NEW_PICKED_AT_2),
    Pick("TH-07", "BTCUSD", "BTCUSD", "Three-way confirmation on 30 minutes", 1, 4.96, 0.0, 100, "never backtested",
         NEW_PICKED_AT_2),
    Pick("NJ-27", "BTCUSD", "BTCUSD", "20-candle channel breakout with EMA 200 and ATR stops, 4 hours", 1, 3.03, 0.0, 100,
         "never backtested", NEW_PICKED_AT_2),
    Pick("PT-04", "BTCUSD", "BTCUSD", "4-hour inside-bar breakout in the trend, 2R", 1, 1.90, 0.0, 100,
         "loses: -0.20R a trade over 270 trades (t -2.3)", NEW_PICKED_AT_2),
    Pick("SB-04", "BTCUSD", "BTCUSD", "200 EMA retest with a confirmation candle", 1, 1.80, 0.0, 100, "never backtested",
         NEW_PICKED_AT_2),
    # the owner's 22 Nov screenshots of the Crypto tab (records at NEW_PICKED_AT_4, 14:30 IST): seven bitcoin books ...
    Pick("DT-05", "BTCUSD", "BTCUSD", "15-minute Chaikin Money Flow side + MACD cross, 1.5R", 24, 4.44, 0.76, 54,
         "loses: -0.26R a trade over 1,540 trades (t -9.2)", NEW_PICKED_AT_4),
    Pick("TL-03", "BTCUSD", "BTCUSD", "DEMA 200 + Supertrend (12, 3), exit on the opposite signal", 10, 6.51, 0.91, 50,
         "loses: -0.22R a trade over 1,313 trades (t -5.2)", NEW_PICKED_AT_4),
    Pick("RU-04", "BTCUSD", "BTCUSD", "Williams fractal breakout in the 200 MA trend, 1.5R", 21, 1.58, 0.32, 43,
         "loses: -0.16R a trade over 1,178 trades (t -5.3)", NEW_PICKED_AT_4),
    Pick("KA-01", "BTCUSD", "BTCUSD", "Break of the previous hour/day high or low after a staircase approach, two closes, "
         "swing stop, 1R", 5, 1.19, 0.74, 60, "never backtested", NEW_PICKED_AT_4),
    Pick("DD-01", "BTCUSD", "BTCUSD", "Over-extended RSI: RSI (14) crossing above 70 with the SSL trend and the TDFI, 1% "
         "stop, half at 1%, rest at 2%", 10, 4.23, 1.23, 60, "never backtested", NEW_PICKED_AT_4),
    Pick("TD-04", "BTCUSD", "BTCUSD", "UT Bot + linear-regression candles trend ride (1-hour)", 16, 0.86, 0.35, 38,
         "loses: -0.12R a trade over 929 trades (t -5.8)", NEW_PICKED_AT_4),
    Pick("TC-04", "BTCUSD", "BTCUSD", "5-minute EMA 100 trend, a close outside the opposite Bollinger Band (20, 1) back "
         "inside within 3 bars, 3R", 10, 1.65, 0.27, 40, "never backtested", NEW_PICKED_AT_4),
    # ... and two ether books, on Delta's ETHUSD perpetual (their bitcoin books are not picks)
    Pick("DD-04", "ETHUSD", "ETHUSD", "Bollinger 1-2-3: above the upper band, under the lower, rejected at the middle, "
         "break of the 1-3 line, 1.5R", 9, 4.38, 1.31, 56, "never backtested", NEW_PICKED_AT_4),
    Pick("BX-02", "ETHUSD", "ETHUSD", "TradingView Pivot Reversal (4, 2) on 1-hour bars: stop orders at the latest pivots, "
         "stop and reverse", 10, 2.04, 0.35, 30, "never backtested", NEW_PICKED_AT_4),
    # the owner's 24 Nov screenshots of the Crypto tab (records at NEW_PICKED_AT_5, 00:30 IST): six more bitcoin books,
    # DD-04's among them (its ether book is above; a pick is (account, market)) ...
    Pick("NJ-43", "BTCUSD", "BTCUSD", "Williams Alligator pullback to the teeth", 11, 2.69, 0.58, 55, "never backtested",
         NEW_PICKED_AT_5),
    Pick("TD-03", "BTCUSD", "BTCUSD", "UT Bot pair + Schaff Trend Cycle, 2R (15-minute)", 21, 1.38, 0.24, 48,
         "loses: -0.20R a trade over 1,092 trades (t -5.5)", NEW_PICKED_AT_5),
    Pick("NJ-28", "BTCUSD", "BTCUSD", "Fibonacci OTE: a 0.618 tap with an FVG", 8, 0.57, 0.13, 50, "never backtested",
         NEW_PICKED_AT_5),
    Pick("SC-02", "BTCUSD", "BTCUSD", "Cumulative delta divergence: a higher high (lower low) with a lower (higher) "
         "session CVD, close through, 2R", 3, 4.01, 3.76, 100, "never backtested", NEW_PICKED_AT_5),
    Pick("NJ-37", "BTCUSD", "BTCUSD", "The New York open fair value gap", 3, 2.49, 0.85, 67, "never backtested",
         NEW_PICKED_AT_5),
    Pick("DD-04", "BTCUSD", "BTCUSD", "Bollinger 1-2-3: above the upper band, under the lower, rejected at the middle, "
         "break of the 1-3 line, 1.5R", 8, 1.03, 0.31, 50, "never backtested", NEW_PICKED_AT_5),
    # ... and two more ether books on ETHUSD (their bitcoin books are not picks)
    Pick("DD-03", "ETHUSD", "ETHUSD", "Hull MA cross with the Awesome Oscillator and CMF above zero, T3 (300) and TDFI "
         "filters, 3 ATR stop, 1.3R", 27, 1.04, 0.26, 37, "never backtested", NEW_PICKED_AT_5),
    Pick("BX-01", "ETHUSD", "ETHUSD", "First green Heikin Ashi candle with MFI (14) at 20 or below, out on the first red "
         "one after MFI 80 (long only)", 5, 3.97, 0.83, 60, "never backtested", NEW_PICKED_AT_5),
)
# 24 Nov 2026 (evening), the owner's ask: the Gold Desk H1 test's six best paper records as a SEPARATE real-money book,
# "Premium Gold Strategies", beside the gold desk (which keeps its own copies of them). In the order of the Gold Desk's
# "Strategy records" ranking; records = their closed H1 positions at NEW_PICKED_AT_6 (20:30 IST), in R.
PREMIUM_GOLD_PICKS: tuple[Pick, ...] = (
    _h1("H1-RIB", "ema_ribbon", "EMA Ribbon Compression · 4h", 12, 5.57, 1.00, 50, NEW_PICKED_AT_6),
    _h1("H1-PIV", "pivot_break", "Pivot R1/S1 Break · 4h", 23, 7.22, 0.95, 43, NEW_PICKED_AT_6),
    _h1("H1-DCF", "donchian_fast", "Donchian Breakout (fast) · 4h", 20, 7.02, 1.03, 45, NEW_PICKED_AT_6),
    _h1("H1-RND", "round_number_break", "Round Number Break · 4h", 22, 3.99, 0.56, 41, NEW_PICKED_AT_6),
    _h1("H1-DCS", "donchian_slow", "Donchian Breakout (slow) · 4h", 7, 2.34, 0.54, 43, NEW_PICKED_AT_6),
    _h1("H1-KLT", "keltner_break", "Keltner Breakout · 4h", 17, 3.98, 0.64, 41, NEW_PICKED_AT_6),
)
GOLD_NOTES = (
    "Real money on 254 unproven gold strategies: five picked on 13 Nov, CP-06 on 15 Nov, TL-04's gold book on 16 Nov, "
    "on 18 Nov seventeen more Premium gold books and six templates of the Gold Desk's H1 test, on 19 Nov the Gold "
    "Desk Strategy Factory board's top 20, and on 22 Nov ten more Premium gold books, a seventh H1 template and 38 more "
    "of the Factory board's top 56, on 24 Nov three more Premium gold books (JR-05, BG-05, JR-01), and on 27 Nov "
    "152 more of the Factory board's top 209, at the owner's "
    "chosen size: one contract a trade, the smallest order Delta allows "
    "(or $1 to $5 of risk picked on this page).",
    "Sixteen lose in their own 2-year backtests, five earn too little there to mean anything (t under 2), sixteen were "
    "never backtested, the seven H1 templates were tested only as a family and the 210 Factory strategies only by the "
    "Factory's own backtest (whose replay reads future 4-hour bars); a few good paper trades picked them.",
    "Every one of them trades on Delta's own live data: the paper desk reads gold from Delta's XAUTUSD one-minute "
    "candles (not from COMEX or Yahoo), the Gold Desk's H1 test and its Strategy Factory tab trade Delta's XAUTUSD, and "
    "the real orders go to Delta's XAUTUSD perpetual.",
    "EVERY signal becomes a real position (the owner's ask, 19 Nov): an open paper trade of any of the 254 is copied, "
    "however late this desk sees it and however far the price has moved from the paper entry, including trades already "
    "open when the desk was switched on, with the paper's own stop and target. There is no daily loss stop and no cap on "
    "what one contract may lose: the only rule is the size, one contract.",
    "A copy waits, and is tried again every cycle, while the price is not at least a little inside the paper's stop and "
    "target (5 ticks and a tenth of its risk, so a fill cannot land past a level), while its source is silent, while "
    "Delta gives no quote, or while the wallet has too little free margin; it is never given up for being late. A paper "
    "trade that closes before it is copied is not copied, and the switches (this desk's and Main Control) still apply.",
    "A paper trade with no stop at all (PR-12's Supertrend ladder) gets a protective stop on Delta 3% from its fill, so no "
    "real trade is ever without a stop; it otherwise closes when its paper trade does. A stop farther than 7% from the "
    "price is pulled in to 7%: at 10x leverage Delta liquidates a position about 9.5% against it.",
    "The seven H1 templates' trades are the Gold Desk's own H1 positions (4-hour bars, held up to ten days), and the 210 "
    "Factory strategies' are the positions of the Gold Desk's Strategy Factory tab ($1,111 paper sleeves on closed bars "
    "of 5 minutes to 4 hours); both are copied the same way, and this desk only reads them.",
    "One gold contract is 0.001 XAUT (about $4 of gold), so a trade of one contract loses cents at its stop.",
    "All 254 can hold a trade at the same time (from 15 Nov), up to Delta's 100 open orders on XAUTUSD (below): "
    "each trade is its own order with its own stop on Delta, and Delta shows their sum as one gold position.",
    "This desk trades gold (XAUTUSD) only; the bitcoin desk is beside it on the Delta Exchange Live Trading page. Each "
    "has its own switch.",
    "Each trade's stop lives on Delta itself, so it stays protected if this server goes down. Its target is this "
    "server's (from 25 Nov): once the price reaches it the trade is closed at the market at the next check (every 20 "
    "seconds), so each trade holds one open order on Delta, not two.",
    "Delta allows an account 100 open orders on XAUTUSD, shared with the Premium Gold book. When they are full, a new "
    "signal is skipped and recorded as \"Delta's 100-order limit full\"; live trading stays on, and new signals go "
    "through again as trades close.",
    "Leverage is set to 10x on XAUTUSD before going live; positions are capped at $2,500 of notional.",
    "Fees and funding are Delta's own, read from its fills. Profit and loss are in US dollars.",
)
CRYPTO_NOTES = (
    "Real money on 32 strategies the owner picked: 28 on bitcoin (TH-05, TL-04, TH-01 on 14 Nov 2026 and TD-02 on 15 "
    "Nov from the Crypto tab; TH-06, DT-02, RU-06, NJ-47, RU-03, TH-04, DT-01, TH-07, NJ-27, PT-04 and SB-04 on 18 Nov "
    "from the Premium leaderboard; DT-05, TL-03, RU-04, KA-01, DD-01, TD-04 and TC-04 on 22 Nov and NJ-43, TD-03, "
    "NJ-28, SC-02, NJ-37 and DD-04's bitcoin book on 24 Nov from the Crypto tab) and four ether books on Delta's "
    "ETHUSD (DD-04 and BX-02 from 22 Nov, DD-03 and BX-01 from 24 Nov), at the owner's chosen size: one contract a "
    "trade, the smallest order Delta allows (or $1 to $5 of risk picked on this page).",
    "None is proven: eleven lose in their own 2-year bitcoin backtests (TL-04 -0.31R a trade over 2,134 trades, TD-02 "
    "-0.37R over 998, DT-02 -0.18R over 1,170, RU-03 -0.081R over 417, DT-01 -0.11R over 281, PT-04 -0.20R over 270, "
    "DT-05 -0.26R over 1,540, TL-03 -0.22R over 1,313, RU-04 -0.16R over 1,178, TD-04 -0.12R over 929, TD-03 -0.20R "
    "over 1,092) and twenty-one, the four ether books among them, were never backtested; 0 to 27 paper trades picked "
    "them.",
    "EVERY signal becomes a real position (the owner's ask, 19 Nov): each real trade is the paper desk's trade on "
    "Delta's live BTCUSD (or ETHUSD) candles, its entry, stop, target and exit, copied however late this desk sees it "
    "and however far the price has moved, including trades already open when the desk was switched on. There is no "
    "daily loss stop and no cap on what one contract may lose: the only rule is the size, one contract (0.001 BTC, or "
    "0.01 ETH).",
    "A copy waits, and is tried again every cycle, while the price is not at least a little inside the paper's stop and "
    "target, while the paper desk is silent, while Delta gives no quote, or while the wallet has too little free margin: "
    "each open bitcoin contract holds about a tenth of its notional (about $6) as margin, an ether contract about $2. "
    "A paper trade that closes before it is copied is not copied.",
    "A stop farther than 7% from the price is pulled in to 7% on Delta (TH-04's paper stops have been 15-30% away): at "
    "10x leverage Delta liquidates a position about 9.5% against it, so a farther stop could never be reached. A paper "
    "trade with no stop gets one 3% away.",
    "All 32 can hold a trade at the same time (from 15 Nov): each trade is its own order with its own stop and "
    "target on Delta, and Delta shows their sum as one position a product (one bitcoin, one ether).",
    "Each trade's stop and target live on Delta itself, so it stays protected if this server goes down.",
    "Leverage is set to 10x on BTCUSD before going live, and confirmed at 10x on ETHUSD before its first trade; "
    "positions are capped at $2,500 of notional.",
    "Fees and funding are Delta's own, read from its fills. Profit and loss are in US dollars.",
    "This desk and the gold desk (beside it on this page, and on Premium Strategies > Real money · Delta gold) share the "
    "Delta account and its keys; each has its own switch.",
)
PREMIUM_GOLD_NOTES = (
    "Real money on six strategies of the Gold Desk's H1 test, picked by the owner on 24 Nov 2026 from its Strategy "
    "records: EMA Ribbon Compression, Pivot R1/S1 Break, Donchian Breakout (fast and slow), Round Number Break and "
    "Keltner Breakout, all on 4-hour bars. A separate book: the gold desk copies the same six at its own size, so each "
    "of their signals opens two real positions on Delta, one a book.",
    "None is proven: the H1 test's nine templates were tested only as a family (pooled, +12.2 bp a trade net on Delta's "
    "2026 data, the data they were found in); these six had its best paper records at the pick (7 to 23 trades each).",
    "Size: each strategy's own lots, 1 until changed in this book's table. One lot is 0.001 XAUT, about $3.6 of gold "
    "at $3,600 an ounce, and at 10x it holds a tenth of that as margin; the page shows any lots in dollars and rupees. "
    "Every trade is capped at $2,500 of notional and at the product's most lots a trade.",
    "EVERY signal becomes a real position, as on the gold desk: an open H1 position of the six is copied however late "
    "this book sees it, with that position's own stop on Delta (a stop more than 7% away is pulled in to 7%) and its "
    "target closed by this server at the market, as on the gold desk. "
    "A copy waits while the price is not inside its stop and target with room, while the Gold Desk is silent, while Delta "
    "gives no quote, or while the wallet has too little free margin. No daily loss stop.",
    "This book starts OFF: its own switch, on this tab, turns it on (one confirmation). The gold desk's switch does not "
    "move it, nor this one the gold desk.",
    "Delta shows all of the account's XAUTUSD trades, both books', as one position; each book checks the account against "
    "the sum of both, and each trade closes only its own contracts. Each trade's stop lives on Delta itself; its "
    "target is this server's (25 Nov). The two books share Delta's 100 open orders on XAUTUSD: when they are full, a "
    "new signal is skipped and recorded as \"Delta's 100-order limit full\", and the book stays on.",
    "Fees and funding are Delta's own, read from its fills. Profit and loss are in US dollars.",
)


@dataclass(frozen=True)
class Desk:
    key: str
    title: str
    picks: tuple[Pick, ...]
    state_coll: str
    trades_coll: str
    risk_usd: float
    daily_stop_usd: float
    picked_at: str
    notes: tuple[str, ...]
    max_lag_s: int = MAX_LAG_S      # a paper entry seen later than this after its entry time is skipped
    follow_all: bool = False        # True: every open paper trade is copied, however late or far (lag/drift unused)
    cid_salt: str = ""              # hashed into its client order ids: a desk copying another's paper trades needs one

    @property
    def pick(self) -> dict:
        return {(p.acct, p.mkt): p for p in self.picks}

    @property
    def products(self) -> list[str]:
        return sorted({p.product for p in self.picks})


DESKS: dict[str, Desk] = {
    "gold": Desk("gold", "Real money · Delta gold", GOLD_PICKS, "live_delta_state", "live_delta_trades", RISK_USD,
                 DAILY_STOP_USD, PICKED_AT, GOLD_NOTES, GOLD_MAX_LAG_S, follow_all=True),
    "crypto": Desk("crypto", "Delta Exchange Live Trading", CRYPTO_PICKS, "live_crypto_state", "live_crypto_trades",
                   CRYPTO_RISK_USD, CRYPTO_DAILY_STOP_USD, CRYPTO_PICKED_AT, CRYPTO_NOTES, CRYPTO_MAX_LAG_S,
                   follow_all=True),
    # 24 Nov 2026: a second gold book beside the gold desk, on the same product (see the module docstring)
    "premium_gold": Desk("premium_gold", "Premium Gold Strategies", PREMIUM_GOLD_PICKS, "live_pgold_state",
                         "live_pgold_trades", RISK_USD, DAILY_STOP_USD, NEW_PICKED_AT_6, PREMIUM_GOLD_NOTES,
                         GOLD_MAX_LAG_S, follow_all=True, cid_salt="pgold|"),
}
if set(DESKS["gold"].products) & set(DESKS["crypto"].products):
    raise RuntimeError("two desks may never trade the same product")
_DESK_LIST = list(DESKS.values())
for _i, _a in enumerate(_DESK_LIST):                # desks sharing a product (24 Nov) must never share order ids
    for _b in _DESK_LIST[_i + 1:]:
        if set(_a.products) & set(_b.products) and _a.cid_salt == _b.cid_salt:
            raise RuntimeError(f"the {_a.key} and {_b.key} desks share a product, so they need different cid_salt")
for _k, _desk in DESKS.items():
    if len(_desk.pick) != len(_desk.picks):
        raise RuntimeError(f"the {_k} desk names one book twice")
    if any(p.src in (GOLD_H1, GOLD_SF) and not p.template for p in _desk.picks):
        raise RuntimeError(f"the {_k} desk has an H1 or Factory pick without its template")
    if any("." in f"{p.acct}|{p.mkt}" or f"{p.acct}|{p.mkt}".startswith("$") for p in _desk.picks):
        raise RuntimeError(f"the {_k} desk has a pick whose key cannot be a stored field name (pick_cfg)")
# The desk the current task works for. The loop and every API call set it (_use); the default is the gold desk, so
# a caller that names no desk gets the original one.
_CUR: contextvars.ContextVar[str] = contextvars.ContextVar("premium_live_desk", default="gold")


def _d() -> Desk:
    return DESKS[_CUR.get()]


@contextlib.contextmanager
def _use(key: str):
    if key not in DESKS:
        raise KeyError(key)
    tok = _CUR.set(key)
    try:
        yield DESKS[key]
    finally:
        _CUR.reset(tok)


def _sc(db):
    """This desk's state collection."""
    return getattr(db, _d().state_coll)


def _tc(db):
    """This desk's trade records."""
    return getattr(db, _d().trades_coll)


OPEN_STATUSES = ("entering", "open", "closing")
MODULE = "delta_live"          # its key in Main Control (module_registry)


async def open_count() -> int:
    """Trades still open on either desk: Main Control's probe for STOPPING (manage them) versus PAUSED (skip the loop).

    Raises when the database cannot answer, which Main Control reads as "may still hold something" and keeps managing."""
    db = _db()
    if db is None:
        return 0
    n = 0
    for desk in DESKS.values():
        n += int(await getattr(db, desk.trades_coll).count_documents({"status": {"$in": list(OPEN_STATUSES)}}))
    return n

# -- small helpers -------------------------------------------------------------------------------------


def _now() -> float:
    return time.time()


def _day(t: float | None = None) -> str:
    return datetime.fromtimestamp(t if t is not None else _now(), IST).date().isoformat()


def _db():
    """The box's local MongoDB that holds the paper desk (premium_paper._database); None when not configured."""
    from app.api.routes.premium_paper import _database
    return _database()


def _cid(trade_id: str, suffix: str = "") -> str:
    """A client order id Delta keeps beside its own: the paper trade's id, hashed (Delta allows 32 characters). A desk
    that copies the same paper trades as another (the Premium Gold book, 24 Nov) salts the hash, so the two books'
    orders never share an id; the two original desks have no salt, their ids exactly as before."""
    return ("p5" + hashlib.sha1((_d().cid_salt + trade_id).encode()).hexdigest())[:30 - len(suffix)] + suffix


def _side(side: int) -> str:
    return "buy" if side > 0 else "sell"


def _fee(notional: float, rate: float) -> float:
    return abs(notional) * rate * (1 + GST)


def _sizing(st: dict) -> str:
    """"min" (one contract a trade, the smallest order: the default from 15 Nov) or "risk" (sized to the owner's dollar
    risk). A dollar risk chosen before the one-contract choice existed (risk_set_at, no sizing) counts as "risk"."""
    s = st.get("sizing")
    if s in ("min", "risk"):
        return s
    return "risk" if st.get("risk_set_at") else SIZING_DEFAULT


def _risk(st: dict) -> float:
    """The most a new trade of this desk may lose at its stop: the owner's choice on the page (RISK_MIN_USD up to the
    desk's own risk), or the desk's own risk until one is chosen."""
    try:
        r = float(st.get("risk_usd"))
    except (TypeError, ValueError):
        return _d().risk_usd
    return min(max(r, RISK_MIN_USD), _d().risk_usd) if math.isfinite(r) else _d().risk_usd


def _trade_risk(t: dict) -> float:
    """The risk a trade was sized for, for its R (records from before 15 Nov were all sized at the desk's own)."""
    try:
        r = float((t.get("plan") or {}).get("risk_set_usd") or 0)
    except (TypeError, ValueError):
        r = 0.0
    return r if r > 0 else _d().risk_usd


def _pkey(p: Pick) -> str:
    """A strategy's key in the desk's state and on the page: "acct|mkt" (a pick is an account and its market)."""
    return f"{p.acct}|{p.mkt}"


def _lots_max(product: str) -> int:
    return int(LOTS_MAX.get(product, LOTS_DEFAULT))


def _cfg(st: dict, p: Pick) -> dict:
    """A strategy's own size and switch (23 Nov 2026): {"contracts", "on", "at"}; the defaults (one contract, ON) until
    the owner changes them. A stored size outside 1..LOTS_MAX (a cap lowered later) is read inside it."""
    c = (st.get("pick_cfg") or {}).get(_pkey(p)) or {}
    try:
        n = int(c.get("contracts", LOTS_DEFAULT))
    except (TypeError, ValueError):
        n = LOTS_DEFAULT
    return {"contracts": min(max(n, 1), _lots_max(p.product)), "on": c.get("on") is not False, "at": c.get("at")}


async def _state(db) -> dict:
    st = await _sc(db).find_one({"_id": "state"})
    if st is None:
        st = {"_id": "state", "mode": "off", "since": _now(), "errors_in_row": 0, "pin_fails": [], "products": {},
              "created_at": _now()}
        await _sc(db).update_one({"_id": "state"}, {"$setOnInsert": {k: v for k, v in st.items() if k != "_id"}},
                                             upsert=True)
        st = await _sc(db).find_one({"_id": "state"}) or st
    return st


async def _set_state(db, **fields) -> None:
    await _sc(db).update_one({"_id": "state"}, {"$set": {**fields, "updated_at": _now()}}, upsert=True)


async def _set_trade(db, tid: str, **fields) -> None:
    await _tc(db).update_one({"_id": tid}, {"$set": {**fields, "updated_at": _now()}})


async def _venue_ok(db, st: dict) -> None:
    """Delta answered: the count of venue errors IN A ROW starts again. (Before 15 Nov only an entry or arming reset it,
    so scattered timeouts added up until a desk switched itself off.)"""
    if st.get("errors_in_row"):
        st["errors_in_row"] = 0
        await _set_state(db, errors_in_row=0)


async def _venue_error(db, st: dict, what: str) -> None:
    n = int(st.get("errors_in_row") or 0) + 1
    st["errors_in_row"] = n
    fields = {"errors_in_row": n, "last_error": what, "last_error_at": _now()}
    if n >= ERRORS_TO_STOP and st.get("mode") == "live":
        fields.update(mode="off", switched_off=f"{n} venue errors in a row: {what}")
        st["mode"] = "off"
    await _set_state(db, **fields)
    logger.warning("[premium live %s] %s", _d().key, what)


async def _switch_off(db, st: dict, why: str) -> None:
    st["mode"] = "off"
    await _set_state(db, mode="off", switched_off=why, last_error=why, last_error_at=_now())
    logger.error("[premium live %s] switched off: %s", _d().key, why)


_FULL: dict[str, float] = {}       # product -> when Delta last refused an order there for its 100-order limit
_TQ: dict[str, dict] = {}          # product -> its last quote for the target check (TARGET_QUOTE_TTL_S)
_CONVERTED: dict[str, int] = {}    # desk -> targets handed to this server this pass (CONVERT_PER_PASS)


def _cap_refusal(exc: BaseException) -> bool:
    """Delta's refusal once the account holds 100 open orders on the product (seen 24-25 Nov 2026)."""
    return "max_orders_count_exceeded" in str(exc)


def _venue_full(sym: str) -> bool:
    """Has Delta refused an order on this product for its 100-order limit since a trade on it last closed, within
    VENUE_FULL_RETRY_S? Its new signals are then skipped without being sent (25 Nov 2026)."""
    at = _FULL.get(sym)
    if at is not None and _now() - at > VENUE_FULL_RETRY_S:
        _FULL.pop(sym, None)
        at = None
    return at is not None


async def _products(db, st: dict, extra: set | None = None) -> dict[str, Product]:
    """The desk's products' specs from Delta (plus any product a still-open trade holds), cached in the state; never a
    default (sizes differ a thousandfold)."""
    cached = st.get("products") or {}
    out: dict[str, Product] = {}
    for sym in sorted(set(_d().products) | set(extra or ())):
        c = cached.get(sym)
        if c and _now() - float(c.get("at") or 0) < 6 * 3600:
            out[sym] = Product(int(c["id"]), sym, float(c["contract_value"]), float(c["tick"]),
                               float(c["maintenance_pct"]), float(c["taker_rate"]))
            continue
        p = await D.product(sym)
        out[sym] = p
        cached[sym] = {**asdict(p), "at": _now(), "leverage": (c or {}).get("leverage")}
    st["products"] = cached
    await _set_state(db, products=cached)
    return out


async def _desk_age(db) -> float:
    """Seconds since the paper desk last wrote its status (it does after every cycle)."""
    s = await db.premium_meta.find_one({"_id": "status"}, {"segments_at": 1})
    try:
        at = datetime.fromisoformat(str((s or {}).get("segments_at")))
        return _now() - (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return float("inf")


async def _paper(db, since: float, ids: list[str]) -> dict[str, dict]:
    """The desk's picks' sized paper trades that entered since `since`, plus any an open real trade points at (kept
    even when its book is no longer a pick, so a trade from before a re-pick is still managed to its close). A desk that
    follows every paper trade (follow_all) also reads every one still open, however long ago it entered."""
    want = set(ids)
    accts = sorted({p.acct for p in _d().picks if p.src == PREMIUM})
    ors: list[dict] = [{"acct": {"$in": accts}, "entry_t": {"$gte": int(since) - _d().max_lag_s}},
                       {"_id": {"$in": [i for i in ids if not (i.startswith(H1_ID) or i.startswith(SF_ID))]}}]
    if _d().follow_all:
        ors.append({"acct": {"$in": accts}, "open": True})
    q = {"qty": {"$gt": 0}, "$or": ors}
    out = {}
    async for t in db.premium_trades.find(q):
        if t["_id"] in want or (t.get("acct"), t.get("mkt")) in _d().pick:
            out[t["_id"]] = t
    return out


# -- the second source: the Gold Desk's H1 positions (18 Nov 2026) --------------------------------------


def _h1_coll():
    """The Gold Desk's positions, in the app's main database (a function, so a test can swap it)."""
    from app.core.db import gold_positions_collection
    return gold_positions_collection


def _h1_state_coll():
    from app.core.db import gold_state_collection
    return gold_state_collection


def _ts(v) -> float | None:
    """A stored time as epoch seconds; a naive datetime is UTC (how the database hands it back)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp()
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _h1_picks() -> dict[str, Pick]:
    """This desk's H1 picks by the Gold Desk template they copy."""
    return {p.template: p for p in _d().picks if p.src == GOLD_H1 and p.template}


def is_h1(trade_id: str) -> bool:
    return str(trade_id).startswith(H1_ID)


def _h1_as_paper(pos: dict, pick: Pick | None) -> dict:
    """A Gold Desk H1 position in the shape of a paper trade: what _enter and the managers read."""
    status = str(pos.get("status") or "").upper()
    void = bool(pos.get("void")) or status == "VOID"
    side = str(pos.get("side") or "").upper()
    reason = "void" if void else pos.get("exit_reason")
    return {"_id": H1_ID + str(pos["position_id"]), "src": GOLD_H1,
            "acct": pick.acct if pick else f"H1-{pos.get('strategy_template')}", "mkt": pick.mkt if pick else "XAUTUSD",
            "side": 1 if side in ("BUY", "LONG", "1") else -1,
            "entry": float(pos.get("entry_price") or 0.0), "stop": float(pos.get("stoploss") or 0.0),
            "target": float(pos["target"]) if pos.get("target") else None,
            "entry_t": _ts(pos.get("opened_at")) or 0.0, "open": status == "OPEN" and not void,
            "exit": float(pos["exit_price"]) if pos.get("exit_price") is not None else None,
            # the Gold Desk says "stoploss"; the paper desk's word (which shadow mode reads) is "stop"
            "reason": "stop" if reason == "stoploss" else reason,
            "setup": pos.get("strategy_template"), "qty": float(pos.get("qty") or 0.0)}


async def _paper_h1(since: float, ids: list[str]) -> dict[str, dict]:
    """The desk's H1 picks' positions opened since `since`, plus any an open real trade points at. Raises when the
    Gold Desk cannot be read: the caller then leaves the H1 trades waiting (never closed for a failed read)."""
    picks = _h1_picks()
    held = [i[len(H1_ID):] for i in ids if is_h1(i)]
    if not picks and not held:
        return {}
    ors: list[dict] = []
    if picks:
        ors.append({"strategy_template": {"$in": sorted(picks)},
                    "opened_at": {"$gte": datetime.fromtimestamp(int(since) - _d().max_lag_s, timezone.utc)}})
        if _d().follow_all:                        # every open position of the picks, however old (19 Nov)
            ors.append({"strategy_template": {"$in": sorted(picks)}, "status": "OPEN"})
    if held:
        ors.append({"position_id": {"$in": held}})
    out = {}
    async for pos in _h1_coll().find({"venue": "delta", "h1": True, "symbol": "XAUTUSD", "$or": ors}):
        t = _h1_as_paper(pos, picks.get(pos.get("strategy_template")))
        out[t["_id"]] = t
    return out


async def _h1_age() -> float:
    """Seconds since the Gold Desk's Delta venue last ran its cycle (gold_desk_state "delta" last_run_at)."""
    s = await _h1_state_coll().find_one({"_id": "delta"}, {"last_run_at": 1})
    at = _ts((s or {}).get("last_run_at"))
    return _now() - at if at else float("inf")


# -- the third source: the Gold Desk's Strategy Factory tab (19 Nov 2026) -----------------------------------

SF_DESK = "gold"                               # the Factory tab whose positions the gold desk copies
_SF_FIELDS = {"position_id": 1, "strategy_id": 1, "strategy_name": 1, "signal_side": 1, "side": 1, "entry_px": 1,
              "under_entry": 1, "stop": 1, "target": 1, "opened_at": 1, "status": 1, "exit_px": 1, "exit_reason": 1,
              "pattern": 1, "capital_deployed": 1, "closed_at": 1, "under_ltp": 1, "realized_pnl": 1}


def _sf_coll():
    """The Factory tabs' positions, in the Factory's own store (a function, so a test can swap it)."""
    from app.services.factory_desks import POSITIONS
    return POSITIONS


def _sf_state_coll():
    from app.services.factory_desks import STATE
    return STATE


def _sf_picks() -> dict[str, Pick]:
    """This desk's Factory picks by strategy_id."""
    return {p.template: p for p in _d().picks if p.src == GOLD_SF and p.template}


def is_sf(trade_id: str) -> bool:
    return str(trade_id).startswith(SF_ID)


def _sf_as_paper(pos: dict, pick: Pick | None) -> dict:
    """A Factory tab position in the shape of a paper trade. Its stop and target are levels of XAUTUSD itself (the tab
    trades the perpetual both sides at 1x); qty = its sleeve in ounces, for its R."""
    status = str(pos.get("status") or "").upper()
    side = str(pos.get("signal_side") or pos.get("side") or "").upper()
    entry = float(pos.get("entry_px") or pos.get("under_entry") or 0.0)
    reason = pos.get("exit_reason")
    return {"_id": SF_ID + str(pos["position_id"]), "src": GOLD_SF,
            "acct": pick.acct if pick else str(pos.get("strategy_id")), "mkt": pick.mkt if pick else "XAUTUSD",
            "side": 1 if side == "BUY" else -1, "entry": entry, "stop": float(pos.get("stop") or 0.0),
            "target": float(pos["target"]) if pos.get("target") else None,
            "entry_t": _ts(pos.get("opened_at")) or 0.0, "open": status == "OPEN",
            "exit": float(pos["exit_px"]) if pos.get("exit_px") is not None else None,
            "reason": "stop" if reason == "stoploss" else reason,
            "setup": pos.get("pattern") or pos.get("strategy_name"),
            "qty": float(pos.get("capital_deployed") or 0.0) / entry if entry else 0.0}


async def _paper_sf(since: float, ids: list[str]) -> dict[str, dict]:
    """The desk's Factory picks' positions opened since `since` (every open one on a follow_all desk), plus any an open
    real trade points at. Raises when the Factory's store cannot be read: the caller then leaves those trades waiting."""
    picks = _sf_picks()
    held = [i[len(SF_ID):] for i in ids if is_sf(i)]
    if not picks and not held:
        return {}
    ors: list[dict] = []
    if picks:
        ors.append({"strategy_id": {"$in": sorted(picks)},
                    "opened_at": {"$gte": datetime.fromtimestamp(int(since) - _d().max_lag_s, timezone.utc)}})
        if _d().follow_all:
            ors.append({"strategy_id": {"$in": sorted(picks)}, "status": "OPEN"})
    if held:
        ors.append({"position_id": {"$in": held}})
    out = {}
    async for pos in _sf_coll().find({"desk": SF_DESK, "symbol": "XAUTUSD", "$or": ors}, _SF_FIELDS):
        t = _sf_as_paper(pos, picks.get(pos.get("strategy_id")))
        out[t["_id"]] = t
    return out


async def _sf_age() -> float:
    """Seconds since the Gold Desk's Strategy Factory tab last finished a cycle (factory_desk_state "cycle:gold" at)."""
    s = await _sf_state_coll().find_one({"_id": f"cycle:{SF_DESK}"}, {"at": 1})
    at = _ts((s or {}).get("at"))
    return _now() - at if at else float("inf")


# -- the page's paper view (18 Nov 2026): each strategy's own paper trades beside what this desk did with them ----

PAPER_TTL_S = 30.0             # the paper view is re-read at most this often a desk (the page polls every 15 s)
SIGNALS_N = 60                 # the latest paper trades the page lists, each with this desk's decision on it
_PAPER_CACHE: dict[str, tuple[float, dict]] = {}
_PAPER_FIELDS = {"acct": 1, "mkt": 1, "side": 1, "entry_t": 1, "entry": 1, "stop": 1, "target": 1, "open": 1, "exit": 1,
                 "exit_t": 1, "reason": 1, "r_net": 1, "last": 1, "unit": 1, "qty": 1}
_REAL_FIELDS = {"status": 1, "reason": 1, "close_reason": 1, "pnl_usd": 1, "unrealised_usd": 1, "contracts": 1, "mode": 1}


def _sign(v) -> int:
    try:
        return 1 if int(v or 0) > 0 else -1
    except (TypeError, ValueError):
        return -1


def _r_now(t: dict) -> float | None:
    """An open paper trade's R at its last mark: side x (last - entry) / its risk a unit."""
    try:
        unit = float(t.get("unit") or abs(float(t["entry"]) - float(t["stop"])))
        if not unit or t.get("last") is None:
            return None
        return round(_sign(t.get("side")) * (float(t["last"]) - float(t["entry"])) / unit, 2)
    except (TypeError, ValueError, KeyError):
        return None


async def _paper_rows(db) -> list[dict]:
    """Every sized paper trade of this desk's picks: premium_trades, and the H1 picks' Gold Desk positions read the same
    way (their R = realised P&L over |entry - stop| x quantity; a voided position has none)."""
    rows: list[dict] = []
    prem = sorted({p.acct for p in _d().picks if p.src == PREMIUM})
    if prem:
        async for t in db.premium_trades.find({"acct": {"$in": prem}, "qty": {"$gt": 0}}, _PAPER_FIELDS):
            if (t.get("acct"), t.get("mkt")) in _d().pick:
                rows.append(t)
    picks = _h1_picks()
    if picks:
        async for pos in _h1_coll().find({"venue": "delta", "h1": True, "symbol": "XAUTUSD",
                                          "strategy_template": {"$in": sorted(picks)}}):
            t = _h1_as_paper(pos, picks.get(pos.get("strategy_template")))
            unit = abs(t["entry"] - t["stop"])
            closed = str(pos.get("status") or "").upper() == "CLOSED" and not pos.get("void")
            t.update(exit_t=_ts(pos.get("closed_at")), last=pos.get("ltp"), unit=unit,
                     r_net=float(pos.get("realized_pnl") or 0.0) / (unit * t["qty"]) if closed and unit and t["qty"] else None)
            rows.append(t)
    sfp = _sf_picks()
    if sfp:                                    # the Factory picks' tab positions, read the same way (19 Nov)
        async for pos in _sf_coll().find({"desk": SF_DESK, "symbol": "XAUTUSD", "strategy_id": {"$in": sorted(sfp)}},
                                         _SF_FIELDS):
            t = _sf_as_paper(pos, sfp.get(pos.get("strategy_id")))
            unit = abs(t["entry"] - t["stop"])
            closed = str(pos.get("status") or "").upper() == "CLOSED"
            t.update(exit_t=_ts(pos.get("closed_at")), last=pos.get("under_ltp"), unit=unit,
                     r_net=float(pos.get("realized_pnl") or 0.0) / (unit * t["qty"]) if closed and unit and t["qty"] else None)
            rows.append(t)
    return rows


async def _paper_view(db, st: dict) -> dict | None:
    """What the page shows of the paper side: each pick's paper record and open trades now (every sized trade since
    the paper desk started it), and the latest SIGNALS_N paper trades with this desk's decision on each - copied (and
    how it went), skipped and why, or none (the desk was off, or the trade came before it was switched on). Read only;
    cached PAPER_TTL_S a desk; None when the paper side cannot be read (the rest of the page still shows)."""
    hit = _PAPER_CACHE.get(_d().key)
    if hit and _now() - hit[0] < PAPER_TTL_S:
        return hit[1]
    try:
        rows = await _paper_rows(db)
        per: dict[str, dict] = {}
        rs: dict[str, list] = {}                   # each closed paper trade (exit time, R, id), for the rank; not shown
        for t in rows:
            key = f"{t.get('acct')}|{t.get('mkt')}"
            x = per.setdefault(key, {"trades": 0, "wins": 0, "sum_r": 0.0, "open": [], "last_t": None})
            et = float(t.get("entry_t") or 0)
            x["last_t"] = max(x["last_t"] or 0.0, et) or None
            if t.get("open"):
                x["open"].append({"id": t["_id"], "side": _sign(t.get("side")), "entry": t.get("entry"),
                                  "stop": t.get("stop"), "target": t.get("target"), "entry_t": et, "r_now": _r_now(t)})
            elif t.get("r_net") is not None:
                r = float(t["r_net"])
                x["trades"] += 1
                x["wins"] += 1 if r > 0 else 0
                x["sum_r"] += r
                if math.isfinite(r):
                    rs.setdefault(key, []).append((float(t.get("exit_t") or t.get("entry_t") or 0), r, t["_id"]))
        for x in per.values():
            x["sum_r"] = round(x["sum_r"], 2)
            x["open"].sort(key=lambda o: -o["entry_t"])
        rows.sort(key=lambda t: -float(t.get("entry_t") or 0))
        latest = rows[:SIGNALS_N]
        real = {d["_id"]: d async for d in _tc(db).find({"_id": {"$in": [t["_id"] for t in latest]}}, _REAL_FIELDS)}
        since, mode = float(st.get("since") or 0), st.get("mode")
        follow, waits = _d().follow_all, _WAITING.get(_d().key, {})
        signals = []
        for t in latest:
            et, d = float(t.get("entry_t") or 0), real.get(t["_id"])
            if d is not None:
                why = d.get("close_reason") if d.get("status") in ("closed", "closing") else d.get("reason")
                desk = {"status": d.get("status"), "why": why, "pnl_usd": d.get("pnl_usd"), "mode": d.get("mode"),
                        "unrealised_usd": d.get("unrealised_usd"), "contracts": d.get("contracts")}
            elif mode not in ("live", "shadow"):
                desk = {"status": "off", "why": "this desk is off"}
            elif follow and t.get("open") and t["_id"] in waits:
                desk = {"status": "waiting", "why": waits[t["_id"]]["why"]}
            elif follow and t.get("open"):
                desk = {"status": "pending", "why": "being copied"}       # however old: this desk copies every open one
            elif since and et < since:
                desk = {"status": "before", "why": "before this desk was switched on"}
            elif follow:
                desk = {"status": "missed", "why": "closed on paper before this desk copied it"}
            else:
                desk = {"status": "pending", "why": "being decided"}
            closed = not t.get("open") and t.get("r_net") is not None
            signals.append({"id": t["_id"], "acct": t.get("acct"), "mkt": t.get("mkt"), "src": t.get("src", PREMIUM),
                            "side": _sign(t.get("side")), "entry_t": et, "entry": t.get("entry"), "stop": t.get("stop"),
                            "target": t.get("target"), "open": bool(t.get("open")), "exit": t.get("exit"),
                            "exit_t": t.get("exit_t"), "reason": t.get("reason"),
                            "r": round(float(t["r_net"]), 2) if closed else None,
                            "r_now": _r_now(t) if t.get("open") else None, "desk": desk})
        view = {"per": per, "signals": signals, "at": _now(), "paper_age_s": round(await _desk_age(db), 1), "rs": rs}
        if _h1_picks():
            view["gold_desk_age_s"] = round(await _h1_age(), 1)
        if _sf_picks():
            view["factory_age_s"] = round(await _sf_age(), 1)
    except Exception:  # noqa: BLE001 - the page then shows the desk without its paper side
        logger.warning("[premium live] the paper view could not be read", exc_info=True)
        return None
    _PAPER_CACHE[_d().key] = (_now(), view)
    return view


# -- P&L -----------------------------------------------------------------------------------------------


def _pnl(side: int, entry: float, exit_: float, contracts: int, cv: float, fees: float) -> float:
    return round(side * (exit_ - entry) * contracts * cv - fees, 4)


async def _exit_from_fills(t: dict, product: Product, fallback_price: float | None, fallback_fee: float | None) -> dict:
    """The exit as Delta recorded it: the fills on the product after the entry that are not the entry order's own."""
    try:
        rows = await D.fills(product.id, float(t.get("opened_at") or _now()) - 5)
    except DeltaError:
        rows = []
    entry_id = str((t.get("entry_order") or {}).get("id") or "")
    close_side = "sell" if t["side"] > 0 else "buy"
    ex = [f for f in rows if f["order_id"] != entry_id and str(f.get("side")).lower() == close_side and f["size"] > 0]
    size = sum(f["size"] for f in ex)
    if size >= t["contracts"]:
        take, left, px, fee = [], t["contracts"], 0.0, 0.0
        for f in sorted(ex, key=lambda f: str(f.get("created_at"))):
            n = min(left, f["size"])
            px += f["price"] * n
            fee += f["commission"] * n / f["size"]
            left -= n
            if left <= 0:
                break
        return {"price": px / t["contracts"], "fee": fee, "basis": "fills"}
    if fallback_price:
        return {"price": fallback_price, "fee": fallback_fee if fallback_fee is not None
                else _fee(fallback_price * t["contracts"] * product.contract_value, product.taker_rate), "basis": "order"}
    # nothing read: the stop's limit, the worst the bracket allowed, so the daily stop errs on the safe side
    worst = float((t.get("legs") or {}).get("stop_limit") or t["stop"])
    return {"price": worst, "fee": _fee(worst * t["contracts"] * product.contract_value, product.taker_rate),
            "basis": "estimated (no fills read)"}


async def _record_close(db, t: dict, ex: dict, reason: str, product: Product, extra_pnl: float = 0.0) -> None:
    """`extra_pnl`: what offsetting legs that filled beyond the trade's size made or cost; part of its result."""
    fees = float(t.get("entry_fee") or 0.0) + float(ex["fee"] or 0.0)
    pnl = round(_pnl(t["side"], float(t["fill"]), float(ex["price"]), int(t["contracts"]), product.contract_value, fees)
                + extra_pnl, 4)
    await _set_trade(db, t["_id"], status="closed", exit_price=round(float(ex["price"]), 6), exit_fee=round(float(ex["fee"]), 6),
                     exit_basis=ex["basis"], fees=round(fees, 6), pnl_usd=pnl, r=round(pnl / _trade_risk(t), 3),
                     close_reason=reason, closed_at=_now(), day_closed=_day(), unrealised_usd=0.0,
                     **({"extra_pnl": extra_pnl} if extra_pnl else {}))
    _FULL.pop(product.symbol, None)             # a trade on the product closed: room on Delta again (25 Nov)


async def _day_pnl(db, mode: str, positions: dict | None) -> float:
    """Today's (IST) closed P&L plus the open trades' marks, in USD, for one mode."""
    total = 0.0
    async for t in _tc(db).find({"mode": mode, "day_closed": _day(), "status": "closed"}, {"pnl_usd": 1}):
        total += float(t.get("pnl_usd") or 0.0)
    async for t in _tc(db).find({"mode": mode, "status": {"$in": ["open", "closing"]}}, {"unrealised_usd": 1}):
        total += float(t.get("unrealised_usd") or 0.0)
    return round(total, 4)


# -- managing what is open -------------------------------------------------------------------------------


async def _manage_bracket(db, st: dict, t: dict, paper: dict | None, positions: dict, products: dict, desk_age: float) -> None:
    """A trade from before 15 Nov: its one bracket covers the whole position, so the position is the trade."""
    product = products[t["product"]]
    pos = positions.get(product.id)
    size = int(pos["size"]) if pos else 0
    if t["status"] == "entering":
        # left half-done (the process stopped between the order and its record)
        if _now() - float(t.get("created_at") or 0) < 90:
            return
        if size and (size > 0) == (t["side"] > 0) and t.get("adoptable", True):
            await _set_trade(db, t["_id"], status="open", contracts=abs(size), fill=pos["entry"], opened_at=_now(),
                             recovered=True)
            t.update(status="open", contracts=abs(size), fill=pos["entry"])
            try:
                legs = await D.bracket(product, _side(t["side"]), pos["entry"], float(t["stop"]),
                                       float(t["target"]) if t.get("target") else None)
                await _set_trade(db, t["_id"], legs=_legs(legs))
            except DeltaError as exc:
                await _set_trade(db, t["_id"], status="closing", close_reason=f"bracket refused on recovery: {exc}")
                await _switch_off(db, st, f"{t['acct']}: bracket refused on recovery ({exc})")
            return
        await _set_trade(db, t["_id"], status="skipped", reason="entry not confirmed by Delta")
        return
    if size == 0:
        # flat on the venue: its bracket (or anyone) closed it
        try:
            await D.cancel_stops(product.id)
        except DeltaError:
            pass
        ex = await _exit_from_fills(t, product, None, None)
        lv = t.get("legs") or {}
        why = "venue stop" if lv.get("stop") and _near(ex["price"], float(lv["stop"]), float(t["fill"])) else \
              "venue target" if lv.get("target") and _near(ex["price"], float(lv["target"]), float(t["fill"])) else "closed on Delta"
        await _record_close(db, t, ex, why, product)
        return
    if (size > 0) != (t["side"] > 0):
        await _switch_off(db, st, f"{product.symbol}: the account's position is opposite to {t['acct']}'s trade; "
                                  "not touched - check Delta")
        return
    reason = None
    if t["status"] == "closing":
        reason = t.get("close_reason") or "closing"
    elif paper is None:
        gone = float(t.get("paper_missing_since") or 0)
        if not gone:
            await _set_trade(db, t["_id"], paper_missing_since=_now())
        elif _now() - gone > MISSING_GRACE_S:
            reason = "the paper trade disappeared"
    elif not paper.get("open"):
        reason = f"paper exit: {paper.get('reason') or 'closed'}"
    elif desk_age > DESK_DEAD_S:
        reason = "the paper desk stopped updating"
    if reason is None:
        mark = float(pos.get("mark") or 0.0)
        u = _pnl(t["side"], float(t["fill"]), mark, abs(size), product.contract_value, float(t.get("entry_fee") or 0.0)) if mark else 0.0
        fields = {"mark": mark, "unrealised_usd": u, "contracts_open": abs(size)}
        if paper is not None:
            fields["paper_missing_since"] = None       # seen again: the grace clock starts over
        await _set_trade(db, t["_id"], **fields)
        return
    try:
        o = await D.market(product.id, abs(size), "sell" if t["side"] > 0 else "buy", reduce_only=True,
                           client_order_id=_cid(t["_id"], "x"))
    except DeltaError as exc:
        await _set_trade(db, t["_id"], status="closing", close_reason=reason)
        await _venue_error(db, st, f"{t['acct']}: close refused ({exc})")
        return
    try:
        await D.cancel_stops(product.id)
    except DeltaError:
        pass
    ex = await _exit_from_fills(t, product, o.get("avg_price") or None, o.get("commission"))
    await _record_close(db, t, ex, reason, product)


async def _manage_live(db, st: dict, t: dict, paper: dict | None, positions: dict, products: dict, desk_age: float,
                       resting: dict | None) -> None:
    """A live trade: with its own stop and target on Delta (from 15 Nov), or one from before whose bracket covers the
    whole position (managed the old way)."""
    if _own(t):
        if resting is None:                     # the resting orders could not be read this cycle: next cycle
            return
        await _manage_own(db, st, t, paper, positions, products[t["product"]], desk_age, resting.get(t["product"], {}))
    else:
        await _manage_bracket(db, st, t, paper, positions, products, desk_age)


# -- each trade's own legs (15 Nov 2026) ---------------------------------------------------------------------------
# Every strategy of a desk may hold a trade at the same time (the owner's choice, 15 Nov). Delta keeps one netted
# position per product and one bracket per position, so each trade carries its own stop and target: standalone stop
# orders of its own size, not reduce-only (one trade's leg may have to open or flip the net position), their ids on
# the trade. A leg that fills ends the trade and the other leg is cancelled. When the desk closes a trade it cancels
# both legs FIRST and then closes at the market only what is still held, so its own order and a leg never both close
# the same contracts. Legs that filled beyond the trade's size (both, in a very fast move) are offset at once. Every
# cycle the account's position is checked against the sum of the desks' trades (_check_books).


def _own(t: dict) -> bool:
    return t.get("protect") == "own"


async def _leg_order(product: Product, side: str, size: int, kind: str, trigger: float, limit: float, cid: str) -> dict:
    """Place one leg; an answer that was lost is looked up by its client id (it may exist without our knowing)."""
    try:
        return await D.stop_order(product, side, size, kind, trigger, limit, client_order_id=cid)
    except DeltaError as exc:
        if not exc.ambiguous:
            raise
        try:
            o = await D.order_by_client_id(cid)
        except DeltaError:
            raise exc from None
        if not o.get("id") or o.get("state") == "cancelled":
            raise
        return {**o, "stop_price_sent": fmt_tick(trigger, product.tick), "limit_price_sent": fmt_tick(limit, product.tick)}


async def _place_legs(db, tid: str, product: Product, side: int, contracts: int, fill: float, stop: float,
                      target: float | None) -> dict:
    """The trade's own stop (and target) on Delta, each saved on the trade as soon as it is placed. Raises DeltaError;
    the caller then closes the trade (a leg already placed is on the trade, so it is cancelled with it). On
    APP_TARGET_PRODUCTS the target is not an order: it is kept as legs["target_app"] for this server to watch."""
    long_ = side > 0
    if (long_ and stop >= fill) or (not long_ and stop <= fill):
        raise DeltaError(f"legs: the stop {stop} is on the wrong side of the fill {fill}")
    if target is not None and ((long_ and target <= fill) or (not long_ and target >= fill)):
        raise DeltaError(f"legs: the target {target} is on the wrong side of the fill {fill}")
    if abs(fill - stop) < 2 * product.tick:
        raise DeltaError("legs: the stop is under two ticks from the fill")
    out = "sell" if long_ else "buy"
    slip = max(abs(fill - stop) * 0.20, 2 * product.tick)     # the stop's limit sits past its trigger (see delta_rest)
    s = await _leg_order(product, out, contracts, "stop_loss_order", stop, stop - slip if long_ else stop + slip,
                         _cid(tid, "s"))
    legs = {"stop": s["stop_price_sent"], "stop_limit": s["limit_price_sent"], "stop_id": s["id"], "target": None,
            "target_id": None}
    await _set_trade(db, tid, legs=legs)
    if target is not None and product.symbol in APP_TARGET_PRODUCTS:
        # 25 Nov 2026: this server takes the target (Delta's 100 open orders a product): one order a trade, its stop
        legs.update(target_app=fmt_tick(target, product.tick))
        await _set_trade(db, tid, legs=legs)
    elif target is not None:
        tp = await _leg_order(product, out, contracts, "take_profit_order", target, target, _cid(tid, "t"))
        legs.update(target=tp["stop_price_sent"], target_id=tp["id"])
        await _set_trade(db, tid, legs=legs)
    return legs


def _leg_kind(o: dict) -> str:
    """"filled" (wholly or partly) | "cancelled" | "resting" | "unknown", from an order read back."""
    s = o.get("state") or ""
    if o.get("filled") or s == "closed":
        return "filled"
    if s == "cancelled":
        return "cancelled"
    if s in ("open", "pending"):
        return "resting"
    return "unknown"


async def _leg(product: Product, oid: str | None, resting: dict) -> tuple[str, dict]:
    """A leg's state: from the cycle's list of resting orders, else read back by its id."""
    if not oid:
        return "none", {}
    if oid in resting:
        o = resting[oid]
        return ("filled" if o.get("filled") else "resting"), o
    try:
        o = await D.order(oid)
    except DeltaError:
        return "unknown", {}
    return _leg_kind(o), o


async def _cancel_leg(product: Product, oid: str) -> tuple[str, dict]:
    """Cancel one leg and say how it ended. Delta refuses to cancel an order that already filled or is gone
    ("open_order_not_found"), so a refusal is answered by reading the order back."""
    try:
        o = await D.cancel_order(product.id, oid)
    except DeltaError:
        try:
            o = await D.order(oid)
        except DeltaError:
            return "unknown", {}
    k = _leg_kind(o)
    if k == "filled" and o.get("state") in ("open", "pending"):
        return "unknown", o                  # partly filled and still resting: not settled yet
    return k, o


async def _market_once(db, st: dict, t: dict, product: Product, size: int, side: str, tag: str) -> dict | None:
    """A market order a trade sends to close ("x") or to offset legs that filled beyond it ("f"), sent once: the
    result is kept on the trade, and an answer that was lost is looked up by its client id before anything is sent
    again. None when it did not go through this cycle."""
    cid = _cid(t["_id"], tag)
    prev = (t.get("orders") or {}).get(tag) or {}
    if prev.get("filled"):
        return prev
    if prev.get("ambiguous"):
        try:
            o = await D.order_by_client_id(cid)
            if o.get("filled"):
                await _set_trade(db, t["_id"], **{f"orders.{tag}": o})
                return o
        except DeltaError:
            pass                                    # not found: it never went through
    try:
        o = await D.market(product.id, size, side, client_order_id=cid)
    except DeltaError as exc:
        await _set_trade(db, t["_id"], **{f"orders.{tag}": {"ambiguous": exc.ambiguous, "error": str(exc)[:200]}})
        if _cap_refusal(exc):                       # Delta's 100 orders full (25 Nov): tried again next pass
            _FULL[product.symbol] = _now()
            logger.warning("[premium live %s] %s: %s, its market order waits for room", _d().key, t["acct"], VENUE_FULL)
            return None
        await _venue_error(db, st, f"{t['acct']}: market order refused ({exc})")
        return None
    await _set_trade(db, t["_id"], **{f"orders.{tag}": o})
    if not o.get("filled"):
        await _venue_error(db, st, f"{t['acct']}: the market order did not fill")
        return None
    return o


async def _close_own(db, st: dict, t: dict, product: Product, reason: str, resting: dict) -> bool:
    """Close a trade that has its own legs: cancel both legs first, close at the market only what is still held, and
    offset at once anything its legs filled beyond its size. True when the trade is closed; False leaves it closing,
    tried again next cycle (nothing more is sent while a leg cannot be settled)."""
    n = int(t.get("contracts") or 0)
    legs = t.get("legs") or {}
    out = "sell" if t["side"] > 0 else "buy"
    if t.get("status") != "closing" or t.get("close_reason") != reason:
        await _set_trade(db, t["_id"], status="closing", close_reason=reason)
    got: list[dict] = []
    for k in ("stop", "target"):
        oid = legs.get(f"{k}_id")
        if not oid:
            continue
        kind, o = await _leg(product, oid, resting)
        if kind in ("resting", "unknown") or (kind == "filled" and o.get("state") in ("open", "pending")):
            kind, o = await _cancel_leg(product, oid)
        if kind in ("resting", "unknown"):
            await _venue_error(db, st, f"{t['acct']}: its {k} on Delta could not be cancelled or read")
            return False
        if kind == "filled":
            got.append(o)
    qty = sum(int(o["filled"]) for o in got)
    value = sum(float(o.get("avg_price") or 0.0) * int(o["filled"]) for o in got)
    fee = sum(float(o.get("commission") or 0.0) for o in got)
    if qty < n:
        o = await _market_once(db, st, t, product, n - qty, out, "x")
        if o is None:
            return False
        qty += int(o["filled"])
        value += float(o.get("avg_price") or 0.0) * int(o["filled"])
        fee += float(o.get("commission") or 0.0)
    extra, extra_pnl = qty - n, 0.0
    if extra > 0:
        # its legs filled more than it held (both, in a very fast move): the overshoot is taken back at once
        o = await _market_once(db, st, t, product, extra, _side(t["side"]), "f")
        if o is None:
            return False
        avg = value / qty
        extra_pnl = round(-t["side"] * (float(o.get("avg_price") or avg) - avg) * extra * product.contract_value
                          - float(o.get("commission") or 0.0), 6)
    price = value / qty if qty else float(t.get("fill") or 0.0)
    await _record_close(db, t, {"price": price, "fee": fee, "basis": "fills"}, reason, product, extra_pnl)
    return True


async def _replace_leg(db, t: dict, product: Product, k: str) -> None:
    """Put back, once, a leg that was cancelled on Delta by someone other than this desk."""
    legs = dict(t.get("legs") or {})
    n, out = int(t["contracts"]), ("sell" if t["side"] > 0 else "buy")
    if k == "stop":
        stop = float(t["stop"])
        slip = max(abs(float(t["fill"]) - stop) * 0.20, 2 * product.tick)
        o = await _leg_order(product, out, n, "stop_loss_order", stop, stop - slip if t["side"] > 0 else stop + slip,
                             _cid(t["_id"], "s2"))
        legs.update(stop_id=o["id"], stop_replaced=True)
    else:
        target = float(t["target"])
        o = await _leg_order(product, out, n, "take_profit_order", target, target, _cid(t["_id"], "t2"))
        legs.update(target_id=o["id"], target_replaced=True)
    await _set_trade(db, t["_id"], legs=legs)


async def _settle_entry(db, st: dict, t: dict, product: Product) -> None:
    """An entry whose answer was lost (or whose record stopped half-way): Delta is asked for it by its client id."""
    if _now() - float(t.get("created_at") or 0) < 60:
        return
    try:
        o = await D.order_by_client_id(_cid(t["_id"]))
    except DeltaError:
        o = None
    if o and o.get("filled"):
        fill = float(o.get("avg_price") or (t.get("plan") or {}).get("price") or 0.0)
        n = int(o["filled"])
        await _set_trade(db, t["_id"], status="open", contracts=n, fill=fill, entry_fee=float(o.get("commission") or 0.0),
                         entry_order=o, opened_at=_now(), recovered=True)
        try:
            await _place_legs(db, t["_id"], product, t["side"], n, fill, float(t["stop"]),
                              float(t["target"]) if t.get("target") else None)
        except DeltaError as exc:
            t = await _tc(db).find_one({"_id": t["_id"]})
            if _cap_refusal(exc):               # Delta's 100 orders full (25 Nov): closed at once, the desk stays on
                await _close_own(db, st, t, product, f"closed at once: {VENUE_FULL} on {product.symbol}, no room "
                                                     "for its stop", {})
                _FULL[product.symbol] = _now()
                return
            await _switch_off(db, st, f"{t['acct']}: its stop or target was refused on recovery ({exc})")
            await _close_own(db, st, t, product, f"stop or target refused on recovery: {exc}", {})
        return
    if (o is not None and not o.get("filled")) or _now() - float(t.get("created_at") or 0) > 300:
        await _set_trade(db, t["_id"], status="skipped", reason="entry not confirmed by Delta")


async def _manage_own(db, st: dict, t: dict, paper: dict | None, positions: dict, product: Product, desk_age: float,
                      resting: dict) -> None:
    """One trade with its own stop and target on Delta."""
    if t["status"] == "entering":
        await _settle_entry(db, st, t, product)
        return
    if t["status"] == "closing":
        await _close_own(db, st, t, product, t.get("close_reason") or "closing", resting)
        return
    legs = t.get("legs") or {}
    state = {k: await _leg(product, legs[f"{k}_id"], resting) for k in ("stop", "target") if legs.get(f"{k}_id")}
    hit = [k for k, (kind, _o) in state.items() if kind == "filled"]
    if hit:
        why = "venue stop and target" if len(hit) > 1 else f"venue {hit[0]}"
        await _close_own(db, st, t, product, why, resting)
        return
    lost = [k for k, (kind, _o) in state.items() if kind == "cancelled"]
    if lost:
        k = lost[0]
        if k == "target" and product.symbol in APP_TARGET_PRODUCTS:
            await _target_to_app(db, t, product)      # 25 Nov: never put back; this server watches it from now
            return
        if legs.get(f"{k}_replaced"):
            await _close_own(db, st, t, product, f"its {k} was cancelled on Delta again", resting)
            return
        try:
            await _replace_leg(db, t, product, k)
        except DeltaError as exc:
            await _close_own(db, st, t, product, f"its {k} was cancelled on Delta and could not be put back ({exc})",
                             resting)
        return
    if legs.get("target_id") and product.symbol in APP_TARGET_PRODUCTS \
            and _CONVERTED.get(_d().key, 0) < CONVERT_PER_PASS:
        # a trade from before 25 Nov: its resting target is handed to this server, freeing its order on Delta
        _CONVERTED[_d().key] = _CONVERTED.get(_d().key, 0) + 1
        kind, _o = await _cancel_leg(product, legs["target_id"])
        if kind == "filled":                        # it filled (wholly or in part) first: the venue target
            await _close_own(db, st, t, product, "venue target", resting)
            return
        if kind == "cancelled":
            await _target_to_app(db, t, product)
            t = await _tc(db).find_one({"_id": t["_id"]}) or t
        # anything else (not read): tried again next pass, its target still resting on Delta meanwhile
    reason = None
    if paper is None:
        gone = float(t.get("paper_missing_since") or 0)
        if not gone:
            await _set_trade(db, t["_id"], paper_missing_since=_now())
        elif _now() - gone > MISSING_GRACE_S:
            reason = "the paper trade disappeared"
    elif not paper.get("open"):
        reason = f"paper exit: {paper.get('reason') or 'closed'}"
    elif desk_age > DESK_DEAD_S:
        reason = "the paper desk stopped updating"
    if reason is None and await _app_target_hit(t, product):
        reason = APP_TARGET_WHY                     # the target this server watches (25 Nov)
    if reason is not None:
        await _close_own(db, st, t, product, reason, resting)
        return
    mark = float((positions.get(product.id) or {}).get("mark") or 0.0)
    if not mark:                                   # the net position can be flat while trades are open
        try:
            mark = float((await D.ticker(product.symbol))["mark"])
        except DeltaError:
            mark = 0.0
    n = int(t.get("contracts") or 0)
    u = _pnl(t["side"], float(t["fill"]), mark, n, product.contract_value, float(t.get("entry_fee") or 0.0)) if mark else 0.0
    fields = {"mark": mark, "unrealised_usd": u, "contracts_open": n}
    if paper is not None:
        fields["paper_missing_since"] = None
    await _set_trade(db, t["_id"], **fields)


async def _target_to_app(db, t: dict, product: Product) -> None:
    """The trade's target becomes this server's to watch, with no target order on Delta any more (25 Nov 2026)."""
    legs = dict(t.get("legs") or {})
    level = legs.get("target") or (fmt_tick(float(t["target"]), product.tick) if t.get("target") else None)
    legs.update(target=None, target_id=None, target_app=level, target_app_at=_now())
    await _set_trade(db, t["_id"], legs=legs)
    t["legs"] = legs
    logger.info("[premium live %s] %s: its target %s is watched by the app, no longer an order on Delta",
                _d().key, t.get("acct"), level)


async def _target_quote(product: Product) -> dict | None:
    """One quote a product per TARGET_QUOTE_TTL_S, shared by the desks' target checks; None when Delta gives none."""
    q = _TQ.get(product.symbol)
    if q is not None and _now() - float(q["read_at"]) <= TARGET_QUOTE_TTL_S:
        return q
    try:
        q = {**(await D.ticker(product.symbol)), "read_at": _now()}
    except DeltaError:
        return None
    _TQ[product.symbol] = q
    return q


async def _app_target_hit(t: dict, product: Product) -> bool:
    """Has the price reached the target this server watches for the trade (25 Nov 2026)? A long's when the bid is
    at or above it, a short's when the ask is at or below it: the prices its market close fills at."""
    level = (t.get("legs") or {}).get("target_app")
    if not level:
        return False
    q = await _target_quote(product)
    if q is None:                                   # no quote this pass: the next pass looks again
        return False
    return q["bid"] >= float(level) if int(t["side"]) > 0 else q["ask"] <= float(level)


async def _expected_net(db) -> dict[str, int]:
    """Contracts the desks' live trades hold, signed, by product symbol, across every desk: what the account's netted
    positions should be. Entries still in flight are not counted."""
    out: dict[str, int] = {}
    for d in DESKS.values():
        async for t in getattr(db, d.trades_coll).find({"mode": "live", "status": {"$in": ["open", "closing"]}},
                                                       {"product": 1, "side": 1, "contracts": 1}):
            out[t["product"]] = out.get(t["product"], 0) + int(t["side"]) * int(t.get("contracts") or 0)
    return out


async def _legacy_products(db) -> set[str]:
    """Products where a trade from before 15 Nov is open (its one bracket covers the whole position): no new entry
    there until it closes."""
    out = set()
    for d in DESKS.values():
        async for t in getattr(db, d.trades_coll).find({"mode": "live", "status": {"$in": ["entering", "open", "closing"]}},
                                                       {"product": 1, "protect": 1}):
            if t.get("protect") != "own":
                out.add(t["product"])
    return out


async def _in_flight_elsewhere(db) -> set[str]:
    """This desk's products on which ANOTHER desk has a live trade in flight (entering: its answer lost and being
    looked for; closing: its close sent, not yet recorded). The account may already differ from every desk's records
    there, so a mismatch on such a product only makes entries wait (24 Nov 2026, two books on XAUTUSD). Empty for
    desks that share no product (the bitcoin and gold desks)."""
    mine = set(_d().products)
    out: set[str] = set()
    for d in DESKS.values():
        if d.key == _d().key or not mine & set(d.products):
            continue
        async for t in getattr(db, d.trades_coll).find({"mode": "live", "status": {"$in": ["entering", "closing"]}},
                                                       {"product": 1}):
            if t.get("product") in mine:
                out.add(t["product"])
    return out


async def _check_books(db, st: dict, products: dict, positions: dict) -> dict[str, bool]:
    """Does the account's position on each of this desk's products equal the sum of the desks' trades on it? A
    mismatch can be Delta's lag (its positions can take up to 10 s) or a trade in flight, so new entries just wait;
    seen on three checks in a row (about a minute), the desk switches off and touches nothing: someone looks at Delta."""
    want = await _expected_net(db)
    flight = await _in_flight_elsewhere(db)        # another desk's trade in flight: wait, never counted (24 Nov)
    out, bad = {}, []
    for sym in _d().products:
        p = products.get(sym)
        if p is None:
            continue
        have = int((positions.get(p.id) or {}).get("size") or 0)
        out[sym] = have == want.get(sym, 0)
        if not out[sym] and sym not in flight:
            bad.append(f"{sym}: the account holds {have:+d} contracts, the trades {want.get(sym, 0):+d}")
    n = int(st.get("mismatch_checks") or 0) + 1 if bad else 0
    if n != int(st.get("mismatch_checks") or 0):
        st["mismatch_checks"] = n
        await _set_state(db, mismatch_checks=n, mismatch="; ".join(bad) or None)
    if bad and n >= ERRORS_TO_STOP and st.get("mode") == "live":
        await _switch_off(db, st, f"the account's position has not matched this desk's trades for {n} checks "
                                  f"({'; '.join(bad)}): nothing was touched - check Delta")
    return out


def _is_lev(v) -> bool:
    try:
        return int(round(float(v))) == LEVERAGE
    except (TypeError, ValueError):
        return False


async def _confirm_leverage(db, st: dict, products: dict) -> dict[str, bool]:
    """Is each of this desk's products at LEVERAGE on Delta? Going live sets it on every product the desk has then
    (_set_mode_one) and the state keeps it; a product that joins a desk already live (22 Nov 2026: ether on the bitcoin
    desk) never went through that, so it is read here before its first entry and, if Delta does not already say
    LEVERAGE, set and read back, once. A product not confirmed takes no new entry this pass (its signals wait); a
    failed call counts as a venue error, and the next pass tries again."""
    cached = st.get("products") or {}
    out: dict[str, bool] = {}
    for sym in _d().products:
        p = products.get(sym)
        if p is None:
            continue
        if _is_lev((cached.get(sym) or {}).get("leverage")):
            out[sym] = True
            continue
        try:
            got = await D.leverage(p.id)
            if not _is_lev(got):
                await D.set_leverage(p.id, LEVERAGE)
                got = await D.leverage(p.id)
        except DeltaError as exc:
            await _venue_error(db, st, f"{sym}: its leverage could not be confirmed at {LEVERAGE}x ({exc})")
            out[sym] = False
            continue
        out[sym] = _is_lev(got)
        if out[sym]:
            cached.setdefault(sym, {})["leverage"] = LEVERAGE
            st["products"] = cached
            await _set_state(db, products=cached)
            logger.info("[premium live %s] %s leverage confirmed at %sx before its first entry", _d().key, sym, LEVERAGE)
        else:
            await _set_state(db, last_error=f"{sym}: leverage reads {got}x, not {LEVERAGE}x: its signals wait",
                             last_error_at=_now())
    return out


def _near(px: float, level: float, entry: float) -> bool:
    return abs(px - level) <= max(abs(entry - level) * 0.35, 1e-9)


def _legs(legs: dict) -> dict:
    sl, tp = legs.get("stop_loss_order") or {}, legs.get("take_profit_order") or {}
    return {"stop": sl.get("stop_price"), "stop_limit": sl.get("limit_price"), "target": tp.get("stop_price")}


async def _manage_shadow(db, t: dict, paper: dict | None, desk_age: float, products: dict) -> None:
    product = products[t["product"]]
    reason, at = None, None
    if paper is None:
        gone = float(t.get("paper_missing_since") or 0)
        if not gone:
            await _set_trade(db, t["_id"], paper_missing_since=_now())
            return
        if _now() - gone > MISSING_GRACE_S:
            reason = "the paper trade disappeared"
    elif not paper.get("open"):
        reason = f"paper exit: {paper.get('reason') or 'closed'}"
        if paper.get("reason") in ("stop", "target", "be_stop", "stop_gap") and paper.get("exit"):
            at = float(paper["exit"])           # a venue bracket would have filled about there
    elif desk_age > DESK_DEAD_S:
        reason = "the paper desk stopped updating"
    if reason is None and t["status"] != "closing":
        try:
            q = await D.ticker(product.symbol)
            mark = q["bid"] if t["side"] > 0 else q["ask"]
            u = _pnl(t["side"], float(t["fill"]), mark, int(t["contracts"]), product.contract_value,
                     float(t.get("entry_fee") or 0.0))
            fields = {"mark": mark, "unrealised_usd": u}
            if paper is not None:
                fields["paper_missing_since"] = None
            await _set_trade(db, t["_id"], **fields)
        except DeltaError:
            pass
        return
    if at is None:
        try:
            q = await D.ticker(product.symbol)
            at = q["bid"] if t["side"] > 0 else q["ask"]
        except DeltaError:
            return
    ex = {"price": at, "fee": _fee(at * int(t["contracts"]) * product.contract_value, product.taker_rate), "basis": "simulated"}
    await _record_close(db, t, ex, reason or "closing", product)


# -- entries -------------------------------------------------------------------------------------------


_WAITING: dict[str, dict[str, dict]] = {}   # desk -> paper trade id -> why its copy waits (follow_all desks; memory only)


async def _enter(db, st: dict, pick: Pick, paper: dict, products: dict, busy: set, day_pnl: float,
                 desk_age: float, cache: dict | None = None) -> str:
    """Decide one new paper trade, once. Returns what happened, for the cycle's report. On a desk that follows every
    paper trade (follow_all), a copy that cannot go in yet WAITS instead (nothing is recorded, it is tried again next
    cycle, and the reason is kept in _WAITING for the page): see FOLLOW EVERY PAPER TRADE."""
    tid, mode = paper["_id"], st["mode"]
    follow = _d().follow_all
    waits = _WAITING.setdefault(_d().key, {})
    side = 1 if int(paper.get("side") or 0) > 0 else -1
    stop = float(paper.get("stop") or 0.0)
    target = float(paper["target"]) if paper.get("target") else None
    entry = float(paper.get("entry") or 0.0)
    base = {"_id": tid, "acct": pick.acct, "mkt": pick.mkt, "product": pick.product, "name": pick.name, "mode": mode,
            "side": side, "paper_entry": entry, "paper_entry_t": paper.get("entry_t"), "stop": stop, "target": target,
            "setup": paper.get("setup"), "day": _day(), "created_at": _now(), "protect": "own"}

    async def skip(why: str, **extra) -> str:
        waits.pop(tid, None)
        try:
            await _tc(db).insert_one({**base, **extra, "status": "skipped", "reason": why})
        except Exception:  # noqa: BLE001 - decided by an earlier pass
            pass
        return f"skipped: {why}"

    async def hold(why: str, **extra) -> str:
        """Not yet: a follow_all desk waits and tries again next cycle; any other desk skips, as it always has."""
        if not follow:
            return await skip(why, **extra)
        waits[tid] = {"why": why, "at": _now()}
        return f"waiting: {why}"

    cfg = _cfg(st, pick)
    if not cfg["on"]:
        # switched off by the owner (23 Nov): no new real trade. A follow_all desk keeps its open paper trades waiting,
        # so switching the strategy back on copies what is still open (as switching the desk on does).
        if not paper.get("open"):
            return await skip("closed on paper while this strategy was switched off")
        return await hold("this strategy is switched off: no new real trade until it is switched on")
    lag = _now() - float(paper.get("entry_t") or 0)
    if not paper.get("open"):
        return await skip("closed on paper before it could be copied")
    if not follow and lag > _d().max_lag_s:
        return await skip(f"seen {lag / 60:.0f} min after its entry (limit {_d().max_lag_s // 60})", lag_s=round(lag))
    guard = follow and stop <= 0 and entry > 0       # no stop on paper: the copy carries a protective one (19 Nov)
    if (stop <= 0 and not guard) or entry <= 0:
        return await skip("no stop on the paper trade")
    if not follow and day_pnl <= -_d().daily_stop_usd:    # a follow_all desk has no daily stop (the owner, 19 Nov)
        return await skip(f"daily loss stop reached ({day_pnl:+.2f} USD today)")
    if desk_age > DESK_STALE_S:
        who = {GOLD_H1: "the Gold Desk", GOLD_SF: "the Gold Desk's Strategy Factory tab"}.get(paper.get("src"),
                                                                                           "the paper desk")
        return await hold(f"{who} has not updated for over 20 minutes")
    product = products[pick.product]
    if mode == "live" and pick.product in busy:
        return await hold(f"{pick.product} holds an older trade whose one bracket covers the whole position")
    cache = {} if cache is None else cache          # one cycle's quotes (and a failed wallet read), shared by its entries
    try:
        q = cache.get(("quote", product.symbol)) or await D.ticker(product.symbol)
    except DeltaError as exc:
        return await hold(f"no quote ({exc})")
    cache[("quote", product.symbol)] = q
    px = q["ask"] if side > 0 else q["bid"]
    if guard:
        stop = round(px * (1 - GUARD_STOP_FRAC) if side > 0 else px * (1 + GUARD_STOP_FRAC), 6)
        base.update(stop=stop, paper_stop=None, guard_stop=True)
    elif follow and side * (px - stop) > MAX_STOP_FRAC * px:
        # with no cap on what one contract may lose, the liquidation distance is the limit: pulled in to 7%
        base.update(paper_stop=stop, stop_capped=True)
        stop = round(px * (1 - MAX_STOP_FRAC) if side > 0 else px * (1 + MAX_STOP_FRAC), 6)
        base["stop"] = stop
    lo, hi = (stop, target if target else math.inf) if side > 0 else (target if target else 0.0, stop)
    if follow:
        # however late, however far: only the price must still sit inside both levels, with room for the fill
        pad = max(FOLLOW_PAD_TICKS * product.tick, FOLLOW_PAD_FRAC * abs((px if guard else entry) - stop))
        if not lo + pad < px < hi - pad:
            return await hold(f"price {px} is not inside the stop and the target with room to fill "
                              f"({pad:.2f} from each)", price=px)
    else:
        if not lo < px < hi:
            return await skip(f"price {px} is no longer between the stop and the target", price=px)
        if abs(px - entry) > DRIFT_FRAC * abs(entry - stop):
            return await skip(f"price moved {abs(px - entry) / abs(entry - stop):.0%} of the risk away from the paper "
                              "entry", price=px)
    if follow:
        base["late_s"] = round(lag)
    sizing = _sizing(st)
    one = abs(px - stop) * product.contract_value           # what a single contract loses at the stop
    lots = cfg["contracts"]
    if sizing == "min":         # the strategy's own lots: one contract (the smallest order) unless the owner chose more
        #                         (23 Nov); the desk's own risk caps it, except on a follow_all desk (19 Nov)
        if one * lots > _d().risk_usd and not follow:
            what = "one contract" if lots == 1 else f"{lots} contracts"
            return await skip(f"{what} would lose ${one * lots:.2f} at its stop, more than the ${_d().risk_usd:.2f} cap "
                              "a trade", price=px)
        risk, by_risk = one * lots, lots
    else:
        risk = _risk(st)
        by_risk = math.floor(risk / one)
    by_cap = math.floor(MAX_NOTIONAL_USD / (px * product.contract_value))
    contracts = min(by_risk, by_cap)
    if contracts < 1:
        why = (f"one contract would lose ${one:.2f} at its stop, more than the ${risk:.2f} a trade you set" if by_risk < 1
               else "under one contract within the notional cap")
        return await skip(why, price=px)
    notional = contracts * product.contract_value * px
    plan = {"price": px, "contracts": contracts, "risk_usd": round(one * contracts, 6), "risk_set_usd": round(risk, 6),
            "sizing": sizing, "notional_usd": round(notional, 2), "margin_usd": round(notional / LEVERAGE, 2),
            "capped": by_cap < by_risk, "lots": lots if sizing == "min" else None}

    if mode == "shadow":
        waits.pop(tid, None)
        fee = _fee(notional, product.taker_rate)
        await _tc(db).insert_one({**base, "status": "open", "plan": plan, "contracts": contracts, "fill": px,
                                               "entry_fee": round(fee, 6), "opened_at": _now(), "unrealised_usd": -fee})
        return f"shadow entry: {contracts} {pick.product} at {px}"

    if _venue_full(product.symbol):
        # Delta refused an order here for its 100-order limit and no trade on the product has closed since (25 Nov):
        # skipped and recorded without sending; the desk stays on
        return await skip(f"{VENUE_FULL} on {product.symbol}", price=px)
    if cache.get("wallet_down"):                     # already failed this cycle: one venue error a cycle, not one a copy
        return await hold("could not read the wallet")
    w = cache.get("wallet")
    if w is None:                                    # read once a pass; each entry then takes its margin off it
        try:
            w = dict(await D.wallet())
        except DeltaError as exc:
            cache["wallet_down"] = True
            await _venue_error(db, st, f"wallet read failed ({exc})")
            return await hold("could not read the wallet")
        cache["wallet"] = w
    if w["available"] < plan["margin_usd"] * MARGIN_BUFFER:
        return await hold(f"not enough free balance (${w['available']:.2f} for ${plan['margin_usd']:.2f} of margin)")
    waits.pop(tid, None)
    w["available"] -= plan["margin_usd"]
    await _tc(db).insert_one({**base, "status": "entering", "plan": plan, "contracts": contracts})
    try:
        o = await D.market(product.id, contracts, _side(side), client_order_id=_cid(tid))
    except DeltaError as exc:
        if exc.ambiguous:
            # the order may have filled: it stays "entering", and the next cycles ask Delta for it by its client id
            await _set_trade(db, tid, reason=f"entry answer lost ({exc}); checking the account")
            await _venue_error(db, st, f"{pick.acct}: entry answer lost ({exc})")
            return f"error: entry answer lost ({exc})"
        if _cap_refusal(exc):
            # Delta's 100 open orders on the product (25 Nov): skipped and recorded, not a venue error; the desk stays on
            _FULL[product.symbol] = _now()
            await _set_trade(db, tid, status="skipped", reason=f"{VENUE_FULL} on {product.symbol}", adoptable=False)
            logger.warning("[premium live %s] %s: %s on %s, skipped", _d().key, pick.acct, VENUE_FULL, product.symbol)
            return f"skipped: {VENUE_FULL}"
        await _set_trade(db, tid, status="error", reason=f"entry refused: {exc}", adoptable=False)
        await _venue_error(db, st, f"{pick.acct}: entry refused ({exc})")
        return f"error: entry refused ({exc})"
    if o["filled"] < 1:
        await _set_trade(db, tid, status="skipped", reason="the market order did not fill", entry_order=o)
        return "skipped: not filled"
    fill = float(o["avg_price"] or px)
    await _set_trade(db, tid, contracts=o["filled"], fill=fill, entry_fee=float(o.get("commission") or 0.0), entry_order=o,
                     opened_at=_now())
    try:
        await _place_legs(db, tid, product, side, int(o["filled"]), fill, stop, target)
    except DeltaError as exc:
        if _cap_refusal(exc):
            # Delta's 100 open orders on the product were full by the time its stop went in (25 Nov): out at once,
            # as ever (never unprotected), and the desk stays on
            t = await _tc(db).find_one({"_id": tid})
            done = await _close_own(db, st, t, product, f"closed at once: {VENUE_FULL} on {product.symbol}, no room "
                                                        "for its stop", {})
            _FULL[product.symbol] = _now()
            logger.warning("[premium live %s] %s: %s, no room for its stop; closed at once", _d().key, pick.acct,
                           VENUE_FULL)
            return f"skipped: {VENUE_FULL}, no room for its stop; " + ("closed at once" if done else
                                                                      "the close is retried every cycle")
        # never left unprotected: out at once, and the desk stops until someone looks
        await _switch_off(db, st, f"{pick.acct} {pick.product}: its stop or target was refused ({exc}); the trade was closed")
        t = await _tc(db).find_one({"_id": tid})
        done = await _close_own(db, st, t, product, f"stop or target refused, closed at once: {exc}", {})
        return f"error: stop or target refused ({exc}); " + ("closed at once" if done else "the close is retried every cycle")
    await _set_trade(db, tid, status="open", unrealised_usd=-float(o.get("commission") or 0.0))
    st["errors_in_row"] = 0
    await _set_state(db, errors_in_row=0)
    return f"live entry: {o['filled']} {pick.product} at {fill}"


# -- the cycle -----------------------------------------------------------------------------------------

_LOCKS: dict[str, asyncio.Lock] = {k: asyncio.Lock() for k in DESKS}


def _entries_blocked() -> bool:
    """True inside the manage-only pass Main Control runs while this module is OFF and a trade is still open."""
    try:
        from app.services import desk_switches
        return bool(desk_switches.entries_blocked())
    except Exception:  # noqa: BLE001 - never let the switch stop a pass that manages real trades
        return False


async def _cycle_one() -> dict:
    """One pass of the current desk."""
    db = _db()
    if db is None:
        return {"error": "the paper desk's database is not configured on this server"}
    async with _LOCKS[_d().key]:
        st = await _state(db)
        await _set_state(db, last_cycle_at=_now())
        _CONVERTED[_d().key] = 0                    # targets handed to this server this pass (25 Nov)
        out: dict = {"mode": st["mode"], "managed": [], "entered": []}
        # Main Control OFF with a trade still open somewhere: this pass only manages, like mode off (see MAIN CONTROL)
        blocked = _entries_blocked()
        if blocked:
            out["main_control"] = "off: managing open trades only"
        open_rows = [t async for t in _tc(db).find({"status": {"$in": list(OPEN_STATUSES)}})]
        if (st["mode"] == "off" or blocked) and not open_rows:
            return out
        try:
            products = await _products(db, st, {t["product"] for t in open_rows})
        except DeltaError as exc:
            await _venue_error(db, st, f"product specs unavailable ({exc})")
            return {**out, "error": str(exc)}
        desk_age = await _desk_age(db)
        since, held = float(st.get("since") or _now()), [t["_id"] for t in open_rows]
        follow = _d().follow_all
        waits = _WAITING.setdefault(_d().key, {})
        want = held + [i for i in waits if i not in held]   # a waiting copy is read even once it closes on paper
        paper = await _paper(db, since, want)
        h1_age, h1_ok = float("inf"), True                 # the Gold Desk's H1 positions: the second source
        if _h1_picks() or any(is_h1(i) for i in want):
            try:
                paper.update(await _paper_h1(since, want))
                h1_age = await _h1_age()
            except Exception as exc:  # noqa: BLE001 - its trades wait for the next good read, never closed for this
                h1_ok = False
                out["gold_desk"] = f"the Gold Desk's H1 positions could not be read ({str(exc)[:120]}): its trades wait"
                logger.warning("[premium live] the Gold Desk's H1 positions could not be read", exc_info=True)
        sf_age, sf_ok = float("inf"), True                 # the Gold Desk's Strategy Factory tab: the third source
        if _sf_picks() or any(is_sf(i) for i in want):
            try:
                paper.update(await _paper_sf(since, want))
                sf_age = await _sf_age()
            except Exception as exc:  # noqa: BLE001 - its trades wait for the next good read, never closed for this
                sf_ok = False
                out["factory"] = (f"the Gold Desk's Strategy Factory positions could not be read ({str(exc)[:120]}): "
                                  "its trades wait")
                logger.warning("[premium live] the Gold Desk's Strategy Factory positions could not be read", exc_info=True)

        def unread(i: str) -> bool:                         # a source that could not be read this pass
            return (is_h1(i) and not h1_ok) or (is_sf(i) and not sf_ok)

        def age_of(i: str, src: str | None = None) -> float:
            if is_h1(i) or src == GOLD_H1:
                return h1_age
            return sf_age if (is_sf(i) or src == GOLD_SF) else desk_age
        live_rows = [t for t in open_rows if t.get("mode") == "live"]
        positions: dict | None = None
        resting: dict | None = {}
        if st["mode"] == "live" or live_rows:
            try:
                positions = await D.positions()
            except DeltaError as exc:
                await _venue_error(db, st, f"positions unavailable ({exc})")
                positions = None
            else:
                await _venue_ok(db, st)                     # errors count only in a row
            if positions is not None and _now() - float(st.get("wallet_at") or 0) > 300:
                try:
                    await _set_state(db, wallet=await D.wallet(), wallet_at=_now())
                except DeltaError:
                    pass
            try:                                            # the resting legs of the trades that carry their own
                for sym in sorted({t["product"] for t in live_rows if _own(t)}):
                    resting[sym] = await D.open_orders(products[sym].id)
            except DeltaError as exc:
                await _venue_error(db, st, f"resting orders unavailable ({exc})")
                resting = None
        for t in open_rows:
            if unread(t["_id"]) and t.get("status") == "open":
                # unread, not gone: its stop rests on Delta until the next pass, and a target this server watches
                # (25 Nov) is still watched
                if t.get("mode") == "live" and positions is not None and resting is not None and _own(t) \
                        and await _app_target_hit(t, products[t["product"]]):
                    await _close_own(db, st, t, products[t["product"]], APP_TARGET_WHY, resting.get(t["product"], {}))
                    out["managed"].append(t["_id"])
                continue
            age = age_of(t["_id"])
            if t.get("mode") == "live":
                if positions is not None:
                    await _manage_live(db, st, t, paper.get(t["_id"]), positions, products, age, resting)
            else:
                await _manage_shadow(db, t, paper.get(t["_id"]), age, products)
            out["managed"].append(t["_id"])
        if st["mode"] == "off" or blocked or (st["mode"] == "live" and positions is None):
            return out
        decided = {t["_id"] async for t in _tc(db).find({"_id": {"$in": list(paper)}}, {"_id": 1})}
        books: dict[str, bool] = {}
        lev: dict[str, bool] = {}
        busy: set = set()
        if st["mode"] == "live":
            try:
                positions = await D.positions()
            except DeltaError as exc:
                await _venue_error(db, st, f"positions unavailable ({exc})")
                return out
            books = await _check_books(db, st, products, positions)
            if st["mode"] != "live":                        # the books check switched the desk off
                return out
            lev = await _confirm_leverage(db, st, products)  # a product that joined after going live (22 Nov)
            if st["mode"] != "live":
                return out
            busy = await _legacy_products(db)
        day_pnl = await _day_pnl(db, st["mode"], positions)
        for tid in [i for i in waits if i in decided or (i not in paper and not unread(i))]:
            waits.pop(tid, None)                            # decided elsewhere, or gone from the paper desk
        cache: dict = {}                                    # this pass's quotes, shared by its entries
        for tid, p in sorted(paper.items(), key=lambda kv: kv[1].get("entry_t") or 0):
            if tid in decided:
                continue
            if float(p.get("entry_t") or 0) < float(st.get("since") or 0) and not (
                    follow and (p.get("open") or tid in waits)):
                continue                    # from before the switch-on: only a follow_all desk takes it, while open
            if st["mode"] not in ("shadow", "live"):
                break
            pk = _d().pick.get((p["acct"], p["mkt"]))
            if pk is None:                      # a trade from before a re-pick: managed above, never entered again
                continue
            if st["mode"] == "live" and not books.get(pk.product, False):
                continue                        # the account does not match the trades yet: wait, undecided
            if st["mode"] == "live" and not lev.get(pk.product, False):
                if follow:                      # its leverage is not confirmed yet: wait, undecided (the page says why)
                    waits[tid] = {"why": f"{pk.product}'s leverage is not yet confirmed at {LEVERAGE}x", "at": _now()}
                continue
            res = await _enter(db, st, pk, p, products, busy, day_pnl, age_of(tid, p.get("src")), cache)
            if res.startswith("waiting:"):
                out["waiting"] = out.get("waiting", 0) + 1     # counted, not listed: the loop logs only real decisions
            else:
                out["entered"].append({"id": tid, "result": res})
        return out


_PRIORITY_SENT: tuple[list[str], float] | None = None


async def _publish_priority() -> None:
    """Name the books these desks copy to the paper desk (premium_meta 'live_priority', "ACCT|MARKET"). Its bitcoin pass
    runs them first, right after it reads new candles, so their trades reach these desks minutes sooner. Written after
    a restart, when the picks change and every PRIORITY_REFRESH_S; a failure is only logged (only speed depends on it)."""
    global _PRIORITY_SENT
    books = sorted({f"{p.acct}|{p.mkt}" for d in DESKS.values() for p in d.picks if p.src == PREMIUM})
    if _PRIORITY_SENT and _PRIORITY_SENT[0] == books and _now() - _PRIORITY_SENT[1] < PRIORITY_REFRESH_S:
        return
    db = _db()
    if db is None:
        return
    try:
        await db.premium_meta.update_one({"_id": "live_priority"}, {"$set": {"books": books, "at": _now(),
                                                                             "by": "premium_live"}}, upsert=True)
        _PRIORITY_SENT = (books, _now())
    except Exception:  # noqa: BLE001
        logger.warning("[premium live] could not name the priority books to the paper desk", exc_info=True)


async def cycle(desk: str | None = None) -> dict:
    """One pass of one desk (its report), or of every desk when none is named ({desk: report})."""
    if desk is not None:
        with _use(desk):
            return await _cycle_one()
    out = {}
    for key in DESKS:
        try:
            with _use(key):
                out[key] = await _cycle_one()
        except Exception as exc:  # noqa: BLE001 - one desk's failure must not stop the other
            logger.warning("[premium live %s] cycle failed", key, exc_info=True)
            out[key] = {"error": f"cycle failed: {exc}"}
    await _publish_priority()
    return out


async def loop() -> None:
    """Every TICK_S seconds, around the clock, every desk in turn. Started by the premium routes' startup hook.

    Through Main Control's gate: ON runs the pass as always; OFF with a trade open runs it manage-only; OFF and flat
    skips it (an empty report). The gate fails open: a switch it cannot read counts as ON, and a gate that cannot even
    be loaded leaves the loop running ungated rather than leaving open trades unmanaged."""
    try:
        from app.services import desk_switches
        gate = desk_switches.gated
    except Exception:  # noqa: BLE001
        logger.exception("[premium live] Main Control unavailable: the desks run without its switch")
        gate = None
    await asyncio.sleep(60)
    while True:
        try:
            r = await (gate(MODULE, cycle) if gate is not None else cycle())
            for key, rep_ in r.items():
                if rep_.get("entered") or rep_.get("error"):
                    logger.info("[premium live %s] %s", key, rep_)
        except Exception:  # noqa: BLE001 - the loop must outlive any one bad cycle
            logger.warning("[premium live] cycle failed", exc_info=True)
        await asyncio.sleep(TICK_S)


# -- the owner's controls ------------------------------------------------------------------------------


def _pin_ok(pin: str | None) -> bool | None:
    """True / False, or None when no PIN is set on the server."""
    s = DR.secrets()
    want, salt = s.get("LIVE_ARM_PIN_SHA256"), s.get("LIVE_ARM_SALT", "")
    if not want:
        return None
    got = hashlib.sha256((salt + (pin or "")).encode()).hexdigest()
    return hmac.compare_digest(got, want)


async def _check_pin(db, st: dict, pin: str | None) -> str | None:
    """None if the PIN is right; otherwise why not (wrong PINs are counted and lock it for the hour). None at once when
    no PIN is required (REQUIRE_PIN off: the owner's choice on 15 Nov)."""
    if not REQUIRE_PIN:
        return None
    fails = [f for f in (st.get("pin_fails") or []) if _now() - float(f) < 3600]
    if len(fails) >= PIN_TRIES:
        return "too many wrong PINs: locked for an hour"
    ok = _pin_ok(pin)
    if ok is None:
        return "no PIN is set on the server (the deploy script sets it)"
    if not ok:
        await _set_state(db, pin_fails=fails + [_now()])
        return f"wrong PIN ({PIN_TRIES - len(fails) - 1} tries left this hour)"
    if fails:
        await _set_state(db, pin_fails=[])
    return None


async def _holders(db, sym: str) -> list[str]:
    """The desks' open live trades on one product, as the page names them ("NJ-47 short 1")."""
    out = []
    for d in DESKS.values():
        async for t in getattr(db, d.trades_coll).find({"mode": "live", "status": {"$in": ["open", "closing"]},
                                                        "product": sym}, {"acct": 1, "side": 1, "contracts": 1}):
            out.append(f"{t.get('acct')} {'long' if int(t['side']) > 0 else 'short'} {int(t.get('contracts') or 0)}")
    return out


async def _mismatch_why(db, sym: str, have: int, need: int) -> str:
    """Why going live is refused on one product, and the order on Delta that makes the account match. 26 Nov 2026: the
    refusal said "close it on Delta first" whatever the numbers; the account held 14 hand-bought BTCUSD beside the
    desk's own short of 1, the owner closed the whole position, and the refusal stayed (account 0, trades -1)."""
    if need == 0:
        return f"{sym}: the account holds {have:+d} contracts and the desks' trades none: close those {abs(have)} on Delta"
    diff = need - have
    names = await _holders(db, sym)
    told = f" ({', '.join(names[:6])}{', ...' if len(names) > 6 else ''})" if names else ""
    fix = f"{'buy' if diff > 0 else 'sell'} {abs(diff)} {sym} on Delta"
    if have == 0:
        return f"{sym}: the account holds none, the desks' open trades {need:+d}{told}: {fix} to put them back"
    return (f"{sym}: the account holds {have:+d} contracts, the desks' open trades {need:+d}{told}: {fix} to make them match "
            f"(closing the whole position would close the trades' own contracts too)")


async def _set_mode_one(mode: str, pin: str | None = None, confirm: str | None = None) -> dict:
    db = _db()
    if db is None:
        return {"ok": False, "why": "the paper desk's database is not configured on this server"}
    if mode not in ("off", "shadow", "live"):
        return {"ok": False, "why": f"unknown mode {mode!r}"}
    st = await _state(db)
    if mode in ("off", "shadow"):
        fields = {"mode": mode, "switched_off": None}
        if mode == "shadow" and st.get("mode") != "shadow":
            fields["since"] = _now()
        await _set_state(db, **fields)
        return {"ok": True, "mode": mode}
    why = await _check_pin(db, st, pin)
    if why:
        return {"ok": False, "why": why}
    if (confirm or "").strip().upper() != CONFIRM:
        return {"ok": False, "why": f"type {CONFIRM} to confirm real orders"}
    if not DR.configured():
        return {"ok": False, "why": "Delta API keys are not set on the server (the deploy script sets them)"}
    try:
        products = await _products(db, st)
        w = await D.wallet()
        positions = await D.positions()
        lev = {}
        for sym, p in products.items():
            read = await D.leverage(p.id)
            if not _is_lev(read):        # set only when needed (24 Nov: another book may hold this product's positions)
                got = await D.set_leverage(p.id, LEVERAGE)
                read = await D.leverage(p.id) or got
            if not _is_lev(read):
                return {"ok": False, "why": f"{sym}: leverage reads {read}x, not {LEVERAGE}x"}
            lev[sym] = LEVERAGE
    except DeltaError as exc:
        return {"ok": False, "why": f"Delta refused the check: {exc}"}
    want = await _expected_net(db)
    why = [await _mismatch_why(db, sym, int((positions.get(p.id) or {}).get("size") or 0), want.get(sym, 0))
           for sym, p in products.items() if int((positions.get(p.id) or {}).get("size") or 0) != want.get(sym, 0)]
    if why:
        return {"ok": False, "why": "the account's position does not match the desks' trades, so the desk stays off: "
                                    + "; ".join(why)}
    cached = st.get("products") or {}
    for sym in lev:
        cached.setdefault(sym, {})["leverage"] = lev[sym]
    await _set_state(db, mode="live", since=_now(), armed_at=_now(), errors_in_row=0, switched_off=None,
                     mismatch_checks=0, mismatch=None, products=cached, wallet=w, wallet_at=_now())
    return {"ok": True, "mode": "live", "wallet": w, "leverage": lev}


async def _flatten_one(pin: str | None = None) -> dict:
    """Close every open real position this desk holds, now, and switch it off."""
    db = _db()
    if db is None:
        return {"ok": False, "why": "the paper desk's database is not configured on this server"}
    st = await _state(db)
    why = await _check_pin(db, st, pin)
    if why:
        return {"ok": False, "why": why}
    await _set_state(db, mode="off", switched_off="flattened by the owner")
    n = 0
    async for t in _tc(db).find({"status": {"$in": ["open", "entering"]}}):
        await _set_trade(db, t["_id"], status="closing", close_reason="flattened by the owner")
        n += 1
    r = await _cycle_one()
    return {"ok": True, "closing": n, "cycle": r}


async def set_mode(mode: str, pin: str | None = None, confirm: str | None = None, desk: str = "gold") -> dict:
    """Switch one desk (the gold desk unless named). Going live needs the PIN and the words REAL MONEY."""
    if desk not in DESKS:
        return {"ok": False, "why": f"unknown desk {desk!r}"}
    with _use(desk):
        return await _set_mode_one(mode, pin, confirm)


async def flatten(pin: str | None = None, desk: str = "gold") -> dict:
    """Close every open real position one desk holds (the gold desk unless named), and switch it off."""
    if desk not in DESKS:
        return {"ok": False, "why": f"unknown desk {desk!r}"}
    with _use(desk):
        return await _flatten_one(pin)


async def _set_risk_one(risk_usd, pin: str | None = None) -> dict:
    db = _db()
    if db is None:
        return {"ok": False, "why": "the paper desk's database is not configured on this server"}
    if isinstance(risk_usd, str) and risk_usd.strip().lower() in ("min", "1 contract", "one contract"):
        r = None                                            # one contract a trade, the smallest order
    else:
        try:
            r = round(float(risk_usd), 2)
        except (TypeError, ValueError):
            return {"ok": False, "why": "the size must be one contract (min) or a number of US dollars"}
        if not (math.isfinite(r) and RISK_MIN_USD <= r <= _d().risk_usd):
            return {"ok": False, "why": f"the risk a trade must be from ${RISK_MIN_USD:.0f} to ${_d().risk_usd:.0f}"}
    st = await _state(db)
    why = await _check_pin(db, st, pin)
    if why:
        return {"ok": False, "why": why}
    if r is None:
        await _set_state(db, sizing="min", risk_set_at=_now())
        return {"ok": True, "sizing": "min"}
    await _set_state(db, sizing="risk", risk_usd=r, risk_set_at=_now())
    return {"ok": True, "sizing": "risk", "risk_usd": r}


async def set_risk(risk_usd, pin: str | None = None, desk: str = "gold") -> dict:
    """A desk's trade size, picked by the owner on the page: "min" (one contract a trade, the smallest order) or the most
    one trade may lose at its stop, RISK_MIN_USD up to the desk's own risk. Needs the PIN; a trade already open keeps
    the size it was given."""
    if desk not in DESKS:
        return {"ok": False, "why": f"unknown desk {desk!r}"}
    with _use(desk):
        return await _set_risk_one(risk_usd, pin)


def _as_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("on", "true", "1", "yes"):
        return True
    if isinstance(v, str) and v.strip().lower() in ("off", "false", "0", "no"):
        return False
    return None


async def _set_pick_one(key, contracts=None, on=None, pin: str | None = None, confirm: str | None = None) -> dict:
    db = _db()
    if db is None:
        return {"ok": False, "why": "the paper desk's database is not configured on this server"}
    p = next((x for x in _d().picks if _pkey(x) == str(key or "")), None)
    if p is None:
        return {"ok": False, "why": f"{key!r} is not one of this desk's strategies"}
    st = await _state(db)
    cur = _cfg(st, p)
    new = {"contracts": cur["contracts"], "on": cur["on"]}
    if contracts is not None:
        try:
            n = float(contracts)
        except (TypeError, ValueError):
            return {"ok": False, "why": "the lot size must be a whole number of contracts"}
        hi = _lots_max(p.product)
        if not (math.isfinite(n) and n == int(n) and 1 <= n <= hi):
            return {"ok": False, "why": f"the lot size of a {p.product} strategy must be a whole number from 1 to {hi} "
                                        "contracts"}
        new["contracts"] = int(n)
    if on is not None:
        b = _as_bool(on)
        if b is None:
            return {"ok": False, "why": "on must be true or false"}
        new["on"] = b
    if new == {"contracts": cur["contracts"], "on": cur["on"]}:
        return {"ok": True, "key": _pkey(p), **new, "changed": False}
    raises = new["contracts"] > cur["contracts"] or (new["on"] and not cur["on"])
    if raises:                  # more real money at stake: the words, and the PIN when one is required, as going live
        if str(confirm or "").strip().upper() != CONFIRM:
            return {"ok": False, "why": f"raising a strategy's size or switching it on needs the words {CONFIRM}"}
        why = await _check_pin(db, st, pin)
        if why:
            return {"ok": False, "why": why}
    # lowering or switching off only takes risk away: never a PIN, as switching the desk off never needs one
    at = _now()
    entry = {"key": _pkey(p), "at": at, "from": {"contracts": cur["contracts"], "on": cur["on"]}, "to": dict(new)}
    log = [x for x in (st.get("pick_log") or []) if isinstance(x, dict)][-(PICK_LOG_N - 1):] + [entry]
    await _set_state(db, **{f"pick_cfg.{_pkey(p)}": {**new, "at": at}, "pick_log": log})
    logger.info("[premium live %s] %s: %s -> %s", _d().key, _pkey(p), entry["from"], entry["to"])
    return {"ok": True, "key": _pkey(p), **new, "changed": True}


async def set_pick(key, contracts=None, on=None, pin: str | None = None, confirm: str | None = None,
                   desk: str = "gold") -> dict:
    """One strategy's own size and switch (23 Nov 2026), set from the page: `contracts` (1..LOTS_MAX of its product;
    used in the desk's contract sizing) and/or `on`. Raising the size or switching a strategy on needs confirm=REAL
    MONEY (and the PIN when one is required); lowering or switching off needs neither. A trade already open keeps its
    size and is managed to its close."""
    if desk not in DESKS:
        return {"ok": False, "why": f"unknown desk {desk!r}"}
    with _use(desk):
        return await _set_pick_one(key, contracts, on, pin, confirm)


# -- the read model ------------------------------------------------------------------------------------


def _clean(t: dict) -> dict:
    t = dict(t)
    t["id"] = t.pop("_id")
    return t


# Results (21 Nov 2026): what a desk and each of its strategies did with real money, counted from EVERY trade row (the
# page's "recent" holds only the latest 150): trades, % won, profit factor, t, net P&L, return %, trading days and the
# average a trading day. Return % = net P&L / the most margin the strategy (or the desk) had in use at one time: the
# capital it actually tied up at 10x. (Summing each trade's return on its own margin would let one 4-contract win and
# many 1-contract losses disagree in sign with the net.) A trading day = an IST day on which one of its trades closed.
HELD = ("entering", "open", "closing")


def _margin(t: dict, prods: dict) -> float:
    """The margin a real trade holds: its contracts x contract value x fill / leverage, else what its plan said."""
    p = (prods or {}).get(t.get("product")) or {}
    try:
        cv, lev = float(p.get("contract_value") or 0), float(p.get("leverage") or LEVERAGE)
        n, fill = float(t.get("contracts") or 0), float(t.get("fill") or 0)
        if cv > 0 and lev > 0 and n > 0 and fill > 0:
            return n * cv * fill / lev
        return float((t.get("plan") or {}).get("margin_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _peak_margin(trades: list, prods: dict, now: float) -> float:
    """The most margin these trades held at one time (an open trade holds it until now)."""
    ev = []
    for t in trades:
        m = _margin(t, prods)
        if m <= 0:
            continue
        o = float(t.get("opened_at") or t.get("created_at") or now)
        c = float(t.get("closed_at") or o) if t.get("status") == "closed" else now
        ev += [(o, 1, m), (max(c, o), 0, -m)]       # at the same second a close frees its margin before an open takes it
    cur = peak = 0.0
    for _, _, m in sorted(ev):
        cur += m
        peak = max(peak, cur)
    return peak


def _record(trades: list, prods: dict, now: float, by_day: bool = False) -> dict:
    """The real-money record of a set of live trades (one strategy's, or a whole desk's)."""
    closed = sorted((t for t in trades if t.get("status") == "closed"), key=lambda t: float(t.get("closed_at") or 0))
    held = [t for t in trades if t.get("status") in HELD]
    pnl = [float(t.get("pnl_usd") or 0.0) for t in closed]
    n, net = len(pnl), sum(pnl)
    wins = sum(1 for x in pnl if x > 0)
    won, lost = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x < 0)
    t_stat = None
    if n >= 2:
        sd = math.sqrt(sum((x - net / n) ** 2 for x in pnl) / (n - 1))
        t_stat = round((net / n) / (sd / math.sqrt(n)), 2) if sd > 0 else None
    peak = _peak_margin(closed + held, prods, now)
    ret = 100.0 * net / peak if n and peak > 0 else None
    days: dict[str, list] = {}
    for t, x in zip(closed, pnl):
        d = days.setdefault(t.get("day_closed") or _day(float(t.get("closed_at") or now)), [0, 0, 0.0])
        d[0] += 1
        d[1] += 1 if x > 0 else 0
        d[2] += x
    eq = top = dd = 0.0
    for x in pnl:
        eq += x
        top = max(top, eq)
        dd = min(dd, eq - top)
    holds = [float(t["closed_at"]) - float(t["opened_at"]) for t in closed if t.get("closed_at") and t.get("opened_at")]
    nd = len(days)
    out = {
        "trades": n, "wins": wins, "open": len(held), "win_pct": round(100.0 * wins / n, 1) if n else None,
        "net_usd": round(net, 4), "fees_usd": round(sum(float(t.get("fees") or 0.0) for t in closed), 4),
        "won_usd": round(won, 4), "lost_usd": round(lost, 4), "pf": round(won / lost, 2) if lost > 0 else None,
        "t": t_stat, "peak_margin_usd": round(peak, 4), "return_pct": None if ret is None else round(ret, 2),
        "days": nd, "avg_day_pct": round(ret / nd, 3) if ret is not None and nd else None,
        "avg_day_usd": round(net / nd, 4) if nd else None, "avg_trade_usd": round(net / n, 4) if n else None,
        "avg_trade_pct": round(ret / n, 3) if ret is not None else None,
        "best_usd": round(max(pnl), 4) if pnl else None, "worst_usd": round(min(pnl), 4) if pnl else None,
        "max_dd_usd": round(dd, 4), "avg_hold_s": round(sum(holds) / len(holds)) if holds else None,
        "open_usd": round(sum(float(t.get("unrealised_usd") or 0.0) for t in held), 4),
        "first_at": min((float(t.get("opened_at") or t.get("created_at") or now) for t in closed + held), default=None),
        "last_at": (float(closed[-1].get("closed_at") or 0) or None) if closed else None,
    }
    if by_day:
        out["by_day"] = [{"day": d, "trades": v[0], "wins": v[1], "pnl_usd": round(v[2], 4),
                          "return_pct": round(100.0 * v[2] / peak, 2) if peak > 0 else None}
                         for d, v in sorted(days.items())]
        out["green_days"] = sum(1 for v in days.values() if v[2] > 0)
    return out


def _results(rows: list, prods: dict, now: float) -> dict:
    """The desk's real-money record (with each IST day) and each strategy's, keyed "acct|mkt"."""
    live = [t for t in rows if t.get("mode") == "live" and t.get("status") in ("closed",) + HELD]
    per: dict[str, list] = {}
    for t in live:
        per.setdefault(f"{t.get('acct')}|{t.get('mkt')}", []).append(t)
    return {"desk": _record(live, prods, now, by_day=True), "per": {k: _record(v, prods, now) for k, v in per.items()}}


# The rank (23 Nov 2026): every strategy of a desk in order of its EXPECTED net R a trade, best first, estimated from
# all the evidence it has - and shrunk, because most of these records are short and many were picked for a lucky start:
# 1. a prior from its own backtest: the R a trade it reported, trusted by its number of trades (sd 1.3 / sqrt(n)) plus
#    RANK_DRIFT_SD for the backtest-to-live drift; untested (or graded only by the Strategy Factory, whose replay reads
#    future bars), it starts at its desk's average backtest with RANK_UNTESTED_SD; the H1 templates, whose only test is
#    pooled, at 0 with RANK_POOLED_SD;
# 2. its whole paper record, each trade's net R (at most RANK_R_CLIP either way): trades after its pick count fully, those
#    before at RANK_PRE_W (that record is what got it picked); a record's own spread of R once it has RANK_SD_N trades;
# 3. how its real Delta copies did against their own paper twins (R real - R paper: fees, slippage, late copies), its
#    own pairs weighed against RANK_GAP_K of the desk's.
# Normal-normal: posterior mean = (prior / prior var + sum of R / spread^2) / (1 / prior var + n / spread^2). Rank by it;
# "likely positive" = the chance the edge is above zero. Read only: it changes nothing the desk does.
RANK_METHOD = ("Rank = expected net R a trade (R = what a trade risks at its stop), best first: each strategy's own "
               "backtest as the starting point (trusted by its number of trades; an untested one starts at its desk's "
               "average backtest), updated by its whole paper record (trades before it was picked count a quarter: a "
               "good record is what got it picked), then corrected by how its real Delta copies did against their paper "
               "twins. A short record stays near its starting point. % = how likely that edge is above zero.")
_BT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)R a trade over ([\d,]+)")


def _bt_edge(backtest: str) -> tuple[float, int] | None:
    """A pick's own backtest as (R a trade, trades) when it reports one ("loses: -0.06R a trade over 795 trades")."""
    if not str(backtest or "").startswith(("loses", "earns")):
        return None
    m = _BT_RE.search(backtest)
    return (float(m.group(1)), int(m.group(2).replace(",", ""))) if m else None


def _iso_ts(s) -> float | None:
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except (TypeError, ValueError):
        return None


def _sd(xs: list) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _real_r(t: dict) -> float | None:
    """A closed real trade's net R: its P&L over what it risked at its stop when it went in."""
    try:
        risk = float((t.get("plan") or {}).get("risk_usd") or 0.0) or _trade_risk(t)
        r = float(t.get("pnl_usd") or 0.0) / risk if risk > 0 else None
    except (TypeError, ValueError):
        return None
    return r if r is not None and math.isfinite(r) else None


def _rank(picks: list, rs: dict, rows: list) -> dict:
    """Each pick's rank, keyed "acct|mkt": pos (1 = best), edge_r (expected net R a trade), p_pos and the parts."""
    def clip(x: float, c: float) -> float:
        return max(-c, min(c, x))
    tested = [e for e in (_bt_edge(p.backtest) for p in picks) if e]
    desk_mu = sum(e[0] for e in tested) / len(tested) if tested else -0.10
    own_sd: dict[str, float] = {}
    for p in picks:
        xs = [clip(r, RANK_R_CLIP) for _, r, _ in rs.get(_pkey(p), [])]
        s = _sd(xs) if len(xs) >= RANK_SD_N else None
        if s:
            own_sd[_pkey(p)] = min(max(s, RANK_SD_MIN), RANK_SD_MAX)
    sds = sorted(own_sd.values())
    sd_desk = sds[len(sds) // 2] if sds else RANK_SD_DEFAULT
    paper_r = {i: r for v in rs.values() for _, r, i in v}
    gaps: dict[str, list] = {}
    for t in rows:
        if t.get("mode") != "live" or t.get("status") != "closed" or t.get("_id") not in paper_r:
            continue
        rr = _real_r(t)
        if rr is not None:
            gaps.setdefault(f"{t.get('acct')}|{t.get('mkt')}", []).append(clip(rr - paper_r[t["_id"]], RANK_GAP_CLIP))
    allg = [g for v in gaps.values() for g in v]
    g_desk = sum(allg) / len(allg) if allg else 0.0
    sg = (_sd(allg) if len(allg) >= 3 else None) or 0.5
    out: dict[str, dict] = {}
    for p in picks:
        k = _pkey(p)
        bt = _bt_edge(p.backtest)
        if bt:
            mu0, tau, kind = bt[0], math.sqrt(RANK_SD_DEFAULT ** 2 / max(bt[1], 1) + RANK_DRIFT_SD ** 2), "backtest"
        elif str(p.backtest).startswith("pooled only"):
            mu0, tau, kind = 0.0, RANK_POOLED_SD, "pooled"
        else:
            mu0, tau, kind = desk_mu, RANK_UNTESTED_SD, "untested"
        t_pick = _iso_ts(p.picked_at or _d().picked_at) or 0.0
        mine = rs.get(k, [])
        pre = [clip(r, RANK_R_CLIP) for x, r, _ in mine if x < t_pick]
        post = [clip(r, RANK_R_CLIP) for x, r, _ in mine if x >= t_pick]
        s = own_sd.get(k, sd_desk)
        prec = 1.0 / tau ** 2 + (RANK_PRE_W * len(pre) + len(post)) / s ** 2
        mean = (mu0 / tau ** 2 + (RANK_PRE_W * sum(pre) + sum(post)) / s ** 2) / prec
        g = gaps.get(k, [])
        gap = (sum(g) + RANK_GAP_K * g_desk) / (len(g) + RANK_GAP_K) if allg else 0.0
        var = 1.0 / prec + ((sg ** 2) / (len(g) + RANK_GAP_K) if allg else 0.0)
        edge, sd = mean + gap, math.sqrt(var)
        out[k] = {"edge_r": round(edge, 4), "sd_r": round(sd, 4),
                  "p_pos": round(0.5 * (1.0 + math.erf(edge / sd / math.sqrt(2.0))), 4) if sd > 0 else float(edge > 0),
                  "prior_r": round(mu0, 4), "prior_sd": round(tau, 4), "prior": kind,
                  "pre_n": len(pre), "post_n": len(post), "post_r": round(sum(post) / len(post), 4) if post else None,
                  "paper_r": round(mean, 4), "gap_r": round(gap, 4), "gap_n": len(g)}
    order = sorted(out, key=lambda k: (-out[k]["edge_r"], -out[k]["p_pos"], k))
    for n, k in enumerate(order, start=1):
        out[k].update(pos=n, of=len(order))
    return out


# The page's lot conversions (24 Nov 2026): what one contract of each product is worth now, in dollars and rupees.
QUOTE_TTL_S = 60          # a product's price is asked of Delta at most once a minute for the page
QUOTE_WAIT_S = 2.0        # ... and the page never waits longer than this for it (the read goes on in the background)
MARK_FRESH_S = 600        # an open trade's mark (updated every pass) younger than this is the price
FX_TTL_S = 600
_QUOTES: dict[str, tuple[float, float]] = {}     # product -> (price, when)
_QUOTE_TASKS: dict[str, asyncio.Task] = {}
_FX: dict = {"rate": None, "asof": None, "at": 0.0}
_FX_TASK: list = [None]


async def _read_quote(sym: str) -> None:
    try:
        q = await D.ticker(sym)
        px = float(q.get("mark") or 0) or (float(q.get("bid") or 0) + float(q.get("ask") or 0)) / 2
        if px > 0:
            _QUOTES[sym] = (px, _now())
    except Exception:  # noqa: BLE001 - a read for the page only
        logger.debug("[premium live] %s: no quote for the page", sym, exc_info=True)


async def _prices(db, products: list[str]) -> dict:
    """Each product's latest price for the page's lot conversions: the freshest mark of any desk's open real trade on
    it (updated every pass), else one public ticker read at most every QUOTE_TTL_S, never waited on longer than
    QUOTE_WAIT_S. A product with neither is left out (the page then shows lots without their money). Never raises."""
    out: dict = {}
    for sym in products:
        best = None
        try:
            for d in DESKS.values():
                async for t in getattr(db, d.trades_coll).find({"product": sym, "status": {"$in": ["open", "closing"]},
                                                               "mark": {"$gt": 0}}, {"mark": 1, "updated_at": 1}):
                    at = float(t.get("updated_at") or 0)
                    if best is None or at > best[1]:
                        best = (float(t["mark"]), at)
        except Exception:  # noqa: BLE001
            best = None
        if best is None or _now() - best[1] > MARK_FRESH_S:
            hit = _QUOTES.get(sym)
            if hit is None or _now() - hit[1] > QUOTE_TTL_S:
                task = _QUOTE_TASKS.get(sym)
                if task is None or task.done():
                    task = _QUOTE_TASKS[sym] = asyncio.create_task(_read_quote(sym))
                try:
                    await asyncio.wait_for(asyncio.shield(task), QUOTE_WAIT_S)
                except Exception:  # noqa: BLE001 - slow or failed: the page goes on without it
                    pass
                hit = _QUOTES.get(sym) or hit
            if hit is not None and (best is None or hit[1] > best[1]):
                best = hit
        if best is not None:
            out[sym] = {"price": round(best[0], 6), "at": round(best[1], 3)}
    return out


async def _read_fx() -> None:
    try:
        from app.services import gold_desk
        rate, asof = await gold_desk.usd_inr()
        if rate:
            _FX.update(rate=float(rate), asof=asof, at=_now())
    except Exception:  # noqa: BLE001 - a read for the page only
        logger.debug("[premium live] USD/INR unavailable for the page", exc_info=True)


async def _usd_inr() -> dict | None:
    """USD/INR for the page's rupee figures: the Gold Desk's reader (Yahoo INR=X), refreshed every FX_TTL_S in the
    background and never waited on longer than QUOTE_WAIT_S; None until it has been read once. Never raises."""
    if not _FX["rate"] or _now() - float(_FX["at"] or 0) > FX_TTL_S:
        task = _FX_TASK[0]
        if task is None or task.done():
            task = _FX_TASK[0] = asyncio.create_task(_read_fx())
        try:
            await asyncio.wait_for(asyncio.shield(task), QUOTE_WAIT_S)
        except Exception:  # noqa: BLE001
            pass
    if not _FX["rate"]:
        return None
    return {"rate": round(float(_FX["rate"]), 4), "asof": _FX["asof"], "source": "Yahoo INR=X (the Gold Desk's reader)"}


async def _status_one() -> dict:
    db = _db()
    if db is None:
        return {"configured_db": False}
    st = await _state(db)
    rows = [t async for t in _tc(db).find({})]
    rows.sort(key=lambda t: -(float(t.get("created_at") or 0)))
    per: dict[str, dict] = {}
    for t in rows:
        if t.get("status") not in ("closed", "open", "closing", "entering"):
            continue
        x = per.setdefault(f"{t['mode']}|{t['acct']}|{t['mkt']}", {"trades": 0, "wins": 0, "pnl_usd": 0.0, "open": 0})
        if t["status"] == "closed":
            x["trades"] += 1
            x["wins"] += 1 if (t.get("pnl_usd") or 0) > 0 else 0
            x["pnl_usd"] = round(x["pnl_usd"] + float(t.get("pnl_usd") or 0.0), 4)
        else:
            x["open"] += 1
    view = await _paper_view(db, st)
    try:
        res = _results(rows, st.get("products") or {}, _now())
    except Exception:                                  # extras for the page: never let them break what it reads
        logger.exception("premium live %s: results not counted", _d().key)
        res = None
    rank = None
    if view is not None:
        try:
            rank = _rank(list(_d().picks), view.get("rs") or {}, rows)
        except Exception:                              # an extra for the page: never let it break what it reads
            logger.exception("premium live %s: rank not computed", _d().key)
    empty = {"trades": 0, "wins": 0, "sum_r": 0.0, "open": [], "last_t": None}
    picks = []
    for p in _d().picks:
        picks.append({**asdict(p), "live": per.get(f"live|{p.acct}|{p.mkt}"), "shadow": per.get(f"shadow|{p.acct}|{p.mkt}"),
                      "paper": None if view is None else view["per"].get(f"{p.acct}|{p.mkt}", empty),
                      "results": None if res is None else res["per"].get(f"{p.acct}|{p.mkt}"),
                      "cfg": {**_cfg(st, p), "max": _lots_max(p.product)},
                      "rank": None if rank is None else rank.get(_pkey(p))})
    today = {m: await _day_pnl(db, m, None) for m in ("live", "shadow")}
    totals = {}
    for m in ("live", "shadow"):
        closed = [t for t in rows if t.get("mode") == m and t.get("status") == "closed"]
        totals[m] = {"trades": len(closed), "wins": sum(1 for t in closed if (t.get("pnl_usd") or 0) > 0),
                     "pnl_usd": round(sum(float(t.get("pnl_usd") or 0) for t in closed), 4),
                     "fees_usd": round(sum(float(t.get("fees") or 0) for t in closed), 4),
                     "skipped": sum(1 for t in rows if t.get("mode") == m and t.get("status") == "skipped"),
                     "errors": sum(1 for t in rows if t.get("mode") == m and t.get("status") == "error")}
    return {
        "configured_db": True, "keys": DR.configured(), "pin_set": _pin_ok(None) is not None, "pin_required": REQUIRE_PIN,
        "mode": st.get("mode"), "since": st.get("since"), "armed_at": st.get("armed_at"),
        "switched_off": st.get("switched_off"), "last_error": st.get("last_error"), "last_error_at": st.get("last_error_at"),
        "errors_in_row": st.get("errors_in_row"), "last_cycle_at": st.get("last_cycle_at"), "wallet": st.get("wallet"),
        "wallet_at": st.get("wallet_at"), "products": st.get("products"),
        "limits": {"risk_usd": _risk(st), "risk_cap_usd": _d().risk_usd, "risk_min_usd": RISK_MIN_USD,
                   "risk_set_at": st.get("risk_set_at"), "sizing": _sizing(st), "daily_stop_usd": _d().daily_stop_usd,
                   "max_notional_usd": MAX_NOTIONAL_USD, "leverage": LEVERAGE, "max_lag_s": _d().max_lag_s,
                   "drift_frac": DRIFT_FRAC, "tick_s": TICK_S, "follow_all": _d().follow_all,
                   "daily_stop_on": not _d().follow_all, "contract_cap_on": not _d().follow_all,
                   "waiting": len(_WAITING.get(_d().key, {})),
                   "pick_cfg": True, "lots_default": LOTS_DEFAULT, "lots_max": dict(LOTS_MAX)},
        "pick_log": [x for x in (st.get("pick_log") or []) if isinstance(x, dict)][-30:], "rank_method": RANK_METHOD,
        "today": today, "totals": totals, "picked_at": _d().picked_at, "picks": picks,
        "results": None if res is None else res["desk"],
        "desk": _d().key, "title": _d().title, "desk_products": _d().products,
        "open": [_clean(t) for t in rows if t.get("status") in ("entering", "open", "closing")],
        "recent": [_clean(t) for t in rows[:150]], "notes": list(_d().notes),
        "signals": None if view is None else view["signals"],
        "paper_view": None if view is None else {k: view[k] for k in ("at", "paper_age_s", "gold_desk_age_s", "factory_age_s")
                                                          if k in view},
        "quotes": await _prices(db, _d().products), "usd_inr": await _usd_inr(),   # the page's lot conversions (24 Nov)
    }


async def status(desk: str = "gold") -> dict:
    """What a desk's page reads (the gold desk unless named)."""
    if desk not in DESKS:
        return {"error": f"unknown desk {desk!r}"}
    with _use(desk):
        return await _status_one()
