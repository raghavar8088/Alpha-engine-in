"""Stocks in play: which of the liquid universe is trading unusually today.

The opening-range-breakout evidence this upgrade leans on (Zarattini, Barbon & Aziz,
2024) is specific: the edge lives in "stocks in play" — names whose volume in the first
minutes is a multiple of their normal — and is weak in the rest. So the measure is
RELATIVE VOLUME at the same time of day, not today's raw volume:

    rvol(k) = volume in today's first k fifteen-minute bars
              / mean of the same first-k-bars volume over the previous 14 sessions

Comparing to the SAME window matters: NSE volume is heavily U-shaped (the first half hour
and the close carry far more than midday), so "volume so far vs a whole day's average"
would call every stock quiet at 10:00 and busy at 15:00.

Alongside it, per name: the opening gap against the exchange's previous close, the
opening range (first k bars), and a 14-session ATR built from the 15-minute bars — the
unit an ORB stop is sized in.

Only CLOSED bars are used (intraday_store guarantees it), so nothing here looks ahead.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.services import intraday_universe
from app.services.intraday_store import _ist, store

IST = timezone(timedelta(hours=5, minutes=30))
BASELINE_SESSIONS = 14
ATR_SESSIONS = 14


def _by_day(rows) -> dict[date, list[tuple]]:
    out: dict[date, list[tuple]] = {}
    for r in rows:
        out.setdefault(_ist(r[0]).date(), []).append(r)
    return out


def _daily_atr(days: dict[date, list[tuple]], before: date, n: int) -> float | None:
    past = sorted(d for d in days if d < before)[-(n + 1):]
    if len(past) < n + 1:
        return None
    trs = []
    for prev, cur in zip(past, past[1:]):
        pc = days[prev][-1][4]
        hi = max(r[2] for r in days[cur]); lo = min(r[3] for r in days[cur])
        trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    return sum(trs) / len(trs)


def measure(symbol: str, now: datetime | None = None, k: int | None = None) -> dict | None:
    """In-play measures for one symbol at the last closed 15m boundary (or after k bars)."""
    now = (now or datetime.now(IST)).astimezone(IST)
    cutoff = int(now.timestamp())
    rows = [r for r in store.get(symbol).rows() if r[0] + 900 <= cutoff]
    days = _by_day(rows)
    today = now.date()
    bars_today = days.get(today, [])
    if not bars_today:
        return None
    k = len(bars_today) if k is None else min(k, len(bars_today))
    vol_today = sum(r[5] for r in bars_today[:k])
    history = [d for d in sorted(days) if d < today][-BASELINE_SESSIONS:]
    base = [sum(r[5] for r in days[d][:k]) for d in history if len(days[d]) >= k]
    baseline = sum(base) / len(base) if base else None
    prev_close = days[history[-1]][-1][4] if history else None
    from app.services.angel_stream import stream
    live = stream.day_stats(symbol)
    if live and live.get("prev_close"):
        prev_close = live["prev_close"]          # the exchange's own previous close
    first = bars_today[0]
    or_hi = max(r[2] for r in bars_today[:k]); or_lo = min(r[3] for r in bars_today[:k])
    atr = _daily_atr(days, today, ATR_SESSIONS)
    last = bars_today[k - 1][4]
    return {
        "symbol": symbol, "bars": k,
        "as_of": _ist(bars_today[k - 1][0] + 900).strftime("%H:%M"),
        "rvol": round(vol_today / baseline, 2) if baseline else None,
        "volume": vol_today, "baseline_volume": round(baseline) if baseline else None,
        "baseline_sessions": len(base),
        "gap_pct": round((first[1] - prev_close) / prev_close * 100, 2) if prev_close else None,
        "or_high": or_hi, "or_low": or_lo,
        "or_range_pct": round((or_hi - or_lo) / first[1] * 100, 2) if first[1] else None,
        "atr14": round(atr, 2) if atr else None,
        "atr14_pct": round(atr / last * 100, 2) if atr and last else None,
        "or_range_atr": round((or_hi - or_lo) / atr, 2) if atr else None,
        "last": last, "move_pct": round((last - first[1]) / first[1] * 100, 2) if first[1] else None,
        "src_stream_bars": sum(1 for r in bars_today[:k] if r[6] == 2),
    }


async def ranked(top: int = 25, k: int | None = None, now: datetime | None = None) -> dict:
    """The universe ranked by relative volume, highest first."""
    members = await intraday_universe.members()
    rows, missing = [], 0
    for m in members:
        r = measure(m["symbol"], now, k)
        if r is None or r["rvol"] is None:
            missing += 1
            continue
        r["turnover_cr"] = m.get("turnover_cr")
        r["cas"] = m.get("cas")
        rows.append(r)
    rows.sort(key=lambda r: -r["rvol"])
    return {"as_of": rows[0]["as_of"] if rows else None, "measured": len(rows),
            "not_measurable": missing, "universe": len(members), "top": rows[:top],
            "rule": f"rvol = first-k-bars volume / mean of the same window over the previous "
                    f"{BASELINE_SESSIONS} sessions"}
