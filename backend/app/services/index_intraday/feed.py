"""Indian Index Intraday — live 1-minute bars for the indexes and their ETFs.

WHY ITS OWN CONNECTION
The app's shared stream (angel_stream) subscribes NSE cash tokens only, and SENSEX / BANKEX are
BSE indexes (exchange type 3). Angel allows three WebSocket connections per client; the shared
stream uses one. This module opens its own for its 16 tokens and builds bars with the shared
stream's tested parser and minute builder (angel_stream.parse_packet / TokenState) — the same
rules, and a fault here cannot disturb the desks on the shared stream.

COMPLETE MINUTES ONLY
A minute the connection missed (a late start, a reconnect) is filled from Angel's ONE_MINUTE
candle endpoint — the authoritative record — through the app's paced candle door. Strategies
read `today(symbol)`: finished minutes, stream bars with candle bars filling every hole.

HISTORY
After each close, `append_today()` writes the session's 1-minute candles to the same store the
research read (/data/intraday/idx1m/<SYMBOL>/<date>.csv.gz), so tomorrow's indicators and daily
ATR see today.
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np

from app.services import market_calendar
from app.services.angel_client import angel_client

from .data import DATA, _read

logger = logging.getLogger("index_intraday.feed")

IST = timezone(timedelta(hours=5, minutes=30))
STORE = str(DATA)                      # each session is appended where the engine and the Lab read from
CONNECT_FROM, CONNECT_UNTIL = "09:05", "15:36"
SESSION_DONE = "15:35"                 # after this a session's 1-minute candles are complete
EXCH_TYPE = {"NSE": 1, "BSE": 3}

# symbol -> (exchange, token, kind, the index an ETF tracks)
INSTRUMENTS: dict[str, tuple[str, str, str, str | None]] = {
    "NIFTY": ("NSE", "99926000", "index", None),
    "BANKNIFTY": ("NSE", "99926009", "index", None),
    "FINNIFTY": ("NSE", "99926037", "index", None),
    "NIFTYNXT50": ("NSE", "99926013", "index", None),
    "NIFTY100": ("NSE", "99926012", "index", None),
    "MIDCPNIFTY": ("NSE", "99926074", "index", None),
    "SENSEX": ("BSE", "99919000", "index", None),
    "BANKEX": ("BSE", "99919012", "index", None),
    "INDIAVIX": ("NSE", "99926017", "vix", None),
    "NIFTYBEES": ("NSE", "10576", "etf", "NIFTY"),
    "BANKBEES": ("NSE", "11439", "etf", "BANKNIFTY"),
    "JUNIORBEES": ("NSE", "10939", "etf", "NIFTYNXT50"),
    "FINIETF": ("NSE", "12578", "etf", "FINNIFTY"),
    "MIDSELIETF": ("NSE", "17702", "etf", "MIDCPNIFTY"),
    "NIF100BEES": ("NSE", "29577", "etf", "NIFTY100"),
    "SENSEXIETF": ("NSE", "4378", "etf", "SENSEX"),
}
LABELS = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FIN SERVICE",
          "NIFTYNXT50": "NIFTY NEXT 50", "NIFTY100": "NIFTY 100", "MIDCPNIFTY": "NIFTY MIDCAP SELECT",
          "SENSEX": "SENSEX", "BANKEX": "BANKEX", "INDIAVIX": "INDIA VIX"}


def _minute_start(epoch: int) -> int:
    return epoch - epoch % 60


class IndexFeed:
    def __init__(self) -> None:
        from app.services.angel_stream import TokenState
        self.states = {s: TokenState(s, tok) for s, (_e, tok, _k, _t) in INSTRUMENTS.items()}
        self.by_token = {(EXCH_TYPE[e], tok): s for s, (e, tok, _k, _t) in INSTRUMENTS.items()}
        self.candles: dict[str, dict[int, tuple]] = {s: {} for s in INSTRUMENTS}
        self.candle_day: date | None = None
        self.last_backfill: dict[str, float] = {}
        self.connected = False
        self.connected_since = 0.0
        self.last_message = 0.0
        self.reconnects = 0
        self.messages = 0
        self.last_error: str | None = None
        # set by the scheduler: should the stream run at all? (Main Control ON, or a position open)
        self.wanted = None

    async def _is_wanted(self) -> bool:
        if self.wanted is None:
            return True
        try:
            return bool(await self.wanted())
        except Exception:  # noqa: BLE001 - fail open: a broken check must not blind open positions
            return True

    # ── the connection ──────────────────────────────────────────────────────────
    async def _connect_once(self) -> None:
        import websockets

        from app.services.angel_stream import (HEARTBEAT_S, MODE_QUOTE, SILENCE_RECONNECT_S, WS_URL,
                                               parse_packet)
        jwt = await angel_client._session()
        feed = angel_client.feed_token
        feed = feed() if callable(feed) else feed
        creds = angel_client.creds
        headers = {"Authorization": f"Bearer {jwt}", "x-api-key": creds.api_key,
                   "x-client-code": creds.client_code, "x-feed-token": feed or ""}
        async with websockets.connect(WS_URL, additional_headers=headers, ping_interval=None,
                                      open_timeout=20, close_timeout=5, max_queue=4096) as ws:
            lists = {}
            for s, (e, tok, _k, _t) in INSTRUMENTS.items():
                lists.setdefault(EXCH_TYPE[e], []).append(tok)
            await ws.send(json.dumps({"correlationID": "idxintra", "action": 1, "params": {
                "mode": MODE_QUOTE, "tokenList": [{"exchangeType": et, "tokens": toks} for et, toks in lists.items()]}}))
            self.connected, self.connected_since = True, time.time()
            logger.info("index intraday feed connected: %d tokens", sum(len(v) for v in lists.values()))

            async def heartbeat():
                while True:
                    await asyncio.sleep(HEARTBEAT_S)
                    await ws.send("ping")
            hb = asyncio.create_task(heartbeat())
            checked = time.time()
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=SILENCE_RECONNECT_S)
                    self.last_message = time.time()
                    if self.last_message - checked > 30:
                        checked = self.last_message
                        # leave at the end of the window, or when the module is switched off with nothing open
                        if datetime.now(IST).strftime("%H:%M") >= CONNECT_UNTIL or not await self._is_wanted():
                            logger.info("index intraday feed: disconnecting (window over or module off)")
                            self.connected = False
                            return
                    if isinstance(msg, (bytes, bytearray)):
                        p = parse_packet(bytes(msg))
                        if p is None:
                            continue
                        self.messages += 1
                        sym = self.by_token.get((int(p.get("exchange") or 0), str(p["token"])))
                        if sym is None:
                            sym = next((s for (et, tok), s in self.by_token.items() if tok == str(p["token"])), None)
                        if sym is not None:
                            self.states[sym].on_tick(p)
            finally:
                hb.cancel()

    async def run(self) -> None:
        backoff = 2.0
        closer = asyncio.create_task(self._closer())
        try:
            while True:
                now = datetime.now(IST)
                hhmm = now.strftime("%H:%M")
                if not (market_calendar.is_trading_day(now) and CONNECT_FROM <= hhmm < CONNECT_UNTIL) or (
                        not await self._is_wanted()):
                    self.connected = False
                    await asyncio.sleep(30)
                    continue
                try:
                    await self._connect_once()
                    backoff = 2.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.connected = False
                    self.reconnects += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                    logger.warning("index intraday feed dropped (%s) — retry in %.0fs", self.last_error, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(60.0, backoff * 2)
        finally:
            closer.cancel()

    async def _closer(self) -> None:
        """Close each running minute once its end has passed (the stream only closes a minute
        when the next tick arrives; a quiet index must still finish its minute)."""
        while True:
            boundary = _minute_start(int(time.time()))
            for st in self.states.values():
                st.close_through(boundary)
            await asyncio.sleep(1.0)

    # ── reading ─────────────────────────────────────────────────────────────────
    def _stream_minutes(self, symbol: str, day: date) -> dict[int, tuple]:
        st = self.states[symbol]
        if st.day != day:
            return {}
        return {int(st.mt[i]): (st.mo[i], st.mh[i], st.ml[i], st.mc[i], float(st.mv[i])) for i in range(len(st.mt))}

    def today(self, symbol: str, now: datetime | None = None) -> dict[int, tuple]:
        """Finished minutes of today's session: candle bars where fetched, stream bars elsewhere."""
        now = now or datetime.now(IST)
        day = now.date()
        out = self._stream_minutes(symbol, day)
        if self.candle_day == day:
            out.update(self.candles[symbol])
        cut = _minute_start(int(now.timestamp()))
        return {t: b for t, b in out.items() if t < cut}

    def holes(self, symbol: str, now: datetime | None = None) -> int:
        """Session minutes already finished that today() does not hold."""
        now = now or datetime.now(IST)
        start = int(datetime(now.year, now.month, now.day, 9, 15, tzinfo=IST).timestamp())
        end = min(_minute_start(int(now.timestamp())), start + 375 * 60)
        have = self.today(symbol, now)
        if INSTRUMENTS[symbol][2] == "etf":
            return 0 if have else max(0, (end - start) // 60)      # a quiet ETF minute prints nothing
        return sum(1 for t in range(start, end, 60) if t not in have)

    async def backfill(self, symbol: str, now: datetime | None = None, min_gap_s: float = 120.0) -> int:
        """Fill today's minutes from the candle endpoint (at most every `min_gap_s` a symbol)."""
        now = now or datetime.now(IST)
        if time.time() - self.last_backfill.get(symbol, 0) < min_gap_s:
            return 0
        self.last_backfill[symbol] = time.time()
        e, tok, _k, _t = INSTRUMENTS[symbol]
        try:
            rows = await angel_client.candles(e, tok, "1", f"{now:%Y-%m-%d} 09:15", f"{now:%Y-%m-%d %H:%M}")
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"backfill {symbol}: {exc}"[:300]
            return 0
        if self.candle_day != now.date():
            self.candles = {s: {} for s in INSTRUMENTS}
            self.candle_day = now.date()
        n = 0
        cut = _minute_start(int(now.timestamp()))
        for r in rows:
            try:
                t = int(datetime.fromisoformat(r[0]).timestamp())
            except Exception:  # noqa: BLE001
                continue
            if t < cut:
                self.candles[symbol][t] = (float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0))
                n += 1
        return n

    def ltp(self, symbol: str, max_age_s: float = 90) -> float | None:
        st = self.states.get(symbol)
        if st is None or st.last_ltp is None or time.time() - st.last_tick > max_age_s:
            return None
        return float(st.last_ltp)

    def day_fields(self, symbol: str) -> dict:
        st = self.states[symbol]
        return {"ltp": st.last_ltp, "open": st.day_open, "high": st.day_high, "low": st.day_low,
                "prev_close": st.prev_close, "ticked_s_ago": round(time.time() - st.last_tick) if st.last_tick else None}

    def describe(self) -> dict:
        now = time.time()
        return {"connected": self.connected, "connected_for_s": round(now - self.connected_since) if self.connected else 0,
                "reconnects": self.reconnects, "messages": self.messages,
                "seconds_since_message": round(now - self.last_message) if self.last_message else None,
                "ticking": sorted(s for s, st in self.states.items() if st.last_tick and now - st.last_tick < 120),
                "last_error": self.last_error}

    # ── after the close: extend the history store ───────────────────────────────
    def _write_day(self, symbol: str, day: date, rows: list) -> int:
        """One session's candles as <STORE>/<symbol>/<day>.csv.gz (atomic; rewrites the day)."""
        folder = os.path.join(STORE, symbol)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{day.isoformat()}.csv.gz")
        tmp = path + ".part"
        n = 0
        with gzip.open(tmp, "wt", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "open", "high", "low", "close", "volume"])
            for r in rows:
                try:
                    w.writerow([int(datetime.fromisoformat(r[0]).timestamp()), r[1], r[2], r[3], r[4], r[5]])
                    n += 1
                except Exception:  # noqa: BLE001
                    continue
        os.replace(tmp, path)
        return n

    async def append_today(self, day: date | None = None) -> dict:
        day = day or datetime.now(IST).date()
        out = {}
        for s, (e, tok, _k, _t) in INSTRUMENTS.items():
            try:
                rows = await angel_client.candles(e, tok, "1", f"{day} 09:15", f"{day} 15:30", bulk=True)
            except Exception as exc:  # noqa: BLE001
                out[s] = f"error: {str(exc)[:80]}"
                continue
            out[s] = self._write_day(s, day, rows) if rows else 0
        return out

    async def heal(self, symbols: list[str] | None = None, lookback_days: int = 30, now: datetime | None = None,
                   include_today: bool = False) -> dict:
        """Fill whole trading days missing from the history store: an append that failed (Angel's
        candle endpoint refuses ~1 call in 3 at busy hours — 7 of 16 instruments failed on
        2026-10-16), or the days between the research download (to 2026-10-09) and the first
        deploy. The families read YESTERDAY's high, low, close and ATR, so a missing day would
        hand the engine the wrong yesterday. Finished days only: today counts once its session
        is over (`include_today`, from SESSION_DONE). At most `lookback_days` back (Angel serves
        30 days of minutes a request) — one candle request a symbol, only when something is
        missing. A day stored as its own file is found without reading it, so a heal with
        nothing to do costs no broker call and almost no CPU."""
        now = now or datetime.now(IST)
        today = now.date()
        since = today - timedelta(days=lookback_days)
        today_done = include_today and now.strftime("%H:%M") >= SESSION_DONE
        want = [since + timedelta(days=k) for k in range(lookback_days + 1)]
        want = [d for d in want if (d < today or (d == today and today_done)) and market_calendar.is_trading_day(d)]
        out: dict[str, object] = {}
        for s in symbols or list(INSTRUMENTS):
            unknown = [d for d in want if not os.path.exists(os.path.join(STORE, s, f"{d.isoformat()}.csv.gz"))]
            if not unknown:
                continue
            have = await asyncio.to_thread(days_with_rows, s, min(unknown))    # inside a 30-day window file?
            missing = [d for d in unknown if d not in have]
            if not missing:
                continue
            e, tok, _k, _t = INSTRUMENTS[s]
            try:
                rows = await angel_client.candles(e, tok, "1", f"{missing[0]} 09:15", f"{missing[-1]} 15:30", bulk=True)
            except Exception as exc:  # noqa: BLE001
                out[s] = f"error: {str(exc)[:80]}"
                continue
            by_day: dict[date, list] = {}
            for r in rows or []:
                try:
                    d = datetime.fromisoformat(r[0]).astimezone(IST).date()
                except Exception:  # noqa: BLE001
                    continue
                by_day.setdefault(d, []).append(r)
            rows_by_day = {d.isoformat(): self._write_day(s, d, by_day[d]) for d in missing if by_day.get(d)}
            filled = [d for d, n in rows_by_day.items() if n]
            out[s] = {"missing": [d.isoformat() for d in missing], "filled": filled,
                      "rows": {d: rows_by_day[d] for d in filled}}
        if out:
            logger.info("index intraday history healed: %s", out)
        return out


def days_with_rows(symbol: str, since: date) -> set[date]:
    """The IST dates on which the store holds any session minute of `symbol` from `since` on."""
    try:
        rows = _read(symbol, since)
    except Exception:  # noqa: BLE001
        return set()
    if not len(rows):
        return set()
    local = rows[:, 0].astype("int64") + 19800
    mins = (local % 86400) // 60
    keep = (mins >= 9 * 60 + 15) & (mins < 15 * 60 + 30)
    days = np.unique(local[keep] // 86400).astype("datetime64[D]")
    return {d.astype(object) for d in days if d.astype(object) >= since}

feed = IndexFeed()
