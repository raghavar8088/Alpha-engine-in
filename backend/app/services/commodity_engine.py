"""Commodity Trading desk — the paper engine.

311 pattern strategies (39 templates x 8 timeframes, minus opening-range on daily), each
with its own ₹10,00,000 paper account, trading the 8 front-month MCX futures on live
Angel One prices. Paper only; the point is to find which patterns actually pay before any
real money is put behind them.

THREE THINGS THIS DESK DOES THAT THE PATTERN LITERATURE USUALLY DOESN'T
-----------------------------------------------------------------------
1. **Real MCX charges on every fill.** Commodities are not equities: there is no STT,
   there IS Commodity Transaction Tax (0.01%, sell side, non-agri), the exchange charge
   is different again, and the whole lot attracts GST. Charged here on both sides plus
   slippage, because a 2-ATR target on a 1-minute bar is small enough that costs decide
   whether the pattern is an edge or a subsidy to the broker.
2. **Shorts are real.** These are futures, so a head-and-shoulders SELLS rather than
   being skipped. Testing only the bullish half of a two-sided library would report on
   half the strategy.
3. **Bars come from the store, never inline.** Angel throttles the candle endpoint hard
   (measured: 5 of 8 unpaced requests returned 403), so `commodity_bars` polls on a paced
   background loop and the engine only ever reads what has already landed.

CONCENTRATION
-------------
The universe is 8 contracts and the catalog is 311 strategies, so without a cap a single
gold print could be held by dozens of strategies at once. `MAX_STRATEGIES_PER_SYMBOL`
bounds that, the same lesson the option and momentum desks each had to learn.
"""

import logging
import math
import os
import time as _time
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    commodity_equity_collection,
    commodity_positions_collection,
    commodity_scores_collection,
    commodity_state_collection,
    commodity_trades_collection,
)
from tradingai_shared import mcx_calendar as mcal

from app.services import mcx_market
from app.services.commodity_bars import (
    IST,
    TIMEFRAMES,
    front_month_universe,
    is_market_open,
    last_contract_price,
    load_bars,
)
from app.services.commodity_patterns import (
    COMMODITY_BY_ID,
    COMMODITY_CATALOG,
    FAMILY_LABELS,
    evaluate,
)

logger = logging.getLogger("commodity_engine")

STATE_ID = "commodity"

# ── capital ──────────────────────────────────────────────────────────────────────
PER_STRATEGY_ALLOCATION = float(os.getenv("COMMODITY_PER_STRATEGY_CAPITAL", "1000000"))  # ₹10 lakh
MAX_POSITIONS_PER_STRATEGY = int(os.getenv("COMMODITY_MAX_POSITIONS", "1"))
POSITION_NOTIONAL = PER_STRATEGY_ALLOCATION / max(MAX_POSITIONS_PER_STRATEGY, 1)
INITIAL_CAPITAL = PER_STRATEGY_ALLOCATION * max(len(COMMODITY_CATALOG), 1)

MAX_STRATEGIES_PER_SYMBOL = int(os.getenv("COMMODITY_MAX_PER_SYMBOL", "12"))
# Bars of a strategy's OWN timeframe after which an unresolved position is closed. Scaling
# the hold to the timeframe is the point: 60 bars is an hour on 1m and three months on 1d,
# which is what makes one number sane for a catalog spanning both.
MAX_HOLD_BARS = int(os.getenv("COMMODITY_MAX_HOLD_BARS", "60"))
DAILY_LOSS_BREAKER_PCT = float(os.getenv("COMMODITY_DAILY_LOSS_PCT", "0.03"))
PAUSE_NEW_ENTRIES = os.getenv("COMMODITY_PAUSE_ENTRIES", "0").lower() not in ("0", "false", "")
SLIPPAGE_BPS = float(os.getenv("COMMODITY_SLIPPAGE_BPS", "5"))

# RETIRED TIMEFRAMES take no new entries; their open positions run to their own exits and
# their records stay. Evidence (live record 2026-08-17..10-02): 1m + 5m were 27,642 trades
# and -Rs1.72 cr, 64% of the desk's whole loss. 1m's raw move before slippage and charges
# was -0.1 bp even with the flattering stale fills; honestly filled 5m lost 8.5 bp BEFORE
# costs (t -4.0). A 1m trade was held ~6 minutes while its bars reached the store every 5
# and the desk ticked every 2 — the signal was older than the trade. The strategy ids stay
# in the catalog (ids are positional; removing them would re-label every other record).
RETIRED_TIMEFRAMES = {t.strip() for t in os.getenv("COMMODITY_RETIRED_TIMEFRAMES", "1m,5m").split(",") if t.strip()}
RETIRED_ON = "2026-10-05"
# Every position opened from here carries this, so records can be split at the fix.
DATA_VERSION = 2

# ── MCX charges (non-agri futures) ───────────────────────────────────────────────
# ONE schedule, shared (tradingai_shared.mcx_fees): Angel's card — Rs 20 an order, MCX
# exchange 0.0021% (this desk had 0.0026%, MCX's rate before 2024-10-01), CTT 0.01% on
# sells, stamp 0.002% on buys, SEBI Rs 10/crore, GST 18%. The Pre-Live desk, the Natural
# Gas book and the Gold desk all import `order_charges` from here, so they move together.
from tradingai_shared.mcx_fees import leg_breakdown as _mcx_leg  # noqa: E402


def order_charges(price: float, qty: float, is_buy: bool) -> float:
    """Total MCX charges for one executed side (qty in price units)."""
    return _mcx_leg(price, qty, is_buy)["total"]


