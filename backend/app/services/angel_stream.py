"""Live 15-minute bars for the intraday universe, built from Angel One's WebSocket V2 stream.

WHY A STREAM
The intraday desks decided on DAILY bars plus one quote, and the pattern desk polled
Angel's candle endpoint — which refuses at a fraction of its documented rate (see
angel_client). A stream has no request budget: one connection carries every tick for the
whole universe (Angel allows 1000 tokens a session, 3 connections a client; this uses one
connection and ~200 tokens).

HOW A BAR IS BUILT (QUOTE mode, 123-byte little-endian packets — layout from Angel's own
SmartWebSocketV2: token, exchange timestamp ms, LTP, cumulative day volume, day OHLC,
previous close; prices in paise)
- Ticks roll into exact 1-minute bars by EXCHANGE timestamp, not arrival time.
- Volume is the difference of the cumulative day volume, attributed at tick granularity,
  so the bars' volumes add up to the exchange's day volume exactly.
- Angel may conflate ticks; when the day high/low moves inside a minute, that minute's
  high/low is widened to it, so an extreme the stream skipped is not lost.
- The 09:15 bar opens at the day's open (the pre-open auction price) and carries the
  pre-open volume — the same as Angel's own 09:15 candle (RELIANCE 2026-10-01: 1,222,704).
- Ticks stamped 15:30 or later are not session trading and are ignored.
- A 15-minute bar is emitted 5 s after its boundary, from the minutes inside it.

WHAT IS NOT BUILT FROM THE STREAM (left for the candle gap-fill instead)
- Any 15-minute bucket the stream was not connected for in full (a restart, a reconnect):
  a bucket with missing ticks would have a wrong high, low or volume and look complete.
- The first bucket after joining mid-session, for the same reason — and its volume
  baseline is the cumulative volume AT JOIN, never zero, or the first bar would carry the
  whole morning's volume.
Every stream bar is marked SRC_STREAM; the nightly reconcile replaces it with Angel's
candle and records how far apart they were.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import time
from array import array
from datetime import datetime, timedelta, timezone

from app.services import market_calendar
from app.services.angel_client import angel_client
from app.services.intraday_store import (BASE_MIN, SESSION_CLOSE_MIN, SESSION_OPEN_MIN,
                                         SRC_STREAM, store, store5)

logger = logging.getLogger("angel_stream")

IST = timezone(timedelta(hours=5, minutes=30))
WS_URL = "wss://smartapisocket.angelone.in/smart-stream"
MODE_QUOTE = 2
EXCH_NSE_CM = 1
QUOTE_LEN = 123
SUB_CHUNK = 50
HEARTBEAT_S = 10
SILENCE_RECONNECT_S = 45
EMIT_GRACE_S = 5
CONNECT_FROM = os.getenv("ANGEL_STREAM_FROM", "09:05")
CONNECT_UNTIL = os.getenv("ANGEL_STREAM_UNTIL", "15:36")
ENABLED = os.getenv("ANGEL_STREAM_ENABLED", "1").lower() not in ("0", "false", "no")

_HEAD = struct.Struct("<BB25sqqq")            # mode, exchange, token, seq, exch_ts_ms, ltp
_QUOTE_TAIL = struct.Struct("<qqqddqqqq")     # ltq, atp, cum_vol, tbq, tsq, open, high, low, close


def parse_packet(buf: bytes) -> dict | None:
    """One binary QUOTE packet -> dict, or None if it is not one. Prices in rupees."""
    if len(buf) < 51:
        return None
    mode, _ex, tok, _seq, exch_ms, ltp = _HEAD.unpack_from(buf, 0)
    out = {"mode": mode, "token": tok.split(b"\x00", 1)[0].decode(errors="ignore"),
           "exch_ms": exch_ms, "ltp": ltp / 100.0}
    if mode >= MODE_QUOTE and len(buf) >= QUOTE_LEN:
        _ltq, _atp, cum, _tbq, _tsq, o, h, l, c = _QUOTE_TAIL.unpack_from(buf, 51)
        out.update({"cum_vol": cum, "open": o / 100.0, "high": h / 100.0, "low": l / 100.0,
                    "prev_close": c / 100.0})
    return out


def _minute_start(epoch: int) -> int:
    return epoch - (epoch % 60)


def _session_epoch(day, minute_of_day: int) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=IST).timestamp()) + minute_of_day * 60


class TokenState:
    """One instrument's day: running minute bar, finished minutes, day fields."""

    __slots__ = ("symbol", "token", "day", "joined_at", "cum_vol", "day_high", "day_low",
                 "day_open", "prev_close", "last_ltp", "last_tick", "cur", "cur_v0",
                 "last_closed", "mt", "mo", "mh", "ml", "mc", "mv", "ticks")

    def __init__(self, symbol: str, token: str):
        self.symbol, self.token = symbol, token
        self.day = None
        self.reset_day(None)

    def reset_day(self, day) -> None:
        self.day = day
        self.joined_at = None
        self.cum_vol = 0
        self.day_high = self.day_low = self.day_open = self.prev_close = None
        self.last_ltp = None
        self.last_tick = 0.0
        self.cur = None            # [minute_start, o, h, l, c]
        self.cur_v0 = 0
        self.last_closed = 0       # start of the last minute already closed
        self.mt = array("q"); self.mo = array("d"); self.mh = array("d")
        self.ml = array("d"); self.mc = array("d"); self.mv = array("q")
        self.ticks = 0

    def _close_minute(self) -> None:
        if self.cur is None:
            return
        t, o, h, l, c = self.cur
        self.mt.append(t); self.mo.append(o); self.mh.append(h); self.ml.append(l)
        self.mc.append(c); self.mv.append(max(0, self.cum_vol - self.cur_v0))
        self.cur_v0 = self.cum_vol
        self.last_closed = t
        self.cur = None

    def on_tick(self, p: dict) -> None:
        exch = p["exch_ms"] // 1000
        d = datetime.fromtimestamp(exch, IST)
        if self.day != d.date():
            self.reset_day(d.date())
        self.ticks += 1
        self.last_tick = time.time()
        ltp = p["ltp"]
        if ltp <= 0:
            return
        cum = p.get("cum_vol")
        first = self.joined_at is None
        if first:
            self.joined_at = exch
            # Joined late: everything traded before now is not ours to attribute.
            if d.hour * 60 + d.minute >= SESSION_OPEN_MIN + 1 and cum:
                self.cum_vol = self.cur_v0 = int(cum)
        if p.get("open"):
            self.day_open = p["open"]
            self.prev_close = p.get("prev_close")
        minute = d.hour * 60 + d.minute
        hi, lo = p.get("high"), p.get("low")
        in_session = SESSION_OPEN_MIN <= minute < SESSION_CLOSE_MIN
        start = _minute_start(exch)
        # Pre-open (09:00-09:08 auction) and after-close ticks move the DAY fields and the
        # cumulative volume only. A pre-open LTP is the previous close or the indicative
        # price, not a trade inside the 09:15 bar; the auction's real trade arrives as the
        # day's OPEN, which the 09:15 bar takes below. Late ticks for a minute already
        # closed move no price either (their volume still flows through cum_vol).
        if in_session and start > self.last_closed:
            if self.cur is None or start > self.cur[0]:
                self._close_minute()
                o = ltp
                if minute == SESSION_OPEN_MIN and self.day_open:
                    o = self.day_open
                self.cur = [start, o, max(o, ltp), min(o, ltp), ltp]
                if first and minute == SESSION_OPEN_MIN:
                    # Joined inside the first minute: every extreme so far happened in it.
                    if hi:
                        self.cur[2] = max(self.cur[2], hi)
                    if lo:
                        self.cur[3] = min(self.cur[3], lo)
            else:
                c = self.cur
                c[2] = max(c[2], ltp); c[3] = min(c[3], ltp); c[4] = ltp
            # A new day extreme inside this minute that the (conflated) ticks skipped.
            if hi and self.day_high and hi > self.day_high:
                self.cur[2] = max(self.cur[2], hi)
            if lo and self.day_low and lo < self.day_low:
                self.cur[3] = min(self.cur[3], lo)
        if hi:
            self.day_high = hi if self.day_high is None else max(self.day_high, hi)
        if lo:
            self.day_low = lo if self.day_low is None else min(self.day_low, lo)
        if cum is not None and cum > self.cum_vol:
            self.cum_vol = int(cum)
        self.last_ltp = ltp

    def close_through(self, boundary: int) -> None:
        """Close the running minute if it ends at or before `boundary`."""
        if self.cur is not None and self.cur[0] + 60 <= boundary:
            self._close_minute()

    def bar(self, start: int, end: int) -> tuple | None:
        """The 15-minute bar [start, end) from finished minutes, or None if no trades."""
        o = h = l = c = None
        v = 0
        for i in range(len(self.mt)):
            t = self.mt[i]
            if t < start or t >= end:
                continue
            if o is None:
                o, h, l = self.mo[i], self.mh[i], self.ml[i]
            else:
                h = max(h, self.mh[i]); l = min(l, self.ml[i])
            c = self.mc[i]
            v += self.mv[i]
        if o is None:
            return None
        return (start, o, h, l, c, v, SRC_STREAM)


