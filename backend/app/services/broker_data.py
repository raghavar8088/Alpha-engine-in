"""Broker-agnostic read path for live prices and candles: Dhan first, Angel One as standby.

Dhan permits one active access token per account, so the whole desk goes blind the
moment that token is rotated out from under us. These two helpers keep the read
paths alive by retrying against Angel One, which authenticates independently.

Only quotes and candles fail over. Orders, margin and the option chain stay on
Dhan — Angel has no single-call option chain, and a paper desk gains nothing from
routing orders to a second broker.

Whichever source answered is reported back to the caller (`ltp_source` /
`"source"`) so the UI never implies Dhan data when the number came from Angel.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from app.core.db import instruments_collection
from app.services.angel_client import AngelAPIError, angel_client
from app.services.dhan_client import DhanRateLimitError

logger = logging.getLogger("broker_data")

IST = timezone(timedelta(hours=5, minutes=30))

# Once Dhan throttles us, retrying on the very next call is the behaviour that turns
# a 429 into a blocked account — its own message warns as much. Trip a shared
# cooldown instead and serve from Angel until it lapses. Shared, not per-instrument:
# the limit applies to the account, so one 429 means every symbol should stand down.
DHAN_COOLDOWN_SECONDS = 120
_dhan_blocked_until = 0.0


def dhan_is_cooling_down() -> bool:
    return time.monotonic() < _dhan_blocked_until


def note_dhan_rate_limit() -> None:
    global _dhan_blocked_until
    _dhan_blocked_until = time.monotonic() + DHAN_COOLDOWN_SECONDS
    logger.warning(
        "Dhan rate-limited — pausing Dhan market-data calls for %ss, serving from Angel One",
        DHAN_COOLDOWN_SECONDS,
    )


async def _angel_ref(security_id: str, exchange_segment: str) -> tuple[str, str] | None:
    doc = await instruments_collection.find_one(
        {"security_id": security_id, "exchange_segment": exchange_segment},
        {"angel_token": 1, "angel_exchange": 1},
    )
    if not doc or not doc.get("angel_token"):
        return None
    return str(doc["angel_token"]), doc.get("angel_exchange") or "NSE"


async def get_ltp(dhan, security_id: str, exchange_segment: str) -> tuple[float | None, str]:
    """Last traded price plus the source that produced it ("dhan_quote" | "angel_quote").

    Returns (None, "unavailable") when neither broker can price it — callers already
    treat a missing price as "skip this one" rather than as zero.
    """
    if not dhan_is_cooling_down():
        try:
            raw = await dhan.quote_data({exchange_segment: [int(security_id)]})
            data = raw.get("data", {}) if isinstance(raw, dict) else {}
            row = data.get(exchange_segment, {}).get(str(security_id))
            if row and row.get("last_price"):
                return float(row["last_price"]), "dhan_quote"
        except DhanRateLimitError:
            note_dhan_rate_limit()
        except Exception as exc:
            logger.warning("Dhan quote failed for %s/%s (%s) — trying Angel", security_id, exchange_segment, exc)

    if not angel_client.configured():
        return None, "unavailable"
    ref = await _angel_ref(security_id, exchange_segment)
    if ref is None:
        return None, "unavailable"
    token, exchange = ref
    try:
        prices = await angel_client.ltp({exchange: [token]})
    except AngelAPIError as exc:
        logger.warning("Angel quote failed for token %s (%s)", token, exc)
        return None, "unavailable"
    price = prices.get(token)
    return (float(price), "angel_quote") if price is not None else (None, "unavailable")


def _to_angel_dt(ts: int, end_of_day: bool = False) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST)
    return dt.strftime("%Y-%m-%d 15:30" if end_of_day else "%Y-%m-%d 09:15")


async def angel_bars(
    security_id: str, exchange_segment: str, resolution: str, from_ts: int, to_ts: int
) -> dict | None:
    """Candles from Angel in the same UDF-ish shape the chart already consumes,
    or None if this instrument has no Angel mapping / Angel can't serve it.

    Angel returns rows of [iso_timestamp, o, h, l, c, v]; weekly isn't offered, so
    "W" is left to the caller to aggregate from daily as it already does for Dhan.
    """
    if not angel_client.configured():
        return None
    ref = await _angel_ref(security_id, exchange_segment)
    if ref is None:
        return None
    token, exchange = ref
    try:
        rows = await angel_client.candles(
            exchange, token, resolution, _to_angel_dt(from_ts), _to_angel_dt(to_ts, end_of_day=True)
        )
    except AngelAPIError as exc:
        logger.warning("Angel candles failed for token %s (%s)", token, exc)
        return None
    if not rows:
        return None

    t, o, h, low, c, v = [], [], [], [], [], []
    for row in rows:
        try:
            stamp = datetime.fromisoformat(row[0])
        except (ValueError, TypeError, IndexError):
            continue
        t.append(int(stamp.timestamp()))
        o.append(float(row[1]))
        h.append(float(row[2]))
        low.append(float(row[3]))
        c.append(float(row[4]))
        v.append(float(row[5]))
    if not t:
        return None
    return {"s": "ok", "t": t, "o": o, "h": h, "l": low, "c": c, "v": v, "source": "angel"}