# ── promotion gate (same shape as the Momentum desk's) ───────────────────────────
MIN_TRADES_FOR_VERDICT = int(os.getenv("COMMODITY_MIN_TRADES", "30"))
MIN_PROFIT_FACTOR = float(os.getenv("COMMODITY_MIN_PF", "1.2"))
MIN_WIN_RATE = float(os.getenv("COMMODITY_MIN_WIN_RATE", "0.30"))
MAX_DRAWDOWN_PCT = float(os.getenv("COMMODITY_MAX_DD_PCT", "20"))
MIN_T_STAT = float(os.getenv("COMMODITY_MIN_T_STAT", "1.5"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist() -> date:
    return datetime.now(IST).date()


def _session_start_utc() -> datetime:
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _size(price: float, budget: float, cash: float) -> int:
    if price <= 0:
        return 0
    return max(int(min(budget, cash) // price), 0)


# ── capital helpers ──────────────────────────────────────────────────────────────


async def _deployed(strategy_id: str) -> float:
    total = 0.0
    async for p in commodity_positions_collection.find(
        {"strategy_id": strategy_id, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed", 0.0)
    return total


async def _realized(strategy_id: str) -> float:
    total = 0.0
    async for p in commodity_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _available_cash(strategy_id: str) -> float:
    return PER_STRATEGY_ALLOCATION + await _realized(strategy_id) - await _deployed(strategy_id)


async def today_pnl() -> float:
    start = _session_start_utc()
    total = 0.0
    async for p in commodity_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in commodity_positions_collection.find(
        {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}
    ):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state() -> dict:
    pnl = await today_pnl()
    limit = DAILY_LOSS_BREAKER_PCT * INITIAL_CAPITAL
    return {"breaker_tripped": pnl <= -limit, "today_pnl": round(pnl, 2),
            "daily_loss_limit": round(limit, 2), "daily_loss_pct": DAILY_LOSS_BREAKER_PCT}


# ── scoring / verdict ────────────────────────────────────────────────────────────


def _trade_stats(closed: list[dict], base: float | None = None) -> dict:
    """Trade statistics for one record, with drawdown and return measured against `base`.

    `base` defaults to this desk's Rs 10 lakh per-strategy stake. It is a parameter because
    the Pre-Live Commodity desk reuses this function against a Rs 1,00,000 per-CONTRACT
    book: percentage drawdown is meaningless unless it is taken against the capital the
    record was actually run on, and hard-coding Rs 10 lakh there would understate every
    drawdown by a factor of ten."""
    base = PER_STRATEGY_ALLOCATION if base is None else base
    trades = len(closed)
    pnls = [t.get("realized_pnl") or 0.0 for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net, gp, gl = sum(pnls), sum(wins), abs(sum(losses))
    equity = peak = base
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    t_stat = sd = None
    if trades >= 2:
        mean = net / trades
        sd = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (trades - 1))
        if sd > 0:
            t_stat = round(mean / (sd / math.sqrt(trades)), 3)
    return {
        "trades": trades, "wins": len(wins),
        "win_rate": round(len(wins) / trades, 4) if trades else 0.0,
        "net_pnl": round(net, 2), "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
        "total_costs": round(sum(t.get("costs") or 0.0 for t in closed), 2),
        "profit_factor": round(gp / gl, 3) if gl > 0 else None,
        "expectancy": round(net / trades, 2) if trades else 0.0,
        "max_drawdown_pct": round(max_dd, 2), "t_stat": t_stat,
        "pnl_stdev": round(sd, 2) if sd is not None else None,
        "return_pct": round(net / base * 100, 2) if base else 0.0,
    }


def _verdict(s: dict) -> tuple[str, list[str]]:
    if s["trades"] < MIN_TRADES_FOR_VERDICT:
        return "PENDING", [f"{s['trades']}/{MIN_TRADES_FOR_VERDICT} closed trades — not enough evidence yet."]
    fails = []
    if s["net_pnl"] <= 0:
        fails.append(f"Net P&L ₹{s['net_pnl']:,.0f} is not positive after real MCX charges.")
    pf = s["profit_factor"]
    if pf is None and s["gross_loss"] == 0 and s["gross_profit"] > 0:
        pass
    elif pf is None or pf <= MIN_PROFIT_FACTOR:
        fails.append(f"Profit factor {'undefined (no winning trades)' if pf is None else round(pf, 2)} "
                     f"is not above {MIN_PROFIT_FACTOR}.")
    if s["expectancy"] <= 0:
        fails.append(f"Expectancy ₹{s['expectancy']:,.0f} per trade is not positive.")
    if s["win_rate"] < MIN_WIN_RATE:
        fails.append(f"Win rate {s['win_rate']*100:.0f}% is below the {MIN_WIN_RATE*100:.0f}% floor.")
    if s["max_drawdown_pct"] > MAX_DRAWDOWN_PCT:
        fails.append(f"Peak-to-trough drawdown {s['max_drawdown_pct']:.1f}% exceeds {MAX_DRAWDOWN_PCT:.0f}%.")
    t = s["t_stat"]
    if t is None and s.get("pnl_stdev") == 0 and s["net_pnl"] > 0:
        pass
    elif t is None or t < MIN_T_STAT:
        fails.append(f"t-statistic {'undefined' if t is None else round(t, 2)} is below {MIN_T_STAT} — "
                     "this record is not separable from luck yet.")
    if fails:
        return "REJECTED", fails
    return "READY", [
        f"{s['trades']} trades, profit factor {'no losing trades' if pf is None else format(pf, '.2f')}, "
        f"expectancy ₹{s['expectancy']:,.0f}/trade, max drawdown {s['max_drawdown_pct']:.1f}%, "
        f"t-stat {'n/a' if t is None else format(t, '.2f')} — clears the gate net of MCX charges."
    ]


def _record_status(s: dict) -> tuple[str, list[str]]:
    """No promotion from this desk any more — every strategy is a RECORD.

    The READY verdict promoted the luckiest of ~350 strategies (11 of 16 READY lost money
    afterwards; rankings did not persist, Spearman -0.035). A record states what happened
    on honest fills; deciding what deserves money is the Commodity Lab's job, on history it
    did not choose and with the number of tries counted."""
    if s["trades"] < 20:
        return "RECORD", [f"{s['trades']} honest trades — too few for a t-statistic to mean anything."]
    t = s.get("t_stat")
    return "RECORD", [f"{s['trades']} honest trades, net Rs{s['net_pnl']:,.0f}, t {t if t is not None else 'n/a'}. "
                      "A record, not a verdict: with ~350 strategies about 8 clear t > 2 by luck alone. "
                      "Only the Commodity Lab can promote a strategy."]


# Honest trades only: filled at a live quote, MCX open at entry and exit, on their own
# contract (see commodity_records). `record_pnl` is the repriced P&L where the old loop
# closed a trade on the next month's contract.
HONEST = {"honest": True}


async def _update_score(strategy_id: str) -> None:
    spec = COMMODITY_BY_ID.get(strategy_id)
    if spec is None:
        return
    closed = [{"realized_pnl": p.get("record_pnl"), "costs": p.get("costs")}
              async for p in commodity_positions_collection.find(
                  {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}, **HONEST},
                  {"record_pnl": 1, "costs": 1, "closed_at": 1}).sort("closed_at", 1)]
    stats = _trade_stats(closed)
    verdict, reasons = _record_status(stats)
    await commodity_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {"strategy_id": strategy_id, "name": spec.name, "family": spec.family,
                  "family_label": FAMILY_LABELS.get(spec.family, spec.family),
                  "template": spec.template, "timeframe": spec.timeframe, **stats,
                  "allocated_capital": round(PER_STRATEGY_ALLOCATION + stats["net_pnl"], 2),
                  "verdict": verdict, "verdict_reasons": reasons, "updated_at": _now()}},
        upsert=True,
    )


async def rescore_all() -> int:
    """Recompute every strategy's record from honest trades (after a relabel)."""
    n = 0
    for spec in COMMODITY_CATALOG:
        await _update_score(spec.strategy_id)
        n += 1
    return n


# ── position lifecycle ───────────────────────────────────────────────────────────


def signal_key(spec, inst: dict, sig) -> str:
    """One signal's identity: strategy, contract, side and the level it fired at.

    THE CHURN THIS STOPS. A breakout fires at a level that does not move from bar to bar,
    so after a stop-out the very next bar re-offers the same breakout at the same level and
    the desk bought it again — 14,945 of 37,053 closed trades were such repeats (same
    strategy, contract, side and signal price on the same day). The per-bar guard could not
    see them because the bar changes; the level does not."""
    return f"{spec.strategy_id}|{inst.get('expiry')}|{sig.side}|{float(sig.entry):.6g}"


async def _open_position(spec, symbol: str, inst: dict, sig, bar_ts: datetime,
                         quote: "mcx_market.McxQuote | None" = None, key: str | None = None) -> bool:
    if quote is None or not quote.fresh or not quote.ltp:
        return False          # no live market this cycle — no fill is invented
    market = float(quote.ltp)
    if await commodity_positions_collection.count_documents(
        {"strategy_id": spec.strategy_id, "status": "OPEN"}
    ) >= MAX_POSITIONS_PER_STRATEGY:
        return False
    if await commodity_positions_collection.find_one(
        {"strategy_id": spec.strategy_id, "symbol": symbol, "status": "OPEN"}
    ):
        return False
    # FILL AT THE MARKET, NOT AT THE BAR.
    # `sig.entry` is a price off the signal's own candle. On a 1d or 4h timeframe that
    # candle does not move for hours, so entering at it after the market has travelled
    # opens a position already past its own target — the next manage tick then closes it
    # as a "win" and the unchanged bar produces the same signal again. Measured across
    # this desk: 9,652 of 32,796 closed rows were same-day repeats of an identical entry.
    # Target and stop are rescaled by the same ratio so the signal's reward:risk survives.
    slip = SLIPPAGE_BPS / 10000.0
    ref = float(market or 0.0)
    if ref <= 0 or not sig.entry:
        return False          # no tradeable price this cycle — skip rather than invent one
    ratio = ref / float(sig.entry)
    target = float(sig.target) * ratio
    stoploss = float(sig.stoploss) * ratio
    fill = ref * (1 + slip) if sig.side == "BUY" else ref * (1 - slip)
    cash = await _available_cash(spec.strategy_id)
    qty = _size(fill, POSITION_NOTIONAL, cash)
    if qty < 1:
        return False
    entry_costs = order_charges(fill, qty, sig.side == "BUY")
    await commodity_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "strategy_id": spec.strategy_id, "strategy_name": spec.name,
        "family": spec.family, "family_label": FAMILY_LABELS.get(spec.family, spec.family),
        "template": spec.template, "timeframe": spec.timeframe, "pattern": sig.pattern,
        "symbol": symbol, "display_name": inst.get("symbol"),
        "instrument": {"symbol": inst.get("symbol"), "security_id": str(inst.get("security_id")),
                       "angel_token": str(inst.get("angel_token") or inst.get("security_id")),
                       "exchange_segment": inst.get("exchange_segment"), "expiry": inst.get("expiry"),
                       "lot_size": inst.get("lot_size", 1), "underlying_symbol": symbol},
        "side": sig.side, "signal_price": round(sig.entry, 4), "entry_price": round(fill, 4),
        "qty": qty, "capital_deployed": round(fill * qty, 2), "entry_costs": round(entry_costs, 2),
        "target": round(target, 4), "stoploss": round(stoploss, 4),
        "ltp": round(fill, 4), "ltp_source": "market_quote",
        # What the market showed at the fill: the paper fill is LTP +- slippage, and the
        # touch (ask for a buy, bid for a sell) is kept beside it so the real-money price
        # can be measured against the paper one.
        "fill_basis": "market_quote", "entry_quote": quote.as_doc(),
        "entry_touch": quote.touch(sig.side), "entry_spread_bp": (round(quote.spread_bp, 2)
                                                                  if quote.spread_bp is not None else None),
        "session": quote.session, "signal_key": key, "data_version": DATA_VERSION,
        "contract_exit_days": mcx_market.exit_days(symbol),
        "unrealized_pnl": 0.0, "pnl_pct": 0.0, "realized_pnl": None, "costs": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "confidence": round(sig.confidence, 2), "rationale": sig.rationale,
        "entry_bar_ts": bar_ts, "bars_held": 0, "max_hold_bars": MAX_HOLD_BARS,
        "opened_at": _now(), "opened_on": _today_ist().isoformat(),
        "updated_at": _now(), "closed_at": None,
    })
    return True


async def _close(pos: dict, ltp: float, reason: str, quote: "mcx_market.McxQuote | None" = None,
                 exit_basis: str = "market_quote") -> float:
    """Close at `ltp` — always a price of the position's OWN contract.

    `exit_basis` says where that price came from: "market_quote" (a live quote of the
    contract), or "contract_last_bar" / "last_mark" for a contract that has already
    expired and that Angel no longer quotes."""
    slip = SLIPPAGE_BPS / 10000.0 if exit_basis == "market_quote" else 0.0
    is_long = pos["side"] == "BUY"
    fill = ltp * (1 - slip) if is_long else ltp * (1 + slip)
    qty = pos["qty"]
    gross = (fill - pos["entry_price"]) * qty * (1 if is_long else -1)
    costs = (pos.get("entry_costs") or 0.0) + order_charges(fill, qty, not is_long)
    net = gross - costs
    exit_side = "SELL" if is_long else "BUY"
    extra = {
        "exit_basis": exit_basis, "contract_ok": True,
        "exit_quote": quote.as_doc() if quote is not None else None,
        "exit_touch": quote.touch(exit_side) if quote is not None else None,
    }
    # What one real lot of this contract would have made: in at the touch the market showed
    # at entry, out at the touch at exit (a settlement exits at the settlement price),
    # Angel's charges. None for trades from before quotes were recorded.
    from app.services.mcx_risk import real_trade
    real_exit = extra["exit_touch"] or (ltp if exit_basis != "market_quote" else None)
    extra["real"] = real_trade(pos["symbol"], pos["side"], pos.get("entry_touch"), real_exit)
    await commodity_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"],
        "strategy_name": pos["strategy_name"], "family": pos.get("family"),
        "template": pos.get("template"), "timeframe": pos.get("timeframe"),
        "pattern": pos.get("pattern"), "symbol": pos["symbol"], "side": pos["side"],
        "entry_price": pos["entry_price"], "exit_price": round(fill, 4), "qty": qty,
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "realized_pnl": round(net, 2),
        "exit_reason": reason, "rationale": pos.get("rationale"),
        "expiry": (pos.get("instrument") or {}).get("expiry"),
        "data_version": pos.get("data_version"), **extra,
        "opened_at": pos["opened_at"], "closed_at": _now(),
    })
    await commodity_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_price": round(fill, 4), "exit_reason": reason,
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "realized_pnl": round(net, 2),
        "unrealized_pnl": 0.0, "closed_at": _now(), "updated_at": _now(), "ltp": round(ltp, 4),
        **extra,
    }})
    from app.services.commodity_records import label_one
    await label_one(pos["_id"])
    return net


