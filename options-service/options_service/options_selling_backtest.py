"""Backtest driver for the option-SELLING library — net-credit structures, margin
blocked, mark-to-market while open, and risk control the strategy cannot opt out of.

RELATIONSHIP TO `options_backtest.py`
------------------------------------
That module owns the PRICING (Black-Scholes fed by the underlying's realized vol) and
this one reuses it wholesale — `Leg`, `_structure_value`, `_realized_vol`,
`_daily_close_series`, `_real_entry_dte` are imported, not reimplemented. There is one
pricing engine in this app and this is not a second one.

What is genuinely different, and why this is a separate driver rather than a flag on the
buying one:

  1. RISK IS INVERTED. A buyer's worst case is the premium paid and the engine can
     simply let a losing position run to expiry. A seller's worst case on an uncovered
     short is unbounded, so exits are mandatory and are evaluated against the bar's
     EXTREMES, not just its close (see `_worst_intrabar_value`). A close-only stop on a
     short strangle systematically under-reports the losses that actually kill selling
     desks.

  2. MARGIN, NOT PREMIUM, IS THE CAPITAL CONSTRAINT. Every entry blocks margin
     (`options_service.margin`), positions are refused when margin exceeds free capital,
     and the results report return-on-margin — the only capital-efficiency number that
     means anything for a seller.

  3. P&L IS MARKED TO MARKET, NOT ENTRY-VS-EXIT. Credit is taken in at entry; the
     open position's unrealized P&L is (credit - current cost to close) at every bar,
     which is what drives both the equity curve and the stop.

  4. TAIL METRICS ARE FIRST-CLASS. `compute_metrics` alone cannot gate a selling
     strategy: an 85%-win-rate short strangle that gives it all back on three gap days
     passes every win-rate test and is still ruinous. The `selling` block added to the
     metrics carries worst-trade-vs-capital, tail ratio, and the naked share of trades,
     which is what the Phase 2 qualification gate actually reads.

EXIT VOCABULARY
---------------
  target           premium decayed to the take-profit fraction of the credit
  stop             cost-to-close expanded past the loss cap (checked intrabar)
  strike_pressure  spot reached a short strike's buffer — capped before the stop had to
  capital_stop     unrealized loss breached the hard % -of-capital ceiling
  expiry           held to expiry (worthless credit kept, or assigned intrinsic paid)
  signal           the strategy's own regime read forced it shut
  eod              intraday style squared off at the session's last bar

HONEST LIMITS
-------------
  * Premiums are modelled (Black-Scholes on realized vol), not quoted. Dhan serves no
    expired-chain history, the same constraint the buying lab accepted.
  * Stops fill at the stop level. A real gap through a short strike fills worse; this
    engine cannot model that, so a naked strategy's true tail is at least as bad as
    reported here and never better.
  * One structure open at a time per run, matching the rest of this codebase's model.
  * Fixed lot count per run so strategies stay comparable in a sweep. Margin-budgeted
    sizing belongs to the live desk, which knows its own free capital.
"""

import math
from datetime import timedelta
from uuid import uuid4

from backtesting_service.charts import compute_charts
from backtesting_service.costs import CostModel
from backtesting_service.engine import BacktestConfig, BacktestRun
from backtesting_service.metrics import compute_metrics
from options_service.greeks import black_scholes_greeks
from options_service.margin import estimate_margin
from options_service.options_backtest import (
    Leg,
    _daily_close_series,
    _real_entry_dte,
    _realized_vol,
    _round_to_step,
    _structure_value,
)
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
from tradingai_shared.domain import (
    AssetClass,
    Bar,
    SignalAction,
    Timeframe,
    Trade,
    TradeStatus,
    TransactionType,
)

