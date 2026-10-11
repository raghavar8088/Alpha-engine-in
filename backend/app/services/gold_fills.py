"""How the Gold Desk fills an exit — the rule its research replay measured, used live.

WHY A MODULE OF ITS OWN
-----------------------
The desk used to read one price every 180 s and close AT that price once it was past a
level (D4 in GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md). A target that price had overshot was
booked beyond the target (+3.4 to +5.4 bp on average in replay), a stop beyond the stop,
and a wick through a level between two polls was never seen at all. That is the polling
being measured, not the strategy.

These functions are the exit rule of the research replay (`backend/research/gold_2026_10/
gd_replay.py: _resolve`), written once and used by the live desk, so the desk's record and
the replay that justified running it fill by exactly the same rule. A test holds the two
together case by case.

THE RULE
--------
Walk the COMPLETED one-minute bars since the position was last checked, oldest first:
  * a level touched inside a minute fills AT the level;
  * a minute that OPENS beyond a level fills at that open — worse for a stop (a stop-market
    order meets the gap), better for a target (a resting limit is filled at the open);
  * a minute touching both levels is a stop — unless it opened beyond the target;
  * the entry minute itself cannot "open beyond" a level: the position was filled at its open.
Stops and time exits are market orders and pay the venue's measured half-spread
(`market_exit_price`); a target is a resting limit and pays nothing extra.

No I/O here. Every function is pure and tested in backend/tests/gold_desk.
"""

from __future__ import annotations

from dataclasses import dataclass

Minute = tuple  # (ts_epoch_seconds_of_the_minute_open, open, high, low, close)


@dataclass(frozen=True)
class Exit:
    ts: int          # epoch seconds of the minute the exit happened in (its open)
    price: float     # the fill, before any market-exit slippage
    reason: str      # "target" | "stoploss"
    basis: str       # "level" (filled at the level) | "gap_open" (the minute opened past it)


def walk_exit(side: int, minutes: list[Minute], target: float, stop: float,
              entry_minute_ts: int | None = None) -> Exit | None:
    """The first exit among `minutes` (oldest first, all completed), or None.

    `side` is +1 for a long, -1 for a short. `entry_minute_ts` is the minute the position
    was filled at the open of; inside that minute an open "beyond" a level is impossible."""
    for ts, o, h, lo, _c in minutes:
        o, h, lo = float(o), float(h), float(lo)
        at_entry = entry_minute_ts is not None and int(ts) == int(entry_minute_ts)
        if side > 0:
            stop_hit, tgt_hit = lo <= stop, h >= target
            gap_tgt, gap_stop = o >= target, o <= stop
        else:
            stop_hit, tgt_hit = h >= stop, lo <= target
            gap_tgt, gap_stop = o <= target, o >= stop
        if not stop_hit and not tgt_hit:
            continue
        if tgt_hit and not stop_hit:
            if gap_tgt and not at_entry:
                return Exit(int(ts), o, "target", "gap_open")
            return Exit(int(ts), float(target), "target", "level")
        if tgt_hit and stop_hit and gap_tgt and not at_entry:
            return Exit(int(ts), o, "target", "gap_open")
        # a stop — alone, or sharing the minute with the target (stop assumed first)
        if gap_stop and not at_entry:
            return Exit(int(ts), o, "stoploss", "gap_open")
        return Exit(int(ts), float(stop), "stoploss", "level")
    return None


def market_exit_price(price: float, side: int, slip_bp: float) -> float:
    """What a market order closing a `side` position actually gets: a long sells into the
    bid, a short buys from the ask — `slip_bp` (the measured half-spread) worse."""
    return float(price) * (1 - slip_bp / 1e4) if side > 0 else float(price) * (1 + slip_bp / 1e4)


def time_exit(minutes: list[Minute], until_ts: int) -> tuple[int, float] | None:
    """The hold limit: the close of the last completed minute that STARTS before `until_ts`
    (the close of the strategy's 60th bar). None when no such minute is in hand yet."""
    last = None
    for ts, _o, _h, _lo, c in minutes:
        if int(ts) < int(until_ts):
            last = (int(ts), float(c))
        else:
            break
    return last


def funding_exchanges(since_ts: int, until_ts: int, interval_s: int) -> list[int]:
    """Funding exchange times (epoch seconds, multiples of `interval_s`) in (since, until].

    A position open across an exchange pays or receives that exchange's funding; one opened
    and closed between two exchanges owes nothing."""
    if interval_s <= 0 or until_ts <= since_ts:
        return []
    first = (int(since_ts) // interval_s + 1) * interval_s
    return list(range(first, int(until_ts) + 1, interval_s))


def funding_cost(side: int, notional: float, rate_pct: float) -> float:
    """Funding one exchange costs this position, in the venue's currency. Positive = paid.
    A positive rate means longs pay shorts."""
    return float(side) * float(notional) * float(rate_pct) / 100.0
