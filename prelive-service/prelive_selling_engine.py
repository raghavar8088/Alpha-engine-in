"""Pre-Live paper desk engine for option SELLING — multi-leg credit structures held
across sessions, on real live Dhan premiums and paper capital.

WHY THIS IS NOT `PreLiveEngine` WITH A FLAG
-------------------------------------------
The buying desk's engine is built on assumptions that are all false here:

  * A buying position is ONE leg. Every structure this desk opens is 1-4 legs that must
    be priced, marked, stopped and closed as a single unit. A partially closed condor is
    not a smaller condor — it is a naked position the desk never chose to take.
  * Max loss is the premium paid, so the buying engine can size by premium and needs no
    margin model. Selling blocks margin, and sizing by credit collected would let this
    desk oversell its paper capital by ~18x on a naked strangle.
  * A buying position is flat by 15:15 every day. The qualified selling basket is
    dominated by SWING strategies that hold for ~7 days, across nights and weekends. That
    single fact drives most of what follows: positions must survive process restarts,
    survive weekends, and be re-marked against gaps that happened while the desk slept.
  * Buying has no daily loss circuit breaker because its worst case is bounded by
    construction. Selling needs one.

RISK CONTROLS, IN THE ORDER THEY FIRE
-------------------------------------
  1. Premium stop        cost-to-close reaches `loss_cap_mult` x credit collected
  2. Strike wall         spot reaches a short strike that started OTM
  3. Capital backstop    unrealized loss reaches max_loss_pct_capital of the pool
  4. Daily circuit breaker   the DESK stops opening anything new for the rest of the day
  5. Expiry square-off   every leg closed on the expiry date, no exceptions

1-3 are per-position and are checked on EVERY tick, not on bar close — a bar-close-only
stop on a short book systematically misses the intrabar moves that hurt it. 4 is
desk-level. 5 is the one that must never be skipped: an unclosed short leg through expiry
is an assignment, which paper capital cannot model and a real account cannot afford.

MIRRORS THE BUYING DESK DELIBERATELY where the problem is genuinely the same: the Dhan
feed wrapper, credential rotation, the `prelive_*` collection layout, and the heartbeat
state doc. Those were debugged the hard way in production and there is no reason to
re-learn them here.
"""

import os
from datetime import date, datetime, timedelta, timezone

from db_selling import (
    daily_pnl_collection,
    equity_collection,
    instruments_collection,
    option_sweeps_selling_collection,
    positions_collection,
    scores_collection,
    state_collection,
    trades_collection,
)

from options_service.margin import estimate_margin
from options_service.options_selling_backtest import OPTION_SELLING_CATEGORIES
from strategy_service.strategies.options_selling._base import LegSpec
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
from tradingai_shared.domain import Bar, SignalAction, Timeframe, TransactionType

IST = timezone(timedelta(hours=5, minutes=30))
LOT_SIZE = 75
STRIKE_STEP = 50

# Paper capital for the SELLING desk — its own pool, never the buying desk's.
INITIAL_CAPITAL = float(os.getenv("PRELIVE_SELLING_INITIAL_CAPITAL", "10000000"))  # Rs 1 crore

# Margin budget per structure, as a share of the pool. Sizing is by MARGIN, not credit:
# credit-based sizing is what would let this desk think a 1-lot naked strangle costs it
# Rs 20k when the exchange has blocked Rs 3.7 lakh.
MARGIN_PER_TRADE_PCT = float(os.getenv("PRELIVE_SELLING_MARGIN_PER_TRADE_PCT", "0.05"))
MAX_LOTS_PER_TRADE = int(os.getenv("PRELIVE_SELLING_MAX_LOTS", "10"))
MAX_OPEN_STRUCTURES = int(os.getenv("PRELIVE_SELLING_MAX_OPEN", "12"))

# Desk-level daily circuit breaker: once the day's realized+unrealized loss crosses this
# share of the pool, NOTHING new opens for the rest of the session. Existing positions
# are still managed (a breaker that stopped managing open risk would be worse than none).
DAILY_LOSS_BREAKER_PCT = float(os.getenv("PRELIVE_SELLING_DAILY_LOSS_PCT", "0.03"))

# One structure at a time per strategy, same as the buying desk.
SUPPORTED_TIMEFRAMES = {"5m", "15m", "1h", "1d"}
STYLE_TF = {
    "options_sell_intraday": "15m",
    "options_sell_expiry": "15m",
    "options_sell_swing": "15m",
    "options_sell_positional": "1d",
}

