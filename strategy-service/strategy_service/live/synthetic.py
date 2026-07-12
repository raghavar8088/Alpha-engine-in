"""Synthetic bar generator for SIMULATION mode — lets a strategy run be exercised (and
this whole pipeline be smoke-tested) without needing real market hours or real data.
A simple bounded random walk, not a claim of realism."""

import random
from datetime import datetime, timedelta

from tradingai_shared.domain import Bar, Timeframe

_TIMEFRAME_STEP = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.D1: timedelta(days=1),
    Timeframe.W1: timedelta(weeks=1),
}


def generate_synthetic_bars(
    symbol: str,
    timeframe: Timeframe,
    n_bars: int,
    start_price: float = 1000.0,
    daily_vol_pct: float = 1.5,
    start_ts: datetime | None = None,
    seed: int | None = None,
) -> list[Bar]:
    rng = random.Random(seed)
    step = _TIMEFRAME_STEP[timeframe]
    ts = start_ts or datetime.now()
    price = start_price
    bars = []
    for _ in range(n_bars):
        drift = rng.gauss(0, daily_vol_pct / 100)
        open_price = price
        close_price = max(open_price * (1 + drift), 0.01)
        high = max(open_price, close_price) * (1 + abs(rng.gauss(0, daily_vol_pct / 400)))
        low = min(open_price, close_price) * (1 - abs(rng.gauss(0, daily_vol_pct / 400)))
        bars.append(
            Bar(
                symbol=symbol, timeframe=timeframe, ts=ts,
                open=round(open_price, 2), high=round(high, 2), low=round(low, 2),
                close=round(close_price, 2), volume=rng.randint(1000, 50000),
            )
        )
        price = close_price
        ts += step
    return bars