# Style defaults for the selling library. The management numbers are the ones real
# premium sellers actually run, not invented constants:
#
#   credit_target_pct 0.50 — buy the structure back once half the credit has decayed.
#     Standard practice: the last half of the credit takes disproportionately longer to
#     earn and carries the whole gamma tail while it does.
#   loss_cap_mult 1.0 — close when the unrealized LOSS reaches N times the credit taken
#     in. Note the convention: this counts the loss, not the buy-back price. The common
#     industry phrasing "stop at 2x credit" means paying 2C to close a position that
#     collected C, i.e. a loss of 1C — so that rule is loss_cap_mult = 1.0, not 2.0.
#     Paired with a 50%-of-credit target this is a 1:2 reward:risk, which needs a ~67%
#     win rate to break even; premium selling routinely runs 70-85%, so the pairing is
#     coherent rather than arbitrary.
#   strike_buffer_pct — close when spot comes within this fraction of a SHORT strike
#     (0.0 = the strike itself). This is a BACKSTOP, not a first responder: on a typical
#     12-delta short the premium stop is much tighter (premium doubles after roughly a
#     third of the distance to the strike) and fires first. The wall earns its place in
#     the cases where premium has NOT repriced to match the danger — thin quotes, a
#     volatility collapse masking a directional move — because it reads the underlying
#     rather than the option.
#   max_loss_pct_capital — the non-negotiable backstop. Nothing can hold a position past
#     it, whatever the strategy or the other thresholds say.
OPTION_SELLING_CATEGORIES = {
    # Sell in the morning, flat by the close. No overnight gap risk at all, which is why
    # this style tolerates the tightest strikes and the loosest loss cap.
    "options_sell_intraday": {
        "dte_days": 3, "square_off_eod": True,
        "credit_target_pct": 0.50, "loss_cap_mult": 1.0,
        "strike_buffer_pct": 0.0, "max_loss_pct_capital": 0.02,
    },
    # Expiry-day and near-expiry decay harvesting: the fastest theta in the cycle and
    # the sharpest gamma. Tightest loss cap in the library, for exactly that reason.
    "options_sell_expiry": {
        "dte_days": 1, "square_off_eod": True,
        "credit_target_pct": 0.40, "loss_cap_mult": 0.75,
        "strike_buffer_pct": 0.0, "max_loss_pct_capital": 0.02,
    },
    # Entries read off 15m bars, then HELD across sessions to the weekly expiry.
    #
    # This style exists because of a measured result, not a hunch. The intraday style
    # above squares off at the bell, and that alone destroyed the edge of every neutral
    # strategy in the library: `sell_dead_tape_condor` runs at PF 0.66 (net -9,787) as
    # an intraday trade and PF 2.16 (net +276,855) on identical entries and strikes when
    # simply held to a 7-day expiry. Theta is paid in days; a position closed after a few
    # hours has collected a sliver of decay and paid round-trip charges for it, while
    # carrying the full gamma risk in between. Holding across sessions adds real
    # overnight gap exposure, which is why this style sits between intraday and
    # positional on the capital ceiling.
    #
    # Callers should pass `expiry_weekday` so entries price off the REAL weekly cycle;
    # the 7-day figure here is only the fallback when they do not. A flat 7 days is not
    # a listed contract on any entry day but one, and it overstates the time value a
    # late-week entry actually collects.
    "options_sell_swing": {
        "dte_days": 7, "square_off_eod": False,
        "credit_target_pct": 0.50, "loss_cap_mult": 1.0,
        "strike_buffer_pct": 0.0, "max_loss_pct_capital": 0.025,
    },
    # Held across sessions to the monthly. Carries real gap risk, so it gets the widest
    # strike buffer and the tightest capital ceiling.
    "options_sell_positional": {
        "dte_days": 30, "square_off_eod": False,
        "credit_target_pct": 0.50, "loss_cap_mult": 1.5,
        "strike_buffer_pct": 0.002, "max_loss_pct_capital": 0.03,
    },
}

DEFAULT_STRIKE_STEP = 50.0
DEFAULT_IV_LOOKBACK = 20
# Widest window the delta solver will look for a strike, as a fraction of spot. A
# 0.05-delta strike on a quiet weekly sits well inside this; anything outside it is a
# strike nobody would actually trade.
_DELTA_SEARCH_PCT = 0.25


def _selling_category(strategy_id: str) -> str | None:
    cls = STRATEGY_REGISTRY.get(strategy_id)
    if cls is None:
        return None
    category = cls.metadata.category
    return category if category in OPTION_SELLING_CATEGORIES else None


