"""Does the pattern board still answer once its scan has expired?

The scan is ~30 seconds of single-threaded CPU over 500 symbols on two timeframes, and
its entry expires hourly, so the question that matters is what happens at the moment it
goes stale. Waiting an hour to find out is not a test, so the cache timestamp is backdated
instead — the code under test only ever compares `time.monotonic()` against it.

What has to hold:
  * a stale entry is SERVED, not recomputed on the caller's thread
  * it is served honestly, carrying stale_s, and the board can say so
  * a refresh is actually launched behind that request
  * past the grace window the caller waits rather than being handed ancient data
  * fresh=true always recomputes, or the Refresh button is a lie

Run: python -m tests.screener.verify_pattern_cache
"""
import asyncio
import sys
import time

from app.services.screener import patterns as P

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def backdate(key: str, seconds: float) -> None:
    """Make the cached entry look `seconds` old."""
    stamp, value = P._cache[key]
    P._cache[key] = (stamp - seconds, value)


async def go() -> None:
    from app.services.screener.momentum import DEFAULT_INDEX

    index = DEFAULT_INDEX
    key = f"patterns:{index}"

    print("priming the cache (this is the one call that legitimately waits)…")
    t0 = time.monotonic()
    first = await P.scan(index)
    cold = time.monotonic() - t0
    print(f"  cold scan {cold:.1f}s — {len(first['rows'])} rows over {first['scanned']} symbols\n")

    # ---- warm ------------------------------------------------------------------
    t0 = time.monotonic()
    warm = await P.scan(index)
    warm_s = time.monotonic() - t0
    check("a warm entry is served without rescanning", warm_s < 0.05,
          f"{warm_s * 1000:.1f}ms")
    check("the warm entry is not marked stale", "stale_s" not in warm)

    # ---- stale but inside the grace window --------------------------------------
    age = P.SCAN_TTL + 60
    backdate(key, age)
    t0 = time.monotonic()
    stale = await P.scan(index)
    stale_s = time.monotonic() - t0
    check("a stale entry is served immediately, not recomputed", stale_s < 0.05,
          f"{stale_s * 1000:.1f}ms (a rescan would be ~{cold:.0f}s)")
    check("the stale entry says so", stale.get("stale_s", 0) >= P.SCAN_TTL,
          f"stale_s={stale.get('stale_s')}")
    check("the rows are still there", len(stale["rows"]) == len(first["rows"]),
          f"{len(stale['rows'])}")

    # the refresh it launched should replace the entry shortly
    print("  waiting for the background refresh to land…")
    for _ in range(90):
        await asyncio.sleep(1)
        if time.monotonic() - P._cache[key][0] < P.SCAN_TTL:
            break
    fresh_again = await P.scan(index)
    check("the background refresh replaced the stale entry",
          "stale_s" not in fresh_again,
          "still stale" if "stale_s" in fresh_again else "refreshed")

    # ---- past the grace window ---------------------------------------------------
    backdate(key, P.STALE_GRACE + 60)
    t0 = time.monotonic()
    await P.scan(index)
    old_s = time.monotonic() - t0
    check("past the grace window the caller waits for a real scan", old_s > 1.0,
          f"{old_s:.1f}s")

    # ---- fresh=true ---------------------------------------------------------------
    t0 = time.monotonic()
    await P.scan(index, fresh=True)
    forced = time.monotonic() - t0
    check("fresh=true recomputes rather than returning the cache", forced > 1.0,
          f"{forced:.1f}s")

    # ---- single flight ------------------------------------------------------------
    backdate(key, P.STALE_GRACE + 60)
    t0 = time.monotonic()
    await asyncio.gather(*(P.scan(index) for _ in range(3)))
    three = time.monotonic() - t0
    check("three concurrent cold callers run ONE scan between them",
          three < cold * 2,
          f"{three:.1f}s for three, one scan is ~{cold:.0f}s")


async def main() -> None:
    await go()
    print("\n" + "=" * 64)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("pattern cache holds")


asyncio.run(main())
