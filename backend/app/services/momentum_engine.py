"""Momentum Trading desk — the pre-live paper engine.

WHAT THIS DESK IS FOR
----------------------
It is a **gate**, not a strategy. Every strategy in `momentum_strategies.MOMENTUM_CATALOG`
gets its own ₹10,000 paper account and trades the live Angel One equity feed. A strategy
that clears the promotion gate (`_verdict`) has earned a look at real money on the Live
Trading desk; one that does not, has not. Nothing here places a real order.

THREE DESIGN CHOICES THAT COME STRAIGHT FROM THIS APP'S OWN LOSSES
-------------------------------------------------------------------
1. **Fills are charged real Indian transaction costs.** The Intraday Lab desk charged
   ZERO costs on paper fills, so its paper P&L was not evidence of anything — and when
   the same catalog met a fee-honest daily-bar backtest, 16 of 16 measurable strategies
   lost, with gross +₹128k swamped by ₹1.48m of costs. A pre-live gate whose P&L is gross
   cannot answer the only question being asked of it. Every close here nets off brokerage,
   STT, exchange and SEBI charges, stamp duty, GST (`backtesting_service.costs.CostModel`,
   NSE rate card) plus slippage on both fills, and delivery-vs-intraday rates are applied
   per the strategy's own holding period.

2. **A cap on how many strategies may hold one symbol** (`MAX_STRATEGIES_PER_SYMBOL`).
   The buying desk lost -29% in a day because six near-identical strategies bought the
   same option strike at once, and the Intraday Lab reproduced it exactly (three "VWAP
   Fade" variants buying the identical LT print). This catalog deliberately contains
   parameter variants of the same idea, so the same failure is available to it by
   construction; the cap is what stops one wrong read becoming a 37x position.

3. **A market-regime gate** (`_regime`). Momentum's catastrophic losses are not random:
   Daniel & Moskowitz showed they cluster in panic states — after market declines, when
   volatility is high, during the rebound. So new entries are withheld while the Nifty is
   below its 200-day average or index volatility is above `MAX_INDEX_VOL_PCT`. Open
   positions keep being managed either way; a desk that stopped managing its book would
   leave real risk untracked, which is worse.

FEED
----
Angel One first, Dhan for whatever Angel cannot price, last daily close as an honest
fallback — the shared `intraday_lab_engine._equity_quote_map`, so `ltp_source` on every
row says which broker actually answered and nothing is ever fabricated.
"""

import logging
import math
import os
from datetime import datetime, timezone
from uuid import uuid4

from anyio import to_thread

from app.core.db import (
    instruments_collection,
    momentum_equity_collection,
    momentum_positions_collection,
    momentum_scores_collection,
    momentum_state_collection,
    momentum_trades_collection,
)
from app.services.angel_client import angel_client
from app.services.call_engine import IST, _scored_daily_symbols
from app.services.dhan_client import DhanClient
from app.services.intraday_lab_engine import _equity_quote_map, _size
from app.services.momentum_strategies import (
    MOMENTUM_BY_ID,
    MOMENTUM_CATALOG,
    STYLE_LABELS,
    SymbolMomentum,
    annualised_vol,
    evaluate,
    normalise_z,
    pct_return,
)
from backtesting_service.costs import DELIVERY, INTRADAY, CostModel
from backtesting_service.service import load_bars
from strategy_service.indicators import ema, sma
from tradingai_shared.domain import Timeframe
from tradingai_shared.sectors import get_sector

logger = logging.getLogger("momentum_engine")

STATE_ID = "momentum"

# ── capital ──────────────────────────────────────────────────────────────────────
# ₹10,000 per strategy, exactly as briefed. Each strategy trades ONLY its own account,
# never a shared pool, so one strategy can never starve another and each is judged
# against the same starting stake.
PER_STRATEGY_ALLOCATION = float(os.getenv("MOMENTUM_PER_STRATEGY_CAPITAL", "10000"))
# ...and it deploys that whole ₹10,000 in ONE position at a time by default. Splitting a
# ₹10,000 account into a 3-5 name basket (which is what a cross-sectional momentum sleeve
# would normally do) produces ₹2,000-₹3,300 positions, where the ₹20 flat intraday
# brokerage alone is ~1.2% of the round trip — the sizing, not the signal, would decide
# the leaderboard. One uniform full-size bet per strategy keeps the comparison about
# WHICH stock each strategy picks and WHEN. Raise MOMENTUM_MAX_POSITIONS to run baskets
# once the desk graduates to a larger stake.
MAX_POSITIONS_PER_STRATEGY = int(os.getenv("MOMENTUM_MAX_POSITIONS", "1"))
POSITION_NOTIONAL = PER_STRATEGY_ALLOCATION / max(MAX_POSITIONS_PER_STRATEGY, 1)
INITIAL_CAPITAL = PER_STRATEGY_ALLOCATION * max(len(MOMENTUM_CATALOG), 1)

# ── costs ────────────────────────────────────────────────────────────────────────
COST_MODEL = CostModel()  # NSE rate card; Dhan pricing (free delivery, ₹20/0.03% intraday)
SLIPPAGE_BPS = float(os.getenv("MOMENTUM_SLIPPAGE_BPS", "5"))  # 0.05% each side