# ── cycles ───────────────────────────────────────────────────────────────────────


async def scan_cycle() -> dict:
    notes: list[str] = []
    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {"opened": 0, "evaluated": 0, "notes": [
            f"DAILY LOSS BREAKER TRIPPED — today's P&L ₹{breaker['today_pnl']:,.0f} crossed the "
            f"₹{breaker['daily_loss_limit']:,.0f} limit. No new positions; open ones still managed."]}

    universe = await front_month_universe()
    if not universe:
        return {"opened": 0, "evaluated": 0,
                "notes": ["No unexpired MCX front-month futures with an Angel token on file."]}

    holders: dict[str, int] = {}
    async for p in commodity_positions_collection.find({"status": "OPEN"}, {"symbol": 1}):
        holders[p["symbol"]] = holders.get(p["symbol"], 0) + 1

    by_tf: dict[str, list] = {}
    for spec in COMMODITY_CATALOG:
        by_tf.setdefault(spec.timeframe, []).append(spec)

    # One FULL quote per contract for the whole sweep: last price, the two-sided book and
    # the time of the last trade. A contract whose quote is frozen (no trade this session,
    # or none for MCX_STALE_AFTER_MIN) is skipped outright — on 2026-10-02 the old LTP-only
    # quote kept answering with the previous day's price and the desk traded on it all day.
    qmap = await mcx_market.quotes(list(universe.values()))
    market: dict[str, mcx_market.McxQuote] = {}
    frozen: list[str] = []
    for _sym, _inst in universe.items():
        q = qmap.get(str(_inst.get("angel_token") or _inst.get("security_id")))
        if q is not None and q.fresh:
            market[_sym] = q
        else:
            frozen.append(f"{_sym} ({q.why if q else 'no quote'})")

    # ONE ENTRY PER (strategy, contract) PER BAR. Without it an unchanged 1d/4h candle
    # re-offers the same signal on every 2-minute tick.
    bar_state = await commodity_state_collection.find_one({"_id": "entry_bars"}) or {}
    last_entry_bar: dict = bar_state.get("last", {})
    fresh_bars: dict[str, str] = {}
    # ...and ONE ENTRY PER SIGNAL PER DAY (see `signal_key`).
    today = _today_ist().isoformat()
    sk_doc = await commodity_state_collection.find_one({"_id": "signal_keys"}) or {}
    traded_keys: set[str] = set(sk_doc.get("keys", [])) if sk_doc.get("date") == today else set()
    new_keys: list[str] = []

    opened = evaluated = capped = repeats = 0
    retired = 0
    thin: list[str] = []
    for tf, specs in by_tf.items():
        if tf in RETIRED_TIMEFRAMES:
            retired += len(specs)
            continue
        need = max(s.min_bars for s in specs) + 5
        for symbol, inst in universe.items():
            q = market.get(symbol)
            if q is None:
                continue
            # Closed bars only, on one back-adjusted series that ends on THIS contract.
            bars = await load_bars(symbol, tf, limit=max(need, 250), closed_only=True,
                                   prefer_expiry=inst.get("expiry"))
            if len(bars) < need:
                thin.append(f"{symbol}/{tf}({len(bars)})")
                continue
            bar_ts = bars[-1].ts
            for spec in specs:
                if holders.get(symbol, 0) >= MAX_STRATEGIES_PER_SYMBOL:
                    capped += 1
                    break
                guard = f"{spec.strategy_id}:{symbol}"
                if last_entry_bar.get(guard) == str(bar_ts):
                    continue
                evaluated += 1
                sig = evaluate(spec, bars)
                if sig is None:
                    continue
                fresh_bars[guard] = str(bar_ts)
                key = signal_key(spec, inst, sig)
                if key in traded_keys:
                    repeats += 1
                    continue
                if await _open_position(spec, symbol, inst, sig, bar_ts, q, key):
                    opened += 1
                    holders[symbol] = holders.get(symbol, 0) + 1
                    traded_keys.add(key)
                    new_keys.append(key)
    if fresh_bars:
        await commodity_state_collection.update_one(
            {"_id": "entry_bars"},
            {"$set": {f"last.{k}": v for k, v in fresh_bars.items()}}, upsert=True)
    if new_keys:
        if sk_doc.get("date") == today:
            await commodity_state_collection.update_one(
                {"_id": "signal_keys"}, {"$addToSet": {"keys": {"$each": new_keys}}}, upsert=True)
        else:
            await commodity_state_collection.update_one(
                {"_id": "signal_keys"}, {"$set": {"date": today, "keys": new_keys}}, upsert=True)

    if frozen:
        notes.append(f"No entries on {len(frozen)} contract(s) — quote not live: {', '.join(frozen[:6])}"
                     f"{'…' if len(frozen) > 6 else ''}")
    if retired:
        notes.append(f"{retired} strategies on retired timeframes ({', '.join(sorted(RETIRED_TIMEFRAMES))}) "
                     f"take no new entries since {RETIRED_ON}; their records stay.")
    if repeats:
        notes.append(f"{repeats} repeat signal(s) skipped — the same strategy, contract, side and level "
                     "already traded today.")
    if thin:
        notes.append(f"{len(thin)} (symbol, timeframe) series had too few bars to evaluate — "
                     f"the store is still filling: {', '.join(thin[:8])}"
                     f"{'…' if len(thin) > 8 else ''}")
    if capped:
        notes.append(f"{capped} signals were withheld because their contract already had "
                     f"{MAX_STRATEGIES_PER_SYMBOL} strategies in it — an 8-contract universe "
                     "against 311 strategies concentrates fast without this cap.")
    return {"opened": opened, "evaluated": evaluated, "notes": notes}


