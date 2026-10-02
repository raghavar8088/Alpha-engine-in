"""NSE option charges on Angel One's rate card — the one copy every service reads.

The backend (`app.services.angel_fees.option_round_trip`) and the Pre-Live paper daemons
(separate containers) used to keep their own copies, and they drifted: the daemon charged a
Dhan-style brokerage of min(Rs20, 0.03% of turnover) — about Rs2 on a Rs6,500 premium leg —
and no STT at all until 2026-10-02, while the real-money desk executes on Angel, which
charges a flat Rs20 per executed option order. One schedule here, dated, so a paper P&L, a
backtest and a real-money estimate can never disagree about costs again.

Rates (per leg unless noted), effective dates newest first:
  brokerage   Rs20 per executed order (Angel One, options)
  STT         on the premium SOLD: 0.15% from 2026-04-01 (Budget 2026-27), 0.10% from
              2024-10-01, 0.0625% before
  exchange    NSE option transaction charge on premium turnover: 0.03503% from 2024-10-01
  SEBI        Rs10 per crore of turnover
  stamp duty  0.003% of the premium BOUGHT
  GST         18% on brokerage + exchange + SEBI (never on STT or stamp duty)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

BROKERAGE_PER_ORDER = 20.0
GST = 0.18
SEBI = 0.000001
STAMP_BUY = 0.00003
STT_SELL_SCHEDULE = [(date(2026, 4, 1), 0.0015), (date(2024, 10, 1), 0.001), (date(1900, 1, 1), 0.000625)]
EXCHANGE_SCHEDULE = [(date(2024, 10, 1), 0.0003503), (date(1900, 1, 1), 0.0005)]


def rate(schedule: list[tuple[date, float]], on: date | datetime | str | None = None) -> float:
    if isinstance(on, str):
        on = date.fromisoformat(on[:10])
    d = on.astimezone(IST).date() if isinstance(on, datetime) else (on or datetime.now(IST).date())
    for start, r in schedule:
        if d >= start:
            return r
    return schedule[-1][1]


KEYS = ("brokerage", "stt", "exchange", "sebi", "stamp", "gst")


def _leg(premium: float, qty: int, sell: bool, on) -> dict:
    turnover = max(float(premium), 0.0) * max(int(qty), 0)
    if turnover <= 0:
        return {k: 0.0 for k in KEYS}
    brokerage = BROKERAGE_PER_ORDER
    exchange = turnover * rate(EXCHANGE_SCHEDULE, on)
    sebi = turnover * SEBI
    return {"brokerage": brokerage, "stt": turnover * rate(STT_SELL_SCHEDULE, on) if sell else 0.0,
            "exchange": exchange, "sebi": sebi, "stamp": 0.0 if sell else turnover * STAMP_BUY,
            "gst": GST * (brokerage + exchange + sebi)}


def option_leg(premium: float, qty: int, sell: bool, on=None) -> dict:
    """Charges on ONE executed option order (rounded once, at the end)."""
    raw = _leg(premium, qty, sell, on)
    return {**{k: round(v, 2) for k, v in raw.items()}, "total": round(sum(raw.values()), 2)}


def option_round_trip(entry_premium: float, exit_premium: float, qty: int, on=None) -> dict:
    """Buy then sell `qty` units of one option: both legs' charges and the total."""
    b, s = _leg(entry_premium, qty, False, on), _leg(exit_premium, qty, True, on)
    raw = {k: b[k] + s[k] for k in KEYS}
    return {**{k: round(v, 2) for k, v in raw.items()}, "total": round(sum(raw.values()), 2)}