# ── session / risk ───────────────────────────────────────────────────────────────
MAX_SYMBOLS_PER_SCAN = int(os.getenv("MOMENTUM_MAX_SYMBOLS", "150"))
MAX_STRATEGIES_PER_SYMBOL = int(os.getenv("MOMENTUM_MAX_STRATEGIES_PER_SYMBOL", "3"))
# How far the live price may sit from the last daily close before the symbol is skipped.
# The cross-sectional families (relative strength, NSE score, sector rotation) gate on
# DAILY-BAR statistics but fill at the LIVE price, so those two must describe the same
# instrument. A bonus/split that the backfilled bars have not been adjusted for — routine
# on NSE — halves the price while leaving the momentum stats reading "very strong", and
# the desk would buy a 1:2 split at a "momentum" it never had. A bad tick does the same
# thing faster. 20% is far wider than any real intraday gap on a liquid name, so this
# rejects corrupted data without rejecting genuine moves.
MAX_QUOTE_DEVIATION_PCT = float(os.getenv("MOMENTUM_MAX_QUOTE_DEVIATION_PCT", "20"))
EOD_SQUAREOFF_HHMM = "15:15"
ENTRY_CUTOFF_HHMM = os.getenv("MOMENTUM_ENTRY_CUTOFF", "15:00")
DAILY_LOSS_BREAKER_PCT = float(os.getenv("MOMENTUM_DAILY_LOSS_PCT", "0.03"))
# Paper money, and accruing the track record IS the point — so this ships armed. The
# real-money desk is the one that ships disarmed.
PAUSE_NEW_ENTRIES = os.getenv("MOMENTUM_PAUSE_ENTRIES", "0").lower() not in ("0", "false", "")

# ── regime gate (momentum-crash mitigation) ──────────────────────────────────────
BENCHMARK_SYMBOL = os.getenv("MOMENTUM_BENCHMARK", "NIFTY")
REGIME_MA_PERIOD = int(os.getenv("MOMENTUM_REGIME_MA", "200"))
MAX_INDEX_VOL_PCT = float(os.getenv("MOMENTUM_MAX_INDEX_VOL", "30"))  # annualised, 20d
REGIME_GATE_ON = os.getenv("MOMENTUM_REGIME_GATE", "1").lower() not in ("0", "false")