async def settle_expired(pos: dict, reason: str = "contract_expired") -> float | None:
    """Close a position whose contract has already expired, at that contract's last price.

    Angel quotes nothing for an expired token, so the price is the store's last bar of
    THAT contract, else the position's own last mark. Never the next contract's price —
    that is the roll bug this replaces (148 trades closed on a different contract)."""
    inst = pos.get("instrument") or {}
    got = await last_contract_price(pos["symbol"], inst.get("expiry")) if inst.get("expiry") else None
    if got:
        price, basis = got[0], "contract_last_bar"
    elif pos.get("ltp"):
        price, basis = float(pos["ltp"]), "last_mark"
    else:
        return None
    return await _close(pos, price, reason, None, exit_basis=basis)


async def manage_cycle() -> int:
    """Mark and exit every open position ON ITS OWN CONTRACT.

    The old loop priced a position at its underlying's CURRENT front month. After a roll
    that is another contract, so a position opened on COPPER-Sep was valued, stopped out or
    "won" on COPPER-Oct's price — the calendar spread booked as a move. Now:
      * the contract stamped on the position is the one quoted;
      * a contract inside its exit window (delivery tender days for bullion and base
        metals, the last two sessions for energy) is closed at its own price ("roll_exit");
      * a contract already expired is settled at its last recorded price;
      * a frozen quote (market shut, or no trade for MCX_STALE_AFTER_MIN) moves nothing —
        no stop or target fires on a price nobody is trading at."""
    open_positions = [p async for p in commodity_positions_collection.find({"status": "OPEN"})]
    if not open_positions:
        return 0
    today = mcal.as_date(None)
    qmap = await mcx_market.quotes([mcx_market.position_contract(p) for p in open_positions])

    updated = 0
    touched: set[str] = set()
    for pos in open_positions:
        forced = mcx_market.forced_exit(pos, today)
        if forced == "contract_expired":
            if await settle_expired(pos) is not None:
                touched.add(pos["strategy_id"])
            continue
        q = qmap.get(mcx_market.position_token(pos))
        if q is None or not q.fresh or not q.ltp:
            await commodity_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
                "quote_status": (q.why if q else "no quote"), "updated_at": _now()}})
            continue
        ltp, src = float(q.ltp), "market_quote"
        is_long = pos["side"] == "BUY"
        qty = pos["qty"]
        gross = (ltp - pos["entry_price"]) * qty * (1 if is_long else -1)
        projected = (pos.get("entry_costs") or 0.0) + order_charges(ltp, qty, not is_long)
        unrealized = gross - projected

        # Bars elapsed on this position's OWN timeframe.
        tf_minutes = TIMEFRAMES.get(pos.get("timeframe", "1d"), (None, 1440))[1]
        entry_ts = pos.get("entry_bar_ts")
        if entry_ts is not None and entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
        bars_held = 0
        if entry_ts is not None:
            bars_held = mcal.bars_elapsed(entry_ts, tf_minutes)  # trading time, not wall clock

        changes = {"ltp": round(ltp, 4), "ltp_source": src, "unrealized_pnl": round(unrealized, 2),
                   "pnl_pct": round((ltp - pos["entry_price"]) / pos["entry_price"] * 100 * (1 if is_long else -1), 3)
                   if pos["entry_price"] else 0.0,
                   "bars_held": bars_held, "updated_at": _now(), "quote_status": "live"}

        hit_target = ltp >= pos["target"] if is_long else ltp <= pos["target"]
        hit_stop = ltp <= pos["stoploss"] if is_long else ltp >= pos["stoploss"]
        expired = bars_held >= pos.get("max_hold_bars", MAX_HOLD_BARS)
        reason = ("target" if hit_target else "stoploss" if hit_stop
                  else "max_hold_expired" if expired else forced)       # forced = "roll_exit" or None

        await commodity_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
        if reason:
            await _close({**pos, **changes}, ltp, reason, q)
            touched.add(pos["strategy_id"])
        updated += 1

    for sid in touched:
        await _update_score(sid)
    return updated


