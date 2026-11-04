"""How an intraday equity paper desk fills — one set of rules for every desk that uses it.

WHY THIS MODULE EXISTS. The tournament (`intraday_v2_engine`) fills like a broker: it walks
the Angel stream's minute bars since its last check, so a stop or target fills AT ITS LEVEL
on the first minute that crosses it — the stop assumed first when one minute crosses both,
a minute that opens beyond a level filling at that open — and every market fill pays
slippage by the name's liquidity. The Patterns desk instead closed at whatever LTP its
three-minute poll happened to see, which booked price that had run PAST a target as profit
and charged no slippage at all. Over its first four sessions (6-9 Oct 2026) that turned a
-Rs23 lakh desk into a reported +Rs53 lakh. These functions were the tournament's own, moved
here verbatim (2026-10-10) so both desks fill by exactly the same rules and cannot drift.

`slippage_bp` stays importable from `intraday_v2_engine` too; its backtest and the S4 study
import it from there.
"""

from __future__ import annotations

import math
import time

from app.services.angel_stream import stream

# ── the cost of a market order ────────────────────────────────────────────────────
# MEASURED, from 2026-11-04 (INTRADAY_STOCKS_AI_UPGRADE_PLAN.md Phase 1; October plan I4).
# The H1 study read Angel's five-level book at 3,355 live tournament entries (12 Oct - 3 Nov
# 2026) and priced a Rs 10 lakh market order against it. Per side, against the LTP the paper
# desks fill at, by the name's traded value that day — 10%-trimmed mean (median):
#     >= 1,000 cr    1.50 bp (1.17)   n 142     half-spread 0.72
#     300-1,000 cr   2.85 bp (2.60)   n 873     half-spread 1.32
#     150-300 cr     3.73 bp (3.53)   n 1,556   half-spread 1.54
#     < 150 cr       4.12 bp (3.79)   n 784     half-spread 1.78
# The average, not the median, because a cost model must charge what trades cost on average
# and these costs are right-skewed; trimmed because a few samples read a stale LTP (-27 to
# +58 bp). Still a LOWER bound where the book was thin: H1 prices the part of an order beyond
# the five visible levels at the worst visible level, and the book was that thin in 11% /
# 41% / 58% / 70% of samples by band.
# ORDER SIZE was only measured at Rs 10 lakh. A smaller order costs less, down to the
# half-spread; until Phase 3's cost model replaces this, cost = half-spread + (measured -
# half-spread) x sqrt(notional / Rs 10 lakh) — the square root being the cautious choice.
COST_MODEL = "h1-measured-2026-11-04"
COST_CUTOVER = "2026-11-05"        # the first session filled under this model (deployed 4 Nov, 22:20 IST)
_MEASURED_NOTIONAL = 1_000_000.0
_BANDS = ((1000.0, 1.50, 0.72), (300.0, 2.85, 1.32), (150.0, 3.73, 1.54), (0.0, 4.12, 1.78))


def slippage_bp(turnover_cr: float | None, notional: float | None = None) -> float:
    """Per-side cost, in bp of price, of one market order in a name with this daily traded
    value (Rs crore), for an order of `notional` rupees (default: the measured Rs 10 lakh).
    An unknown turnover pays the thinnest band. Same function for the backtest."""
    t = turnover_cr or 0.0
    cost, half_spread = _BANDS[-1][1], _BANDS[-1][2]
    for floor, c, hs in _BANDS:
        if t >= floor:
            cost, half_spread = c, hs
            break
    if notional is None or abs(notional - _MEASURED_NOTIONAL) < 1.0:
        return cost
    scale = math.sqrt(max(float(notional), 0.0) / _MEASURED_NOTIONAL)
    return round(half_spread + (cost - half_spread) * scale, 2)


def legacy_slippage_bp(turnover_cr: float | None) -> float:
    """The turnover-bucket model used until 2026-11-04 (1-4 bp, set for a ~Rs 2 lakh order).

    Kept ONLY for pre-registered strategies (iv2_orb_sel15 / iv2_orb_sel30): their expected
    profit was written down under this model, and changing the cost in the middle of their
    forward test would move the verdict without the rule having changed. Everything else
    pays the measured cost above."""
    t = turnover_cr or 0.0
    if t >= 1000:
        return 1.0
    if t >= 300:
        return 2.0
    if t >= 150:
        return 3.0
    return 4.0


def adverse(price: float, side: str, bp: float, opening: bool) -> float:
    """A market fill `bp` basis points worse than `price` for the trader."""
    buying = (side == "BUY") == opening
    return price * (1 + bp / 1e4) if buying else price * (1 - bp / 1e4)


def stream_ltp(symbol: str, max_age_s: float = 90) -> float | None:
    st = stream.states.get(symbol)
    if st is None or st.last_ltp is None or time.time() - st.last_tick > max_age_s:
        return None
    return st.last_ltp


def stream_minutes(symbol: str, since: int) -> list[tuple[int, float, float, float, float]]:
    """Stream minute bars (start, o, h, l, c) from `since` on, including the forming one."""
    st = stream.states.get(symbol)
    if st is None:
        return []
    out = [(st.mt[i], st.mo[i], st.mh[i], st.ml[i], st.mc[i]) for i in range(len(st.mt)) if st.mt[i] >= since]
    if st.cur is not None and st.cur[0] >= since:
        out.append(tuple(st.cur))
    return out


def stream_covers(symbol: str) -> bool:
    """Whether the stream carries this name at all - it subscribes the ~200-name universe."""
    return symbol in stream.states


def scan_exit(p: dict, minutes: list[tuple[int, float, float, float, float]] | None = None
              ) -> tuple[str, float, int] | None:
    """Walk minute bars since the last check: (reason, level price, minute).

    The stream's bars by default. `minutes` (start, o, h, l, c) for a name the stream does
    not carry - Angel's own 1-minute candles - so every name fills by this one rule (added
    2026-10-18; the tournament never passes it)."""
    sign = 1 if p["side"] == "BUY" else -1
    stop, target = p["stoploss"], p.get("target")
    since = p.get("checked_through", 0)
    bars = stream_minutes(p["symbol"], since) if minutes is None else [m for m in minutes if m[0] >= since]
    for t, o, h, l, _c in bars:
        lo, hi = (l, h) if sign > 0 else (-h, -l)
        s_lvl = sign * stop
        o_s = sign * o
        if o_s <= s_lvl:
            return "stoploss", o, t                      # opened through the stop
        if target is not None and o_s >= sign * target:
            return "target", o, t                        # opened through the target
        if lo <= s_lvl:
            return "stoploss", stop, t                   # stop first when both in one minute
        if target is not None and hi >= sign * target:
            return "target", target, t
    return None