# ── promotion gate ───────────────────────────────────────────────────────────────
# The bar a strategy must clear before it is worth real money. Win rate is deliberately
# LOW (momentum wins by asymmetry — the published Indian ORB record is a ~49% win rate at
# a 1.23 profit factor); the binding constraints are profit factor and drawdown.
MIN_TRADES_FOR_VERDICT = int(os.getenv("MOMENTUM_MIN_TRADES", "20"))
MIN_PROFIT_FACTOR = float(os.getenv("MOMENTUM_MIN_PF", "1.2"))
MIN_WIN_RATE = float(os.getenv("MOMENTUM_MIN_WIN_RATE", "0.30"))
MAX_DRAWDOWN_PCT = float(os.getenv("MOMENTUM_MAX_DD_PCT", "20"))
# ...and the criterion that stops LUCK clearing the gate. Profit factor and net P&L are
# both passable by a coin flip over a few dozen trades: a simulated 60-trade sequence of
# random ±₹200 outcomes landed at +₹2,000 with a 1.40 profit factor — indistinguishable
# from an edge on every other criterion here. The t-statistic of per-trade P&L
# (mean / (stdev/√n)) asks the different question "is this separable from noise at all?",
# and the same coin flip scores 1.29 against a genuine edge's 3.8. It is a screen, not a
# formal test — trades are not iid and there is selection bias in ranking 37 strategies —
# so it is set at a deliberately modest 1.5 and is one criterion among several.
MIN_T_STAT = float(os.getenv("MOMENTUM_MIN_T_STAT", "1.5"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist():
    return datetime.now(IST).date()


def _session_start_utc() -> datetime:
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _product(spec) -> str:
    """Intraday strategies pay intraday rates (STT 0.025% sell-side only); anything held
    overnight pays DELIVERY rates (STT 0.1% BOTH sides, ~4x the drag). Charging one rate
    for both would flatter half the catalog and penalise the other half."""
    return INTRADAY if spec.is_intraday else DELIVERY


# --------------------------------------------------------------------------------
# Universe momentum table (built once per cycle, shared by all 37 strategies)
# --------------------------------------------------------------------------------


# Which return window each sector-rotation lookback ranks on, and the set of lookbacks the
# catalog actually uses — derived FROM the catalog so adding a variant with a new lookback
# cannot silently fall back to somebody else's window.
_RET_ATTR_FOR_LOOKBACK = {21: "ret_21", 63: "ret_63", 126: "ret_126", 252: "ret_252"}
SECTOR_LOOKBACKS: list[int] = sorted(
    {s.params["lookback"] for s in MOMENTUM_CATALOG if s.family == "sector_rotation"}
)
_unsupported = [lb for lb in SECTOR_LOOKBACKS if lb not in _RET_ATTR_FOR_LOOKBACK]
assert not _unsupported, f"sector_rotation lookback(s) with no return window: {_unsupported}"


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    """Rank -> 0..1 percentile where 1.0 is the strongest. Ties share the mean rank so a
    universe of identical scores does not hand one arbitrary symbol the top decile."""
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    if n == 1:
        return {ordered[0][0]: 1.0}
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        mean_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            out[ordered[k][0]] = mean_rank / (n - 1)
        i = j + 1
    return out


def _zscores(values: dict[str, float]) -> dict[str, float]:
    """Cross-sectional z-score, winsorised at ±3 (NSE winsorises before normalising, so a
    single berserk small-cap cannot dominate the whole distribution)."""
    if len(values) < 2:
        return {k: 0.0 for k in values}
    xs = list(values.values())
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
    sd = math.sqrt(var)
    if sd <= 0:
        return {k: 0.0 for k in values}
    return {k: max(-3.0, min(3.0, (v - mean) / sd)) for k, v in values.items()}


def build_universe(scored: list, bench_bars: list) -> dict[str, SymbolMomentum]:
    """Per-symbol momentum stats plus universe-wide percentiles and sector ranks.

    `scored` is `call_engine._scored_daily_symbols()` output: (symbol, score, reasons,
    atr14, bars). `bench_bars` are the benchmark's daily bars, used for the relative
    strength legs. Symbols the benchmark has no aligned history for simply get None
    relative-strength values — they are still eligible for the absolute families."""
    bench_by_date = {b.ts.date(): b.close for b in bench_bars}
    rows: dict[str, SymbolMomentum] = {}

    for symbol, _score, _reasons, _atr14, bars in scored:
        if len(bars) < 60:
            continue
        m = SymbolMomentum(symbol=symbol, close=bars[-1].close)
        m.ret_21 = pct_return(bars, 21)
        m.ret_63 = pct_return(bars, 63)
        m.ret_126 = pct_return(bars, 126)
        m.ret_252 = pct_return(bars, 252)
        m.vol_ann = annualised_vol(bars, 252)

        window = bars[-252:]
        if window:
            m.high_52w = max(b.high for b in window)
            if m.high_52w > 0:
                m.dist_52w = bars[-1].close / m.high_52w

        # Relative strength = own return minus the benchmark's over the SAME calendar
        # span (aligned by date, not by bar count — a symbol that missed sessions would
        # otherwise be compared against a different window than the index).
        for lb, attr in ((63, "rs_63"), (126, "rs_126"), (252, "rs_252")):
            own = pct_return(bars, lb)
            if own is None or len(bars) < lb + 1:
                continue
            start_close = bench_by_date.get(bars[-(lb + 1)].ts.date())
            end_close = bench_by_date.get(bars[-1].ts.date())
            if not start_close or not end_close or start_close <= 0:
                continue
            bench_ret = (end_close / start_close - 1.0) * 100.0
            setattr(m, attr, own - bench_ret)

        m.sector = get_sector(symbol)
        rows[symbol] = m

    # ── NSE normalised momentum score: risk-adjusted 6M/12M -> z -> normalise ──
    ra6 = {s: m.ret_126 / m.vol_ann for s, m in rows.items() if m.ret_126 is not None and m.vol_ann}
    ra12 = {s: m.ret_252 / m.vol_ann for s, m in rows.items() if m.ret_252 is not None and m.vol_ann}
    z6, z12 = _zscores(ra6), _zscores(ra12)
    for symbol, m in rows.items():
        if symbol in z6:
            m.norm_score_6m = normalise_z(z6[symbol])
        if symbol in z12:
            m.norm_score_12m = normalise_z(z12[symbol])
        if symbol in z6 and symbol in z12:
            m.norm_score = normalise_z((z6[symbol] + z12[symbol]) / 2.0)

    for attr, pct_attr in (
        ("norm_score", "pct_norm"), ("norm_score_6m", "pct_norm_6m"), ("norm_score_12m", "pct_norm_12m"),
        ("rs_63", "pct_rs_63"), ("rs_126", "pct_rs_126"), ("rs_252", "pct_rs_252"),
    ):
        vals = {s: getattr(m, attr) for s, m in rows.items() if getattr(m, attr) is not None}
        for symbol, p in _percentiles(vals).items():
            setattr(rows[symbol], pct_attr, p)

    # ── sector ranking, computed once PER LOOKBACK the catalog actually asks for ──
    # Ranking every variant on one fixed window would make the "1M", "3M" and "6M"
    # sector-rotation strategies the same strategy wearing three different labels.
    for lookback in SECTOR_LOOKBACKS:
        ret_attr = _RET_ATTR_FOR_LOOKBACK.get(lookback)
        if ret_attr is None:
            continue
        by_sector: dict[str, list[tuple[float, str]]] = {}
        for symbol, m in rows.items():
            ret = getattr(m, ret_attr)
            if m.sector and ret is not None:
                by_sector.setdefault(m.sector, []).append((ret, symbol))
        sector_strength = sorted(
            ((sum(r for r, _ in members) / len(members), sec) for sec, members in by_sector.items()),
            reverse=True,
        )
        for rank, (_avg, sec) in enumerate(sector_strength, start=1):
            for pos, (_ret, symbol) in enumerate(sorted(by_sector[sec], reverse=True), start=1):
                rows[symbol].sector_ranks[lookback] = (rank, len(sector_strength), pos)
    return rows


# --------------------------------------------------------------------------------
# Regime gate
# --------------------------------------------------------------------------------


async def _regime() -> dict:
    """Is the market in a state where long momentum is worth taking at all?

    Two published conditions, both from the momentum-crash literature: the index must be
    above its long moving average (trend intact), and index volatility must not be in a
    panic state. Returns `ok=True` with an explicit reason when the gate is switched off
    or the benchmark simply has no bars — never silently."""
    bars = await to_thread.run_sync(load_bars, BENCHMARK_SYMBOL, Timeframe.D1, 2.0)
    if not bars or len(bars) < REGIME_MA_PERIOD + 1:
        return {
            "ok": True, "gate_enabled": REGIME_GATE_ON, "benchmark": BENCHMARK_SYMBOL,
            "close": bars[-1].close if bars else None, "ma": None, "index_vol": None,
            "reason": f"{BENCHMARK_SYMBOL} has fewer than {REGIME_MA_PERIOD} daily bars — regime gate cannot be evaluated, not enforcing it.",
        }
    closes = [b.close for b in bars]
    ma = sma(closes, REGIME_MA_PERIOD)[-1]
    close = closes[-1]
    vol = annualised_vol(bars, 20)
    above_ma = close > ma
    calm = vol is None or vol <= MAX_INDEX_VOL_PCT

    if not REGIME_GATE_ON:
        reason = "Regime gate disabled (MOMENTUM_REGIME_GATE=0) — entries allowed in any regime."
        ok = True
    elif above_ma and calm:
        reason = f"{BENCHMARK_SYMBOL} {close:,.0f} is above its {REGIME_MA_PERIOD}-DMA {ma:,.0f}" + (
            f" and index volatility {vol:.1f}% is below the {MAX_INDEX_VOL_PCT:.0f}% panic threshold." if vol is not None else "."
        )
        ok = True
    elif not above_ma:
        reason = (
            f"RISK-OFF: {BENCHMARK_SYMBOL} {close:,.0f} is BELOW its {REGIME_MA_PERIOD}-DMA {ma:,.0f}. "
            "Momentum crashes cluster in exactly this state, so no new longs — open positions are still managed."
        )
        ok = False
    else:
        reason = (
            f"RISK-OFF: index volatility {vol:.1f}% is above the {MAX_INDEX_VOL_PCT:.0f}% panic threshold. "
            "No new longs — open positions are still managed."
        )
        ok = False
    return {
        "ok": ok, "gate_enabled": REGIME_GATE_ON, "benchmark": BENCHMARK_SYMBOL,
        "close": round(close, 2), "ma": round(ma, 2),
        "index_vol": round(vol, 2) if vol is not None else None, "reason": reason,
    }


# --------------------------------------------------------------------------------
# Capital, scoring, promotion gate
# --------------------------------------------------------------------------------


async def _deployed_capital(strategy_id: str) -> float:
    total = 0.0
    async for p in momentum_positions_collection.find(
        {"strategy_id": strategy_id, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed", 0.0)
    return total


async def _realized_pnl(strategy_id: str) -> float:
    total = 0.0
    async for p in momentum_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _available_cash(strategy_id: str) -> float:
    return PER_STRATEGY_ALLOCATION + await _realized_pnl(strategy_id) - await _deployed_capital(strategy_id)


async def today_pnl() -> float:
    start = _session_start_utc()
    total = 0.0
    async for p in momentum_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in momentum_positions_collection.find(
        {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}
    ):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state() -> dict:
    pnl = await today_pnl()
    limit = DAILY_LOSS_BREAKER_PCT * INITIAL_CAPITAL
    return {
        "breaker_tripped": pnl <= -limit,
        "today_pnl": round(pnl, 2),
        "daily_loss_limit": round(limit, 2),
        "daily_loss_pct": DAILY_LOSS_BREAKER_PCT,
    }


def _verdict(stats: dict) -> tuple[str, list[str]]:
    """Is this strategy ready for real money? Returns (verdict, reasons).

    PENDING  — too few closed trades to say anything. Absence of a verdict is NOT approval.
    REJECTED — has enough trades and failed at least one criterion (each one named).
    READY    — cleared every criterion net of real transaction costs.
    """
    trades = stats["trades"]
    if trades < MIN_TRADES_FOR_VERDICT:
        return "PENDING", [f"{trades}/{MIN_TRADES_FOR_VERDICT} closed trades — not enough evidence yet."]

    fails: list[str] = []
    if stats["net_pnl"] <= 0:
        fails.append(f"Net P&L ₹{stats['net_pnl']:,.0f} is not positive after real costs.")
    pf = stats["profit_factor"]
    # `profit_factor` is None in two opposite situations, and they must not be conflated:
    # no losses at all (undefined but excellent — gross_loss is the denominator) versus no
    # winning trades (genuinely bad). `gross_loss` tells them apart. Treating both as a
    # failure would reject a flawless record for the nonsense reason "profit factor None".
    if pf is None and stats["gross_loss"] == 0 and stats["gross_profit"] > 0:
        pass  # every trade won — the t-stat and drawdown criteria still have to pass
    elif pf is None or pf <= MIN_PROFIT_FACTOR:
        fails.append(
            f"Profit factor {'undefined (no winning trades)' if pf is None else round(pf, 2)} "
            f"is not above {MIN_PROFIT_FACTOR}."
        )
    if stats["expectancy"] <= 0:
        fails.append(f"Expectancy ₹{stats['expectancy']:,.0f} per trade is not positive.")
    if stats["win_rate"] < MIN_WIN_RATE:
        fails.append(f"Win rate {stats['win_rate'] * 100:.0f}% is below the {MIN_WIN_RATE * 100:.0f}% floor.")
    if stats["max_drawdown_pct"] > MAX_DRAWDOWN_PCT:
        fails.append(f"Peak-to-trough drawdown {stats['max_drawdown_pct']:.1f}% exceeds {MAX_DRAWDOWN_PCT:.0f}%.")
    t_stat = stats["t_stat"]
    # t is undefined when every trade returned the SAME amount (zero dispersion). With a
    # positive mean that is maximally significant, not insignificant — failing it would
    # reject a perfectly consistent record for having no variance to divide by.
    if t_stat is None and stats.get("pnl_stdev") == 0 and stats["net_pnl"] > 0:
        pass
    elif t_stat is None or t_stat < MIN_T_STAT:
        fails.append(
            f"t-statistic {'undefined' if t_stat is None else round(t_stat, 2)} is below {MIN_T_STAT} — "
            "this record is not separable from luck yet."
        )
    if fails:
        return "REJECTED", fails
    return "READY", [
        f"{trades} trades, profit factor {'no losing trades' if pf is None else format(pf, '.2f')}, "
        f"expectancy ₹{stats['expectancy']:,.0f}/trade, "
        f"max drawdown {stats['max_drawdown_pct']:.1f}%, "
        f"t-stat {'n/a (every trade identical)' if t_stat is None else format(t_stat, '.2f')} "
        "— clears the gate net of costs."
    ]


def _trade_stats(closed: list[dict]) -> dict:
    """Performance of one strategy from its closed trades, in chronological order.

    Drawdown is measured against the running PEAK of the equity curve, not against the
    starting allocation — measuring against a fixed start understates drawdown for any
    account that has grown, a bug already found and fixed once on the long-horizon desk."""
    trades = len(closed)
    pnls = [t.get("realized_pnl") or 0.0 for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    costs = sum(t.get("costs") or 0.0 for t in closed)

    equity = PER_STRATEGY_ALLOCATION
    peak = equity
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    # t = mean / (stdev / sqrt(n)) — how many standard errors the average trade sits
    # above zero. See MIN_T_STAT for why net P&L and profit factor alone are not enough.
    # `sd == 0` (every trade returned the identical amount) leaves t undefined rather than
    # zero; `pnl_stdev` is reported alongside so `_verdict` can tell that degenerate case
    # apart from "not enough trades to compute one at all".
    t_stat = None
    sd = None
    if trades >= 2:
        mean = net / trades
        var = sum((p - mean) ** 2 for p in pnls) / (trades - 1)
        sd = math.sqrt(var)
        if sd > 0:
            t_stat = round(mean / (sd / math.sqrt(trades)), 3)

    return {
        "trades": trades,
        "wins": len(wins),
        "win_rate": round(len(wins) / trades, 4) if trades else 0.0,
        "net_pnl": round(net, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "total_costs": round(costs, 2),
        # None whenever it is undefined (no losses to divide by, or no trades at all).
        # Never `inf`: that is not BSON-encodable and would break the leaderboard write.
        # Callers disambiguate "no losses" from "no wins" via gross_loss/gross_profit.
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "expectancy": round(net / trades, 2) if trades else 0.0,
        "avg_win": round(gross_profit / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "max_drawdown_pct": round(max_dd, 2),
        "t_stat": t_stat,
        "pnl_stdev": round(sd, 2) if sd is not None else None,
        "return_pct": round(net / PER_STRATEGY_ALLOCATION * 100, 2),
    }


async def _update_score(strategy_id: str) -> None:
    spec = MOMENTUM_BY_ID.get(strategy_id)
    if spec is None:
        return
    closed = [
        p async for p in momentum_positions_collection.find(
            {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1, "costs": 1, "closed_at": 1}
        ).sort("closed_at", 1)
    ]
    stats = _trade_stats(closed)
    verdict, reasons = _verdict(stats)
    await momentum_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {
            "strategy_id": strategy_id, "name": spec.name, "style": spec.style,
            "style_label": STYLE_LABELS.get(spec.style, spec.style), "horizon": spec.horizon,
            **stats,
            "allocated_capital": round(PER_STRATEGY_ALLOCATION + stats["net_pnl"], 2),
            "verdict": verdict, "verdict_reasons": reasons,
            "updated_at": _now(),
        }},
        upsert=True,
    )


# --------------------------------------------------------------------------------
# Position lifecycle
# --------------------------------------------------------------------------------


async def _open_position(spec, symbol: str, inst: dict, signal, ltp_source: str, uni: SymbolMomentum, atr14: float) -> bool:
    open_count = await momentum_positions_collection.count_documents(
        {"strategy_id": spec.strategy_id, "status": "OPEN"}
    )
    if open_count >= MAX_POSITIONS_PER_STRATEGY:
        return False
    if await momentum_positions_collection.find_one(
        {"strategy_id": spec.strategy_id, "symbol": symbol, "status": "OPEN"}
    ):
        return False

    # A buy fills slightly ABOVE the signal price, never at it.
    fill = signal.entry * (1 + SLIPPAGE_BPS / 10000.0)
    cash = await _available_cash(spec.strategy_id)
    qty = _size(fill, POSITION_NOTIONAL, cash)
    if qty < 1:
        return False
    product = _product(spec)
    entry_costs = COST_MODEL.order_charges(product, fill, qty, True)

    await momentum_positions_collection.insert_one({
        "position_id": uuid4().hex[:12],
        "strategy_id": spec.strategy_id, "strategy_name": spec.name,
        "style": spec.style, "style_label": STYLE_LABELS.get(spec.style, spec.style),
        "horizon": spec.horizon, "product": product,
        "symbol": symbol, "display_name": symbol,
        "instrument": {
            "symbol": inst["symbol"], "security_id": inst["security_id"],
            "exchange_segment": inst["exchange_segment"], "lot_size": inst.get("lot_size", 1),
        },
        "side": "BUY",
        "signal_price": round(signal.entry, 2), "entry_price": round(fill, 4), "qty": qty,
        "capital_deployed": round(fill * qty, 2), "entry_costs": round(entry_costs, 2),
        "target": round(signal.target, 2), "stoploss": round(signal.stoploss, 2),
        "initial_stop": round(signal.stoploss, 2),
        "trail_mode": signal.trail_mode, "trail_param": signal.trail_param,
        # Raw ATR(14) at entry — the unit the chandelier trail ratchets in. Stored
        # separately from the stop distance below, which is a MULTIPLE of it.
        "atr_at_entry": round(atr14, 4),
        "stop_distance": round(signal.entry - signal.stoploss, 4),
        "high_water": round(fill, 4),
        "ltp": round(fill, 2), "ltp_source": ltp_source,
        "unrealized_pnl": 0.0, "pnl_pct": 0.0, "realized_pnl": None, "costs": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "confidence": round(signal.confidence, 2), "rationale": signal.rationale,
        "max_hold_days": spec.max_hold_days,
        "momentum_snapshot": {
            "ret_63": uni.ret_63, "ret_126": uni.ret_126, "ret_252": uni.ret_252,
            "rs_63": uni.rs_63, "norm_score": uni.norm_score, "dist_52w": uni.dist_52w,
            "sector": uni.sector,
            # {lookback: [sector_rank, sector_count, rank_in_sector]} — lists, not tuples,
            # so the doc round-trips through BSON unchanged.
            "sector_ranks": {str(lb): list(v) for lb, v in uni.sector_ranks.items()},
        },
        "opened_at": _now(), "opened_on": _today_ist().isoformat(),
        "updated_at": _now(), "closed_at": None,
    })
    return True


def _new_trailing_stop(pos: dict, ltp: float, ema_now: float | None) -> float | None:
    """Where the stop should ratchet to, or None to leave it. Never loosens a stop —
    a trailing stop that could move DOWN is just a wider stop with extra steps."""
    mode = pos.get("trail_mode") or "none"
    high_water = max(pos.get("high_water") or ltp, ltp)
    param = pos.get("trail_param") or 0.0
    if mode == "pct" and param > 0:
        candidate = high_water * (1 - param)
    elif mode == "chandelier" and param > 0:
        # ONE ATR as measured at entry. This must be the raw ATR, not the stop distance:
        # the stop distance is stop_atr x ATR, so using it here silently multiplied the
        # chandelier width by each strategy's own stop_atr — trailing ~2x too tight on the
        # ORB variants (stop_atr 0.5) and ~2x too loose on the 52-week breakout (stop_atr 2).
        atr_unit = pos.get("atr_at_entry") or 0.0
        if atr_unit <= 0:
            return None
        candidate = high_water - param * atr_unit
    elif mode == "ema" and ema_now:
        candidate = ema_now
    else:
        return None
    current = pos.get("stoploss") or 0.0
    return candidate if candidate > current else None


async def _close(pos: dict, ltp: float, reason: str) -> float:
    """Close a paper position at `ltp`, net of slippage and both sides' real charges."""
    fill = ltp * (1 - SLIPPAGE_BPS / 10000.0)
    qty = pos["qty"]
    gross = (fill - pos["entry_price"]) * qty
    exit_costs = COST_MODEL.order_charges(pos.get("product", DELIVERY), fill, qty, False)
    costs = (pos.get("entry_costs") or 0.0) + exit_costs
    net = gross - costs

    await momentum_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"], "strategy_name": pos["strategy_name"],
        "style": pos.get("style"), "style_label": pos.get("style_label"),
        "symbol": pos["symbol"], "side": pos["side"],
        "entry_price": pos["entry_price"], "exit_price": round(fill, 2), "qty": qty,
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "realized_pnl": round(net, 2),
        "exit_reason": reason, "rationale": pos.get("rationale"),
        "opened_at": pos["opened_at"], "closed_at": _now(),
    })
    await momentum_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_price": round(fill, 2), "exit_reason": reason,
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "realized_pnl": round(net, 2),
        "unrealized_pnl": 0.0, "closed_at": _now(), "updated_at": _now(), "ltp": round(ltp, 2),
    }})
    return net


