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

import time

from app.services.angel_stream import stream


def slippage_bp(turnover_cr: float | None) -> float:
    """Per-side cost of crossing the spread for one market order, by the name's daily
    traded value (Rs crore).

    Calibrated for a ~Rs 2 lakh order, where even the thinnest of the 200 most-traded names
    is a sliver of a minute's volume and this is mostly the half-spread. Positions have been
    Rs 10 lakh since 2026-10-02, which in the thinnest names is about a third of a minute's
    traded value, so the bottom bucket may be optimistic; the measurement that settles it
    (H1 in INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md) records real order-book depth at
    each signal. Same function for the Phase 3 backtest."""
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


def scan_exit(p: dict) -> tuple[str, float, int] | None:
    """Walk the stream's minute bars since the last check: (reason, level price, minute)."""
    sign = 1 if p["side"] == "BUY" else -1
    stop, target = p["stoploss"], p.get("target")
    for t, o, h, l, _c in stream_minutes(p["symbol"], p.get("checked_through", 0)):
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
