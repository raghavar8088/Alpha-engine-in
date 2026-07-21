"""Checks the Phase 3/4 cache TTL + merge logic by exec-ing the pure functions
out of chart_cache.py (its module imports need redis/motor)."""

import ast
from datetime import datetime, timedelta, timezone

SRC = r"d:\INDIAN MARKET\backend\app\services\chart_cache.py"
WANT_FUNCS = {"_parse_session", "_session_start_ist", "market_is_open", "ttl_for", "cache_key", "merge_series"}
WANT_CONSTS = {"IST", "DEFAULT_SESSION", "_COMPLETED_TTL_SECONDS", "_LIVE_TTL_SECONDS",
               "_CLOSED_TTL_SECONDS", "_KEY_PREFIX"}

tree = ast.parse(open(SRC, encoding="utf-8").read())
picked = []
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in WANT_FUNCS:
        picked.append(node)
    elif isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in WANT_CONSTS for t in node.targets
    ):
        picked.append(node)

ns = {"datetime": datetime, "timedelta": timedelta, "timezone": timezone}
exec(compile(ast.Module(body=picked, type_ignores=[]), SRC, "exec"), ns)

market_is_open = ns["market_is_open"]
ttl_for = ns["ttl_for"]
cache_key = ns["cache_key"]
merge_series = ns["merge_series"]
IST = ns["IST"]
COMPLETED, LIVE, CLOSED = ns["_COMPLETED_TTL_SECONDS"], ns["_LIVE_TTL_SECONDS"], ns["_CLOSED_TTL_SECONDS"]

failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got={got!r} want={want!r}")


def ist(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=IST).astimezone(timezone.utc)


# 2026-07-20 is a Monday; 2026-07-25 a Saturday.
EQUITY = "0915-1530"
MCX = "0900-2330"

# --- market_is_open, equity ------------------------------------------------
check("equity closed pre-open (09:00 Mon)", market_is_open(ist(2026, 7, 20, 9, 0), EQUITY), False)
check("equity open at 09:15", market_is_open(ist(2026, 7, 20, 9, 15), EQUITY), True)
check("equity open midday", market_is_open(ist(2026, 7, 20, 12, 0), EQUITY), True)
check("equity open at close bell 15:30", market_is_open(ist(2026, 7, 20, 15, 30), EQUITY), True)
check("equity closed 15:31", market_is_open(ist(2026, 7, 20, 15, 31), EQUITY), False)
check("equity closed Saturday midday", market_is_open(ist(2026, 7, 25, 12, 0), EQUITY), False)
check("equity closed Sunday midday", market_is_open(ist(2026, 7, 26, 12, 0), EQUITY), False)

# --- market_is_open, MCX (the Phase 4 reason this is parameterised) --------
check("MCX open at 21:00 (equity would say closed)", market_is_open(ist(2026, 7, 20, 21, 0), MCX), True)
check("equity says closed at that same 21:00", market_is_open(ist(2026, 7, 20, 21, 0), EQUITY), False)
check("MCX open at 09:00", market_is_open(ist(2026, 7, 20, 9, 0), MCX), True)
check("MCX closed at 23:31", market_is_open(ist(2026, 7, 20, 23, 31), MCX), False)

# --- ttl_for ---------------------------------------------------------------
now_open = ist(2026, 7, 20, 12, 0)          # Monday, equity session live
now_closed = ist(2026, 7, 20, 16, 30)       # Monday, after the bell
session_start = ist(2026, 7, 20, 9, 15)

# A range ending before today's open is finished history -> long TTL.
yesterday_close = int(ist(2026, 7, 17, 15, 30).timestamp())
check("completed history cached long", ttl_for(yesterday_close, now_open, EQUITY), COMPLETED)

# A range covering right now, mid-session -> short TTL (in-progress candle).
right_now = int(now_open.timestamp())
check("live session range cached briefly", ttl_for(right_now, now_open, EQUITY), LIVE)

# Same range, after the close -> medium TTL.
check("today's range after the close", ttl_for(right_now, now_closed, EQUITY), CLOSED)

# The critical Phase 4 case: at 21:00 IST an MCX contract is still trading, so
# its current range must NOT get the long "finished history" TTL.
now_evening = ist(2026, 7, 20, 21, 0)
evening_ts = int(now_evening.timestamp())
check("MCX evening range is treated as live", ttl_for(evening_ts, now_evening, MCX), LIVE)
check("equity evening range is treated as closed", ttl_for(evening_ts, now_evening, EQUITY), CLOSED)