# --------------------------------------------------------------------------------
# Cycles
# --------------------------------------------------------------------------------


async def _universe_coverage(scanned: int) -> dict:
    """How much of the available equity universe this scan could actually see.

    `_scored_daily_symbols()` silently drops any symbol `load_bars` cannot return enough
    history for, so a desk can be starved down to a handful of names while every log line
    still reads "success". That matters more here than on a single-symbol desk: the
    relative-strength, NSE-score and sector-rotation families are CROSS-SECTIONAL — a "top
    decile" of 24 names is 2 stocks, which is a different (and much weaker) strategy than
    the one being advertised. Measured every cycle and surfaced on the page so a starved
    universe is visible rather than inferred from suspiciously few trades.
    """
    try:
        from app.core.db import bars_collection

        available = len(await bars_collection.distinct("symbol", {"timeframe": "1d"}))
    except Exception:  # noqa: BLE001 — a diagnostic must never break a scan
        return {"scanned": scanned, "available": None, "note": None}

    note = None
    if available and scanned < available * 0.5:
        note = (
            f"UNIVERSE STARVED: only {scanned} of {available} symbols with daily bars could be "
            f"scored — the rest lack enough loadable history. Cross-sectional families "
            f"(relative strength, NSE momentum score, sector rotation) are ranking inside a "
            f"{scanned}-name pool, so their percentile cuts are far coarser than intended."
        )
    return {"scanned": scanned, "available": available, "note": note}


