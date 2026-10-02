"""File-backed store of 15-minute bars for the liquid intraday universe.

WHY FILES, NOT MONGO
Two years of 15-minute bars for 200 stocks is ~2.5 million bars. The Atlas M0 cluster sits
at ~230 MB of its 512 MB quota and has write-blocked at that quota before (see
feedback_startup_hooks_must_not_raise); bulk bars there would put every desk at risk. On
local disk the same data is ~50 MB, reads in milliseconds instead of Atlas's multi-second
stalls, and costs no database RAM. Per symbol, one zlib-compressed file of columns.

WHAT A BAR IS HERE
A bar is [start, start + 15 min) in IST, stamped with its START, exactly as Angel's candle
endpoint stamps it ("2026-10-01T09:15:00+05:30"). NSE's session gives 25 of them a day,
09:15 … 15:15, the last one 15 minutes long and, for closing-auction (CAS) stocks, a flat
zero-volume bar — measured on 2026-10-01: RELIANCE 15:15 O=H=L=C=1167.7, volume 0.

ONLY CLOSED BARS LEAVE THIS MODULE. `series()` never returns a bar whose end is in the
future. The pattern desk evaluated Angel's still-forming candle as if it were closed; a
rule that fires on a half-built bar is a different rule from the one any backtest tests.

SESSION-ANCHORED AGGREGATION. 30m, 45m and 1h bars are built from 15m bars bucketed from
09:15 within each session — never by counting bars across the overnight gap, which is how
`nifty_scalp_strategies.resample` built them (a "45 minute" bar holding 15:15 of one day
and 09:15–09:45 of the next). The 1h buckets match Angel's own hourly candles (09:15,
10:15, … 15:15; checked against its ONE_HOUR endpoint on 2026-10-01).

SOURCES. Each bar carries where it came from: CANDLE (Angel's historical endpoint — the
authoritative record) or STREAM (built live from WebSocket ticks). The nightly reconcile
replaces STREAM bars with CANDLE bars and measures how far apart they were.
"""

from __future__ import annotations

import asyncio
import json
from bisect import bisect_left, bisect_right
import logging
import os
import threading
import zlib
from array import array
from datetime import datetime, timedelta, timezone

from app.services.nifty_scalp_strategies import Series

logger = logging.getLogger("intraday_store")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = os.getenv("INTRADAY_DATA_DIR", "/data/intraday")
BASE_MIN = 15
SESSION_OPEN_MIN = 9 * 60 + 15          # 09:15
SESSION_CLOSE_MIN = 15 * 60 + 30        # 15:30
BARS_PER_SESSION = (SESSION_CLOSE_MIN - SESSION_OPEN_MIN) // BASE_MIN   # 25
MEMORY_SESSIONS = int(os.getenv("INTRADAY_MEMORY_SESSIONS", "60"))
AGG_MINUTES = {"15m": 15, "30m": 30, "45m": 45, "1h": 60}

SRC_CANDLE = 1
SRC_STREAM = 2
MAGIC = b"IBAR1\n"


def _ist(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, IST)


def stamp(epoch: int) -> str:
    """Angel's own timestamp format, so code written against candle rows keeps working."""
    return _ist(epoch).isoformat()


def parse_stamp(value) -> int | None:
    """Angel row timestamp ("2026-10-01T09:15:00+05:30") or datetime -> epoch seconds."""
    try:
        if isinstance(value, datetime):
            dt = value if value.tzinfo else value.replace(tzinfo=IST)
        else:
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
        return int(dt.timestamp())
    except (TypeError, ValueError):
        return None


def day_key(epoch: int) -> int:
    """The IST calendar day of an epoch as an integer — integer arithmetic, so grouping
    thousands of bars by day costs nothing (datetime conversion per bar did: it was most
    of a 9.6-second bar-close evaluation)."""
    return (epoch + 19800) // 86400


def day_start(epoch: int) -> int:
    """Epoch of 00:00 IST on `epoch`'s day."""
    return day_key(epoch) * 86400 - 19800


def session_minute(epoch: int) -> int:
    d = _ist(epoch)
    return d.hour * 60 + d.minute


