"""Backtests strategies #46-50 (long_call, long_put, covered_call, bull_put_spread,
iron_condor) with REAL option pricing — Black-Scholes, not the underlying-price proxy
they ran as through Phase 3.

Why modeled rather than historical-quoted premiums: Dhan has no continuous multi-year
option-chain history to backtest against (each contract only trades for one expiry
cycle), and stitching a "continuous option" series the way futures get rolled is a
larger project than this phase's scope. Black-Scholes fed by the underlying's own
realized volatility is the standard fallback technique institutional backtests use
when true historical option chains aren't available — legitimate, but a model, not
a quote, and every result says so.

Each strategy's OWN `on_bar` (unchanged, running on the UNDERLYING'S bars — the
decision to trade options is still a read on the underlying's technicals) drives entry/
exit; this module turns each signal into a real options STRUCTURE (1-4 legs, priced via
Black-Scholes) and tracks its net premium mark-to-market until the strategy exits, the
structure's DTE expires, or a stop/target on the net premium fires. The result is a
`BacktestRun` — the exact same object the equity backtester produces — so
`compute_metrics`/`compute_charts` need no changes to work on it.

Simplifications, stated plainly:
- One structure open at a time per run (matches the equity backtester's model).
- `covered_call` here prices ONLY the short-call overlay's P&L, not the underlying
  shares' own gain/loss — call it "the premium-income leg" of the strategy, not the
  whole covered position (that combination is a straightforward sum with the existing
  equity backtest of the same symbol, left to the caller).
- IV is realized volatility of the underlying (a common real proxy, not the market's
  actual implied vol smile).
- Strikes are ATM/OTM by a configurable percentage, rounded to `strike_step`.
"""

import math
from datetime import timedelta
from uuid import uuid4

from backtesting_service.charts import compute_charts
from backtesting_service.costs import CostModel
from backtesting_service.engine import BacktestConfig, BacktestRun
from backtesting_service.metrics import compute_metrics
from options_service.greeks import black_scholes_price
from tradingai_shared.contracts import STRATEGY_REGISTRY, Strategy, StrategyContext
from tradingai_shared.domain import (
    AssetClass,
    Bar,
    SignalAction,
    Timeframe,
    Trade,
    TradeStatus,
    TransactionType,
)

OPTIONS_STRATEGY_IDS = {"long_call", "long_put", "covered_call", "bull_put_spread", "iron_condor"}
DEFAULT_DTE_DAYS = 30
DEFAULT_IV_LOOKBACK = 20
DEFAULT_OTM_PCT = 0.03
DEFAULT_SPREAD_WIDTH_PCT = 0.02

# Option-BUYING strategy categories (strategy-service strategies/options_buying/):
# any registered strategy in one of these categories backtests here as a premium
# buyer — BUY signal => long ATM CE, SELL signal => long ATM PE. Style defaults
# reflect how each style actually trades: scalps/intraday buy near-expiry premium
# and never carry overnight; swing buys the monthly and rides it.
#
# scalp/intraday `dte_days` here are the FALLBACK used only when `expiry_weekday` is
# not supplied. Callers should pass `expiry_weekday` (NIFTY's real weekly cycle: 1 =
# Tuesday) so the engine prices each entry off its ACTUAL time-to-real-expiry instead
# of this flat guess — verified against real Dhan quotes (2026-07-10) that a flat
# 2-day guess badly underpriced a real 4-day contract. Once DTE and IV (see
# _realized_vol) are both correctly computed, the original 50%/25% and 60%/30%
# thresholds were re-validated empirically as the best-performing (tighter
# thresholds just get chopped by noise) — no arbitrary re-tuning needed.
OPTION_BUYING_CATEGORIES = {
    "options_scalp": {"dte_days": 2, "square_off_eod": True, "premium_stop_pct": 0.25, "premium_target_pct": 0.50},
    "options_intraday": {"dte_days": 3, "square_off_eod": True, "premium_stop_pct": 0.30, "premium_target_pct": 0.60},
    "options_swing": {"dte_days": 30, "square_off_eod": False, "premium_stop_pct": 0.40, "premium_target_pct": 0.80},
    # Selective, high-conviction entries only (opening-range expansion, ADX surge, gap
    # continuation, range breaks) — most days these take NO trade at all, by design.
    # Bigger target/stop than scalp/intraday because the entry gate itself already
    # filters for days where the underlying is expected to move enough to earn it.
    "options_breakout": {"dte_days": 3, "square_off_eod": True, "premium_stop_pct": 0.35, "premium_target_pct": 1.00},
}