async def scan_cycle(dhan: DhanClient | None) -> dict:
    notes: list[str] = []
    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {"opened": 0, "scanned_symbols": 0, "regime": await _regime(), "notes": [
            f"DAILY LOSS BREAKER TRIPPED — today's P&L ₹{breaker['today_pnl']:,.0f} crossed the "
            f"₹{breaker['daily_loss_limit']:,.0f} limit. No new positions this session; open ones still managed."
        ]}

    regime = await _regime()
    if not regime["ok"]:
        return {"opened": 0, "scanned_symbols": 0, "regime": regime, "notes": [regime["reason"]]}

    scored = await _scored_daily_symbols()
    if not scored:
        return {"opened": 0, "scanned_symbols": 0, "regime": regime,
                "notes": ["No scored symbols — backfill daily bars first."]}
    scored = scored[:MAX_SYMBOLS_PER_SCAN]

    bench_bars = await to_thread.run_sync(load_bars, BENCHMARK_SYMBOL, Timeframe.D1, 2.0)
    if not bench_bars:
        notes.append(
            f"No {BENCHMARK_SYMBOL} daily bars — relative-strength and sector families are skipped "
            "this cycle rather than compared against a guessed benchmark."
        )
    universe = build_universe(scored, bench_bars)

    symbols = [s for s, *_ in scored]
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": symbols}}
    )}
    quotes, quote_source = await _equity_quote_map(dhan, list(equities.values()))
    if not quotes:
        angel_on = angel_client.configured()
        notes.append(
            f"No live equity quotes this cycle (Angel One: {'returned none' if angel_on else 'not configured'}; "
            f"Dhan: {'no quote' if dhan else 'not connected'}) — ORB is skipped; daily-bar families "
            "enter at the last close."
        )

    intraday_closed = datetime.now(IST).strftime("%H:%M") >= ENTRY_CUTOFF_HHMM
    if intraday_closed:
        notes.append(f"Past the {ENTRY_CUTOFF_HHMM} IST entry cutoff — no new intraday entries; open positions still managed.")

    # How many strategies already hold each symbol, so the cap spans the whole desk.
    holders: dict[str, int] = {}
    async for p in momentum_positions_collection.find({"status": "OPEN"}, {"symbol": 1}):
        holders[p["symbol"]] = holders.get(p["symbol"], 0) + 1

    opened = 0
    capped = 0
    stale: list[str] = []
    for symbol, _score, _reasons, atr14, bars in scored:
        inst = equities.get(symbol)
        uni = universe.get(symbol)
        if inst is None or uni is None or atr14 <= 0 or len(bars) < 60:
            continue
        key = (inst["exchange_segment"], str(inst["security_id"]))
        quote = quotes.get(key)
        ltp_source = quote_source.get(key, "last_bar_close")

        last_close = bars[-1].close
        if quote and last_close > 0:
            ltp = float(quote.get("last_price") or 0)
            drift = abs(ltp / last_close - 1.0) * 100.0
            if ltp <= 0 or drift > MAX_QUOTE_DEVIATION_PCT:
                stale.append(f"{symbol} ({drift:.0f}%)")
                continue

        ctx = {"bars": bars, "atr14": atr14, "quote": quote, "prev_bar": bars[-2], "uni": uni}

        for spec in MOMENTUM_CATALOG:
            if spec.is_intraday and intraday_closed:
                continue
            if spec.needs_quote and quote is None:
                continue
            if holders.get(symbol, 0) >= MAX_STRATEGIES_PER_SYMBOL:
                capped += 1
                break
            signal = evaluate(spec, symbol, ctx)
            if signal is None:
                continue
            if await _open_position(spec, symbol, inst, signal, ltp_source, uni, atr14):
                opened += 1
                holders[symbol] = holders.get(symbol, 0) + 1

    if stale:
        notes.append(
            f"Skipped {len(stale)} symbol(s) whose live price is more than {MAX_QUOTE_DEVIATION_PCT:.0f}% away from "
            f"their last daily close ({', '.join(stale[:6])}{'…' if len(stale) > 6 else ''}) — most likely an "
            "unadjusted split/bonus or a bad tick, so the daily-bar momentum stats no longer describe the live price."
        )
    if capped:
        notes.append(
            f"{capped} further signals were withheld because their symbol already had "
            f"{MAX_STRATEGIES_PER_SYMBOL} strategies in it — the concentration cap that exists because "
            "near-identical variants firing together is how the option desk lost 29% in one day."
        )
    coverage = await _universe_coverage(len(scored))
    if coverage["note"]:
        notes.insert(0, coverage["note"])
    return {"opened": opened, "scanned_symbols": len(scored), "regime": regime,
            "coverage": coverage, "notes": notes}


