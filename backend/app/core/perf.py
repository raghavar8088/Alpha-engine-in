"""Where the time goes: per-endpoint latency and event-loop lag, in memory.

WHY THIS EXISTS
---------------
"Every module is slow" turned out, on 2026-11-16, to be a CONCURRENCY problem rather than a
slow-query one: 99 page endpoints answered in a median 1.1 s one at a time, but 13.4 s on
average four at a time, ten of them timing out at 60 s. This process serves the API AND runs
every desk's scheduler on ONE event loop, on a CPU-throttled box, so a request is slow because
something else is holding the loop - a commodity cycle, another request's JSON encoding.

Two numbers tell those apart, and this file keeps both:

* EVENT-LOOP LAG - a task that asks to wake every 0.5 s and records how late it woke. Lag is
  time the loop could not serve ANY request. High lag with fast handlers = the loop is busy
  with something else (a scheduler, CPU steal); low lag with slow handlers = the handler.
* PER-ENDPOINT LATENCY - count, p50, p95 and max per normalised path, so the slow ones can be
  named instead of guessed.

Switching modules off in Main Control should show up as lower lag. That is how the toggle's
effect on responsiveness is verified rather than assumed.

Cheap by construction: a dict update per request, one wake-up every 0.5 s. Nothing is written
to the database. Reset by a restart - it is a gauge, not an audit log.
"""

import asyncio
import re
import time
from collections import deque

LAG_INTERVAL_S = 0.5
MAX_KEYS = 400
SAMPLES = 64

_ID_SEG = re.compile(r"^(?:\d+|[0-9a-f]{8,}|[0-9a-f-]{32,36}|[A-Za-z0-9_-]*\d[A-Za-z0-9_-]{10,})$")

_stats: dict[str, dict] = {}
_lag_samples: deque = deque(maxlen=7200)          # (monotonic, lag_s) - one hour at 0.5 s
_lag_task: asyncio.Task | None = None
_started_at = time.monotonic()


def normalise(method: str, path: str) -> str:
    """`GET /api/fno-positions/positions/a1b2c3d4e5f6/exit` -> `GET /api/fno-positions/positions/:id/exit`."""
    segs = [(":id" if _ID_SEG.match(s) else s) for s in path.split("/")]
    return f"{method} {'/'.join(segs)}"


def record(method: str, path: str, seconds: float, status: int) -> None:
    key = normalise(method, path)
    st = _stats.get(key)
    if st is None:
        if len(_stats) >= MAX_KEYS:
            # Drop the least-used key; a one-off URL must not push out the hot ones.
            victim = min(_stats, key=lambda k: _stats[k]["count"])
            _stats.pop(victim, None)
        st = _stats[key] = {"count": 0, "total": 0.0, "max": 0.0, "errors": 0,
                            "recent": deque(maxlen=SAMPLES), "last_at": 0.0}
    st["count"] += 1
    st["total"] += seconds
    st["max"] = max(st["max"], seconds)
    st["recent"].append(seconds)
    st["last_at"] = time.monotonic()
    if status >= 500:
        st["errors"] += 1


def _pct(values, q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


async def _lag_loop() -> None:
    while True:
        t = time.monotonic()
        await asyncio.sleep(LAG_INTERVAL_S)
        _lag_samples.append((time.monotonic(), max(0.0, time.monotonic() - t - LAG_INTERVAL_S)))


def ensure_lag_monitor() -> None:
    """Start the lag sampler once, from inside the running loop (called per request)."""
    global _lag_task
    if _lag_task is None or _lag_task.done():
        try:
            _lag_task = asyncio.get_running_loop().create_task(_lag_loop())
        except RuntimeError:
            pass


def lag_summary() -> dict:
    now = time.monotonic()
    out = {}
    for label, window in (("last_1m", 60), ("last_10m", 600), ("last_60m", 3600)):
        vals = [lag for at, lag in _lag_samples if now - at <= window]
        out[label] = {
            "samples": len(vals),
            "p50_ms": round(_pct(vals, 0.5) * 1000, 1),
            "p95_ms": round(_pct(vals, 0.95) * 1000, 1),
            "max_ms": round(max(vals) * 1000, 1) if vals else 0.0,
            # Share of the window the loop could not answer anything at all.
            "blocked_pct": round(sum(vals) / window * 100, 1) if vals else 0.0,
        }
    return out


def endpoint_summary(limit: int = 40, sort: str = "p95") -> list[dict]:
    rows = []
    for key, st in _stats.items():
        recent = list(st["recent"])
        rows.append({
            "endpoint": key,
            "count": st["count"],
            "mean_s": round(st["total"] / st["count"], 3) if st["count"] else 0.0,
            "p50_s": round(_pct(recent, 0.5), 3),
            "p95_s": round(_pct(recent, 0.95), 3),
            "max_s": round(st["max"], 3),
            "total_s": round(st["total"], 1),
            "errors": st["errors"],
        })
    key = {"p95": "p95_s", "total": "total_s", "count": "count", "max": "max_s"}.get(sort, "p95_s")
    rows.sort(key=lambda r: r[key], reverse=True)
    return rows[:limit]


def summary(limit: int = 40, sort: str = "p95") -> dict:
    return {
        "uptime_s": round(time.monotonic() - _started_at, 1),
        "event_loop_lag": lag_summary(),
        "endpoints": endpoint_summary(limit, sort),
        "tracked_endpoints": len(_stats),
        "how_to_read": (
            "event_loop_lag is time the server could not answer ANY request. If it is high, "
            "pages are slow because the loop is busy (schedulers, CPU steal) - switch off "
            "modules you do not use and watch it fall. If lag is low but an endpoint's p95 is "
            "high, that endpoint itself is slow."),
    }


def reset() -> None:
    _stats.clear()
    _lag_samples.clear()
