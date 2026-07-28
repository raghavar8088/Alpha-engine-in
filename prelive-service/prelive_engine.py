"""Pre-Live paper-trading engine — trades whatever the latest options qualification
sweep says is qualified, on NIFTY, automatically.

Mirrors antigravity's `pre_live` desk: consumes REAL market data, executes on a PAPER
account (no real Dhan orders), and keeps a per-strategy scoreboard so any promotion to
live rests on a forward paper track record — not just backtests. The traded universe
is DYNAMIC: it's read from the `option_sweeps` collection (whatever POST
/api/options/backtest-all last produced), not a hardcoded list, and re-checked at the
start of every session so re-running the sweep changes what the desk trades without a
restart.

Difference from the backtester: premiums here are REAL. When a strategy signals, the
engine buys the ATM CE/PE of the current weekly expiry at its live Dhan LTP, and manages
the stop/target/EOD square-off against the option's live LTP on every poll. This is the
one thing a historical backtest cannot do (Dhan purges expired-contract history), so the
pre-live desk is how real-premium evidence gets built, one session at a time.

The engine is data-source agnostic: `on_bar(strategy_key, bar)` is driven by whatever
polls Dhan (main.py). It holds one Strategy instance + StrategyContext per (strategy,
timeframe), turns signals into paper option positions, and persists everything.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from db import (
    _db,
    daily_pnl_collection,
    equity_collection,
    instruments_collection,
    option_sweeps_collection,
    positions_collection,
    scores_collection,
    state_collection,
    trades_collection,
)

bars_collection = _db["bars"]

# Volatility regime gate for option BUYING. Buying premium only pays when the underlying
# moves enough, fast enough, to beat the theta you bleed every day. Every session this desk
# has traded was flat — NIFTY daily ranges of 0.32-0.54% — and it lost on all of them
# (-Rs1.29L cumulative, 71% of trades stopped out). So new buys are stood aside when the
# recent daily range is below a floor comfortably above those flat days. This is regime
# selection, not a profit guarantee: it removes the proven-losing condition (buying into a
# dead tape); it does NOT claim the desk wins on trending days, for which there is not yet
# any evidence. Env-tunable; set the floor to 0 to disable the gate.
VOL_REGIME_FLOOR_PCT = float(os.getenv("PRELIVE_VOL_FLOOR_PCT", "0.7"))
VOL_REGIME_LOOKBACK_DAYS = int(os.getenv("PRELIVE_VOL_LOOKBACK_DAYS", "5"))

from options_service.options_backtest import OPTION_BUYING_CATEGORIES
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
from tradingai_shared.domain import Bar, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))
LOT_SIZE = 75
STRIKE_STEP = 50
EOD_SQUAREOFF_MIN = 15 * 60 + 15  # 15:15 IST — flat before close

# Paper account starting balance. Overridable so the desk can be resized without a
# code edit; the whole balance()/available_cash()/equity chain reads this one value.
INITIAL_CAPITAL = float(os.getenv("PRELIVE_INITIAL_CAPITAL", "10000000"))  # ₹1 crore

# Risk-based position sizing: each new position gets a fixed % of starting capital as
# its premium budget (not 1 lot flat) — at ₹1cr/2% that's ₹2L/trade, which the smaller
# ₹1L-basket 1-lot-only design badly under-deployed. Lots are floor(budget/premium/lot),
# capped both by MAX_LOTS and by whatever cash is actually still free.
CAPITAL_PER_TRADE_PCT = float(os.getenv("PRELIVE_CAPITAL_PER_TRADE_PCT", "0.02"))
MAX_LOTS_PER_TRADE = int(os.getenv("PRELIVE_MAX_LOTS_PER_TRADE", "20"))

# Desk-level daily circuit breaker. Each buying position's loss is bounded by construction
# (max loss = premium paid), so this engine never needed one — until a basket of correlated
# strategies all read the market wrong on the same day and ran the DESK to -29% on
# 2026-07-20 with no floor under it. Once the day's loss (realized + open MTM) crosses this
# share of the day's starting equity, the desk opens nothing new for the rest of the
# session; open positions are still managed to their stops/targets/EOD. Mirrors the selling
# desk's breaker, which had this from day one for the same reason.
DAILY_LOSS_BREAKER_PCT = float(os.getenv("PRELIVE_DAILY_LOSS_PCT", "0.04"))

# The live bar-builder (main.py) only ever produces these three intraday timeframes.
# A qualified "1d" (swing) strategy can't run here: its whole model assumes a 30-DTE
# position CARRIED across sessions, which conflicts with this engine's EOD square-off
# — so daily-timeframe rows are skipped with a logged warning, not force-mapped onto
# an intraday timeframe where their indicator math and holding-period logic would break.
SUPPORTED_LIVE_TIMEFRAMES = {"5m", "15m", "1h"}

# Opt-in only: the original hand-picked 20-strategy basket, used solely as a fallback
# when PRELIVE_FALLBACK_TOP20=1 and no qualified sweep exists yet.
TOP20 = [
    ("scalp_ibs", "5m"), ("intra_heikin_trend", "15m"), ("intra_ichimoku_tk", "5m"),
    ("scalp_roc_thrust", "15m"), ("intra_cci_trend", "5m"), ("intra_psar", "15m"),
    ("intra_dema_cross", "15m"), ("swing_fractal", "1h"), ("scalp_atr_burst", "5m"),
    ("intra_keltner_trend", "5m"), ("intra_bb_ride", "5m"), ("scalp_rsi2", "5m"),
    ("intra_donchian", "5m"), ("intra_linreg_slope", "5m"), ("intra_hull_cross", "15m"),
    ("intra_cci_trend", "15m"), ("scalp_psar", "15m"), ("scalp_keltner_surf", "5m"),
    ("scalp_pctb", "5m"), ("scalp_cci_burst", "15m"),
]


def load_qualified_universe() -> tuple[list[tuple[str, str]], dict | None]:
    """Read the latest option_sweeps document and return the (strategy_id, timeframe)
    pairs the live desk should trade — every row marked `in_basket`, that resolves to a
    real registered strategy, on a timeframe this engine's bar-builder can produce.
    Returns (pairs, sweep_meta); sweep_meta is None if no sweep document exists at all.

    `in_basket`, not bare `qualified`: a qualifier can be another survivor wearing a
    different name, and trading the whole qualified set is how six near-identical
    strategies all bought the same 24150PE on 2026-07-20 and turned one wrong read into a
    -29% day. `in_basket` = qualified AND independent (survived the entry-day overlap
    de-dup). Absence of a verdict is treated as absence of approval, exactly as the
    selling desk does: a sweep that predates the de-dup marks nothing `in_basket`, so the
    desk trades nothing until the sweep is re-run rather than silently trading duplicates."""
    doc = option_sweeps_collection.find_one({}, sort=[("created_at", -1)])
    if not doc:
        return [], None

    created_at = doc.get("created_at")
    sweep_meta = {
        "sweep_id": doc.get("sweep_id"),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "symbol": doc.get("symbol"), "qualified_count": doc.get("qualified_count"),
        "basket_count": doc.get("basket_count"),
    }

    pairs: list[tuple[str, str]] = []
    for r in doc.get("results") or []:
        if not r.get("in_basket"):
            continue
        sid, tf = r.get("strategy_id"), r.get("timeframe")
        if sid not in STRATEGY_REGISTRY:
            print(f"[prelive] sweep {sweep_meta['sweep_id']}: skipping {sid}@{tf} — no longer in STRATEGY_REGISTRY", flush=True)
            continue
        if tf not in SUPPORTED_LIVE_TIMEFRAMES:
            print(f"[prelive] sweep {sweep_meta['sweep_id']}: skipping {sid}@{tf} — "
                  f"live desk only supports {sorted(SUPPORTED_LIVE_TIMEFRAMES)} (this is likely a "
                  f"multi-day swing strategy that can't run under EOD square-off)", flush=True)
            continue
        pairs.append((sid, tf))
    if not pairs and doc.get("qualified_count"):
        print(f"[prelive] sweep {sweep_meta['sweep_id']} has {doc['qualified_count']} qualified "
              f"strategies but none marked in_basket — it predates the overlap de-dup. Re-run the "
              f"buying sweep (POST /api/options/backtest-all); trading nothing until then rather "
              f"than trading duplicates.", flush=True)
    return pairs, sweep_meta


def _key(strategy_id: str, tf: str) -> str:
    return f"{strategy_id}@{tf}"


class PaperPosition:
    __slots__ = ("key", "strategy_id", "tf", "option_type", "strike", "security_id",
                 "entry_premium", "entry_ts", "stop_pct", "target_pct", "lots")

    def __init__(self, key, strategy_id, tf, option_type, strike, security_id,
                 entry_premium, entry_ts, stop_pct, target_pct, lots=1):
        self.key = key
        self.strategy_id = strategy_id
        self.tf = tf
        self.option_type = option_type
        self.strike = strike
        self.security_id = security_id
        self.entry_premium = entry_premium
        self.entry_ts = entry_ts
        self.stop_pct = stop_pct
        self.target_pct = target_pct
        self.lots = lots


class PreLiveEngine:
    def __init__(self):
        self.strategies = {}      # key -> Strategy instance
        self.contexts = {}        # key -> StrategyContext
        self.positions = {}       # key -> PaperPosition
        self.trades_today = {}    # key -> count
        self.universe: list[tuple[str, str]] = []
        self.universe_source: dict | None = None
        self._weekly_expiry = None
        self.breaker_tripped = False
        self.breaker_reason: str | None = None
        # A signal that fires but cannot become an order is an execution FAILURE, distinct
        # from a strategy that simply didn't signal. Counted per reason so a zero-trade day
        # can say whether the strategies stayed silent or whether valid signals were dropped
        # by the pipeline — the two used to look identical in the logs.
        self.dropped_signals = {"no_contract": 0, "no_premium": 0, "cant_afford": 0}
        # Deliberate stand-asides (a healthy no-trade), counted separately from execution
        # failures. Regime skips = buying declined because the market was too flat to justify
        # paying theta.
        self.regime_skips = 0
        self.low_vol_regime = self._is_low_vol_regime()
        self.refresh_universe(force=True)
        self._restore_open_positions()
        # Set after restore so a mid-session restart measures the day against the equity it
        # actually started the day with, not a fresh ₹1cr.
        self.day_start_equity = self.balance()["balance"]

    def _restore_open_positions(self) -> None:
        """Rebuild in-memory positions from Mongo on startup. Without this, any
        restart while positions are open orphans their docs forever (the Jul 16
        incident left 3 stuck docs, and the Jul 20 mid-session hotfix restart
        would have orphaned the desk's first-ever real trades). stop/target pcts
        are persisted with the doc; older docs fall back to the default style."""
        from datetime import datetime as _dt
        default = OPTION_BUYING_CATEGORIES["options_intraday"]
        n = 0
        for d in positions_collection.find({}):
            try:
                ts = d.get("entry_ts")
                entry_ts = _dt.fromisoformat(ts) if isinstance(ts, str) else (ts or datetime.now(IST))
                pos = PaperPosition(
                    key=d["key"], strategy_id=d["strategy_id"], tf=d.get("timeframe", "15m"),
                    option_type=d.get("option_type"), strike=d.get("strike"),
                    security_id=d["security_id"], entry_premium=d["entry_premium"],
                    entry_ts=entry_ts,
                    stop_pct=d.get("stop_pct") or default["premium_stop_pct"],
                    target_pct=d.get("target_pct") or default["premium_target_pct"],
                    lots=max(1, int(d.get("qty", LOT_SIZE) // LOT_SIZE)),
                )
                self.positions[pos.key] = pos
                n += 1
            except Exception as e:
                print(f"[warn] could not restore position {d.get('key')}: {e}", flush=True)
        if n:
            print(f"[prelive] restored {n} open position(s) from Mongo", flush=True)

    def refresh_universe(self, force: bool = False) -> None:
        """Reload the qualified (strategy_id, timeframe) universe from the latest
        sweep and rebuild strategy/context slots. Open positions are untouched —
        manage_open() tracks them by key independent of the active universe, so a
        strategy dropped from the qualified set simply stops receiving new signals
        while any position it already opened still gets priced/closed normally.
        prelive_strategy_scores history is never deleted either way.

        `force=False` (used for the idle-loop refresh) skips the rebuild when the
        driving sweep hasn't actually changed, so strategy instances (which hold
        internal regime state like a running direction) aren't pointlessly reset
        every idle tick. `force=True` (used at the start of every session) always
        rebuilds, since a new trading day needs fresh per-strategy state regardless."""
        pairs, meta = load_qualified_universe()
        used_fallback = False
        if not pairs and os.getenv("PRELIVE_FALLBACK_TOP20") == "1":
            pairs, used_fallback = list(TOP20), True
            meta = {"sweep_id": None, "created_at": None, "symbol": "NIFTY",
                    "qualified_count": len(TOP20), "fallback": "TOP20"}

        new_sweep_id = meta.get("sweep_id") if meta else None
        old_sweep_id = self.universe_source.get("sweep_id") if self.universe_source else "__unset__"
        if not force and self.universe and new_sweep_id == old_sweep_id:
            return  # nothing changed since the last refresh — keep existing state

        self.universe = pairs
        self.universe_source = meta
        self._init_strategies()
        label = "TOP20 fallback" if used_fallback else (meta.get("sweep_id") if meta else "none")
        print(f"[prelive] universe refreshed: {len(pairs)} strategy slots (source: {label})", flush=True)

    def _init_strategies(self):
        self.strategies = {}
        self.contexts = {}
        self.trades_today = {}
        for sid, tf in self.universe:
            cls = STRATEGY_REGISTRY.get(sid)
            if cls is None:
                continue
            key = _key(sid, tf)
            self.strategies[key] = cls(params={})
            self.contexts[key] = StrategyContext(max_bars=max(500, cls(params={}).warmup + 5))
            self.trades_today[key] = 0

    # ---- expiry / instrument lookup ---------------------------------------

    def current_weekly_expiry(self) -> str | None:
        """Nearest NIFTY option expiry >= today, cached per day."""
        today = datetime.now(IST).date().isoformat()
        if self._weekly_expiry and self._weekly_expiry[0] == today:
            return self._weekly_expiry[1]
        exps = sorted(
            e for e in instruments_collection.distinct(
                "expiry", {"asset_class": "INDEX_OPTION", "symbol": {"$regex": "^NIFTY-"}})
            if e and e >= today
        )
        exp = exps[0] if exps else None
        self._weekly_expiry = (today, exp)
        return exp

    def atm_contract(self, spot: float, option_type: str) -> dict | None:
        exp = self.current_weekly_expiry()
        if not exp:
            return None
        strike = round(spot / STRIKE_STEP) * STRIKE_STEP
        for widen in range(0, 6):  # nearest listed strike, widen if the exact one is missing
            for s in ({strike} if widen == 0 else {strike + widen * STRIKE_STEP, strike - widen * STRIKE_STEP}):
                doc = instruments_collection.find_one({
                    "asset_class": "INDEX_OPTION", "expiry": exp, "strike": float(s),
                    "option_type": option_type, "symbol": {"$regex": "^NIFTY-"}})
                if doc:
                    return {"security_id": doc["security_id"], "strike": float(s),
                            "exchange_segment": doc["exchange_segment"], "symbol": doc["symbol"]}
        return None

    # ---- balance / capital ------------------------------------------------

    def realized_all_time(self) -> float:
        """Sum of every closed paper trade's P&L — the account's lifetime realized."""
        cur = trades_collection.aggregate([{"$group": {"_id": None, "s": {"$sum": "$pnl"}}}])
        docs = list(cur)
        return round(docs[0]["s"], 2) if docs else 0.0

    def deployed_capital(self) -> float:
        """Premium currently locked in open paper positions."""
        return round(sum(p.entry_premium * LOT_SIZE * p.lots for p in self.positions.values()), 2)

    def available_cash(self) -> float:
        """Cash free to open new positions = starting capital + lifetime realized
        − premium already deployed in open positions."""
        return round(INITIAL_CAPITAL + self.realized_all_time() - self.deployed_capital(), 2)

    def balance(self) -> dict:
        realized = self.realized_all_time()
        deployed = self.deployed_capital()
        return {
            "initial_capital": INITIAL_CAPITAL,
            "realized_all_time": realized,
            "deployed": deployed,
            "available_cash": round(INITIAL_CAPITAL + realized - deployed, 2),
            "balance": round(INITIAL_CAPITAL + realized, 2),  # cash + deployed (excl. open MTM)
        }

    # ---- the driving methods (called by main.py) --------------------------

    def new_session(self):
        """Reset per-day counters + fresh strategy state at market open. Always a
        full rebuild (force=True) — a new trading day needs fresh regime state
        regardless of whether the qualified sweep itself changed overnight."""
        self.refresh_universe(force=True)
        self.day_start_equity = self.balance()["balance"]
        self.breaker_tripped = False
        self.breaker_reason = None
        self.dropped_signals = {"no_contract": 0, "no_premium": 0, "cant_afford": 0}
        self.regime_skips = 0
        self.low_vol_regime = self._is_low_vol_regime()
        if self.low_vol_regime:
            print(f"[prelive] LOW-VOL REGIME — recent NIFTY daily range below "
                  f"{VOL_REGIME_FLOOR_PCT:.2f}%. New option buys stand aside today; buying premium "
                  f"in a flat tape is where 100% of this desk's losses came from.", flush=True)

    def _is_low_vol_regime(self) -> bool:
        """True when NIFTY's recent daily range is below the floor — a flat tape where bought
        premium bleeds to theta faster than direction can pay.

        Derives recent daily ranges by aggregating the 1h series, NOT the 1d series: the 1d
        bars are not reliably maintained (found gapped from 2026-07-16 to 07-27, which made a
        naive 1d lookback read stale higher-range days and fail to gate a flat market), while
        the 1h series is written by the live feed and is continuous. Absence of data returns
        False — never gate the desk off on missing evidence."""
        if VOL_REGIME_FLOOR_PCT <= 0:
            return False
        try:
            rows = list(bars_collection.find(
                {"symbol": "NIFTY", "timeframe": "1h"},
                {"ts": 1, "high": 1, "low": 1, "close": 1, "_id": 0},
            ).sort("ts", -1).limit(80))
        except Exception:
            return False
        # (max high, min low, day-close proxy) per date. Rows are newest-first, so the first
        # 1h bar seen for a date is its last hour — a good close proxy for the % denominator.
        byday: dict[str, list[float]] = {}
        for b in rows:
            try:
                ts = b["ts"]
                d = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
                hi, lo, cl = float(b["high"]), float(b["low"]), float(b["close"])
            except (TypeError, ValueError, KeyError):
                continue
            e = byday.setdefault(d, [hi, lo, cl])
            e[0] = max(e[0], hi)
            e[1] = min(e[1], lo)
        ranges = []
        for d in sorted(byday)[-VOL_REGIME_LOOKBACK_DAYS:]:
            hi, lo, cl = byday[d]
            if cl > 0 and hi >= lo:
                ranges.append(100.0 * (hi - lo) / cl)
        if len(ranges) < max(2, VOL_REGIME_LOOKBACK_DAYS // 2):
            return False  # not enough recent data — don't gate blind
        return (sum(ranges) / len(ranges)) < VOL_REGIME_FLOOR_PCT

    def day_pnl(self, fetch_ltp) -> tuple[float, float]:
        """(realized today, unrealized on open positions). The breaker reads both — a desk
        that only counted realized losses would keep opening new risk while its open book
        bled."""
        session = datetime.now(IST).date().isoformat()
        realized = sum(t["pnl"] for t in trades_collection.find({"session": session}, {"pnl": 1}))
        unrealized = 0.0
        for pos in self.positions.values():
            ltp = fetch_ltp(pos.security_id, "NSE_FNO") or pos.entry_premium
            unrealized += (ltp - pos.entry_premium) * (LOT_SIZE * pos.lots)
        return realized, unrealized

    def check_breaker(self, fetch_ltp) -> bool:
        """Trip the desk-level daily breaker once the day's loss crosses the limit. Stays
        tripped for the rest of the session even if the book recovers — a desk that has
        already had its worst day of the month should not be adding risk to it."""
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
            print(f"[BREAKER] {self.breaker_reason} — no new positions this session", flush=True)
        return self.breaker_tripped

    def _status_label(self, running: bool) -> str:
        if not self.universe:
            return "no_qualified_universe"
        return "running" if running else "idle"

    def _universe_note(self) -> str | None:
        if self.universe:
            return None
        return ("No qualified strategies to trade — the latest options sweep has none, or none "
                "on a live-supported timeframe (5m/15m/1h). Run POST /api/options/backtest-all "
                "to refresh the qualified universe, or set PRELIVE_FALLBACK_TOP20=1 to use the "
                "original 20-strategy basket as a stopgap.")

    def on_bar(self, strategy_id: str, tf: str, bar: Bar, fetch_ltp) -> dict | None:
        """Feed one FINALIZED bar to its strategy; open a paper position on a fresh
        signal. `fetch_ltp(security_id, exchange_segment)` returns the live option LTP.
        Returns a trade-open event dict for logging, or None."""
        key = _key(strategy_id, tf)
        strat = self.strategies.get(key)
        ctx = self.contexts.get(key)
        if strat is None:
            return None
        ctx.push(bar)
        if key in self.positions:
            return None  # already holding — managed by manage_open()
        if self.breaker_tripped:
            return None  # desk-level daily circuit breaker: manage open risk, open nothing new
        if self.trades_today[key] >= 6:
            return None  # generous daily cap safety
        if len(ctx.bars) < strat.warmup:
            return None
        signal = strat.on_bar(ctx)
        if signal is None or signal.signal not in (SignalAction.BUY, SignalAction.SELL):
            return None
        # EOD guard: don't open new positions after square-off time
        if _ist_minutes(bar.ts) >= EOD_SQUAREOFF_MIN:
            return None
        # Regime gate: a real signal fired, but the tape is too flat to pay for the theta a
        # bought option bleeds. Stand aside (a healthy decline, counted separately from
        # execution failures) rather than feed premium to the sellers.
        if self.low_vol_regime:
            self.regime_skips += 1
            return None
        option_type = "CE" if signal.signal == SignalAction.BUY else "PE"
        # Past this point a strategy HAS signalled, so any drop below is an execution
        # failure, not a quiet no-setup. Each is logged and counted so it can never again
        # masquerade as "no signal" in a zero-trade session summary.
        contract = self.atm_contract(bar.close, option_type)
        if not contract:
            self.dropped_signals["no_contract"] += 1
            print(f"[prelive] SIGNAL DROPPED ({strategy_id}@{tf}): no ATM {option_type} contract for "
                  f"expiry {self._weekly_expiry[1] if self._weekly_expiry else '?'} near spot {bar.close:.1f} "
                  f"— check the instruments/scrip master is current", flush=True)
            return None
        premium = fetch_ltp(contract["security_id"], contract["exchange_segment"])
        if not premium or premium <= 0:
            self.dropped_signals["no_premium"] += 1
            print(f"[prelive] SIGNAL DROPPED ({strategy_id}@{tf}): feed returned no premium for "
                  f"{contract['symbol']} (sid {contract['security_id']}) — neither Dhan nor Angel could "
                  f"price this leg this tick", flush=True)
            return None

        one_lot_cost = premium * LOT_SIZE
        budget = INITIAL_CAPITAL * CAPITAL_PER_TRADE_PCT
        lots = max(1, int(budget // one_lot_cost))
        lots = min(lots, MAX_LOTS_PER_TRADE)
        affordable_lots = int(self.available_cash() // one_lot_cost)
        lots = min(lots, affordable_lots)
        if lots < 1:
            self.dropped_signals["cant_afford"] += 1
            print(f"[prelive] SIGNAL DROPPED ({strategy_id}@{tf}): can't afford 1 lot of "
                  f"{contract['symbol']} at premium {premium:.2f} (1 lot = Rs{one_lot_cost:,.0f}, "
                  f"available cash Rs{self.available_cash():,.0f})", flush=True)
            return None  # can't even afford 1 lot at this premium — skip, don't force it

        cat = STRATEGY_REGISTRY[strategy_id].metadata.category
        style = OPTION_BUYING_CATEGORIES.get(cat, OPTION_BUYING_CATEGORIES["options_intraday"])
        pos = PaperPosition(
            key=key, strategy_id=strategy_id, tf=tf, option_type=option_type,
            strike=contract["strike"], security_id=contract["security_id"],
            entry_premium=premium, entry_ts=datetime.now(IST),
            stop_pct=style["premium_stop_pct"], target_pct=style["premium_target_pct"],
            lots=lots,
        )
        self.positions[key] = pos
        self.trades_today[key] += 1
        positions_collection.replace_one({"key": key}, self._pos_doc(pos, premium), upsert=True)
        return {"event": "OPEN", "key": key, "type": option_type, "strike": contract["strike"],
                "premium": premium, "lots": lots, "reason": signal.reasoning}

    def manage_open(self, fetch_ltp, force_eod: bool = False) -> list[dict]:
        """Re-price every open position at its live option LTP; close on stop/target/EOD.
        Returns a list of close events."""
        closes = []
        now = datetime.now(IST)
        # Refresh the desk-level breaker each tick (runs far more often than bar close, so a
        # violent intrabar move stops new entries without waiting for the next 15m bar).
        self.check_breaker(fetch_ltp)
        eod = force_eod or _ist_minutes(now) >= EOD_SQUAREOFF_MIN
        for key, pos in list(self.positions.items()):
            ltp = fetch_ltp(pos.security_id, "NSE_FNO")
            if not ltp or ltp <= 0:
                if not eod:
                    continue
                # EOD square-off must NEVER leave a position stuck open. On
                # 2026-07-16 three positions survived overnight because live
                # pricing was unavailable (429/market closed) at square-off and
                # this loop just skipped them. Close at the last persisted mark
                # (falling back to entry premium) and label the pricing honestly.
                doc = positions_collection.find_one({"key": key}, {"mark": 1}) or {}
                fallback = doc.get("mark") or pos.entry_premium
                closes.append(self._close(pos, fallback, "eod", now, pricing="fallback_last_mark"))
                continue
            # keep the persisted mark current so the dashboard shows live MTM and
            # the EOD fallback above always has a recent price to close against
            qty = LOT_SIZE * pos.lots
            positions_collection.update_one({"key": key}, {"$set": {
                "mark": round(ltp, 2), "unrealized": round((ltp - pos.entry_premium) * qty, 2)}})
            move = (ltp - pos.entry_premium) / pos.entry_premium
            reason = None
            if move >= pos.target_pct:
                reason = "target"
            elif move <= -pos.stop_pct:
                reason = "stop"
            elif eod:
                reason = "eod"
            if reason:
                closes.append(self._close(pos, ltp, reason, now))
        return closes

    def _close(self, pos: PaperPosition, exit_premium: float, reason: str, now,
               pricing: str = "real_dhan_ltp") -> dict:
        qty = LOT_SIZE * pos.lots
        gross = (exit_premium - pos.entry_premium) * qty
        charges = _option_charges(pos.entry_premium, qty) + _option_charges(exit_premium, qty)
        pnl = round(gross - charges, 2)
        trade = {
            "key": pos.key, "strategy_id": pos.strategy_id, "timeframe": pos.tf,
            "option_type": pos.option_type, "strike": pos.strike, "security_id": pos.security_id,
            "entry_premium": round(pos.entry_premium, 2), "exit_premium": round(exit_premium, 2),
            "entry_ts": pos.entry_ts, "exit_ts": now, "exit_reason": reason,
            "qty": qty, "charges": round(charges, 2), "pnl": pnl,
            "session": now.date().isoformat(), "pricing": pricing,
        }
        trades_collection.insert_one(dict(trade))
        positions_collection.delete_one({"key": pos.key})
        del self.positions[pos.key]
        self._update_score(pos.strategy_id, pos.tf, pnl)
        trade["exit_ts"] = now.isoformat()
        trade["entry_ts"] = pos.entry_ts.isoformat()
        trade.pop("_id", None)
        return {"event": "CLOSE", **trade}

    # ---- scoreboard + persistence -----------------------------------------

    def _update_score(self, strategy_id: str, tf: str, pnl: float):
        key = _key(strategy_id, tf)
        doc = scores_collection.find_one({"key": key}) or {
            "key": key, "strategy_id": strategy_id, "timeframe": tf,
            "trades": 0, "wins": 0, "gross_win": 0.0, "gross_loss": 0.0, "net_pnl": 0.0,
        }
        doc["trades"] += 1
        doc["wins"] += 1 if pnl > 0 else 0
        if pnl >= 0:
            doc["gross_win"] += pnl
        else:
            doc["gross_loss"] += -pnl
        doc["net_pnl"] = round(doc["gross_win"] - doc["gross_loss"], 2)
        doc["win_rate"] = round(doc["wins"] / doc["trades"], 4)
        doc["profit_factor"] = round(doc["gross_win"] / doc["gross_loss"], 3) if doc["gross_loss"] > 0 else None
        doc["expectancy"] = round(doc["net_pnl"] / doc["trades"], 2)
        doc["updated_at"] = datetime.now(IST).isoformat()
        doc.pop("_id", None)
        scores_collection.replace_one({"key": key}, doc, upsert=True)

    def _pos_doc(self, pos: PaperPosition, mark: float) -> dict:
        qty = LOT_SIZE * pos.lots
        return {
            "key": pos.key, "strategy_id": pos.strategy_id, "timeframe": pos.tf,
            "option_type": pos.option_type, "strike": pos.strike, "security_id": pos.security_id,
            "entry_premium": round(pos.entry_premium, 2), "mark": round(mark, 2),
            "unrealized": round((mark - pos.entry_premium) * qty, 2),
            "entry_ts": pos.entry_ts.isoformat(), "qty": qty,
            # persisted so a restart can restore exits exactly (see _restore_open_positions)
            "stop_pct": pos.stop_pct, "target_pct": pos.target_pct,
        }

    def snapshot_equity(self, fetch_ltp):
        """Write an intraday equity point: realized today + open MTM."""
        now = datetime.now(IST)
        session = now.date().isoformat()
        realized = sum(t["pnl"] for t in trades_collection.find({"session": session}, {"pnl": 1}))
        unrealized = 0.0
        capital_locked = 0.0
        for pos in self.positions.values():
            ltp = fetch_ltp(pos.security_id, "NSE_FNO") or pos.entry_premium
            qty = LOT_SIZE * pos.lots
            unrealized += (ltp - pos.entry_premium) * qty
            capital_locked += pos.entry_premium * qty
        bal = self.balance()
        equity_value = round(bal["balance"] + unrealized, 2)  # cash + deployed + open MTM
        equity_collection.insert_one({
            "ts": now.isoformat(), "session": session,
            "realized": round(realized, 2), "unrealized": round(unrealized, 2),
            "day_pnl": round(realized + unrealized, 2), "capital_locked": round(capital_locked, 2),
            "open_positions": len(self.positions),
            "equity": equity_value, "available_cash": bal["available_cash"],
        })
        state_collection.replace_one({"_id": "engine"}, {
            "_id": "engine", "heartbeat": now.isoformat(), "session": session,
            "open_positions": len(self.positions), "day_pnl": round(realized + unrealized, 2),
            "capital_locked": round(capital_locked, 2), "status": self._status_label(running=True),
            "initial_capital": INITIAL_CAPITAL, "balance": bal["balance"],
            "equity": equity_value, "available_cash": bal["available_cash"],
            "realized_all_time": bal["realized_all_time"],
            "universe_size": len(self.universe), "universe_source": self.universe_source,
            "capital_per_trade": round(INITIAL_CAPITAL * CAPITAL_PER_TRADE_PCT, 2),
            "breaker_tripped": self.breaker_tripped, "breaker_reason": self.breaker_reason,
            "note": self._universe_note(),
        }, upsert=True)

    def publish_idle_state(self, status: str | None = None):
        """Keep the account balance visible on the dashboard even when the market is
        closed and no session is running. Also re-checks the qualified universe (a
        cheap no-op if the driving sweep hasn't changed) so a freshly-run sweep shows
        up on the dashboard without waiting for the next 09:15 session."""
        self.refresh_universe(force=False)
        bal = self.balance()
        now = datetime.now(IST)
        state_collection.replace_one({"_id": "engine"}, {
            "_id": "engine", "heartbeat": now.isoformat(),
            "status": status or self._status_label(running=False),
            "open_positions": len(self.positions),
            "initial_capital": INITIAL_CAPITAL, "balance": bal["balance"],
            "equity": bal["balance"], "available_cash": bal["available_cash"],
            "realized_all_time": bal["realized_all_time"], "capital_locked": bal["deployed"],
            "universe_size": len(self.universe), "universe_source": self.universe_source,
            "capital_per_trade": round(INITIAL_CAPITAL * CAPITAL_PER_TRADE_PCT, 2),
            "breaker_tripped": self.breaker_tripped, "breaker_reason": self.breaker_reason,
            "note": self._universe_note(),
        }, upsert=True)

    def close_session(self, fetch_ltp):
        """Force EOD square-off of anything still open, write the daily P&L doc."""
        self.manage_open(fetch_ltp, force_eod=True)
        now = datetime.now(IST)
        session = now.date().isoformat()
        trades = list(trades_collection.find({"session": session}))
        net = round(sum(t["pnl"] for t in trades), 2)
        peak_cap = _peak_capital(session)
        daily_pnl_collection.replace_one({"session": session}, {
            "session": session, "trades": len(trades), "net_pnl": net,
            "peak_capital": peak_cap, "roi_pct": round(net / peak_cap * 100, 2) if peak_cap else None,
            "wins": sum(1 for t in trades if t["pnl"] > 0),
            "closed_at": now.isoformat(),
        }, upsert=True)
        state_collection.update_one({"_id": "engine"}, {"$set": {"status": "session_closed"}}, upsert=True)


# ---- module helpers -------------------------------------------------------


def _ist_minutes(ts: datetime) -> int:
    ist = ts.astimezone(IST) if ts.tzinfo else ts
    return ist.hour * 60 + ist.minute


def _option_charges(premium: float, qty: int) -> float:
    """Dhan-style option round-trip components (approx): flat brokerage + STT (sell
    side handled by caller pairing) + exchange + GST. Kept simple; the audited
    backtester's CostModel is the source of truth for research runs."""
    turnover = max(premium, 0.05) * qty
    brokerage = min(20.0, turnover * 0.0003)
    exch = turnover * 0.0003503
    gst = (brokerage + exch) * 0.18
    return brokerage + exch + gst


def _peak_capital(session: str) -> float:
    pts = list(equity_collection.find({"session": session}, {"capital_locked": 1}))
    return round(max((p.get("capital_locked", 0) for p in pts), default=0.0), 2)