async def manage_cycle(dhan: DhanClient | None) -> int:
    open_positions = [p async for p in momentum_positions_collection.find({"status": "OPEN"})]
    if not open_positions:
        return 0
    by_symbol: dict[str, list[dict]] = {}
    for p in open_positions:
        by_symbol.setdefault(p["symbol"], []).append(p)
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": list(by_symbol.keys())}}
    )}
    quotes, quote_source = await _equity_quote_map(dhan, list(equities.values()))

    now_ist = datetime.now(IST)
    is_eod = now_ist.strftime("%H:%M") >= EOD_SQUAREOFF_HHMM
    today = _today_ist()

    updated = 0
    touched: set[str] = set()
    for symbol, positions in by_symbol.items():
        inst = equities.get(symbol)
        ltp, ltp_source = None, None
        if inst:
            key = (inst["exchange_segment"], str(inst["security_id"]))
            q = quotes.get(key)
            if q:
                ltp, ltp_source = float(q["last_price"]), quote_source[key]

        # Daily bars are needed for the EMA trail, and as the honest LTP fallback.
        needs_bars = ltp is None or any((p.get("trail_mode") == "ema") for p in positions)
        ema_now = None
        if needs_bars:
            bars = await to_thread.run_sync(load_bars, symbol, Timeframe.D1, 1.0)
            if bars:
                if ltp is None:
                    ltp, ltp_source = bars[-1].close, "last_bar_close"
                periods = {int(p.get("trail_param") or 0) for p in positions if p.get("trail_mode") == "ema"}
                if periods:
                    ema_now = {
                        period: (ema([b.close for b in bars], period)[-1] if len(bars) >= period else None)
                        for period in periods if period > 0
                    }
        if ltp is None:
            continue

        for pos in positions:
            qty = pos["qty"]
            gross = (ltp - pos["entry_price"]) * qty
            # Unrealized is shown NET of the charges the round trip will actually cost,
            # so an open row never looks profitable at a price that would close at a loss.
            projected_costs = (pos.get("entry_costs") or 0.0) + COST_MODEL.order_charges(
                pos.get("product", DELIVERY), ltp, qty, False
            )
            unrealized = gross - projected_costs

            high_water = max(pos.get("high_water") or pos["entry_price"], ltp)
            trail_ema = (ema_now or {}).get(int(pos.get("trail_param") or 0)) if pos.get("trail_mode") == "ema" else None
            changes: dict = {
                "ltp": round(ltp, 2), "ltp_source": ltp_source, "high_water": round(high_water, 4),
                "unrealized_pnl": round(unrealized, 2),
                "pnl_pct": round((ltp - pos["entry_price"]) / pos["entry_price"] * 100, 2) if pos["entry_price"] else 0.0,
                "updated_at": _now(),
            }
            new_stop = _new_trailing_stop({**pos, "high_water": high_water}, ltp, trail_ema)
            stop = pos["stoploss"]
            if new_stop is not None and new_stop < ltp:
                stop = round(new_stop, 2)
                changes["stoploss"] = stop
                changes["stop_trailed"] = True

            days_held = (today - datetime.fromisoformat(pos["opened_on"]).date()).days
            hit_target = ltp >= pos["target"]
            hit_stop = ltp <= stop
            intraday_close = pos.get("max_hold_days", 0) == 0 and (is_eod or days_held >= 1)
            expired = pos.get("max_hold_days", 0) > 0 and days_held >= pos["max_hold_days"]

            reason = (
                "target" if hit_target else
                "trailing_stop" if hit_stop and changes.get("stop_trailed") else
                "stoploss" if hit_stop else
                "eod" if intraday_close else
                "max_hold_expired" if expired else None
            )
            if reason:
                await momentum_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
                await _close({**pos, **changes, "stoploss": stop}, ltp, reason)
                touched.add(pos["strategy_id"])
            else:
                await momentum_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
            updated += 1

    for strategy_id in touched:
        await _update_score(strategy_id)
    return updated