def is_session_bar(epoch: int) -> bool:
    m = session_minute(epoch)
    return (SESSION_OPEN_MIN <= m < SESSION_CLOSE_MIN
            and (m - SESSION_OPEN_MIN) % BASE_MIN == 0
            and _ist(epoch).second == 0)


def bar_end(epoch: int, minutes: int = BASE_MIN) -> int:
    """End of the bar starting at `epoch`, clipped to the session close."""
    d = _ist(epoch)
    close = d.replace(hour=15, minute=30, second=0, microsecond=0)
    return int(min(d + timedelta(minutes=minutes), close).timestamp())


class Bars:
    """Columns of one symbol's 15m bars, oldest first, unique by start time."""

    __slots__ = ("t", "o", "h", "l", "c", "v", "src")

    def __init__(self):
        self.t = array("q"); self.o = array("d"); self.h = array("d")
        self.l = array("d"); self.c = array("d"); self.v = array("q"); self.src = array("b")

    def __len__(self) -> int:
        return len(self.t)

    def rows(self, start: int = 0, stop: int | None = None):
        stop = len(self.t) if stop is None else stop
        for i in range(start, stop):
            yield (self.t[i], self.o[i], self.h[i], self.l[i], self.c[i], self.v[i], self.src[i])

    @classmethod
    def from_rows(cls, rows) -> "Bars":
        b = cls()
        for t, o, h, l, c, v, s in rows:
            b.t.append(int(t)); b.o.append(float(o)); b.h.append(float(h)); b.l.append(float(l))
            b.c.append(float(c)); b.v.append(int(v)); b.src.append(int(s))
        return b

    def merge(self, rows, prefer_existing_candle: bool = True) -> int:
        """Insert or replace bars. A STREAM bar never overwrites a CANDLE bar (the candle is
        the authoritative record); a CANDLE bar always replaces a STREAM one. Returns how
        many bars were added or changed."""
        merged = {r[0]: r for r in self.rows()}
        changed = 0
        for r in rows:
            t = int(r[0])
            old = merged.get(t)
            if old is not None and prefer_existing_candle and old[6] == SRC_CANDLE and r[6] == SRC_STREAM:
                continue
            if old != tuple(r):
                merged[t] = tuple(r)
                changed += 1
        if changed:
            fresh = Bars.from_rows(merged[k] for k in sorted(merged))
            for name in self.__slots__:
                setattr(self, name, getattr(fresh, name))
        return changed

    def trim_sessions(self, keep: int) -> None:
        """Keep the last `keep` sessions in memory (the file keeps everything)."""
        if not len(self.t):
            return
        days, cut = 0, 0
        last_day = None
        for i in range(len(self.t) - 1, -1, -1):
            day = _ist(self.t[i]).date()
            if day != last_day:
                days += 1
                last_day = day
                if days > keep:
                    cut = i + 1
                    break
        if cut:
            for name in self.__slots__:
                setattr(self, name, getattr(self, name)[cut:])


# ── files ────────────────────────────────────────────────────────────────────────


def _path(symbol: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_&" else "_" for ch in symbol.upper())
    return os.path.join(DATA_DIR, "15m", f"{safe}.ibar")


def write_file(symbol: str, bars: Bars) -> None:
    head = json.dumps({"symbol": symbol, "tf": "15m", "n": len(bars),
                       "cols": ["t:q", "o:d", "h:d", "l:d", "c:d", "v:q", "src:b"]}).encode()
    body = b"".join(getattr(bars, name).tobytes() for name in Bars.__slots__)
    blob = zlib.compress(MAGIC + head + b"\n" + body, 6)
    path = _path(symbol)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)                     # atomic: a reader sees old or new, never half


def read_file(symbol: str) -> Bars:
    path = _path(symbol)
    if not os.path.exists(path):
        return Bars()
    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())
    if not raw.startswith(MAGIC):
        raise ValueError(f"{path}: not an intraday bar file")
    head_end = raw.index(b"\n", len(MAGIC))
    head = json.loads(raw[len(MAGIC):head_end])
    n = int(head["n"])
    b = Bars()
    pos = head_end + 1
    for name in Bars.__slots__:
        arr = getattr(b, name)
        size = n * arr.itemsize
        arr.frombytes(raw[pos:pos + size])
        pos += size
    return b