# ── read models ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    # SUMMED AND COUNTED IN MONGO, IN ONE PASS.
    #
    # The closed leg used to stream all 29,000 documents just to add two numbers, which is
    # what kept this endpoint at 20 seconds even after the collection was indexed — an
    # index makes a scan findable, not cheap. Splitting that into two $group stages fixed
    # the streaming but still walked the collection twice, and the two count_documents
    # below walked it twice more; `{"$ne": "OPEN"}` cannot use the status index, so each
    # count was a full scan to produce one integer. Four passes, one $group.
    totals = {"deployed": 0.0, "unrealized": 0.0, "open_costs": 0.0,
              "realized": 0.0, "closed_costs": 0.0, "open_n": 0, "closed_n": 0}
    _open = {"$eq": ["$status", "OPEN"]}
    async for g in commodity_positions_collection.aggregate([
        {"$group": {
            "_id": None,
            "deployed": {"$sum": {"$cond": [_open, {"$ifNull": ["$capital_deployed", 0.0]}, 0.0]}},
            "unrealized": {"$sum": {"$cond": [_open, {"$ifNull": ["$unrealized_pnl", 0.0]}, 0.0]}},
            "open_costs": {"$sum": {"$cond": [_open, {"$ifNull": ["$entry_costs", 0.0]}, 0.0]}},
            "realized": {"$sum": {"$cond": [_open, 0.0, {"$ifNull": ["$realized_pnl", 0.0]}]}},
            "closed_costs": {"$sum": {"$cond": [_open, 0.0, {"$ifNull": ["$costs", 0.0]}]}},
            "open_n": {"$sum": {"$cond": [_open, 1, 0]}},
            "closed_n": {"$sum": {"$cond": [_open, 0, 1]}},
        }},
    ]):
        totals.update({k: g.get(k, totals[k]) for k in totals})
    deployed = totals["deployed"]
    unrealized = totals["unrealized"]
    realized = totals["realized"]
    costs = totals["open_costs"] + totals["closed_costs"]
    open_n, closed_n = totals["open_n"], totals["closed_n"]

    # One row per verdict instead of one document per strategy.
    verdicts = {"READY": 0, "REJECTED": 0, "PENDING": 0}
    scored = 0
    async for g in commodity_scores_collection.aggregate([
        {"$group": {"_id": "$verdict", "n": {"$sum": 1}}},
    ]):
        v = g["_id"] or "PENDING"
        verdicts[v] = verdicts.get(v, 0) + g["n"]
        scored += g["n"]
    verdicts["PENDING"] += len(COMMODITY_CATALOG) - scored

    return {
        "initial_capital": INITIAL_CAPITAL,
        "per_strategy_allocation": round(PER_STRATEGY_ALLOCATION, 2),
        "position_notional": round(POSITION_NOTIONAL, 2),
        "strategy_count": len(COMMODITY_CATALOG),
        "available_cash": round(INITIAL_CAPITAL + realized - deployed, 2),
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "total_costs": round(costs, 2),
        "equity": round(INITIAL_CAPITAL + realized + unrealized, 2),
        "open_positions": open_n,
        "closed_positions": closed_n,
        "ready_count": verdicts.get("READY", 0), "rejected_count": verdicts.get("REJECTED", 0),
        "pending_count": verdicts.get("PENDING", 0),
        "paused": PAUSE_NEW_ENTRIES, "mode": "paper", "costs_charged": True,
        "slippage_bps": SLIPPAGE_BPS, "market_open": is_market_open(),
        "max_strategies_per_symbol": MAX_STRATEGIES_PER_SYMBOL,
        "promotion_gate": {"min_trades": MIN_TRADES_FOR_VERDICT, "min_profit_factor": MIN_PROFIT_FACTOR,
                           "min_win_rate": MIN_WIN_RATE, "max_drawdown_pct": MAX_DRAWDOWN_PCT,
                           "min_t_stat": MIN_T_STAT},
        **(await breaker_state()),
    }