# --------------------------------------------------------------------------------
# Read models
# --------------------------------------------------------------------------------


async def summary() -> dict:
    deployed = realized = unrealized = costs = 0.0
    async for p in momentum_positions_collection.find(
        {"status": "OPEN"}, {"capital_deployed": 1, "unrealized_pnl": 1, "entry_costs": 1}
    ):
        deployed += p.get("capital_deployed", 0.0)
        unrealized += p.get("unrealized_pnl") or 0.0
        # Entry charges on an OPEN position are already spent, so they belong in the
        # running cost total. Counting only closed trades showed "costs charged: Rs0"
        # while 20 positions had each paid real brokerage — on a desk whose entire claim
        # is fee-honesty, that reads as "costs are not being charged".
        costs += p.get("entry_costs") or 0.0
    async for p in momentum_positions_collection.find(
        {"status": {"$ne": "OPEN"}}, {"realized_pnl": 1, "costs": 1}
    ):
        realized += p.get("realized_pnl") or 0.0
        costs += p.get("costs") or 0.0

    verdicts = {"READY": 0, "REJECTED": 0, "PENDING": 0}
    async for s in momentum_scores_collection.find({}, {"verdict": 1}):
        verdicts[s.get("verdict", "PENDING")] = verdicts.get(s.get("verdict", "PENDING"), 0) + 1
    verdicts["PENDING"] += len(MOMENTUM_CATALOG) - sum(verdicts.values())

    return {
        "initial_capital": INITIAL_CAPITAL,
        "per_strategy_allocation": round(PER_STRATEGY_ALLOCATION, 2),
        "position_notional": round(POSITION_NOTIONAL, 2),
        "max_positions_per_strategy": MAX_POSITIONS_PER_STRATEGY,
        "available_cash": round(INITIAL_CAPITAL + realized - deployed, 2),
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_costs": round(costs, 2),
        "equity": round(INITIAL_CAPITAL + realized + unrealized, 2),
        "open_positions": await momentum_positions_collection.count_documents({"status": "OPEN"}),
        "closed_positions": await momentum_positions_collection.count_documents({"status": {"$ne": "OPEN"}}),
        "strategy_count": len(MOMENTUM_CATALOG),
        "ready_count": verdicts.get("READY", 0),
        "rejected_count": verdicts.get("REJECTED", 0),
        "pending_count": verdicts.get("PENDING", 0),
        "paused": PAUSE_NEW_ENTRIES,
        "mode": "paper",
        "costs_charged": True,
        "slippage_bps": SLIPPAGE_BPS,
        "promotion_gate": {
            "min_trades": MIN_TRADES_FOR_VERDICT, "min_profit_factor": MIN_PROFIT_FACTOR,
            "min_win_rate": MIN_WIN_RATE, "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "min_t_stat": MIN_T_STAT,
        },
        **(await breaker_state()),
    }


