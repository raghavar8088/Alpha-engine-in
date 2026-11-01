"""The strategy library, read from where the strategies live - one row per unique strategy.

  Strategy Factory   546 strategies (69 hypotheses x their timeframes), ids SF0001..SF0546.
  Strategies module  every STRATEGY_REGISTRY entry on each timeframe it declares, id
                     "<strategy_id>@<timeframe>" (the app's own convention, as in the tournament's
                     "ema_200_trend@15m"); a timeframe outside the eight crypto ones is dropped.

Nothing is copied. A row carries the definition's own fields (rules, regimes, confirmations,
targets, description, parameters) and the crypto verdict:

  supported     runs unchanged on crypto bars (the session is the UTC day - see config)
  adapted       runs unchanged with one crypto-specific setting, named in `adaptation`
  unsupported   cannot run honestly on this venue's data; `unsupported_reason` says why
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from .config import (
    BENCHMARK_STRATEGIES, BENCHMARK_SYMBOL, HTF_WINDOW, NSE_CLOCK_STRATEGIES, SESSION_NOTE, TIMEFRAMES,
)

OPTIONS_REASON = (
    "Options strategy. Delta Exchange India lists options only on BTC and ETH, and an expired contract's "
    "history is last-trade prints on mostly untraded strikes (e.g. 67 of 288 possible 15-minute candles in "
    "an expired BTC option's last three days, nearly all zero-volume), with no historical bid/ask or "
    "volatility surface. Its entries and exits cannot be priced honestly in a backtest, so it cannot earn "
    "a crypto grade - and without one it may not paper trade.")
UNSUPPORTED = {
    "oi_buildup": ("Needs open interest on every bar. Delta's candles carry none and the venue publishes "
                   "only the current open interest, so there is no history to backtest it on."),
    "calendar_spread": ("Needs two synchronised dated contracts (near and far). These coins trade as "
                        "perpetuals on the venue, and the strategy itself emits nothing until a two-leg "
                        "feed exists."),
}
SESSION_DETECTORS = {"opening_range", "prior_session_break", "gap_fade", "vwap_reclaim", "gap_continuation",
                     "pivot_level_break", "prev_period_break"}
NEEDS_ASSET_ONLY = {"delivery_breakout": "uses its volume proxy for delivery buying (crypto has no delivery data)",
                    "earnings_momentum": "uses its gap + volume announcement proxy (crypto has no earnings calendar)"}


def _factory_rows() -> list[dict]:
    from app.services.strategy_factory.backtest import DEFAULT_MAX_HOLD
    from app.services.strategy_factory.catalog import FACTORY_CATALOG
    from app.services.strategy_factory.primitives import MAX_STOP_ATR, MIN_STOP_ATR
    rows = []
    for s in FACTORY_CATALOG:
        # Detectors (and the VWAP confirmation) that group bars into sessions by the bar's own date:
        # on UTC bars every one of them reads the UTC day - no clock is hard-coded in any of them.
        intraday_session = (s.detector in SESSION_DETECTORS
                            or any(c == "vwap" for c, _ in s.confirmations))
        rows.append({
            "strategy_id": s.strategy_id, "library": "factory", "base_id": s.strategy_id, "name": s.name,
            "family": s.family, "sub_family": s.sub_family, "timeframe": s.timeframe, "htf": s.htf,
            "style": s.style, "fingerprint": s.fingerprint, "min_bars": s.min_bars,
            "rules": {
                "hypothesis": s.hypothesis,
                "entry": (f"Setup '{s.detector}' on a CLOSED {s.timeframe} bar"
                          + (f", confirmed by {', '.join(c for c, _ in s.confirmations)}" if s.confirmations else "")
                          + (f" and the {s.htf} trend (closed {s.htf} bars only)" if s.htf else "")
                          + "; decided only while flat; filled at the NEXT bar's open."),
                "regimes": sorted(s.regimes) or ["any"],
                "stop": (f"Structural (the pattern's invalidation level), clamped to {MIN_STOP_ATR}-{MAX_STOP_ATR} "
                         "ATR(14) from entry."),
                "target": f"The pattern's measured move, else {s.target_r}R.",
                "risk_reward": s.target_r,
                "exit": (f"Stop, target, or {DEFAULT_MAX_HOLD.get(s.timeframe, 60)} bars held - whichever "
                         "comes first, checked from the entry bar on; a bar touching both counts as the stop, "
                         "and a bar opening through a level fills at its open."),
                "sizing": "1% of the account at risk per trade, capped at 1x notional.",
                "params": {k: v for k, v in s.params.items() if isinstance(v, (int, float, str))},
                "confirmations": [{"name": c, "params": p} for c, p in s.confirmations],
            },
            "support": "supported",
            "adaptation": (SESSION_NOTE if intraday_session else
                           "Unchanged; 24/7 bars with UTC timestamps."),
            "unsupported_reason": None,
            "instrument": "USD perpetual on the venue, 1x (long and short)",
        })
    return rows


def _sm_fingerprint(cls) -> str:
    try:
        schema = cls.Params.model_json_schema()
    except Exception:  # noqa: BLE001
        schema = {}
    raw = f"{cls.__module__}.{cls.__qualname__}|{json.dumps(schema, sort_keys=True, default=str)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _strategies_rows() -> list[dict]:
    import strategy_service  # noqa: F401 - fills the registry
    from tradingai_shared.contracts import STRATEGY_REGISTRY
    rows = []
    for sid in sorted(STRATEGY_REGISTRY):
        cls = STRATEGY_REGISTRY[sid]
        m = cls.metadata
        is_options = "options" in cls.__module__ or m.category.startswith("options")
        tfs = [t.value for t in m.timeframes]
        crypto_tfs = [t for t in TIMEFRAMES if t in tfs]
        try:
            params = cls.Params().model_dump()
        except Exception:  # noqa: BLE001
            params = {}
        for tf in crypto_tfs or tfs[:1]:
            support, adaptation, why = "supported", "Unchanged; 24/7 bars with UTC timestamps.", None
            if is_options:
                support, adaptation, why = "unsupported", None, OPTIONS_REASON
            elif sid in UNSUPPORTED:
                support, adaptation, why = "unsupported", None, UNSUPPORTED[sid]
            elif tf not in TIMEFRAMES:
                support, adaptation, why = "unsupported", None, f"declares only {tf}, not one of the eight crypto timeframes"
            elif sid in NSE_CLOCK_STRATEGIES:
                support, adaptation = "adapted", SESSION_NOTE
            elif sid in BENCHMARK_STRATEGIES:
                support, adaptation = "adapted", (f"Benchmark = {BENCHMARK_SYMBOL} (the crypto market's NIFTY), same "
                                                  "timeframe; not applicable to BTC itself.")
            elif sid in NEEDS_ASSET_ONLY:
                support, adaptation = "adapted", f"Runs as written: it {NEEDS_ASSET_ONLY[sid]}."
            rows.append({
                "strategy_id": f"{sid}@{tf}", "library": "strategies", "base_id": sid, "name": f"{m.name} · {tf}",
                "family": m.category, "sub_family": m.suitable_market, "timeframe": tf, "htf": None,
                "style": m.category, "fingerprint": _sm_fingerprint(cls),
                "min_bars": None,
                "rules": {
                    "hypothesis": m.description,
                    "entry": ("The strategy's own on_bar() on each CLOSED bar; BUY opens a long, SELL a short (or "
                              "reverses), filled at the NEXT bar's open."),
                    "regimes": [m.suitable_market],
                    "stop": "The stop_loss its signal carries, checked against every bar's range (a gap fills at the open).",
                    "target": "The target its signal carries, if any.",
                    "risk_reward": m.risk_reward,
                    "exit": "Its own EXIT_LONG / EXIT_SHORT signals, the stop or the target; a bar touching both counts as the stop.",
                    "sizing": "The module's own risk engine: the whole account, 1x notional.",
                    "params": {k: v for k, v in params.items() if isinstance(v, (int, float, str, bool))},
                    "expected_win_rate": m.expected_win_rate,
                    "declared_timeframes": tfs,
                    "declared_asset_classes": [a.value for a in m.asset_classes],
                },
                "support": support, "adaptation": adaptation, "unsupported_reason": why,
                "instrument": None if support == "unsupported" else "USD perpetual on the venue, 1x (long and short)",
            })
    return rows


@lru_cache(maxsize=1)
def library() -> tuple[dict, ...]:
    return tuple(_factory_rows() + _strategies_rows())


def by_id() -> dict[str, dict]:
    return {r["strategy_id"]: r for r in library()}


def pair_unsupported(row: dict, venue_symbol: str) -> str | None:
    """A strategy that runs in general but not on this one coin."""
    if row["base_id"] in BENCHMARK_STRATEGIES and venue_symbol == BENCHMARK_SYMBOL:
        return f"Relative strength needs a benchmark other than the asset itself ({BENCHMARK_SYMBOL} is the benchmark)."
    return None


def summary() -> dict:
    rows = library()
    out = {"strategies": len(rows), "factory": 0, "strategies_module": 0, "supported": 0, "adapted": 0,
           "unsupported": 0, "by_timeframe": {tf: 0 for tf in TIMEFRAMES}, "htf_window": HTF_WINDOW}
    for r in rows:
        out["factory" if r["library"] == "factory" else "strategies_module"] += 1
        out[r["support"]] += 1
        if r["timeframe"] in out["by_timeframe"]:
            out["by_timeframe"][r["timeframe"]] += 1
    return out
