"""The imported strategies, run on this desk's capital, costs and fills.

STOCK MOMENTUM TRADING (frontend/app/stock-momentum -> /api/screener/morning/{index} ->
backend/app/services/screener/morning.py). Its eight rules are executed from the module's OWN file, unmodified:
`load_morning(path)` executes morning.py with two small adapters in place of its imports (the bar store and the fee
card), so `scan` (the 09:30 board) and `triggers` (the bar-close rules) are byte-for-byte the desk's code. Only the
execution is this desk's: entry at the trigger bar's close + measured slippage, the rule's own stop (the signal
candle's extreme) and target (2R; gap fade capped at the previous close), sizing and limits from pis.book.

INTRADAY STOCKS TOURNAMENT (54 rules, backend/app/services/intraday_v2_strategies.py). Signals are never
recomputed here: the research replay re-fills the signals the app's own audit replay recorded
(INTRADAY_STOCKS_54_STRATEGY_AUDIT.md, signals.csv.gz), and the live desk re-fills the rows the tournament writes
to its decision ledger (intraday_signal_ledger). `tournament_intent` turns one signal into this desk's order.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from bisect import bisect_left
from types import SimpleNamespace

from . import costs as C
from .timeutil import IST, OPEN_MIN, day_key, minute

TF_MINUTES = {"15m": 15, "45m": 45, "1h": 60}
MAX_BARS = {"15m": 8, "45m": 4, "1h": 3}          # intraday_v2_strategies.MAX_BARS (time stop)
MORNING_RULES = ("orb15", "orb30", "vwap", "relative", "pullback", "gap_go", "gap_fade", "volume")


class BarsAdapter:
    """What morning.py expects from intraday_store.read_file: parallel arrays and rows(i, j)."""

    def __init__(self, rows: list):
        rows = sorted(rows, key=lambda r: r[0])
        self.t = [int(r[0]) for r in rows]
        self.o = [r[1] for r in rows]
        self.h = [r[2] for r in rows]
        self.l = [r[3] for r in rows]
        self.c = [r[4] for r in rows]
        self.v = [r[5] for r in rows]

    def __len__(self):
        return len(self.t)

    def rows(self, start: int = 0, stop: int | None = None):
        stop = len(self.t) if stop is None else stop
        for i in range(start, stop):
            yield (self.t[i], self.o[i], self.h[i], self.l[i], self.c[i], self.v[i], 1)


def load_morning(path: str, loader=None):
    """Execute the Stock Momentum desk's morning.py from `path` with adapter imports. Returns the module."""
    store = types.ModuleType("app.services.intraday_store")
    store.read_file = loader or (lambda symbol, tf="5m": BarsAdapter([]))
    store.day_start = lambda epoch: day_key(epoch) * 86400 - 19800
    store.session_minute = minute
    store.IST = IST
    store.store5 = None
    fees = types.ModuleType("app.services.angel_fees")
    fees.round_trip = lambda entry, exit_, qty, side="BUY", product="INTRADAY": SimpleNamespace(
        total=C.charges(entry, exit_, int(qty), 1 if side == "BUY" else -1)["total"])
    app = types.ModuleType("app")
    services = types.ModuleType("app.services")
    services.intraday_store = store
    services.angel_fees = fees
    app.services = services
    saved = {k: sys.modules.get(k) for k in ("app", "app.services", "app.services.intraday_store",
                                             "app.services.angel_fees")}
    sys.modules.update({"app": app, "app.services": services, "app.services.intraday_store": store,
                        "app.services.angel_fees": fees})
    try:
        spec = importlib.util.spec_from_file_location("pis_stock_momentum_rules", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return mod


def morning_intent(rule: str, side: int, row: dict, signal_bar, k: int, slip_bp: float, sector: str) -> dict | None:
    """The desk's rule levels (morning.order: stop at the signal candle's extreme, target 2R, gap fade capped at the
    previous close) on this desk's fill: the trigger bar's close."""
    ref = signal_bar[4]
    stop = signal_bar[3] if side == 1 else signal_bar[2]
    risk = (ref - stop) * side
    if risk <= 0:
        return None
    target = ref + side * 2 * risk
    if rule == "gap_fade" and (target - row["prev"]) * side > 0:
        target = row["prev"]
    if (target - ref) * side <= 0:
        return None
    return {"strategy": f"SM:{rule}", "variant": "as-built", "level": "imported", "symbol": row["symbol"],
            "sector": sector, "side": side, "ref": ref, "stop": stop, "target": target, "slip_bp": slip_bp,
            "bar_volume": signal_bar[5], "time_exit_min": 15 * 60 + 5, "knew": {}}


def tournament_tf(sid: str) -> str:
    for tf in ("15m", "45m", "1h"):
        if sid.endswith("_" + tf):
            return tf
    return "day"


def tournament_time_exit(sid: str, entry_close_min: int) -> int:
    tf = tournament_tf(sid)
    if tf == "day":
        return 15 * 60 + 5
    return min(15 * 60 + 5, entry_close_min + MAX_BARS[tf] * TF_MINUTES[tf])
