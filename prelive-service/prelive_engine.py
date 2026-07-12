"""Pre-Live paper-trading engine for the top-20 NIFTY option-buying basket.

Mirrors antigravity's `pre_live` desk: consumes REAL market data, executes on a PAPER
account (no real Dhan orders), and keeps a per-strategy scoreboard so any promotion to
live rests on a forward paper track record — not just backtests.

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

from datetime import datetime, timedelta, timezone

from db import (
    daily_pnl_collection,
    equity_collection,
    instruments_collection,
    positions_collection,
    scores_collection,
    state_collection,
    trades_collection,
)

from options_service.options_backtest import OPTION_BUYING_CATEGORIES
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
from tradingai_shared.domain import Bar, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))
LOT_SIZE = 75
STRIKE_STEP = 50
EOD_SQUAREOFF_MIN = 15 * 60 + 15  # 15:15 IST — flat before close
INITIAL_CAPITAL = 100_000.0       # paper account starting balance (₹1 lakh)

# The audited top-20 basket (strategy_id, timeframe). One paper position max per row.
TOP20 = [
    ("scalp_ibs", "5m"), ("intra_heikin_trend", "15m"), ("intra_ichimoku_tk", "5m"),
    ("scalp_roc_thrust", "15m"), ("intra_cci_trend", "5m"), ("intra_psar", "15m"),
    ("intra_dema_cross", "15m"), ("swing_fractal", "1h"), ("scalp_atr_burst", "5m"),
    ("intra_keltner_trend", "5m"), ("intra_bb_ride", "5m"), ("scalp_rsi2", "5m"),
    ("intra_donchian", "5m"), ("intra_linreg_slope", "5m"), ("intra_hull_cross", "15m"),
    ("intra_cci_trend", "15m"), ("scalp_psar", "15m"), ("scalp_keltner_surf", "5m"),
    ("scalp_pctb", "5m"), ("scalp_cci_burst", "15m"),
]


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
        self._weekly_expiry = None
        self._init_strategies()

    def _init_strategies(self):
        for sid, tf in TOP20:
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
        """Reset per-day counters + fresh strategy state at market open."""
        self._init_strategies()

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
        option_type = "CE" if signal.signal == SignalAction.BUY else "PE"
        contract = self.atm_contract(bar.close, option_type)
        if not contract:
            return None
        premium = fetch_ltp(contract["security_id"], contract["exchange_segment"])
        if not premium or premium <= 0:
            return None
        debit = premium * LOT_SIZE  # 1 lot
        if debit > self.available_cash():
            return None  # not enough paper balance free to take this position
        cat = STRATEGY_REGISTRY[strategy_id].metadata.category
        style = OPTION_BUYING_CATEGORIES.get(cat, OPTION_BUYING_CATEGORIES["options_intraday"])
        pos = PaperPosition(
            key=key, strategy_id=strategy_id, tf=tf, option_type=option_type,
            strike=contract["strike"], security_id=contract["security_id"],
            entry_premium=premium, entry_ts=datetime.now(IST),
            stop_pct=style["premium_stop_pct"], target_pct=style["premium_target_pct"],
        )
        self.positions[key] = pos
        self.trades_today[key] += 1
        positions_collection.replace_one({"key": key}, self._pos_doc(pos, premium), upsert=True)
        return {"event": "OPEN", "key": key, "type": option_type, "strike": contract["strike"],
                "premium": premium, "reason": signal.reasoning}

    def manage_open(self, fetch_ltp, force_eod: bool = False) -> list[dict]:
        """Re-price every open position at its live option LTP; close on stop/target/EOD.
        Returns a list of close events."""
        closes = []
        now = datetime.now(IST)
        eod = force_eod or _ist_minutes(now) >= EOD_SQUAREOFF_MIN
        for key, pos in list(self.positions.items()):
            ltp = fetch_ltp(pos.security_id, "NSE_FNO")
            if not ltp or ltp <= 0:
                continue
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

    def _close(self, pos: PaperPosition, exit_premium: float, reason: str, now) -> dict:
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
            "session": now.date().isoformat(), "pricing": "real_dhan_ltp",
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
            "capital_locked": round(capital_locked, 2), "status": "running",
            "initial_capital": INITIAL_CAPITAL, "balance": bal["balance"],
            "equity": equity_value, "available_cash": bal["available_cash"],
            "realized_all_time": bal["realized_all_time"],
        }, upsert=True)

    def publish_idle_state(self, status: str = "idle"):
        """Keep the account balance visible on the dashboard even when the market is
        closed and no session is running."""
        bal = self.balance()
        now = datetime.now(IST)
        state_collection.replace_one({"_id": "engine"}, {
            "_id": "engine", "heartbeat": now.isoformat(), "status": status,
            "open_positions": len(self.positions),
            "initial_capital": INITIAL_CAPITAL, "balance": bal["balance"],
            "equity": bal["balance"], "available_cash": bal["available_cash"],
            "realized_all_time": bal["realized_all_time"], "capital_locked": bal["deployed"],
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
