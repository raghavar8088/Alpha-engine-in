"""Live equity quotes from Angel One for the Intraday Stocks desk.

The intraday strategies (`intraday_strategies.py`) read a quote dict shaped
`{"ohlc": {open, high, low}, "last_price", "volume"}` — the same shape a Dhan
`/marketfeed/quote` row exposes (see `call_engine._quote_batch`). This helper produces
exactly that shape from Angel One's FULL-mode quote, so the desk can prefer Angel and
fall back to Dhan without the strategies or the engine knowing which broker answered.

Instruments are addressed everywhere in this app by Dhan `(exchange_segment,
security_id)`; Angel answers only to its own `(angel_exchange, angel_token)`, which
`angel_instruments.refresh_angel_tokens()` has already stamped onto each equity doc.
Anything without an Angel token, or that Angel returns no day OHLC for, is left unpriced
— never guessed — the same failover discipline as `broker_data.py`. The caller then asks
Dhan for exactly those misses.
"""

import logging

from app.services.angel_client import AngelAPIError, angel_client

logger = logging.getLogger("angel_equity_feed")


async def equity_quotes(instruments: list[dict]) -> dict[tuple[str, str], dict]:
    """Angel FULL quotes for `instruments`, keyed by our own `(exchange_segment,
    security_id)` and shaped like the strategies' expected `quote` dict.

    `instruments` are `instruments` collection docs (they carry `security_id`,
    `exchange_segment`, and — once the token map is built — `angel_token` /
    `angel_exchange`). Docs without an Angel token are skipped. Returns an empty dict
    when Angel is not configured or the call fails, so the caller falls back cleanly.
    """
    if not angel_client.configured():
        return {}

    token_key: dict[str, tuple[str, str]] = {}   # angel token -> our (segment, security_id)
    by_exchange: dict[str, list[str]] = {}
    for inst in instruments:
        token = inst.get("angel_token")
        if not token:
            continue
        token = str(token)
        by_exchange.setdefault(inst.get("angel_exchange") or "NSE", []).append(token)
        token_key[token] = (inst["exchange_segment"], str(inst["security_id"]))
    if not by_exchange:
        return {}

    try:
        rows = await angel_client.full_quote(by_exchange)
    except (AngelAPIError, Exception) as exc:  # noqa: BLE001 — any failure => Dhan fallback
        logger.warning("Angel equity quote failed (%s) — desk will fall back to Dhan", exc)
        return {}

    out: dict[tuple[str, str], dict] = {}
    for token, q in rows.items():
        key = token_key.get(token)
        if key is None or q.get("ltp") is None or not q.get("open"):
            # No day open = unusable for the ORB/gap/PDH setups; skip rather than
            # feed them a half-quote they'd silently mis-evaluate.
            continue
        out[key] = {
            "ohlc": {"open": q["open"], "high": q.get("high"), "low": q.get("low")},
            "last_price": q["ltp"],
            "volume": q.get("volume") or 0,
        }
    return out