def _real_entry_dte(entry_ts, expiry_weekday: int) -> float:
    """Days from entry to the NEXT real listed expiry of that weekday (e.g. NIFTY's
    Tuesday weekly cycle) — replaces a flat dte_days guess with the actual contract's
    time-to-expiry, which is what determines its real premium level. Entries ON the
    expiry weekday still have real intraday time value (0DTE trades), so they get a
    small positive DTE rather than zero."""
    days_until = (expiry_weekday - entry_ts.weekday()) % 7
    return 0.4 if days_until == 0 else float(days_until)


def _buying_category(strategy_id: str) -> str | None:
    cls = STRATEGY_REGISTRY.get(strategy_id)
    if cls is None:
        return None
    category = cls.metadata.category
    return category if category in OPTION_BUYING_CATEGORIES else None


class Leg:
    __slots__ = ("option_type", "strike", "direction")

    def __init__(self, option_type: str, strike: float, direction: TransactionType):
        self.option_type = option_type
        self.strike = strike
        self.direction = direction

    def price(self, spot: float, t_years: float, sigma: float, rate: float = 0.065) -> float:
        return black_scholes_price(spot, self.strike, t_years, self.option_type, rate, sigma=sigma)


def _round_to_step(value: float, step: float) -> float:
    return round(value / step) * step


# Vol risk premium: index option implied vol runs persistently above realized vol
# (the standard, well-documented VRP). A modest multiplier + a real-IV-matched floor
# keeps synthetic premiums from underpricing quiet-market entries.
_VRP_MULT = 1.15
_MIN_IV = 0.09


def _realized_vol(daily_closes: list[float], window: int) -> float:
    """Always computed from DAILY closes, even for intraday (5m/15m/1h) strategies —
    verified against real NIFTY option IV (2026-07-10, 9.46%): a short intraday
    lookback (e.g. the last 100 minutes) is dominated by transient opening-range
    noise and does not represent the multi-day expectation real option IV prices in.
    A trailing option's IV reflects the underlying's day-to-day vol, not its
    last-hour vol, regardless of how frequently the STRATEGY itself re-evaluates."""
    recent = daily_closes[-window - 1 :]
    if len(recent) < 3:
        return 0.20  # fallback for very short history
    log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent)) if recent[i - 1] > 0]
    if len(log_returns) < 2:
        return 0.20
    mean = sum(log_returns) / len(log_returns)
    var = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    return max(math.sqrt(var) * math.sqrt(252) * _VRP_MULT, _MIN_IV)


def _daily_close_series(bars: list[Bar]) -> tuple[list, list[float]]:
    """(dates, closes) — one entry per calendar date, using each date's LAST bar in
    the series (works whether `bars` is itself daily or intraday)."""
    by_date: dict = {}
    for b in bars:
        by_date[b.ts.date()] = b.close  # bars are chronological, so last write wins
    dates = sorted(by_date)
    return dates, [by_date[d] for d in dates]