# Tournament mode — same idea as the buying desk. The selling desk exists to select
# real-money winners from forward evidence, so it should evaluate the WHOLE library, not
# just the sweep's de-duped basket. With this on, EVERY registered option-selling strategy
# trades — each on its OWN independent PER_STRATEGY_CAPITAL margin account (default ₹10 lakh),
# never a shared pool, so one strategy can never starve another's margin. Every structure is
# a flat 1 lot so the leaderboard ranks entry/exit timing, not size. The qualification +
# out-of-sample + overlap de-dup that protect a REAL-money basket are deliberately NOT
# applied here (that selection happens afterwards from these records); the desk-wide
# MAX_OPEN_STRUCTURES cap is also lifted, since each strategy is already limited to one
# structure and the point is to let all of them run.
TRADE_ALL_STRATEGIES = os.getenv("PRELIVE_SELLING_TRADE_ALL_STRATEGIES", "0").lower() not in ("0", "false", "")
PER_STRATEGY_CAPITAL = float(os.getenv("PRELIVE_SELLING_PER_STRATEGY_CAPITAL", "1000000"))  # ₹10 lakh each
TOURNAMENT_LOTS = int(os.getenv("PRELIVE_SELLING_TOURNAMENT_LOTS", "1"))


def _now():
    return datetime.now(IST)


def load_qualified_basket() -> tuple[list[tuple[str, str]], dict | None]:
    """The qualified basket from the latest SELLING sweep.

    A strategy is traded only if the sweep marked it `in_basket`, which means all three
    of: it passed the gate, it survived the chronological out-of-sample split, and it is
    not a duplicate of something already in the basket.

    The daemon requires the flag rather than deriving it. An earlier version checked
    `qualified` and skipped entries whose `test_qualified` was False — which silently
    admitted everything, because the sweep did not write that field at all. The result
    would have been a desk trading every full-history qualifier, including naked shorts
    that collapse out of sample. Absence of a verdict is now treated as absence of
    approval: no `in_basket`, no trading.
    """
    doc = option_sweeps_selling_collection.find_one({}, sort=[("created_at", -1)])
    if doc is None:
        return [], None
    pairs = []
    for entry in doc.get("results", []):
        if not entry.get("in_basket"):
            continue
        sid = entry["strategy_id"]
        cls = STRATEGY_REGISTRY.get(sid)
        if cls is None:
            continue
        tf = STYLE_TF.get(cls.metadata.category)
        if tf:
            pairs.append((sid, tf))
    meta = {
        "sweep_id": doc.get("sweep_id"), "created_at": doc.get("created_at"),
        "symbol": doc.get("symbol"), "strategy_count": doc.get("strategy_count"),
        "qualified_count": doc.get("qualified_count"),
        "robust_count": doc.get("robust_count"), "basket_count": doc.get("basket_count"),
        "gate": doc.get("gate"), "overlap_threshold": doc.get("overlap_threshold"),
    }
    if not pairs and doc.get("qualified_count"):
        print(f"[selling] sweep {doc.get('sweep_id')} has {doc['qualified_count']} qualified "
              f"strategies but none marked in_basket — it predates the out-of-sample/overlap "
              f"filters. Re-run the selling sweep; trading nothing until then.", flush=True)
    return sorted(set(pairs)), meta


def load_all_selling_universe() -> tuple[list[tuple[str, str]], dict | None]:
    """Tournament universe: every registered option-selling strategy on its style's
    timeframe, bypassing the sweep/in_basket gate. Importing the library registers the
    whole set; each strategy maps to exactly one timeframe via STYLE_TF. Deliberately no
    qualification, out-of-sample or de-dup filter — the point is a complete forward record
    for every candidate, which the later real-money selection reads from."""
    try:
        import strategy_service.strategies.options_selling  # noqa: F401 — registers the library
    except Exception as e:  # pragma: no cover
        print(f"[selling] could not import the options_selling library: {e}", flush=True)

    pairs = []
    for sid, cls in STRATEGY_REGISTRY.items():
        if "options_selling" not in (getattr(cls, "__module__", "") or ""):
            continue
        tf = STYLE_TF.get(cls.metadata.category)
        if tf and tf in SUPPORTED_TIMEFRAMES:
            pairs.append((sid, tf))
    pairs = sorted(set(pairs))
    meta = {
        "sweep_id": "TRADE_ALL", "created_at": None, "symbol": "NIFTY",
        "strategy_count": len(pairs), "qualified_count": len(pairs),
        "basket_count": len(pairs), "mode": "tournament_all",
    }
    print(f"[selling] TOURNAMENT MODE — trading ALL {len(pairs)} option-selling strategies "
          f"(no qualification gate), each on its own Rs{PER_STRATEGY_CAPITAL:,.0f} margin account "
          f"at {TOURNAMENT_LOTS} lot(s)/structure, for forward selection.", flush=True)
    return pairs, meta