async def leaderboard() -> list[dict]:
    scores = {s["strategy_id"]: s async for s in commodity_scores_collection.find({})}
    open_counts: dict[str, int] = {}
    async for p in commodity_positions_collection.find({"status": "OPEN"}, {"strategy_id": 1}):
        open_counts[p["strategy_id"]] = open_counts.get(p["strategy_id"], 0) + 1
    rows = []
    for spec in COMMODITY_CATALOG:
        sc = scores.get(spec.strategy_id) or {}
        net = sc.get("net_pnl", 0.0) or 0.0
        rows.append({
            "strategy_id": spec.strategy_id, "name": spec.name, "family": spec.family,
            "family_label": FAMILY_LABELS.get(spec.family, spec.family),
            "template": spec.template, "timeframe": spec.timeframe,
            "trades": sc.get("trades", 0) or 0, "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(net, 2), "total_costs": sc.get("total_costs", 0.0) or 0.0,
            "profit_factor": sc.get("profit_factor"), "expectancy": sc.get("expectancy", 0.0) or 0.0,
            "max_drawdown_pct": sc.get("max_drawdown_pct", 0.0) or 0.0, "t_stat": sc.get("t_stat"),
            "return_pct": sc.get("return_pct", 0.0) or 0.0,
            "allocated_capital": round(PER_STRATEGY_ALLOCATION + net, 2),
            "open_positions": open_counts.get(spec.strategy_id, 0),
            "verdict": sc.get("verdict", "PENDING"),
            "verdict_reasons": sc.get("verdict_reasons",
                                      [f"0/{MIN_TRADES_FOR_VERDICT} closed trades — not enough evidence yet."]),
        })
    rows.sort(key=lambda r: (r["verdict"] != "READY", -r["net_pnl"]))
    return rows