def build_structure(strategy_id: str, action: SignalAction, spot: float, strike_step: float, otm_pct: float) -> list[Leg]:
    atm = _round_to_step(spot, strike_step)
    up_strike = _round_to_step(spot * (1 + otm_pct), strike_step)
    down_strike = _round_to_step(spot * (1 - otm_pct), strike_step)
    spread_up = _round_to_step(spot * (1 + otm_pct + DEFAULT_SPREAD_WIDTH_PCT), strike_step)
    spread_down = _round_to_step(spot * (1 - otm_pct - DEFAULT_SPREAD_WIDTH_PCT), strike_step)

    if strategy_id == "long_call":
        return [Leg("CE", atm, TransactionType.BUY)]
    if strategy_id == "long_put":
        return [Leg("PE", atm, TransactionType.BUY)]
    if strategy_id == "covered_call":
        return [Leg("CE", up_strike, TransactionType.SELL)]
    if strategy_id == "bull_put_spread":
        return [Leg("PE", down_strike, TransactionType.SELL), Leg("PE", spread_down, TransactionType.BUY)]
    if strategy_id == "iron_condor":
        return [
            Leg("CE", up_strike, TransactionType.SELL), Leg("CE", spread_up, TransactionType.BUY),
            Leg("PE", down_strike, TransactionType.SELL), Leg("PE", spread_down, TransactionType.BUY),
        ]
    if _buying_category(strategy_id) is not None:
        # Premium buyer: bullish signal buys the ATM call, bearish buys the ATM put.
        if action == SignalAction.SELL:
            return [Leg("PE", atm, TransactionType.BUY)]
        return [Leg("CE", atm, TransactionType.BUY)]
    raise ValueError(f"{strategy_id!r} is not an options structure this module knows how to build")


def _structure_value(legs: list[Leg], spot: float, t_years: float, sigma: float) -> float:
    """Net premium to ENTER this structure right now (credit positive, debit
    negative) — a SELL leg pays you its price, a BUY leg costs you its price."""
    total = 0.0
    for leg in legs:
        price = leg.price(spot, t_years, sigma)
        total += price if leg.direction == TransactionType.SELL else -price
    return total


class _OpenStructure:
    def __init__(self, legs: list[Leg], entry_net_premium: float, entry_ts, dte_days: int):
        self.legs = legs
        self.entry_net_premium = entry_net_premium
        self.entry_ts = entry_ts
        self.expiry_ts = entry_ts + timedelta(days=dte_days)