class Stream:
    def __init__(self):
        self.states: dict[str, TokenState] = {}
        self.connected = False
        self.connected_since: float | None = None
        self.outages: list[tuple[float, float]] = []       # (from, to) wall-clock epochs
        self._down_since: float | None = time.time()
        self.reconnects = 0
        self.last_message = 0.0
        self.messages = 0
        self.bars_emitted = 0
        self.bars_emitted_5m = 0
        self.last_emitted_5m = 0
        self.bars_skipped = {"outage": 0, "joined_late": 0, "no_trades": 0}
        self.last_emitted_boundary = 0
        self.last_error: str | None = None
        self.task: asyncio.Task | None = None

    # ── connection ───────────────────────────────────────────────────────────────

    async def _connect_once(self, tokens: dict[str, str]) -> None:
        import websockets

        jwt = await angel_client._session()
        feed = angel_client.feed_token          # a property on the shared client
        feed = feed() if callable(feed) else feed
        creds = angel_client.creds
        headers = {"Authorization": f"Bearer {jwt}", "x-api-key": creds.api_key,
                   "x-client-code": creds.client_code, "x-feed-token": feed or ""}
        async with websockets.connect(WS_URL, additional_headers=headers, ping_interval=None,
                                      open_timeout=20, close_timeout=5, max_queue=4096) as ws:
            toks = list(tokens)
            for i in range(0, len(toks), SUB_CHUNK):
                await ws.send(json.dumps({
                    "correlationID": f"iu{i // SUB_CHUNK}", "action": 1,
                    "params": {"mode": MODE_QUOTE,
                               "tokenList": [{"exchangeType": EXCH_NSE_CM,
                                              "tokens": toks[i:i + SUB_CHUNK]}]}}))
            self.connected, self.connected_since = True, time.time()
            if self._down_since is not None:
                self.outages.append((self._down_since, time.time()))
                self._down_since = None
            self.outages = [o for o in self.outages if o[1] > time.time() - 86400]
            logger.info("Angel stream connected: %d tokens subscribed (QUOTE mode)", len(toks))
            hb = asyncio.create_task(self._heartbeat(ws))
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=SILENCE_RECONNECT_S)
                    self.last_message = time.time()
                    if isinstance(msg, (bytes, bytearray)):
                        p = parse_packet(bytes(msg))
                        if p is None:
                            continue
                        self.messages += 1
                        sym = tokens.get(p["token"])
                        if sym is not None:
                            self.states[sym].on_tick(p)
                    elif msg != "pong":
                        logger.warning("Angel stream says: %s", str(msg)[:300])
            finally:
                hb.cancel()

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            await ws.send("ping")

    def _went_down(self, why: str) -> None:
        if self.connected:
            self.connected = False
            self._down_since = time.time()
        self.last_error = why

    # ── bar emission ─────────────────────────────────────────────────────────────

    def _covered(self, start: int, end: int) -> bool:
        """Was the stream connected for the whole of [start, end)?"""
        for a, b in self.outages:
            if a < end and b > start:
                return False
        if self._down_since is not None and self._down_since < end:
            return False
        return True

    def emit(self, boundary: int, minutes: int = BASE_MIN, target=None) -> int:
        """Emit the `minutes`-long bars ending at `boundary` into `target` (default: the
        15-minute store). The same coverage rules apply at every bar length."""
        target = target if target is not None else store
        start = boundary - minutes * 60
        made = 0
        covered = self._covered(start, boundary)
        for st in self.states.values():
            st.close_through(boundary)
            if st.joined_at is None or not covered:
                if not covered:
                    self.bars_skipped["outage"] += 1
                continue
            # Complete only if this instrument was already streaming when the bucket
            # opened. Joining before 09:16 counts as joining at the open: the first
            # minute's extremes come from the day high/low and its volume from zero.
            joined = datetime.fromtimestamp(st.joined_at, IST)
            joined_at_open = joined.hour * 60 + joined.minute < SESSION_OPEN_MIN + 1
            if not (st.joined_at <= start or (joined_at_open and joined.date()
                                               == datetime.fromtimestamp(start, IST).date())):
                self.bars_skipped["joined_late"] += 1
                continue
            row = st.bar(start, boundary)
            if row is None:
                self.bars_skipped["no_trades"] += 1
                continue
            target.merge(st.symbol, [row])
            made += 1
        if minutes == BASE_MIN:
            self.bars_emitted += made
            self.last_emitted_boundary = boundary
        else:
            self.bars_emitted_5m += made
            self.last_emitted_5m = boundary
        return made

    async def _emitter(self) -> None:
        while True:
            now = time.time()
            d = datetime.fromtimestamp(now - EMIT_GRACE_S, IST)
            m = d.hour * 60 + d.minute
            if SESSION_OPEN_MIN < m <= SESSION_CLOSE_MIN + 1:
                k = (min(m, SESSION_CLOSE_MIN) - SESSION_OPEN_MIN) // BASE_MIN
                boundary = _session_epoch(d.date(), SESSION_OPEN_MIN + k * BASE_MIN)
                if k > 0 and boundary > self.last_emitted_boundary:
                    made = self.emit(boundary)
                    logger.info("stream bars %s: %d emitted", datetime.fromtimestamp(
                        boundary, IST).strftime("%H:%M"), made)
                k5 = (min(m, SESSION_CLOSE_MIN) - SESSION_OPEN_MIN) // 5
                b5 = _session_epoch(d.date(), SESSION_OPEN_MIN + k5 * 5)
                if k5 > 0 and b5 > self.last_emitted_5m:
                    self.emit(b5, 5, store5)
            await asyncio.sleep(1.0)

    # ── lifecycle ────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Connect during the session on trading days; reconnect with backoff."""
        from app.services import intraday_universe

        emitter = asyncio.create_task(self._emitter())
        backoff = 2.0
        try:
            while True:
                now = datetime.now(IST)
                hhmm = now.strftime("%H:%M")
                if not (market_calendar.is_trading_day(now) and CONNECT_FROM <= hhmm < CONNECT_UNTIL):
                    self._went_down("outside session")
                    await asyncio.sleep(30)
                    continue
                members = await intraday_universe.members()
                tokens = {m["token"]: m["symbol"] for m in members}
                for sym_, tok_ in intraday_universe.INDEX_TOKENS.items():
                    tokens[tok_] = sym_
                for tok, sym in tokens.items():
                    if sym not in self.states:
                        self.states[sym] = TokenState(sym, tok)
                try:
                    await self._connect_once(tokens)
                    backoff = 2.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - any failure: mark down, back off, retry
                    self._went_down(f"{type(exc).__name__}: {exc}"[:300])
                    self.reconnects += 1
                    logger.warning("Angel stream dropped (%s) — reconnecting in %.0fs",
                                   self.last_error, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(60.0, backoff * 2)
        finally:
            emitter.cancel()

    def describe(self) -> dict:
        now = time.time()
        live = [s for s in self.states.values() if now - s.last_tick < 120]
        return {
            "enabled": ENABLED, "connected": self.connected,
            "connected_for_s": round(now - self.connected_since) if self.connected and self.connected_since else 0,
            "reconnects": self.reconnects, "messages": self.messages,
            "seconds_since_message": round(now - self.last_message) if self.last_message else None,
            "tokens": len(self.states), "ticking_last_2m": len(live),
            "bars_emitted": self.bars_emitted, "bars_emitted_5m": self.bars_emitted_5m,
            "bars_skipped": dict(self.bars_skipped),
            "last_bar": datetime.fromtimestamp(self.last_emitted_boundary, IST).strftime("%H:%M")
            if self.last_emitted_boundary else None,
            "outages_today": len(self.outages), "last_error": self.last_error,
        }

    def day_stats(self, symbol: str) -> dict | None:
        st = self.states.get(symbol)
        if st is None or st.joined_at is None:
            return None
        return {"open": st.day_open, "prev_close": st.prev_close, "high": st.day_high,
                "low": st.day_low, "ltp": st.last_ltp, "cum_vol": st.cum_vol,
                "joined_at": st.joined_at}


stream = Stream()


async def stream_loop() -> None:
    if not ENABLED:
        logger.info("Angel stream disabled (ANGEL_STREAM_ENABLED=0)")
        return
    await stream.run()