async def ensure_indexes() -> None:
    """Index the desk's collections.

    THIS COLLECTION HAD NO INDEXES AT ALL. Measured on 29,192 documents: a bare
    `count_documents({})` took 21.4 seconds and streaming the collection blew the 45-second
    socket timeout, which took the whole Commodity Trading page down. Every query in this
    module was a full scan; it only became fatal once the collection grew past ~25k rows.

    `strategy_id + symbol` is the shape the per-script leaderboard groups on, and `status`
    the one every open-position pass filters by.
    """
    from pymongo import ASCENDING

    async def _try(coll, keys, **kw):
        try:
            await coll.create_index(keys, background=True, **kw)
        except Exception as exc:  # noqa: BLE001 — an index that exists is not an error
            logger.info("commodity index %s: %s", keys, str(exc)[:120])

    await _try(commodity_positions_collection,
               [("strategy_id", ASCENDING), ("symbol", ASCENDING)])
    await _try(commodity_positions_collection, [("status", ASCENDING)])
    await _try(commodity_positions_collection,
               [("symbol", ASCENDING), ("status", ASCENDING)])
    await _try(commodity_positions_collection, [("opened_at", ASCENDING)])
    await _try(commodity_trades_collection, [("strategy_id", ASCENDING)])
    await _try(commodity_trades_collection, [("symbol", ASCENDING)])
    await _try(commodity_scores_collection, [("strategy_id", ASCENDING)], unique=False)
    logger.info("commodity desk indexes ensured")


# ── per-underlying leaderboard ───────────────────────────────────────────────────
# WHY THIS IS COMPUTED RATHER THAN READ. `commodity_scores_collection` holds ONE blended
# record per strategy — every underlying pooled. That is what the main board shows, and it
# answers a different question from the one people ask of it: "Opening Range Breakout 30m
# is READY" is true of a book dominated by copper, gold, silver and zinc, and false of
# crude oil, where the same strategy is 4 trades and negative.
#
# So the per-script view recomputes the stats from the positions themselves and re-runs the
# SAME gate. A verdict here means "clears the gate ON THIS CONTRACT", which is the only
# reading that supports putting money on one.

_SCRIPT_CACHE: dict | None = None
_SCRIPT_CACHE_AT: float = 0.0
SCRIPT_CACHE_TTL = float(os.getenv("COMMODITY_SCRIPT_TTL", "300"))