class OpenLeg:
    """One leg of a live structure. `sold` decides the sign of everything downstream."""

    __slots__ = ("option_type", "strike", "sold", "security_id", "exchange_segment",
                 "symbol", "entry_premium")

    def __init__(self, option_type, strike, sold, security_id, exchange_segment,
                 symbol, entry_premium):
        self.option_type = option_type
        self.strike = float(strike)
        self.sold = bool(sold)
        self.security_id = security_id
        self.exchange_segment = exchange_segment
        self.symbol = symbol
        self.entry_premium = float(entry_premium)

    def to_doc(self) -> dict:
        return {
            "option_type": self.option_type, "strike": self.strike, "sold": self.sold,
            "security_id": self.security_id, "exchange_segment": self.exchange_segment,
            "symbol": self.symbol, "entry_premium": round(self.entry_premium, 2),
        }

    @staticmethod
    def from_doc(d) -> "OpenLeg":
        return OpenLeg(d["option_type"], d["strike"], d["sold"], d["security_id"],
                       d["exchange_segment"], d.get("symbol"), d["entry_premium"])


class OpenStructure:
    """A live multi-leg credit position. Opened, marked and closed as ONE unit."""

    __slots__ = ("key", "strategy_id", "tf", "legs", "credit", "lots", "margin",
                 "margin_basis", "entry_ts", "entry_spot", "expiry", "loss_cap_mult",
                 "credit_target_pct", "strike_buffer_pct", "max_loss_pct_capital",
                 "wall_ce", "wall_pe")

    def __init__(self, key, strategy_id, tf, legs, credit, lots, margin, margin_basis,
                 entry_ts, entry_spot, expiry, style):
        self.key = key
        self.strategy_id = strategy_id
        self.tf = tf
        self.legs = legs
        self.credit = float(credit)          # net premium received PER UNIT
        self.lots = int(lots)
        self.margin = float(margin)
        self.margin_basis = margin_basis
        self.entry_ts = entry_ts
        self.entry_spot = float(entry_spot)
        self.expiry = expiry                 # ISO date string
        self.loss_cap_mult = style["loss_cap_mult"]
        self.credit_target_pct = style["credit_target_pct"]
        self.strike_buffer_pct = style["strike_buffer_pct"]
        self.max_loss_pct_capital = style["max_loss_pct_capital"]
        # Walls are frozen at entry from strikes that started OTM. Recomputing them
        # against the CURRENT spot would make every strike look breached the moment
        # price arrived at it, which is the alarm itself.
        ce = [l.strike for l in legs if l.sold and l.option_type == "CE" and l.strike > entry_spot]
        pe = [l.strike for l in legs if l.sold and l.option_type == "PE" and l.strike < entry_spot]
        self.wall_ce = min(ce) if ce else None
        self.wall_pe = max(pe) if pe else None

    @property
    def qty(self) -> int:
        return self.lots * LOT_SIZE

    def cost_to_close(self, fetch_ltp) -> float | None:
        """Net premium PER UNIT to buy this structure back right now.

        Returns None if ANY leg is unpriceable. That is deliberate and important: a
        partially-priced multi-leg structure produces a mark that looks precise and is
        wrong, and acting on it (stopping out, or worse, not stopping out) is how a
        short book gets hurt. No price means no decision this tick.
        """
        total = 0.0
        for leg in self.legs:
            px = fetch_ltp(leg.security_id, leg.exchange_segment)
            if px is None or px < 0:
                return None
            total += px if leg.sold else -px
        return total

    def unrealized(self, close_cost: float) -> float:
        """Rupees. Positive = the structure is cheaper to close than the credit taken."""
        return (self.credit - close_cost) * self.qty