async def leaderboard() -> list[dict]:
    scores = {s["strategy_id"]: s async for s in momentum_scores_collection.find({})}
    open_counts: dict[str, int] = {}
    async for p in momentum_positions_collection.find({"status": "OPEN"}, {"strategy_id": 1}):
        open_counts[p["strategy_id"]] = open_counts.get(p["strategy_id"], 0) + 1

    rows = []
    for spec in MOMENTUM_CATALOG:
        sc = scores.get(spec.strategy_id) or {}
        net_pnl = sc.get("net_pnl", 0.0) or 0.0
        rows.append({
            "strategy_id": spec.strategy_id, "name": spec.name,
            "style": spec.style, "style_label": STYLE_LABELS.get(spec.style, spec.style),
            "horizon": spec.horizon, "timeframe": spec.timeframe, "rationale": spec.rationale,
            "max_hold_days": spec.max_hold_days,
            "trades": sc.get("trades", 0) or 0,
            "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(net_pnl, 2),
            "total_costs": sc.get("total_costs", 0.0) or 0.0,
            "profit_factor": sc.get("profit_factor"),
            "expectancy": sc.get("expectancy", 0.0) or 0.0,
            "max_drawdown_pct": sc.get("max_drawdown_pct", 0.0) or 0.0,
            "t_stat": sc.get("t_stat"),
            "return_pct": sc.get("return_pct", 0.0) or 0.0,
            "allocated_capital": round(PER_STRATEGY_ALLOCATION + net_pnl, 2),
            "open_positions": open_counts.get(spec.strategy_id, 0),
            "verdict": sc.get("verdict", "PENDING"),
            "verdict_reasons": sc.get("verdict_reasons", [
                f"0/{MIN_TRADES_FOR_VERDICT} closed trades — not enough evidence yet."
            ]),
        })
    rows.sort(key=lambda r: (r["verdict"] != "READY", -r["net_pnl"]))
    return rows


async def run_cycle(dhan: DhanClient | None) -> dict:
    managed = await manage_cycle(dhan)
    if PAUSE_NEW_ENTRIES:
        scan = {"opened": 0, "scanned_symbols": 0, "regime": await _regime(),
                "notes": ["Momentum entries are paused (MOMENTUM_PAUSE_ENTRIES=1); open positions still managed."]}
    else:
        scan = await scan_cycle(dhan)

    snap = await summary()
    await momentum_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "deployed": snap["deployed_capital"],
        "open_positions": snap["open_positions"],
    })
    await momentum_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {
            "last_run_at": _now(), "last_opened": scan["opened"], "last_managed": managed,
            "last_notes": scan["notes"], "regime": scan["regime"],
            "coverage": scan.get("coverage"),
            "broker_connected": dhan is not None, "angel_configured": angel_client.configured(),
            "paused": PAUSE_NEW_ENTRIES,
        }},
        upsert=True,
    )
    return {
        "opened": scan["opened"], "managed": managed, "scanned_symbols": scan["scanned_symbols"],
        "regime": scan["regime"], "coverage": scan.get("coverage"), "notes": scan["notes"],
    }