# ── the store ────────────────────────────────────────────────────────────────────


class Store:
    """Recent bars in memory for live use; the full history on disk for research."""

    def __init__(self):
        self._mem: dict[str, Bars] = {}
        self._dirty: set[str] = set()
        self._lock = threading.Lock()      # file writes may run in a worker thread
        self.writable = self._check_dir()

    @staticmethod
    def _check_dir() -> bool:
        try:
            os.makedirs(os.path.join(DATA_DIR, "15m"), exist_ok=True)
            probe = os.path.join(DATA_DIR, ".write-probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return True
        except OSError as exc:
            logger.error("intraday bar store: %s is not writable (%s) — bars will be kept in "
                         "memory only and lost on restart", DATA_DIR, exc)
            return False

    def get(self, symbol: str) -> Bars:
        b = self._mem.get(symbol)
        if b is None:
            try:
                b = read_file(symbol)
            except (OSError, ValueError, zlib.error):
                logger.exception("could not read bars for %s — starting empty", symbol)
                b = Bars()
            b.trim_sessions(MEMORY_SESSIONS)
            self._mem[symbol] = b
        return b

    async def preload(self, symbols: list[str]) -> int:
        """Load each symbol's recent window from disk in a worker thread, so the first
        stream bar of the day (09:30:05) and the first evaluation (09:45) never read 200
        files synchronously on the event loop."""
        loaded = 0
        for sym in symbols:
            if sym in self._mem:
                continue
            try:
                b = await asyncio.to_thread(read_file, sym)
            except (OSError, ValueError, zlib.error):
                logger.exception("preload failed for %s", sym)
                continue
            b.trim_sessions(MEMORY_SESSIONS)
            self._mem.setdefault(sym, b)
            loaded += 1
        return loaded

    def merge(self, symbol: str, rows) -> int:
        changed = self.get(symbol).merge(rows)
        if changed:
            self._dirty.add(symbol)
        return changed

    def series(self, symbol: str, tf: str = "15m", n: int | None = None,
               now: datetime | None = None) -> Series:
        """CLOSED bars only, session-anchored for 30m/45m/1h. `n` keeps the last n bars.

        The returned Series also carries `epochs` (bar start times) so callers can find a
        day's bars by binary search instead of parsing timestamps."""
        minutes = AGG_MINUTES[tf]
        factor = minutes // BASE_MIN
        cutoff = int((now or datetime.now(IST)).timestamp())
        b = self.get(symbol)
        # A grid 15m bar ends 15 minutes after it starts (15:15 + 15 = the 15:30 close),
        # so "closed by cutoff" is simply start <= cutoff - 900.
        hi = bisect_right(b.t, cutoff - BASE_MIN * 60)
        lo = 0 if n is None else max(0, hi - (n + 2) * factor - BARS_PER_SESSION)
        rows = [(b.t[i], b.o[i], b.h[i], b.l[i], b.c[i], b.v[i], b.src[i]) for i in range(lo, hi)]
        if minutes != BASE_MIN:
            rows = aggregate(rows, minutes, cutoff)
            if lo > 0 and rows:
                rows = rows[1:]          # the first bucket may be missing its early bars
        if n is not None:
            rows = rows[-n:]
        out = Series([stamp(r[0]) for r in rows], [r[1] for r in rows], [r[2] for r in rows],
                     [r[3] for r in rows], [r[4] for r in rows], [float(r[5]) for r in rows])
        out.epochs = [r[0] for r in rows]
        return out

    def count_between(self, symbol: str, start: int, end: int) -> int:
        """How many bars start in [start, end]."""
        b = self.get(symbol)
        return bisect_right(b.t, end) - bisect_left(b.t, start)

    # File work runs in a worker thread; the arrays it writes are SNAPSHOTS taken on the
    # event-loop thread first, because the stream keeps merging into the live arrays and a
    # merge swaps seven columns one at a time — a reader in another thread could pair one
    # bar's times with another bar's prices.

    def _merge_file(self, symbol: str, rows: list[tuple]) -> tuple[int, int]:
        """File-level merge. A STREAM bar never replaces a CANDLE bar already on disk."""
        with self._lock:
            disk = read_file(symbol)
            changed = disk.merge(rows)
            if changed:
                write_file(symbol, disk)
            return changed, len(disk)

    async def flush_dirty(self) -> dict:
        """Write every symbol whose memory holds bars the file does not."""
        if not self.writable:
            return {"flushed": 0, "pending": len(self._dirty), "writable": False}
        written = 0
        for sym in sorted(self._dirty):
            mem = self._mem.get(sym)
            if mem is None:
                self._dirty.discard(sym)
                continue
            rows = list(mem.rows())                                  # snapshot, loop thread
            try:
                await asyncio.to_thread(self._merge_file, sym, rows)
                self._dirty.discard(sym)
                written += 1
            except Exception:  # noqa: BLE001
                logger.exception("flush failed for %s", sym)
        return {"flushed": written, "pending": len(self._dirty)}

    async def merge_history(self, symbol: str, rows: list[tuple]) -> tuple[int, int]:
        """Bulk history (backfill, reconcile) goes straight to the FILE. Memory only takes
        the part inside its window — two years for 200 symbols held in memory would be
        ~120 MB in a container capped at 800."""
        if self.writable:
            changed, total = await asyncio.to_thread(self._merge_file, symbol, rows)
        else:
            changed, total = self.get(symbol).merge(rows), len(self.get(symbol))
            return changed, total
        mem = self._mem.get(symbol)
        if mem is not None:
            if not len(mem):
                self._mem.pop(symbol, None)          # next get() reads the file and trims
            else:
                recent = [r for r in rows if r[0] >= mem.t[0]]
                if recent:
                    mem.merge(recent)
                    mem.trim_sessions(MEMORY_SESSIONS)
        return changed, total

    def coverage(self, symbols: list[str]) -> dict:
        """What history exists on disk, without loading full files into memory."""
        have, sessions = 0, []
        for sym in symbols:
            path = _path(sym)
            if not os.path.exists(path):
                continue
            have += 1
            b = self._mem.get(sym)
            if b is not None and len(b):
                sessions.append(len({_ist(t).date() for t in b.t}))
        sessions.sort()
        return {"symbols": len(symbols), "with_history": have,
                "memory_sessions_median": sessions[len(sessions) // 2] if sessions else 0,
                "dir": DATA_DIR, "writable": self.writable}

    def mem_stats(self) -> dict:
        bars = sum(len(b) for b in self._mem.values())
        return {"symbols_in_memory": len(self._mem), "bars_in_memory": bars,
                "approx_mb": round(bars * 49 / 1e6, 1), "dirty": len(self._dirty)}


def aggregate(rows: list[tuple], minutes: int, cutoff: int) -> list[tuple]:
    """15m rows -> `minutes` rows, bucketed from 09:15 within each session. A bucket is
    emitted only once it has closed (its end, clipped to 15:30, is at or before `cutoff`).
    The last bucket of a session is shorter than the rest by design: 15:15–15:30 for 1h."""
    out: list[tuple] = []
    cur_key = None
    acc = None
    for t, o, h, l, c, v, s in rows:
        d = _ist(t)
        k = (d.date(), (d.hour * 60 + d.minute - SESSION_OPEN_MIN) // minutes)
        if k != cur_key:
            if acc is not None and bar_end(acc[0], minutes) <= cutoff:
                out.append(tuple(acc))
            start = int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                        + (SESSION_OPEN_MIN + k[1] * minutes) * 60)
            acc = [start, o, h, l, c, v, s]
            cur_key = k
        else:
            acc[2] = max(acc[2], h); acc[3] = min(acc[3], l); acc[4] = c; acc[5] += v
            acc[6] = max(acc[6], s)          # STREAM if any part came from the stream
    if acc is not None and bar_end(acc[0], minutes) <= cutoff:
        out.append(tuple(acc))
    return out


def rows_from_angel(candles: list[list], src: int = SRC_CANDLE) -> list[tuple]:
    """Angel candle rows -> store rows, dropping anything outside the session grid."""
    out = []
    for r in candles:
        if len(r) < 6:
            continue
        t = parse_stamp(r[0])
        if t is None or not is_session_bar(t):
            continue
        try:
            out.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[5] or 0), src))
        except (TypeError, ValueError):
            continue
    return out


store = Store()