class PreLiveSellingEngine:
    def __init__(self):
        self.strategies: dict[str, object] = {}
        self.contexts: dict[str, StrategyContext] = {}
        self.positions: dict[str, OpenStructure] = {}
        self.universe: list[tuple[str, str]] = []
        self.universe_source: dict | None = None
        self._expiry_cache: tuple[str, list[str]] | None = None
        self.session_date: str | None = None
        self.day_start_equity: float = INITIAL_CAPITAL
        self.breaker_tripped: bool = False
        self.breaker_reason: str | None = None
        # A SELL signal that fires but cannot be built into a priced structure is an
        # execution failure, not a quiet regime. Counted per reason so a zero-activity day
        # can distinguish "no regime qualified" from "a valid short couldn't be placed".
        self.dropped_signals = {"no_expiry": 0, "no_contract": 0, "no_premium": 0,
                                "bad_credit": 0, "bad_wing": 0}
        self.refresh_universe(force=True)
        self._restore_open_positions()

    # ---- universe ---------------------------------------------------------

    def refresh_universe(self, force: bool = False) -> None:
        pairs, meta = load_all_selling_universe() if TRADE_ALL_STRATEGIES else load_qualified_basket()
        if not force and meta and self.universe_source and \
                meta.get("sweep_id") == self.universe_source.get("sweep_id"):
            return
        self.universe, self.universe_source = pairs, meta
        self._init_strategies()

    def _init_strategies(self) -> None:
        self.strategies.clear()
        self.contexts.clear()
        for sid, tf in self.universe:
            cls = STRATEGY_REGISTRY.get(sid)
            if cls is None:
                continue
            key = f"{sid}@{tf}"
            self.strategies[key] = cls()
            self.contexts[key] = StrategyContext(max_bars=max(500, cls().warmup + 2))
        # A strategy holding an open structure must NOT think it is flat, or it would
        # try to open a second one the moment its regime re-fires.
        for pos in self.positions.values():
            st = self.strategies.get(pos.key)
            if st is not None:
                st._open = True

    # ---- restart safety ---------------------------------------------------

    def _restore_open_positions(self) -> None:
        """Rebuild open structures from Mongo on startup.

        Non-negotiable for this desk in a way it is not for an intraday one. The buying
        desk is flat overnight, so a restart between sessions loses nothing; a swing
        selling desk is routinely holding 7-day positions, so a process restart without
        this would orphan live short risk in the database — visible on the page, tracked
        by nothing, and never closed. That exact class of bug (a stuck position surviving
        a restart) already happened on the buying desk twice.
        """
        n = 0
        for d in positions_collection.find({}):
            try:
                cls = STRATEGY_REGISTRY.get(d["strategy_id"])
                cat = cls.metadata.category if cls else "options_sell_swing"
                style = OPTION_SELLING_CATEGORIES.get(cat, OPTION_SELLING_CATEGORIES["options_sell_swing"])
                ts = d.get("entry_ts")
                entry_ts = datetime.fromisoformat(ts) if isinstance(ts, str) else (ts or _now())
                pos = OpenStructure(
                    key=d["key"], strategy_id=d["strategy_id"], tf=d.get("timeframe", "15m"),
                    legs=[OpenLeg.from_doc(x) for x in d["legs"]],
                    credit=d["credit"], lots=d.get("lots", 1), margin=d.get("margin", 0.0),
                    margin_basis=d.get("margin_basis", "unknown"), entry_ts=entry_ts,
                    entry_spot=d.get("entry_spot", 0.0), expiry=d.get("expiry"), style=style,
                )
                self.positions[pos.key] = pos
                n += 1
            except Exception as e:
                print(f"[warn] could not restore selling position {d.get('key')}: {e}", flush=True)
        if n:
            print(f"[selling] restored {n} open structure(s) from Mongo — including any held "
                  f"across sessions", flush=True)

    # ---- contracts --------------------------------------------------------

    def expiries(self) -> list[str]:
        today = _now().date().isoformat()
        if self._expiry_cache and self._expiry_cache[0] == today:
            return self._expiry_cache[1]
        exps = sorted(
            e for e in instruments_collection.distinct(
                "expiry", {"asset_class": "INDEX_OPTION", "symbol": {"$regex": "^NIFTY-"}})
            if e and e >= today
        )
        self._expiry_cache = (today, exps)
        return exps

    def expiry_for_style(self, category: str) -> str | None:
        """Nearest expiry for weekly styles; the ~monthly one for positional.

        Positional strategies were qualified on a 30-day structure, so handing them the
        current weekly would be trading something the backtest never evaluated.
        """
        exps = self.expiries()
        if not exps:
            return None
        if category != "options_sell_positional":
            return exps[0]
        target = (_now().date() + timedelta(days=25)).isoformat()
        later = [e for e in exps if e >= target]
        return later[0] if later else exps[-1]

    def contract(self, expiry: str, strike: float, option_type: str) -> dict | None:
        for widen in range(0, 6):
            candidates = {strike} if widen == 0 else {
                strike + widen * STRIKE_STEP, strike - widen * STRIKE_STEP}
            for s in candidates:
                doc = instruments_collection.find_one({
                    "asset_class": "INDEX_OPTION", "expiry": expiry, "strike": float(s),
                    "option_type": option_type, "symbol": {"$regex": "^NIFTY-"}})
                if doc:
                    return {"security_id": doc["security_id"], "strike": float(s),
                            "exchange_segment": doc["exchange_segment"], "symbol": doc["symbol"]}
        return None

    # ---- capital ----------------------------------------------------------

    def realized_all_time(self) -> float:
        cur = trades_collection.aggregate([{"$group": {"_id": None, "s": {"$sum": "$pnl"}}}])
        return float(next(cur, {}).get("s", 0.0) or 0.0)

    def _strategy_realized(self, strategy_id: str) -> float:
        """Lifetime realized P&L of ONE strategy — the balance of its own ₹10L margin
        account. Each selling strategy maps to a single timeframe, so strategy_id keys the
        slot uniquely. Used only in tournament mode."""
        cur = trades_collection.aggregate([
            {"$match": {"strategy_id": strategy_id}},
            {"$group": {"_id": None, "s": {"$sum": "$pnl"}}},
        ])
        return float(next(cur, {}).get("s", 0.0) or 0.0)

    def _total_capital(self) -> float:
        """Desk-wide capital. In tournament mode every strategy has its own
        PER_STRATEGY_CAPITAL account, so the desk total is that times the field size."""
        if TRADE_ALL_STRATEGIES:
            return PER_STRATEGY_CAPITAL * max(len(self.universe), 1)
        return INITIAL_CAPITAL

    def margin_deployed(self) -> float:
        return sum(p.margin for p in self.positions.values())

    def balance(self) -> dict:
        total = self._total_capital()
        realized = self.realized_all_time()
        equity = total + realized
        deployed = self.margin_deployed()
        return {
            "initial_capital": total, "realized": realized, "balance": equity,
            "margin_deployed": deployed, "free_margin": max(equity - deployed, 0.0),
        }

    # ---- session ----------------------------------------------------------

    def new_session(self) -> None:
        self.session_date = _now().date().isoformat()
        self.day_start_equity = self.balance()["balance"]
        self.breaker_tripped = False
        self.breaker_reason = None
        self.dropped_signals = {"no_expiry": 0, "no_contract": 0, "no_premium": 0,
                                "bad_credit": 0, "bad_wing": 0}
        self.refresh_universe(force=True)

    def day_pnl(self, fetch_ltp) -> tuple[float, float]:
        """(realized today, unrealized on open structures). The breaker reads both —
        a desk that only counted realized losses would happily keep opening new risk
        while its open book bled."""
        start = f"{self.session_date}T00:00:00" if self.session_date else None
        realized = 0.0
        if start:
            cur = trades_collection.aggregate([
                {"$match": {"exit_ts": {"$gte": start}}},
                {"$group": {"_id": None, "s": {"$sum": "$pnl"}}},
            ])
            realized = float(next(cur, {}).get("s", 0.0) or 0.0)
        unrealized = 0.0
        for pos in self.positions.values():
            cost = pos.cost_to_close(fetch_ltp)
            if cost is not None:
                unrealized += pos.unrealized(cost)
        return realized, unrealized

    def check_breaker(self, fetch_ltp) -> bool:
        """Trip the desk-level daily circuit breaker if the day's loss crosses the limit.

        Once tripped it stays tripped for the session — it does not un-trip if the book
        recovers, because a desk that has already had its worst day of the month should
        not be adding risk to it.
        """
        if self.breaker_tripped:
            return True
        realized, unrealized = self.day_pnl(fetch_ltp)
        day_loss = -(realized + unrealized)
        limit = DAILY_LOSS_BREAKER_PCT * self.day_start_equity
        if day_loss >= limit:
            self.breaker_tripped = True
            self.breaker_reason = (
                f"day loss Rs{day_loss:,.0f} crossed {DAILY_LOSS_BREAKER_PCT:.1%} of "
                f"Rs{self.day_start_equity:,.0f} (realized Rs{realized:,.0f}, "
                f"unrealized Rs{unrealized:,.0f})"
            )
            print(f"[BREAKER] {self.breaker_reason} — no new structures this session", flush=True)
        return self.breaker_tripped

    # ---- entries ----------------------------------------------------------

    def on_bar(self, strategy_id: str, tf: str, bar: Bar, fetch_ltp) -> dict | None:
        key = f"{strategy_id}@{tf}"
        strategy = self.strategies.get(key)
        ctx = self.contexts.get(key)
        if strategy is None or ctx is None:
            return None
        ctx.push(bar)
        if len(ctx.bars) < strategy.warmup:
            return None
        signal = strategy.on_bar(ctx)
        if signal is None:
            return None

        if signal.signal == SignalAction.EXIT_SHORT:
            pos = self.positions.get(key)
            if pos is not None:
                cost = pos.cost_to_close(fetch_ltp)
                if cost is not None:
                    self._close(pos, cost, "signal", fetch_ltp)
            return None

        if signal.signal != SignalAction.SELL or key in self.positions:
            return None
        # The desk-wide open-structure cap protects a shared real-money pool; in tournament
        # mode each strategy has its own account and is already limited to one structure
        # (key in self.positions above), so the cap is lifted to let the whole field run.
        if self.breaker_tripped or (not TRADE_ALL_STRATEGIES and len(self.positions) >= MAX_OPEN_STRUCTURES):
            # The strategy believes it is short now; keep its flag honest so it can
            # signal again on the next regime change rather than latching open forever.
            strategy.position_closed()
            return None
        return self._open(strategy, key, strategy_id, tf, bar, fetch_ltp)

    def _open(self, strategy, key, strategy_id, tf, bar, fetch_ltp) -> dict | None:
        cls = STRATEGY_REGISTRY[strategy_id]
        category = cls.metadata.category
        style = OPTION_SELLING_CATEGORIES[category]
        expiry = self.expiry_for_style(category)
        if not expiry:
            self.dropped_signals["no_expiry"] += 1
            print(f"[selling] SIGNAL DROPPED ({key}): no {category} expiry available in the "
                  f"instruments/scrip master — check it is current", flush=True)
            strategy.position_closed()
            return None

        ctx = self.contexts[key]
        try:
            specs = strategy.legs(ctx)
        except Exception as e:
            print(f"[warn] {key}: legs() failed: {e}", flush=True)
            strategy.position_closed()
            return None

        # Strikes come from the SAME solver the backtest used, fed live spot and a
        # realized-vol estimate, so the live desk trades the structure the sweep
        # qualified rather than a differently-struck cousin of it.
        from options_service.options_selling_backtest import strike_for_delta
        from options_service.options_backtest import _round_to_step

        t_years = max((date.fromisoformat(expiry) - _now().date()).days, 1) / 365
        sigma = self._sigma(ctx)
        legs, resolved_short = [], {}
        for spec in specs:
            if spec.wing_pct is not None:
                anchor = resolved_short.get(spec.option_type.upper())
                if anchor is None:
                    self.dropped_signals["bad_wing"] += 1
                    print(f"[selling] SIGNAL DROPPED ({key}): wing leg has no short anchor to hang "
                          f"off — malformed {spec.option_type} structure", flush=True)
                    strategy.position_closed()
                    return None
                off = anchor * spec.wing_pct
                raw = anchor + off if spec.option_type.upper() == "CE" else anchor - off
                strike = _round_to_step(raw, STRIKE_STEP)
                if spec.option_type.upper() == "CE" and strike <= anchor:
                    strike = anchor + STRIKE_STEP
                elif spec.option_type.upper() == "PE" and strike >= anchor:
                    strike = anchor - STRIKE_STEP
            elif spec.target_delta is not None:
                strike = strike_for_delta(bar.close, t_years, sigma, spec.option_type,
                                          spec.target_delta, STRIKE_STEP)
            else:
                strike = _round_to_step(bar.close * (1 + spec.otm_pct), STRIKE_STEP)
            if spec.sell:
                resolved_short[spec.option_type.upper()] = strike

            contract = self.contract(expiry, strike, spec.option_type.upper())
            if contract is None:
                self.dropped_signals["no_contract"] += 1
                print(f"[selling] SIGNAL DROPPED ({key}): no {spec.option_type} contract at strike "
                      f"{strike} expiry {expiry} — strike outside the listed ladder or scrip master "
                      f"stale", flush=True)
                strategy.position_closed()
                return None
            premium = fetch_ltp(contract["security_id"], contract["exchange_segment"])
            if premium is None or premium <= 0:
                # No live price for a leg = no honest entry. Never open a structure on a
                # partially-priced book.
                self.dropped_signals["no_premium"] += 1
                print(f"[selling] SIGNAL DROPPED ({key}): feed returned no premium for "
                      f"{contract['symbol']} (sid {contract['security_id']}) — neither Dhan nor Angel "
                      f"could price this leg", flush=True)
                strategy.position_closed()
                return None
            legs.append(OpenLeg(spec.option_type.upper(), contract["strike"], spec.sell,
                                contract["security_id"], contract["exchange_segment"],
                                contract["symbol"], premium))

        credit = sum(l.entry_premium if l.sold else -l.entry_premium for l in legs)
        if credit <= 0:
            self.dropped_signals["bad_credit"] += 1
            print(f"[selling] SIGNAL DROPPED ({key}): net credit Rs{credit:.2f} <= 0 — a credit "
                  f"structure that costs money to open, priced legs look wrong", flush=True)
            strategy.position_closed()
            return None  # a "credit" structure that costs money to open is a bug, not a trade

        # --- margin-based sizing -------------------------------------------
        class _L:  # shape the margin model expects
            def __init__(self, leg):
                self.option_type = leg.option_type
                self.strike = leg.strike
                self.direction = TransactionType.SELL if leg.sold else TransactionType.BUY

        model_legs = [_L(l) for l in legs]
        premiums = [l.entry_premium for l in legs]
        if TRADE_ALL_STRATEGIES:
            # Flat 1 lot, checked against THIS strategy's own ₹10L margin account (starting
            # capital + its own realized). Independent accounts, so no strategy starves
            # another; a strategy that has bled through its ₹10L simply stops trading.
            lots = TOURNAMENT_LOTS
            sized = estimate_margin(model_legs, bar.close, LOT_SIZE, lots, premiums)
            account = PER_STRATEGY_CAPITAL + self._strategy_realized(strategy_id)
            if sized["margin"] > account:
                strategy.position_closed()
                return None
        else:
            one_lot = estimate_margin(model_legs, bar.close, LOT_SIZE, 1, premiums)
            per_lot_margin = one_lot["margin"]
            bal = self.balance()
            budget = MARGIN_PER_TRADE_PCT * bal["balance"]
            lots = int(min(budget // per_lot_margin, MAX_LOTS_PER_TRADE)) if per_lot_margin > 0 else 0
            if lots < 1:
                strategy.position_closed()
                return None
            sized = estimate_margin(model_legs, bar.close, LOT_SIZE, lots, premiums)
            if sized["margin"] > bal["free_margin"]:
                strategy.position_closed()
                return None

        pos = OpenStructure(
            key=key, strategy_id=strategy_id, tf=tf, legs=legs, credit=credit, lots=lots,
            margin=sized["margin"], margin_basis=sized["basis"], entry_ts=_now(),
            entry_spot=bar.close, expiry=expiry, style=style,
        )
        self.positions[key] = pos
        positions_collection.replace_one({"key": key}, self._pos_doc(pos, credit), upsert=True)
        return {
            "key": key, "credit": credit, "lots": lots, "margin": sized["margin"],
            "basis": sized["basis"], "expiry": expiry,
            "legs": [f"{'SELL' if l.sold else 'BUY'} {l.strike:.0f}{l.option_type}" for l in legs],
        }

    def _sigma(self, ctx) -> float:
        """Annualized realized vol from the context's own closes — the same proxy the
        backtest priced with, so live strike selection matches what was qualified."""
        import math

        closes = [b.close for b in ctx.bars][-21:]
        if len(closes) < 3:
            return 0.15
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
        if len(rets) < 2:
            return 0.15
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        # ctx bars are intraday for swing styles; annualize off daily-equivalent vol the
        # same way the backtest's _realized_vol does, with the same VRP multiplier/floor.
        return max(math.sqrt(var) * math.sqrt(252) * 1.15, 0.09)

    # ---- management -------------------------------------------------------

    def manage_open(self, fetch_ltp, force_close: bool = False) -> list[dict]:
        """Re-mark and risk-check every open structure. Called on EVERY tick.

        Order matters: the capital backstop is evaluated before the cheaper controls so
        a violent move exits on the backstop rather than waiting for a premium stop that
        a gap has already blown through.
        """
        events = []
        today = _now().date().isoformat()
        equity = self.balance()["balance"]

        for key in list(self.positions):
            pos = self.positions[key]
            cost = pos.cost_to_close(fetch_ltp)
            if cost is None:
                continue  # unpriceable this tick — no decision on a partial book
            unreal = pos.unrealized(cost)

            reason = None
            if force_close:
                reason = "eod"
            elif pos.expiry and today >= pos.expiry:
                # Expiry square-off. Never skipped: an unclosed short leg through expiry
                # is an assignment, which this desk cannot model and a real one cannot
                # afford.
                reason = "expiry"
            elif unreal <= -(pos.max_loss_pct_capital * equity):
                reason = "capital_stop"
            elif unreal <= -(abs(pos.credit) * pos.loss_cap_mult * pos.qty):
                reason = "stop"
            elif self._wall_breached(pos, fetch_ltp):
                reason = "strike_pressure"
            elif pos.credit > 0 and unreal >= pos.credit * pos.credit_target_pct * pos.qty:
                reason = "target"

            if reason:
                events.append(self._close(pos, cost, reason, fetch_ltp))
            else:
                positions_collection.update_one({"key": key}, {"$set": {
                    "mark": round(cost, 2), "unrealized": round(unreal, 2),
                    "updated_at": _now().isoformat(),
                }})
        return events

    def _wall_breached(self, pos: OpenStructure, fetch_ltp) -> bool:
        spot = fetch_ltp(13, "IDX_I")
        if spot is None:
            return False
        if pos.wall_ce is not None and spot >= pos.wall_ce * (1 - pos.strike_buffer_pct):
            return True
        if pos.wall_pe is not None and spot <= pos.wall_pe * (1 + pos.strike_buffer_pct):
            return True
        return False

    def _close(self, pos: OpenStructure, cost: float, reason: str, fetch_ltp) -> dict:
        """Close EVERY leg as one unit and book the trade.

        There is no partial-close path anywhere in this engine, by design: a half-closed
        condor is a naked position the desk never chose to take.
        """
        pnl = pos.unrealized(cost)
        now = _now()
        trade = {
            "key": pos.key, "strategy_id": pos.strategy_id, "timeframe": pos.tf,
            "legs": [l.to_doc() for l in pos.legs],
            "structure": " / ".join(
                f"{'SELL' if l.sold else 'BUY'} {l.strike:.0f}{l.option_type}" for l in pos.legs),
            "credit": round(pos.credit, 2), "exit_cost": round(cost, 2),
            "lots": pos.lots, "qty": pos.qty, "margin": pos.margin,
            "margin_basis": pos.margin_basis, "expiry": pos.expiry,
            "entry_ts": pos.entry_ts.isoformat() if hasattr(pos.entry_ts, "isoformat") else pos.entry_ts,
            "exit_ts": now.isoformat(), "entry_spot": pos.entry_spot,
            "exit_spot": fetch_ltp(13, "IDX_I"),
            "exit_reason": reason, "pnl": round(pnl, 2),
            "held_days": (now.date() - (pos.entry_ts.date() if hasattr(pos.entry_ts, "date") else now.date())).days,
        }
        trades_collection.insert_one(dict(trade))
        positions_collection.delete_one({"key": pos.key})
        self.positions.pop(pos.key, None)
        st = self.strategies.get(pos.key)
        if st is not None:
            st.position_closed()
        self._update_score(pos.strategy_id, pnl)
        return {"key": pos.key, "exit_reason": reason, "pnl": pnl,
                "structure": trade["structure"]}

    def _update_score(self, strategy_id: str, pnl: float) -> None:
        scores_collection.update_one(
            {"strategy_id": strategy_id},
            {"$inc": {"trades": 1, "net_pnl": round(pnl, 2),
                      "wins": 1 if pnl > 0 else 0, "losses": 0 if pnl > 0 else 1,
                      "gross_win": round(pnl, 2) if pnl > 0 else 0.0,
                      "gross_loss": 0.0 if pnl > 0 else round(-pnl, 2)},
             "$set": {"updated_at": _now().isoformat()}},
            upsert=True,
        )

    # ---- persistence / reporting -----------------------------------------

    def _pos_doc(self, pos: OpenStructure, mark: float) -> dict:
        return {
            "key": pos.key, "strategy_id": pos.strategy_id, "timeframe": pos.tf,
            "legs": [l.to_doc() for l in pos.legs],
            "structure": " / ".join(
                f"{'SELL' if l.sold else 'BUY'} {l.strike:.0f}{l.option_type}" for l in pos.legs),
            "credit": round(pos.credit, 2), "lots": pos.lots, "qty": pos.qty,
            "margin": pos.margin, "margin_basis": pos.margin_basis,
            "expiry": pos.expiry, "entry_spot": pos.entry_spot,
            "entry_ts": pos.entry_ts.isoformat() if hasattr(pos.entry_ts, "isoformat") else pos.entry_ts,
            "mark": round(mark, 2), "unrealized": 0.0, "updated_at": _now().isoformat(),
        }

    def snapshot_equity(self, fetch_ltp) -> None:
        realized, unrealized = self.day_pnl(fetch_ltp)
        bal = self.balance()
        equity_collection.insert_one({
            "ts": _now().isoformat(), "session": self.session_date,
            "equity": round(bal["balance"] + unrealized, 2),
            "realized": round(bal["realized"], 2), "unrealized": round(unrealized, 2),
            "margin_deployed": round(bal["margin_deployed"], 2),
            "open_structures": len(self.positions),
        })

    def close_session(self, fetch_ltp) -> None:
        """End-of-session bookkeeping.

        Only INTRADAY/EXPIRY styles are squared off here. Swing and positional structures
        are meant to be held — squaring them off nightly would destroy the very edge the
        sweep measured (theta accrues in days) and would turn every 7-day strategy into
        the intraday strategy that demonstrably does not work.
        """
        for key in list(self.positions):
            pos = self.positions[key]
            cls = STRATEGY_REGISTRY.get(pos.strategy_id)
            cat = cls.metadata.category if cls else "options_sell_swing"
            if not OPTION_SELLING_CATEGORIES[cat]["square_off_eod"]:
                continue
            cost = pos.cost_to_close(fetch_ltp)
            if cost is not None:
                self._close(pos, cost, "eod", fetch_ltp)

        realized, unrealized = self.day_pnl(fetch_ltp)
        session = self.session_date or _now().date().isoformat()
        cur = trades_collection.count_documents({"exit_ts": {"$gte": f"{session}T00:00:00"}})
        daily_pnl_collection.replace_one(
            {"session": session},
            {"session": session, "realized_pnl": round(realized, 2),
             "unrealized_pnl": round(unrealized, 2), "net_pnl": round(realized + unrealized, 2),
             "trades": cur, "open_carried": len(self.positions),
             "margin_deployed": round(self.margin_deployed(), 2),
             "start_equity": round(self.day_start_equity, 2),
             "breaker_tripped": self.breaker_tripped, "breaker_reason": self.breaker_reason,
             "roi_pct": round((realized + unrealized) / self.day_start_equity * 100, 3)
             if self.day_start_equity else 0.0},
            upsert=True,
        )

    def publish_state(self, running: bool, extra: dict | None = None) -> None:
        bal = self.balance()
        state_collection.replace_one(
            {"_id": "selling"},
            {"_id": "selling", "desk": "selling", "running": running,
             "heartbeat": _now().isoformat(), "session": self.session_date,
             "universe_size": len(self.universe), "universe_source": self.universe_source,
             "open_structures": len(self.positions),
             "breaker_tripped": self.breaker_tripped, "breaker_reason": self.breaker_reason,
             **bal, **(extra or {})},
            upsert=True,
        )