def run_options_backtest(
    strategy_id: str, symbol: str, timeframe: Timeframe, underlying_bars: list[Bar],
    initial_capital: float = 1_000_000, lot_size: int = 75, quantity_lots: int = 1,
    dte_days: int | None = None, otm_pct: float = DEFAULT_OTM_PCT,
    strike_step: float = 50.0, iv_lookback: int = DEFAULT_IV_LOOKBACK, params: dict | None = None,
    square_off_eod: bool | None = None, premium_stop_pct: float | None = None,
    premium_target_pct: float | None = None, include_trades: bool = False,
    adx_regime: float | None = None, expiry_weekday: int | None = None,
) -> dict:
    buying_category = _buying_category(strategy_id)
    if strategy_id not in OPTIONS_STRATEGY_IDS and buying_category is None:
        raise ValueError(
            f"{strategy_id!r} is neither one of the options structures {sorted(OPTIONS_STRATEGY_IDS)} "
            f"nor a registered option-buying strategy (categories {sorted(OPTION_BUYING_CATEGORIES)})"
        )

    style = OPTION_BUYING_CATEGORIES.get(buying_category, {})
    if dte_days is None:
        dte_days = style.get("dte_days", DEFAULT_DTE_DAYS)
    if square_off_eod is None:
        square_off_eod = style.get("square_off_eod", False)
    if premium_stop_pct is None:
        premium_stop_pct = style.get("premium_stop_pct")
    if premium_target_pct is None:
        premium_target_pct = style.get("premium_target_pct")
    # Stops/targets on net premium only make sense for net-debit (buying) structures;
    # the legacy 5 keep their exact Phase 7 behavior unless explicitly overridden.
    manage_premium = buying_category is not None

    # Last bar of each session (tz-agnostic: the date changes on the next bar).
    is_eod = [
        i + 1 >= len(underlying_bars) or underlying_bars[i + 1].ts.date() != bar.ts.date()
        for i, bar in enumerate(underlying_bars)
    ]

    # IV proxy always comes from DAILY closes (see _realized_vol) — precompute once,
    # then track a pointer to the last date STRICTLY BEFORE the current bar's date so
    # sigma never uses today's still-forming session (no lookahead).
    daily_dates, daily_closes = _daily_close_series(underlying_bars)
    daily_ptr = 0

    # Optional regime gate: block NEW entries while ADX(14) is below the threshold
    # (exits/stops still run). Callers apply this to trend-following strategies only.
    adx_series = None
    if adx_regime is not None and len(underlying_bars) >= 29:
        from strategy_service.indicators import adx as _adx

        adx_series, _, _ = _adx(underlying_bars, 14)

    strategy_cls = STRATEGY_REGISTRY[strategy_id]
    strategy: Strategy = strategy_cls(params=params or {})
    ctx = StrategyContext(max_bars=max(500, strategy.warmup + 2))
    cost_model = CostModel()

    cash = initial_capital
    open_structure: _OpenStructure | None = None
    trades: list[Trade] = []
    trade_legs: list[list[tuple[str, float]]] = []  # (option_type, strike) per closed trade
    equity_ts, equity = [], []
    closes: list[float] = []
    total_charges = 0.0

    def leg_charges(legs: list[Leg], premium_each: list[float]) -> float:
        total = 0.0
        for leg, price in zip(legs, premium_each):
            total += cost_model.order_charges(
                "options", max(price, 0.05), lot_size * quantity_lots, is_buy=leg.direction == TransactionType.BUY
            )
        return total

    for i, bar in enumerate(underlying_bars):
        closes.append(bar.close)
        while daily_ptr < len(daily_dates) and daily_dates[daily_ptr] < bar.ts.date():
            daily_ptr += 1
        sigma = _realized_vol(daily_closes[:daily_ptr], iv_lookback)

        if open_structure is not None:
            t_left = max((open_structure.expiry_ts - bar.ts).total_seconds(), 0) / (365 * 24 * 3600)
            expired = t_left <= 0

            ctx.push(bar)
            signal = strategy.on_bar(ctx) if len(ctx.bars) >= strategy.warmup else None
            exits = signal is not None and signal.signal in (SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT)

            exit_reason = None
            if manage_premium and not (expired or exits):
                # Premium stop/target for the debit paid (entry_net_premium < 0 when buying).
                debit = -open_structure.entry_net_premium
                if debit > 0:
                    current_value = _structure_value(open_structure.legs, bar.close, max(t_left, 1e-6), sigma)
                    unrealized = open_structure.entry_net_premium - current_value
                    if premium_stop_pct is not None and unrealized <= -debit * premium_stop_pct:
                        exit_reason = "premium_stop"
                    elif premium_target_pct is not None and unrealized >= debit * premium_target_pct:
                        exit_reason = "premium_target"
            if exit_reason is None and square_off_eod and is_eod[i]:
                exit_reason = "eod"

            if expired or exits or exit_reason is not None:
                exit_value = _structure_value(open_structure.legs, bar.close, max(t_left, 1e-6), sigma)
                leg_prices = [leg.price(bar.close, max(t_left, 1e-6), sigma) for leg in open_structure.legs]
                charges = leg_charges(open_structure.legs, leg_prices)
                total_charges += charges
                # Closing reverses every leg's direction, so the cash flow to close is
                # -exit_value; combined with the +entry_net_premium received/paid at
                # entry, total P&L = entry_net_premium - exit_value (verified against a
                # worked bull-put-spread example: credit 70 decaying to ~0 must show a
                # profit near +70, which only "entry - exit" produces).
                pnl = (open_structure.entry_net_premium - exit_value) * lot_size * quantity_lots - charges

                trade = Trade(
                    trade_id=uuid4().hex[:12], strategy_id=strategy_id, symbol=symbol,
                    direction=TransactionType.BUY, quantity=lot_size * quantity_lots,
                    entry_price=round(open_structure.entry_net_premium, 2), entry_ts=open_structure.entry_ts,
                    exit_price=round(exit_value, 2), exit_ts=bar.ts, status=TradeStatus.CLOSED,
                    exit_reason="expiry" if expired else ("signal" if exits else exit_reason),
                    charges=round(charges, 2), pnl=round(pnl, 2),
                )
                trades.append(trade)
                trade_legs.append([(leg.option_type, leg.strike) for leg in open_structure.legs])
                cash += pnl
                open_structure = None
        else:
            ctx.push(bar)
            signal = strategy.on_bar(ctx) if len(ctx.bars) >= strategy.warmup else None
            is_entry = signal is not None and signal.signal in (SignalAction.BUY, SignalAction.SELL)
            if is_entry and square_off_eod and is_eod[i]:
                is_entry = False  # never open a squared-off style's position on the day's last bar
            if is_entry and adx_series is not None and adx_series[i] < adx_regime:
                is_entry = False  # regime gate: no fresh premium in trendless tape
            if is_entry:
                legs = build_structure(strategy_id, signal.signal, bar.close, strike_step, otm_pct)
                entry_dte = _real_entry_dte(bar.ts, expiry_weekday) if expiry_weekday is not None else dte_days
                t_years = entry_dte / 365
                entry_net = _structure_value(legs, bar.close, t_years, sigma)
                leg_prices = [leg.price(bar.close, t_years, sigma) for leg in legs]
                charges = leg_charges(legs, leg_prices)
                total_charges += charges
                cash -= charges
                open_structure = _OpenStructure(legs, entry_net, bar.ts, entry_dte)

        mark = 0.0
        if open_structure is not None:
            t_left = max((open_structure.expiry_ts - bar.ts).total_seconds(), 0) / (365 * 24 * 3600)
            current_value = _structure_value(open_structure.legs, bar.close, max(t_left, 1e-6), sigma)
            mark = (open_structure.entry_net_premium - current_value) * lot_size * quantity_lots
        equity_ts.append(bar.ts)
        equity.append(cash + mark)

    config = BacktestConfig(
        strategy_id=strategy_id, symbol=symbol, timeframe=timeframe, initial_capital=initial_capital,
        asset_class=AssetClass.INDEX_OPTION, lot_size=lot_size, params=params or {},
    )
    run = BacktestRun(
        config=config, trades=trades, equity_ts=equity_ts, equity=equity,
        bars_in_market=sum(1 for _ in trades), total_bars=len(underlying_bars),
        total_charges=round(total_charges, 2),
    )

    out_trades = None
    if include_trades:
        out_trades = [
            {
                "entry_ts": t.entry_ts, "exit_ts": t.exit_ts, "entry_price": t.entry_price,
                "exit_price": t.exit_price, "pnl": t.pnl, "charges": t.charges,
                "exit_reason": t.exit_reason, "legs": legs,
            }
            for t, legs in zip(trades, trade_legs)
        ]
        if open_structure is not None:  # capital is still locked in this position
            out_trades.append({
                "entry_ts": open_structure.entry_ts, "exit_ts": None,
                "entry_price": round(open_structure.entry_net_premium, 2),
                "exit_price": None, "pnl": None, "charges": None, "exit_reason": "open",
                "legs": [(leg.option_type, leg.strike) for leg in open_structure.legs],
            })
    return {
        "metrics": compute_metrics(run), "charts": compute_charts(run),
        **({"trades": out_trades} if out_trades is not None else {}),
        "structure": {
            "dte_days": dte_days, "otm_pct": otm_pct, "strike_step": strike_step,
            "lot_size": lot_size, "quantity_lots": quantity_lots, "iv_lookback": iv_lookback,
            "pricing_model": "black_scholes_realized_vol_proxy",
            "style": buying_category, "square_off_eod": square_off_eod,
            "premium_stop_pct": premium_stop_pct, "premium_target_pct": premium_target_pct,
            "adx_regime": adx_regime,
        },
    }