async def _script_stats(fresh: bool = False) -> dict:
    """{underlying: {strategy_id: stats}} plus per-underlying totals.

    One pass over every position, grouped in memory. Twenty-odd thousand closed rows is
    a single projected read; doing it per underlying would be eight.
    """
    global _SCRIPT_CACHE, _SCRIPT_CACHE_AT
    now = _time.monotonic()
    if not fresh and _SCRIPT_CACHE and now - _SCRIPT_CACHE_AT < SCRIPT_CACHE_TTL:
        return _SCRIPT_CACHE

    closed: dict[tuple[str, str], list[dict]] = {}
    open_counts: dict[tuple[str, str], int] = {}
    unreal: dict[str, float] = {}
    deployed: dict[str, float] = {}

    # GROUPED IN MONGO, NOT STREAMED. Pulling all 29,000 documents to Python is what made
    # this endpoint exceed the socket timeout and hang the page. Grouping server-side
    # returns roughly 3,500 rows — one per (strategy, contract) — and only the two fields
    # the stats actually need, so the wire carries a fraction of the bytes.
    #
    # `realized_pnl` is pushed as an ARRAY rather than summed: max drawdown, standard
    # deviation and the t-statistic all need the individual trade results, not a total.
    async for g in commodity_positions_collection.aggregate([
        {"$match": {"status": {"$ne": "OPEN"}, **HONEST}},
        {"$group": {"_id": {"s": "$strategy_id", "y": "$symbol"},
                    "pnls": {"$push": {"$ifNull": ["$record_pnl", 0.0]}},
                    "costs": {"$sum": {"$ifNull": ["$costs", 0.0]}}}},
    ]):
        sid, sym = g["_id"].get("s"), g["_id"].get("y")
        if not sid or not sym:
            continue
        closed[(sid, sym)] = [{"realized_pnl": v} for v in g["pnls"]]
        closed[(sid, sym)][0]["costs"] = g.get("costs", 0.0)

    async for g in commodity_positions_collection.aggregate([
        {"$match": {"status": "OPEN"}},
        {"$group": {"_id": {"s": "$strategy_id", "y": "$symbol"},
                    "n": {"$sum": 1},
                    "unreal": {"$sum": {"$ifNull": ["$unrealized_pnl", 0.0]}},
                    "deployed": {"$sum": {"$ifNull": ["$capital_deployed", 0.0]}}}},
    ]):
        sid, sym = g["_id"].get("s"), g["_id"].get("y")
        if not sid or not sym:
            continue
        open_counts[(sid, sym)] = g["n"]
        unreal[sym] = unreal.get(sym, 0.0) + float(g.get("unreal") or 0.0)
        deployed[sym] = deployed.get(sym, 0.0) + float(g.get("deployed") or 0.0)

    symbols = sorted({sym for _sid, sym in closed} | {sym for _sid, sym in open_counts})
    out: dict = {"symbols": symbols, "per_symbol": {}, "totals": {}}
    for sym in symbols:
        rows: dict[str, dict] = {}
        for spec in COMMODITY_CATALOG:
            key = (spec.strategy_id, sym)
            trades = closed.get(key, [])
            opens = open_counts.get(key, 0)
            if not trades and not opens:
                continue          # this strategy has never touched this contract
            st = _trade_stats(trades)
            verdict, reasons = _record_status(st)
            rows[spec.strategy_id] = {**st, "verdict": verdict, "verdict_reasons": reasons,
                                      "open_positions": opens}
        v = {"READY": 0, "REJECTED": 0, "PENDING": 0, "RECORD": 0}
        for r in rows.values():
            v[r["verdict"]] = v.get(r["verdict"], 0) + 1
        out["per_symbol"][sym] = rows
        out["totals"][sym] = {
            "strategies_traded": len(rows),
            "closed_trades": sum(r["trades"] for r in rows.values()),
            "open_positions": sum(r["open_positions"] for r in rows.values()),
            "realised_pnl": round(sum(r["net_pnl"] for r in rows.values()), 2),
            "unrealised_pnl": round(unreal.get(sym, 0.0), 2),
            "deployed": round(deployed.get(sym, 0.0), 2),
            "total_costs": round(sum(r["total_costs"] for r in rows.values()), 2),
            "ready": v["READY"], "rejected": v["REJECTED"], "pending": v["PENDING"],
            "profitable": sum(1 for r in rows.values() if r["net_pnl"] > 0),
        }

    _SCRIPT_CACHE, _SCRIPT_CACHE_AT = out, now
    return out


async def script_overview(fresh: bool = False) -> dict:
    """One row per underlying: how the whole desk did on that contract."""
    stats = await _script_stats(fresh)
    rows = []
    for sym in stats["symbols"]:
        t = stats["totals"][sym]
        rows.append({"symbol": sym, **t,
                     "net_pnl": round(t["realised_pnl"] + t["unrealised_pnl"], 2)})
    rows.sort(key=lambda r: -r["net_pnl"])
    return {
        "rows": rows,
        "gate": {"min_trades": MIN_TRADES_FOR_VERDICT, "min_profit_factor": MIN_PROFIT_FACTOR,
                 "min_win_rate": MIN_WIN_RATE, "max_drawdown_pct": MAX_DRAWDOWN_PCT,
                 "min_t_stat": MIN_T_STAT},
        "note": ("Each strategy trades every contract, so these are the same 353 strategies "
                 "measured separately on each one. A verdict here is per-contract and does "
                 "not follow the blended board."),
    }


async def script_leaderboard(symbol: str, fresh: bool = False) -> dict:
    """The leaderboard for ONE underlying, with the gate re-run on that contract alone."""
    sym = (symbol or "").strip().upper()
    stats = await _script_stats(fresh)
    if sym not in stats["per_symbol"]:
        return {"symbol": sym, "rows": [], "totals": {},
                "available": stats["symbols"],
                "error": f"No positions on record for {sym!r}."}

    per = stats["per_symbol"][sym]
    rows = []
    for spec in COMMODITY_CATALOG:
        r = per.get(spec.strategy_id)
        if not r:
            continue
        rows.append({
            "strategy_id": spec.strategy_id, "name": spec.name, "family": spec.family,
            "family_label": FAMILY_LABELS.get(spec.family, spec.family),
            "template": spec.template, "timeframe": spec.timeframe,
            "symbol": sym,
            **{k: r[k] for k in ("trades", "win_rate", "net_pnl", "total_costs",
                                 "profit_factor", "expectancy", "max_drawdown_pct",
                                 "t_stat", "return_pct", "verdict", "verdict_reasons",
                                 "open_positions")},
        })
    rows.sort(key=lambda r: (r["verdict"] != "READY", -r["net_pnl"]))
    return {"symbol": sym, "rows": rows, "totals": stats["totals"][sym],
            "available": stats["symbols"],
            "note": (f"Stats and the promotion gate recomputed on {sym} trades only — this "
                     f"is NOT the blended verdict from the main board.")}


async def run_cycle() -> dict:
    managed = await manage_cycle()
    if PAUSE_NEW_ENTRIES:
        scan = {"opened": 0, "evaluated": 0,
                "notes": ["Commodity entries are paused (COMMODITY_PAUSE_ENTRIES=1); open positions still managed."]}
    else:
        scan = await scan_cycle()
    snap = await summary()
    await commodity_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "deployed": snap["deployed_capital"],
        "open_positions": snap["open_positions"],
    })
    await commodity_state_collection.update_one({"_id": STATE_ID}, {"$set": {
        "last_run_at": _now(), "last_opened": scan["opened"], "last_managed": managed,
        "last_evaluated": scan["evaluated"], "last_notes": scan["notes"],
        "market_open": is_market_open(), "paused": PAUSE_NEW_ENTRIES,
    }}, upsert=True)
    return {"opened": scan["opened"], "managed": managed, "evaluated": scan["evaluated"],
            "notes": scan["notes"]}