def _inv_norm_cdf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation, ~1e-9 accurate).

    Needed because the strike-for-delta problem inverts in closed form and this is the
    only piece Python's math module does not provide.
    """
    if p <= 0.0:
        return -40.0
    if p >= 1.0:
        return 40.0
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def strike_for_delta(
    spot: float, t_years: float, sigma: float, option_type: str,
    target_delta: float, strike_step: float, rate: float = 0.065,
) -> float:
    """The listed strike whose |delta| is closest to `target_delta`.

    This is how premium sellers actually choose strikes, and it is why `target_delta`
    exists alongside `otm_pct` in LegSpec: a 15-delta strike automatically sits further
    out when volatility is high (exactly when you want more room) and closer in when it
    is low. A fixed OTM percentage does the opposite of what the tape is asking for.

    Solved in closed form rather than scanned. Call delta is N(d1), so the d1 that
    produces a target delta is just the inverse normal CDF of it, and d1's definition
    rearranges to give the strike directly:

        d1 = [ln(S/K) + (r + sigma^2/2)T] / (sigma sqrt(T))
        =>  K = S * exp(-d1*sigma*sqrt(T) + (r + sigma^2/2)T)

    The earlier implementation swept ~250 candidate strikes calling the full Greeks
    routine at each one — 250 evaluations of five Greeks to select a single strike, per
    entry, which dominated the runtime of the whole sweep. This is one evaluation and is
    also exact rather than grid-limited.
    """
    target = min(max(abs(target_delta), 1e-4), 0.9999)
    t = max(t_years, 1e-6)
    vol_t = max(sigma, 1e-6) * math.sqrt(t)
    is_call = option_type.upper() == "CE"
    # Put delta is -N(-d1), so |delta| = N(-d1) and the sign of d1 flips.
    d1 = _inv_norm_cdf(target) if is_call else -_inv_norm_cdf(target)
    strike = spot * math.exp(-d1 * vol_t + (rate + 0.5 * max(sigma, 1e-6) ** 2) * t)
    rounded = _round_to_step(strike, strike_step)
    if rounded <= 0:
        return _round_to_step(spot, strike_step)
    # Keep the leg on the correct side of spot: rounding a near-ATM target can otherwise
    # put a "short call" below spot, silently turning an OTM structure into an ITM one.
    if is_call and rounded <= spot:
        rounded = _round_to_step(spot, strike_step) + strike_step
    elif not is_call and rounded >= spot:
        rounded = _round_to_step(spot, strike_step) - strike_step
    return rounded


def materialize_legs(
    specs, spot: float, t_years: float, sigma: float, strike_step: float,
) -> list[Leg]:
    """Turn a strategy's relative LegSpecs into priced-able Legs at this spot.

    Two passes, because a `wing_pct` leg is defined relative to the short leg it
    protects: shorts and spot-anchored legs resolve first, then wings hang off the
    resolved short strike of their own option type.
    """
    resolved: list[Leg | None] = [None] * len(specs)
    short_strike: dict[str, float] = {}

    for i, spec in enumerate(specs):
        if spec.wing_pct is not None:
            continue
        option_type = spec.option_type.upper()
        if spec.target_delta is not None:
            strike = strike_for_delta(spot, t_years, sigma, option_type, spec.target_delta, strike_step)
        else:
            strike = _round_to_step(spot * (1 + spec.otm_pct), strike_step)
        resolved[i] = Leg(
            option_type, strike, TransactionType.SELL if spec.sell else TransactionType.BUY
        )
        if spec.sell:
            short_strike[option_type] = strike

    for i, spec in enumerate(specs):
        if spec.wing_pct is None:
            continue
        option_type = spec.option_type.upper()
        anchor = short_strike.get(option_type)
        if anchor is None:
            raise ValueError(
                f"wing_pct leg ({option_type}) has no short {option_type} leg to anchor to"
            )
        # A call wing sits above its short call; a put wing below its short put. Forced
        # at least one strike step away so rounding can never collapse the wing onto the
        # short leg and silently turn a defined-risk spread into a naked position.
        offset = anchor * spec.wing_pct
        raw = anchor + offset if option_type == "CE" else anchor - offset
        strike = _round_to_step(raw, strike_step)
        if option_type == "CE" and strike <= anchor:
            strike = anchor + strike_step
        elif option_type == "PE" and strike >= anchor:
            strike = anchor - strike_step
        resolved[i] = Leg(option_type, strike, TransactionType.BUY)

    return [leg for leg in resolved if leg is not None]


def _pressure_levels(legs: list[Leg], entry_spot: float) -> tuple[float | None, float | None]:
    """(short CE wall, short PE wall) — the levels whose breach means the underlying has
    travelled to a strike this structure is short, or None where no such level exists.

    Only strikes that were OUT of the money at entry qualify. An ATM short (a straddle,
    an iron butterfly) is already at its strike the moment it is opened, so treating
    proximity-to-strike as an alarm there would fire on the entry bar of every single
    trade and close it before any decay could happen — which is exactly what an earlier
    version of this engine did, turning all 13 of the expiry straddle's trades into
    one-bar `strike_pressure` scratches. For those structures the premium stop is the
    only per-position control, which is correct: an ATM short has no wall to breach.
    """
    short_ce = [
        l.strike for l in legs
        if l.direction == TransactionType.SELL and l.option_type == "CE" and l.strike > entry_spot
    ]
    short_pe = [
        l.strike for l in legs
        if l.direction == TransactionType.SELL and l.option_type == "PE" and l.strike < entry_spot
    ]
    return (min(short_ce) if short_ce else None, max(short_pe) if short_pe else None)


def _worst_intrabar_value(legs: list[Leg], bar: Bar, t_years: float, sigma: float) -> float:
    """Highest cost-to-close the structure reached anywhere inside this bar.

    A short structure's value is not monotonic in spot (a strangle hurts in both
    directions), so the worst point is whichever of the bar's low, close and high
    reprices the structure most expensively. Evaluating stops on the close alone would
    silently skip every intrabar spike — the exact events a selling desk needs its stop
    to catch.
    """
    return max(
        _structure_value(legs, probe, t_years, sigma)
        for probe in (bar.low, bar.close, bar.high)
        if probe > 0
    )


class _OpenStructure:
    __slots__ = ("legs", "credit", "entry_ts", "expiry_ts", "margin", "margin_basis",
                 "max_loss", "entry_spot", "entry_sigma", "wall_ce", "wall_pe")

    def __init__(self, legs, credit, entry_ts, dte_days, margin_info, entry_spot, entry_sigma):
        self.legs = legs
        self.credit = credit  # net premium RECEIVED per unit, positive for a credit
        self.entry_ts = entry_ts
        self.expiry_ts = entry_ts + timedelta(days=dte_days)
        self.margin = margin_info["margin"]
        self.margin_basis = margin_info["basis"]
        self.max_loss = margin_info["max_loss"]
        self.entry_spot = entry_spot
        self.entry_sigma = entry_sigma
        # Frozen at entry: which strikes started OTM and therefore have a wall worth
        # watching. Recomputing this each bar against the CURRENT spot would make every
        # strike look ATM the moment price reached it, which is the alarm itself.
        self.wall_ce, self.wall_pe = _pressure_levels(legs, entry_spot)


def run_options_selling_backtest(
    strategy_id: str, symbol: str, timeframe: Timeframe, underlying_bars: list[Bar],
    initial_capital: float = 1_000_000, lot_size: int = 75, quantity_lots: int = 1,
    dte_days: int | None = None, strike_step: float = DEFAULT_STRIKE_STEP,
    iv_lookback: int = DEFAULT_IV_LOOKBACK, params: dict | None = None,
    square_off_eod: bool | None = None, credit_target_pct: float | None = None,
    loss_cap_mult: float | None = None, strike_buffer_pct: float | None = None,
    max_loss_pct_capital: float | None = None, include_trades: bool = False,
    expiry_weekday: int | None = None,
) -> dict:
    category = _selling_category(strategy_id)
    if category is None:
        raise ValueError(
            f"{strategy_id!r} is not a registered option-SELLING strategy "
            f"(categories {sorted(OPTION_SELLING_CATEGORIES)})"
        )

    style = OPTION_SELLING_CATEGORIES[category]
    dte_days = style["dte_days"] if dte_days is None else dte_days
    square_off_eod = style["square_off_eod"] if square_off_eod is None else square_off_eod
    credit_target_pct = style["credit_target_pct"] if credit_target_pct is None else credit_target_pct
    loss_cap_mult = style["loss_cap_mult"] if loss_cap_mult is None else loss_cap_mult
    strike_buffer_pct = style["strike_buffer_pct"] if strike_buffer_pct is None else strike_buffer_pct
    max_loss_pct_capital = (
        style["max_loss_pct_capital"] if max_loss_pct_capital is None else max_loss_pct_capital
    )

    quantity = lot_size * quantity_lots

    is_eod = [
        i + 1 >= len(underlying_bars) or underlying_bars[i + 1].ts.date() != bar.ts.date()
        for i, bar in enumerate(underlying_bars)
    ]

    daily_dates, daily_closes = _daily_close_series(underlying_bars)
    daily_ptr = 0

    strategy = STRATEGY_REGISTRY[strategy_id](params=params or {})
    ctx = StrategyContext(max_bars=max(500, strategy.warmup + 2))
    cost_model = CostModel()

    cash = initial_capital
    open_structure: _OpenStructure | None = None
    trades: list[Trade] = []
    trade_extras: list[dict] = []
    equity_ts, equity = [], []
    total_charges = 0.0
    margins_used: list[float] = []
    credits_collected: list[float] = []
    naked_trades = 0
    rejected_for_margin = 0

    def leg_charges(legs: list[Leg], premium_each: list[float]) -> float:
        return sum(
            cost_model.order_charges(
                "options", max(price, 0.05), quantity, is_buy=leg.direction == TransactionType.BUY
            )
            for leg, price in zip(legs, premium_each)
        )

    def close_structure(struct: _OpenStructure, bar: Bar, t_left: float, sigma: float,
                        exit_value: float, reason: str) -> None:
        nonlocal cash, total_charges
        leg_prices = [leg.price(bar.close, max(t_left, 1e-6), sigma) for leg in struct.legs]
        charges = leg_charges(struct.legs, leg_prices)
        total_charges += charges
        # Credit taken in at entry minus what it costs to buy the structure back. Sign
        # convention matches options_backtest: `_structure_value` is positive for a net
        # credit, so entry_credit - exit_value is the per-unit gain.
        pnl = (struct.credit - exit_value) * quantity - charges
        trades.append(
            Trade(
                trade_id=uuid4().hex[:12], strategy_id=strategy_id, symbol=symbol,
                direction=TransactionType.SELL, quantity=quantity,
                entry_price=round(struct.credit, 2), entry_ts=struct.entry_ts,
                exit_price=round(exit_value, 2), exit_ts=bar.ts, status=TradeStatus.CLOSED,
                exit_reason=reason, charges=round(charges, 2), pnl=round(pnl, 2),
            )
        )
        trade_extras.append({
            "legs": [(l.option_type, l.strike, l.direction.value) for l in struct.legs],
            "margin": struct.margin, "margin_basis": struct.margin_basis,
            "credit": round(struct.credit, 2), "entry_spot": round(struct.entry_spot, 2),
            "exit_spot": round(bar.close, 2),
        })
        cash += pnl
        strategy.position_closed()

    for i, bar in enumerate(underlying_bars):
        while daily_ptr < len(daily_dates) and daily_dates[daily_ptr] < bar.ts.date():
            daily_ptr += 1
        sigma = _realized_vol(daily_closes[:daily_ptr], iv_lookback)

        ctx.push(bar)
        signal = strategy.on_bar(ctx) if len(ctx.bars) >= strategy.warmup else None

        if open_structure is not None:
            struct = open_structure
            t_left = max((struct.expiry_ts - bar.ts).total_seconds(), 0) / (365 * 24 * 3600)
            expired = t_left <= 0
            t_price = max(t_left, 1e-6)

            close_value = _structure_value(struct.legs, bar.close, t_price, sigma)
            # Unrealized P&L per unit; negative means the structure costs more to close
            # than the credit taken in.
            unrealized = struct.credit - close_value

            reason, exit_value = None, close_value
            if expired:
                reason = "expiry"
            elif signal is not None and signal.signal == SignalAction.EXIT_SHORT:
                reason = "signal"

            if reason is None:
                # --- risk controls, evaluated worst-first ---------------------------
                pressured = (
                    (struct.wall_ce is not None and bar.high >= struct.wall_ce * (1 - strike_buffer_pct))
                    or (struct.wall_pe is not None and bar.low <= struct.wall_pe * (1 + strike_buffer_pct))
                )
                worst_value = _worst_intrabar_value(struct.legs, bar, t_price, sigma)
                worst_unrealized = struct.credit - worst_value

                stop_level = -abs(struct.credit) * loss_cap_mult
                capital_level = -(max_loss_pct_capital * initial_capital) / quantity

                if worst_unrealized <= capital_level:
                    # Hard capital backstop — the one nothing overrides.
                    reason = "capital_stop"
                    exit_value = struct.credit - capital_level
                elif worst_unrealized <= stop_level:
                    reason = "stop"
                    exit_value = struct.credit - stop_level
                elif pressured:
                    # Spot reached a short strike's buffer. Exit at the honest cost of
                    # closing at that adverse extreme, not at the friendlier close.
                    reason = "strike_pressure"
                    exit_value = worst_value
                elif credit_target_pct is not None and struct.credit > 0 and unrealized >= struct.credit * credit_target_pct:
                    # Take-profit reads the CLOSE, not the intrabar best. Asymmetric on
                    # purpose: losses get the pessimistic read, gains the conservative
                    # one, so nothing here flatters the strategy.
                    reason = "target"
                elif square_off_eod and is_eod[i]:
                    reason = "eod"

            if reason is not None:
                close_structure(struct, bar, t_left, sigma, exit_value, reason)
                open_structure = None

        elif signal is not None and signal.signal == SignalAction.SELL:
            blocked = square_off_eod and is_eod[i]  # never open a squared-off style at the bell
            if not blocked:
                entry_dte = (
                    _real_entry_dte(bar.ts, expiry_weekday) if expiry_weekday is not None else dte_days
                )
                t_years = entry_dte / 365
                specs = strategy.legs(ctx)
                legs = materialize_legs(specs, bar.close, t_years, sigma, strike_step)
                leg_prices = [leg.price(bar.close, t_years, sigma) for leg in legs]
                credit = _structure_value(legs, bar.close, t_years, sigma)

                margin_info = estimate_margin(legs, bar.close, lot_size, quantity_lots, leg_prices)
                if credit <= 0:
                    # A "selling" structure that costs money to put on is a construction
                    # bug, not a trade. Refuse it rather than book a debit as a credit.
                    strategy.position_closed()
                elif margin_info["margin"] > cash:
                    rejected_for_margin += 1
                    strategy.position_closed()
                else:
                    charges = leg_charges(legs, leg_prices)
                    total_charges += charges
                    cash -= charges
                    open_structure = _OpenStructure(
                        legs, credit, bar.ts, entry_dte, margin_info, bar.close, sigma
                    )
                    margins_used.append(margin_info["margin"])
                    credits_collected.append(credit * quantity)
                    if margin_info["basis"] == "naked_span":
                        naked_trades += 1

        mark = 0.0
        if open_structure is not None:
            t_left = max((open_structure.expiry_ts - bar.ts).total_seconds(), 0) / (365 * 24 * 3600)
            current = _structure_value(open_structure.legs, bar.close, max(t_left, 1e-6), sigma)
            mark = (open_structure.credit - current) * quantity
        equity_ts.append(bar.ts)
        equity.append(cash + mark)

    config = BacktestConfig(
        strategy_id=strategy_id, symbol=symbol, timeframe=timeframe,
        initial_capital=initial_capital, asset_class=AssetClass.INDEX_OPTION,
        lot_size=lot_size, params=params or {},
    )
    run = BacktestRun(
        config=config, trades=trades, equity_ts=equity_ts, equity=equity,
        bars_in_market=sum(1 for _ in trades), total_bars=len(underlying_bars),
        total_charges=round(total_charges, 2),
    )
    metrics = compute_metrics(run)
    metrics["selling"] = _selling_metrics(
        trades, metrics, initial_capital, margins_used, credits_collected,
        naked_trades, rejected_for_margin,
    )

    out = {
        "metrics": metrics,
        "charts": compute_charts(run),
        "structure": {
            "style": category, "dte_days": dte_days, "strike_step": strike_step,
            "lot_size": lot_size, "quantity_lots": quantity_lots, "iv_lookback": iv_lookback,
            "square_off_eod": square_off_eod, "credit_target_pct": credit_target_pct,
            "loss_cap_mult": loss_cap_mult, "strike_buffer_pct": strike_buffer_pct,
            "max_loss_pct_capital": max_loss_pct_capital,
            "pricing_model": "black_scholes_realized_vol_proxy",
            "margin_model": "span_exposure_approximation",
        },
    }
    if include_trades:
        out["trades"] = [
            {
                "entry_ts": t.entry_ts, "exit_ts": t.exit_ts, "entry_price": t.entry_price,
                "exit_price": t.exit_price, "pnl": t.pnl, "charges": t.charges,
                "exit_reason": t.exit_reason, **extra,
            }
            for t, extra in zip(trades, trade_extras)
        ]
        if open_structure is not None:
            out["trades"].append({
                "entry_ts": open_structure.entry_ts, "exit_ts": None,
                "entry_price": round(open_structure.credit, 2), "exit_price": None,
                "pnl": None, "charges": None, "exit_reason": "open",
                "legs": [(l.option_type, l.strike, l.direction.value) for l in open_structure.legs],
                "margin": open_structure.margin, "margin_basis": open_structure.margin_basis,
                "credit": round(open_structure.credit, 2),
                "entry_spot": round(open_structure.entry_spot, 2), "exit_spot": None,
            })
    return out


# --- qualification gate ----------------------------------------------------------
#
# The buying lab gates on win rate. Reusing that here would be worse than useless: this
# library's own sweep contains sell_coil_strangle at an 83.9% win rate and a 0.33 profit
# factor, losing money on 31 trades. A win-rate gate would have promoted it.
#
# Every threshold below, and why it is that number:
#
#   min_profit_factor 1.3 — gross wins must exceed gross losses by 30%. Not 1.0: these
#     premiums are Black-Scholes models, not quotes, and the gap between a modelled and a
#     real premium is worth more than a few percent of edge. A strategy at PF 1.05 is
#     indistinguishable from a strategy at PF 0.95 given that modelling error.
#
#   min_trades 20 — below this, profit factor is an anecdote. The buying lab used 10;
#     selling needs more because its P&L is dominated by rare large losers, so a sample
#     that has not yet contained one looks spectacular.
#
#   max_worst_trade_pct_capital 1.5 — no single trade may cost more than 1.5% of
#     capital. Deliberately STRICTER than the engine's own 2%/3% capital backstop: the
#     backstop is what stops a catastrophe, and a strategy that routinely needs it is not
#     one to promote. This is the tail-risk gate proper — the thing win rate cannot see.
#
#   max_drawdown_pct 10 — a selling desk that draws down more than this is not being
#     paid enough for the risk it is running.
#
#   NAKED structures face a stricter bar (PF 1.6, worst trade 1.0%). Not a preference for
#     defined risk on principle, but a correction for known model optimism: this engine
#     fills stops AT the stop level, and the one thing a naked short cannot survive is a
#     gap that fills far through it. The reported tail for a naked strategy is therefore
#     a best case, and the extra margin is the price of that uncertainty. A defined-risk
#     structure has no such gap exposure — its wings cap the loss no matter the fill.
SELLING_GATE = {
    "min_profit_factor": 1.3,
    "min_trades": 20,
    "max_worst_trade_pct_capital": 1.5,
    "max_drawdown_pct": 10.0,
    "naked_min_profit_factor": 1.6,
    "naked_max_worst_trade_pct_capital": 1.0,
    "naked_threshold_pct": 50.0,
}


def qualify(metrics: dict, gate: dict | None = None) -> dict:
    """Judge one selling backtest against the gate.

    Returns {"qualified", "naked", "reasons"} where `reasons` lists every rule the
    strategy FAILED, in plain language. Returning the reasons rather than a bare boolean
    is the point: a qualification a reader cannot audit is not a qualification.
    """
    g = {**SELLING_GATE, **(gate or {})}
    selling = metrics.get("selling") or {}
    naked = (selling.get("naked_trade_pct") or 0) >= g["naked_threshold_pct"]

    min_pf = g["naked_min_profit_factor"] if naked else g["min_profit_factor"]
    max_worst = g["naked_max_worst_trade_pct_capital"] if naked else g["max_worst_trade_pct_capital"]

    pf = metrics.get("profit_factor")
    trades = metrics.get("total_trades") or 0
    worst = selling.get("worst_trade_pct_capital")
    max_dd = metrics.get("max_drawdown_pct")

    reasons = []
    if trades < g["min_trades"]:
        reasons.append(f"only {trades} trades (need {g['min_trades']})")
    if pf is None:
        # No losing trade at all. Flattering, and almost always a tiny sample rather than
        # a strategy that cannot lose — treat it as unproven, not as infinite edge.
        reasons.append("no profit factor (no losing trades yet — unproven, not perfect)")
    elif pf < min_pf:
        reasons.append(f"profit factor {pf:.2f} below {min_pf}{' (naked bar)' if naked else ''}")
    if worst is None:
        reasons.append("no worst-trade figure")
    elif worst > max_worst:
        reasons.append(
            f"worst trade cost {worst:.2f}% of capital (cap {max_worst}%"
            f"{', naked bar' if naked else ''})"
        )
    if max_dd is not None and max_dd > g["max_drawdown_pct"]:
        reasons.append(f"max drawdown {max_dd:.1f}% above {g['max_drawdown_pct']}%")

    return {"qualified": not reasons, "naked": naked, "reasons": reasons}


def entry_days(trades) -> set:
    """The set of calendar dates a strategy OPENED a position on.

    Two strategies that open on the same days with similar structures are one bet,
    however differently their entry rules are worded — see `overlap_groups`.
    """
    out = set()
    for t in trades or []:
        ts = t.get("entry_ts")
        if ts is None:
            continue
        out.add(ts.date() if hasattr(ts, "date") else str(ts)[:10])
    return out


def jaccard(a: set, b: set) -> float:
    """Overlap of two entry-day sets, 0.0 (never coincide) to 1.0 (identical)."""
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# Above this entry-day overlap, two strategies are treated as the same bet. 0.60 is a
# judgement call, and a deliberately conservative one: measured pairs in this library
# cluster either below ~0.5 (genuinely different reads) or above ~0.65 (the same quiet-
# tape condor wearing a different regime name), so the threshold sits in the empty band
# between them rather than cutting through a cluster.
DEFAULT_OVERLAP_THRESHOLD = 0.60


def overlap_groups(days_by_strategy: dict, rank: list, threshold: float = DEFAULT_OVERLAP_THRESHOLD):
    """Greedy de-duplication of a qualified set.

    `rank` is the strategy ids best-first (the survivor of each cluster is the one the
    caller ranks highest). Returns (kept, dropped) where `dropped` maps each removed
    strategy to the kept one it duplicates and their overlap.

    This exists because a count of qualifiers is meaningless without it. In this library
    two 'different' dip strategies opened on the same days 98% of the time, and five
    separately-named quiet-tape condors turned out to be one bet — a desk running all
    five would be 5x concentrated while believing it was diversified.
    """
    kept, dropped = [], {}
    for sid in rank:
        mine = days_by_strategy.get(sid, set())
        clash = None
        for k in kept:
            j = jaccard(mine, days_by_strategy.get(k, set()))
            if j >= threshold:
                clash = (k, round(j, 3))
                break
        if clash is None:
            kept.append(sid)
        else:
            dropped[sid] = {"duplicate_of": clash[0], "overlap": clash[1]}
    return kept, dropped


def _selling_metrics(
    trades, metrics: dict, initial_capital: float, margins: list[float],
    credits: list[float], naked_trades: int, rejected_for_margin: int,
) -> dict:
    """The numbers a selling strategy has to be judged on, which `compute_metrics`
    does not produce.

    `worst_trade_pct_capital` and `tail_ratio` exist because win rate is actively
    misleading here. A short strangle that wins 88 times out of 100 and gives back four
    credits on each of the other 12 is a losing strategy with a beautiful win rate, and
    only these two columns say so.
    """
    pnls = [t.pnl for t in trades if t.pnl is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    worst = min(pnls) if pnls else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    avg_margin = sum(margins) / len(margins) if margins else 0.0
    net_profit = metrics.get("net_profit") or 0.0

    exit_counts: dict[str, int] = {}
    for t in trades:
        exit_counts[t.exit_reason or "?"] = exit_counts.get(t.exit_reason or "?", 0) + 1

    return {
        "total_credit_collected": round(sum(credits), 2),
        "avg_credit": round(sum(credits) / len(credits), 2) if credits else 0.0,
        "avg_margin": round(avg_margin, 2),
        "max_margin": round(max(margins), 2) if margins else 0.0,
        # The capital-efficiency number for a seller: profit earned per rupee actually
        # blocked, not per rupee of nominal account size.
        "return_on_margin_pct": round(net_profit / avg_margin * 100, 2) if avg_margin > 0 else None,
        "worst_trade": round(worst, 2),
        "worst_trade_pct_capital": round(abs(worst) / initial_capital * 100, 3) if initial_capital else None,
        # >1.0 means the average loser is bigger than the average winner — structurally
        # normal for selling, and only survivable if the win rate more than pays for it.
        "tail_ratio": round(avg_loss / avg_win, 3) if avg_win > 0 else None,
        # Denominator is ENTRIES, not closed trades: a position still open when the run
        # ends was margined but never booked, and dividing by closed trades let this
        # report percentages above 100.
        "naked_trade_pct": round(naked_trades / len(margins) * 100, 2) if margins else 0.0,
        "trades_rejected_for_margin": rejected_for_margin,
        "exit_reasons": dict(sorted(exit_counts.items(), key=lambda kv: -kv[1])),
    }