# Boundary: exactly at session start.
check("range ending exactly at session start is live-ish",
      ttl_for(int(session_start.timestamp()), now_open, EQUITY), LIVE)

# --- cache_key -------------------------------------------------------------
k1 = cache_key("1333", "NSE_EQ", "5", 100, 200)
k2 = cache_key("1333", "NSE_EQ", "5", 100, 201)
k3 = cache_key("1333", "NSE_EQ", "15", 100, 200)
k4 = cache_key("1334", "NSE_EQ", "5", 100, 200)
check("same inputs give the same key", k1, cache_key("1333", "NSE_EQ", "5", 100, 200))
check("a different range gives a different key", k1 == k2, False)
check("a different resolution gives a different key", k1 == k3, False)
check("a different instrument gives a different key", k1 == k4, False)
check("key is namespaced", k1.startswith("chart:bars:"), True)

# --- merge_series ----------------------------------------------------------
older = {"t": [10, 20, 30], "o": [1, 2, 3], "h": [1, 2, 3], "l": [1, 2, 3], "c": [1, 2, 3], "v": [10, 20, 30]}
newer = {"t": [30, 40], "o": [99, 4], "h": [99, 4], "l": [99, 4], "c": [99, 4], "v": [99, 40]}
merged = merge_series(older, newer)
check("merged timestamps are sorted and deduped", merged["t"], [10, 20, 30, 40])
check("Dhan wins on the overlapping bar", merged["c"][2], 99)
check("accumulated-only bars survive", merged["c"][0], 1)
check("new bars are appended", merged["c"][3], 4)
check("every column stays the same length",
      {len(merged[k]) for k in ("t", "o", "h", "l", "c", "v")}, {4})

# merging with an empty side must not lose data either way
check("merge with empty newer keeps older", merge_series(older, {k: [] for k in older})["t"], [10, 20, 30])
check("merge with empty older keeps newer", merge_series({k: [] for k in older}, newer)["t"], [30, 40])

# out-of-order input is still sorted
messy = {"t": [50, 5], "o": [5, 0], "h": [5, 0], "l": [5, 0], "c": [5, 0], "v": [5, 0]}
check("merge sorts unordered input", merge_series(messy, {k: [] for k in messy})["t"], [5, 50])

# --- bar_epoch: live-stream bars must land on Dhan's history grid -----------
# Pinned to a real production observation: Dhan's /charts/intraday returned
# 1784173500 for the first 5m bar of 2026-07-16, which is 03:45 UTC = 09:15 IST
# (market open). live_feed publishes that same bar as an IST-aware datetime, so
# converting it must reproduce Dhan's epoch exactly. Getting this wrong put every
# streamed bar 5.5h ahead of history, so live updates never merged at all.
_STREAM_SRC = r"d:\INDIAN MARKET\backend\app\services\chart_stream.py"
_stream_tree = ast.parse(open(_STREAM_SRC, encoding="utf-8").read())
_stream_picked = [n for n in _stream_tree.body if isinstance(n, ast.FunctionDef) and n.name == "bar_epoch"]
assert _stream_picked, "bar_epoch not found in chart_stream.py"
_stream_ns = {"datetime": datetime, "timezone": timezone, "timedelta": timedelta}
exec(compile(ast.Module(body=_stream_picked, type_ignores=[]), _STREAM_SRC, "exec"), _stream_ns)
bar_epoch = _stream_ns["bar_epoch"]

DHAN_0915_IST = 1784173500  # observed in production
check("live bar at 09:15 IST lands on Dhan's grid",
      bar_epoch("2026-07-16T09:15:00+05:30"), DHAN_0915_IST)
check("the next 5m bucket is exactly 300s later",
      bar_epoch("2026-07-16T09:20:00+05:30"), DHAN_0915_IST + 300)
check("an explicit-UTC timestamp gives the same instant",
      bar_epoch("2026-07-16T03:45:00+00:00"), DHAN_0915_IST)
check("15:30 IST close maps to 10:00 UTC",
      bar_epoch("2026-07-16T15:30:00+05:30"),
      int(datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc).timestamp()))
# The specific regression: never re-read IST wall-clock as if it were UTC.
_wall_clock_bug = int(datetime.fromisoformat("2026-07-16T09:15:00+05:30")
                      .replace(tzinfo=timezone.utc).timestamp())
check("does not reintroduce the 5.5h wall-clock bug",
      bar_epoch("2026-07-16T09:15:00+05:30") == _wall_clock_bug, False)

print()
print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
raise SystemExit(0 if failures == 0 else 1)
