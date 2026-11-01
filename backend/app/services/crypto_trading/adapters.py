"""The crypto adapters: the instrument, the two libraries' bars, the Delta fee card and funding.

THE UNIT TRADED IS ONE VENUE CONTRACT
-------------------------------------
Both libraries size in whole units (the Factory's `position_size` floors to an integer, the
Strategies module's risk engine returns an integer quantity), and a $10,000 account cannot hold a
whole BTC. So bars are expressed per CONTRACT: Delta's BTCUSD contract is 0.001 BTC, so a $77,550
BTC bar becomes a $77.55 contract bar, and quantities are contracts - exactly how the venue counts
them. Every indicator, pattern and level these strategies use is scale-free, so nothing they
decide changes. For the Strategies module's engine, which rounds fills to two decimals, the unit is
a bundle of contracts priced at $100 or more (100 XRP contracts, say), so the rounding is below
0.01% of price.

COSTS
-----
Delta India's taker fee on notional plus 18% GST, both sides; slippage per coin (config); funding
at every exchange a position is held through, from the venue's own funding history - charged per
trade after the replay (the replays have no clock for it), using the rate in force at the exchange
(the close of the latest hourly funding candle that had ENDED by then - never a later one).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime

from app.services.gold_fills import funding_cost, funding_exchanges

from .config import DELTA_GST, FUNDING_RES_S, IST, UTC


class FBar:
    """The Strategy Factory's bar shape (strategy_factory.sources.Bar), defined here so the sweep
    imports no database module."""

    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts, o, h, l, c, v):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v


@dataclass(frozen=True)
class Contract:
    symbol: str               # venue symbol, e.g. BTCUSD
    coin: str                 # BTC
    contract_value: float     # coins per contract
    taker_fee: float          # fraction of notional
    funding_interval_s: int
    slippage_bps: float

    @classmethod
    def from_coin(cls, c: dict) -> "Contract":
        return cls(symbol=c["venue_symbol"], coin=c["symbol"], contract_value=float(c["contract_value"]),
                   taker_fee=float(c.get("taker_fee") or 0.0005), funding_interval_s=int(c.get("funding_interval_s") or 28800),
                   slippage_bps=float(c.get("slippage_bps") or 5.0))


def sm_unit(contract: Contract, price: float) -> int:
    """Contracts per Strategies-module unit: the fewest that price a unit at >= $100 (2 BTC
    contracts, 80 XRP), so two-decimal rounding stays below 0.01% while sizing stays fine-grained."""
    per = max(price * contract.contract_value, 1e-12)
    return max(1, math.ceil(100.0 / per))


def factory_bars(rows: list[list], contract: Contract) -> list[FBar]:
    cv = contract.contract_value
    return [FBar(datetime.fromtimestamp(t, UTC), o * cv, h * cv, lo * cv, c * cv, v) for t, o, h, lo, c, v in rows]


def sm_bars(rows: list[list], contract: Contract, tf: str, unit: int, nse_clock: bool):
    """The Strategies module's own Bar model. Volume is an integer there: venue contracts, in units.
    An NSE-clock strategy gets each bar's UTC wall clock relabelled as IST (`ts.replace(tzinfo=IST)`),
    so its IST session logic reads the UTC day - see config.SESSION_NOTE. `real_ts` undoes it."""
    from tradingai_shared.domain import Bar as SBar, Timeframe
    k = contract.contract_value * unit
    out = []
    for t, o, h, lo, c, v in rows:
        dt = datetime.fromtimestamp(t, UTC)
        out.append(SBar(symbol=contract.symbol, timeframe=Timeframe(tf), ts=dt.replace(tzinfo=IST) if nse_clock else dt,
                        open=o * k, high=h * k, low=lo * k, close=c * k, volume=int(v // unit)))
    return out


def real_ts(ts: datetime, nse_clock: bool) -> datetime:
    return ts.replace(tzinfo=UTC) if nse_clock else ts.astimezone(UTC)


def fee(notional: float, taker_fee: float) -> float:
    """Delta India's charge on one fill: the taker rate on notional, plus 18% GST on it."""
    return abs(notional) * taker_fee * (1 + DELTA_GST)


def register_factory_cost_model(contract: Contract) -> str:
    """The Factory looks costs up by NAME (`primitives.COST_MODELS`) and falls back to MCX charges
    for a name it does not know - so the crypto card is registered under its own name first."""
    from app.services.strategy_factory import primitives
    name = f"delta_perp:{contract.symbol}"
    if name not in primitives.COST_MODELS:
        rate = contract.taker_fee
        primitives.COST_MODELS[name] = lambda price, qty, is_buy, _r=rate: fee(price * qty, _r)
    return name


def sm_cost_model(contract: Contract):
    """The Strategies module's CostModel with Delta's card in place of the NSE one."""
    from backtesting_service.costs import CostModel

    class DeltaCostModel(CostModel):
        taker_fee: float = contract.taker_fee

        def order_charges(self, product: str, price: float, quantity: int, is_buy: bool) -> float:  # noqa: ARG002
            return fee(price * quantity, self.taker_fee)

    return DeltaCostModel()


# -- funding ----------------------------------------------------------------------------------------


def rate_at(times: list[int], rates: list[float], ts: int) -> float | None:
    """The funding rate in force at an exchange at `ts`: the close of the latest hourly funding candle
    that had ENDED by then (gold_delta_feed.rate_at's rule; the candle starting AT the exchange
    quotes the NEXT one). None before the series starts."""
    i = bisect_right(times, ts - FUNDING_RES_S) - 1
    return rates[i] if i >= 0 else None


def trade_funding(entry_ts: datetime, exit_ts: datetime, side: int, qty: float, interval_s: int,
                  bar_times: list[int], bar_closes: list[float], f_times: list[int], f_rates: list[float],
                  bar_s: int) -> tuple[float, int]:
    """Funding paid (+) or received (-) by one trade, and the exchanges it was held through. Notional
    at each exchange = the close of the latest bar that had CLOSED by then x quantity (bars already
    per unit; `bar_times` are open times, `bar_s` the bar length)."""
    total, n = 0.0, 0
    for t in funding_exchanges(int(entry_ts.timestamp()), int(exit_ts.timestamp()), interval_s):
        rate = rate_at(f_times, f_rates, t)
        j = bisect_right(bar_times, t - bar_s) - 1
        if rate is None or j < 0:
            continue
        total += funding_cost(side, bar_closes[j] * qty, rate)
        n += 1
    return total, n
