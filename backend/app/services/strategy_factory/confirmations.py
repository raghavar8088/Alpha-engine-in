"""Composable confirmation predicates.

A confirmation never creates a trade — it can only veto one a detector has already
proposed. That separation is what keeps the library honest: the hypothesis lives in the
setup, and confirmations answer "is the context right for it?". Stacking three
indicators that all say the same thing adds no information, so the catalog pairs each
setup with confirmations that test a DIFFERENT dimension: participation (volume),
momentum (RSI/MACD), trend location (EMA/VWAP), trend strength (ADX), volatility (ATR),
or a higher timeframe.

Every predicate returns (passed, reason) so a rejected signal can say which condition
failed, and an accepted one can carry the evidence into the trade record.
"""

from __future__ import annotations

from typing import Callable, Optional

from strategy_service.indicators import (
    adx, atr as atr_series, ema, macd, rsi, session_vwap,
)

Result = tuple[bool, str]


def _closes(bars) -> list[float]:
    return [b.close for b in bars]


def volume_surge(bars, p, side: str, htf=None) -> Result:
    n = p.get("window", 20)
    mult = p.get("mult", 1.5)
    if len(bars) < n + 1:
        return False, "not enough bars for a volume average"
    avg = sum(b.volume for b in bars[-n - 1:-1]) / n
    cur = bars[-1].volume
    if avg <= 0:
        return False, "no volume data"
    ok = cur >= avg * mult
    return ok, f"volume {cur/avg:.1f}x the {n}-bar average (needs {mult}x)"


def rsi_side(bars, p, side: str, htf=None) -> Result:
    r = rsi(_closes(bars), p.get("period", 14))
    if not r:
        return False, "RSI unavailable"
    v = r[-1]
    if side == "BUY":
        ok = v >= p.get("long_min", 50)
        return ok, f"RSI {v:.1f} (needs >= {p.get('long_min', 50)} for longs)"
    ok = v <= p.get("short_max", 50)
    return ok, f"RSI {v:.1f} (needs <= {p.get('short_max', 50)} for shorts)"


def macd_agrees(bars, p, side: str, htf=None) -> Result:
    line, sig, _hist = macd(_closes(bars), p.get("fast", 12), p.get("slow", 26), p.get("signal", 9))
    if not line or not sig:
        return False, "MACD unavailable"
    up = line[-1] > sig[-1]
    ok = up if side == "BUY" else not up
    return ok, f"MACD {'above' if up else 'below'} signal"


def ema_trend(bars, p, side: str, htf=None) -> Result:
    """Price on the correct side of a trend EMA — location, not momentum."""
    e = ema(_closes(bars), p.get("period", 50))
    if not e:
        return False, "EMA unavailable"
    price = bars[-1].close
    above = price > e[-1]
    ok = above if side == "BUY" else not above
    return ok, f"price {'above' if above else 'below'} the {p.get('period', 50)} EMA"


def vwap_side(bars, p, side: str, htf=None) -> Result:
    vw = session_vwap(bars)
    if not vw:
        return False, "VWAP unavailable"
    above = bars[-1].close > vw[-1]
    ok = above if side == "BUY" else not above
    return ok, f"price {'above' if above else 'below'} session VWAP {vw[-1]:.2f}"


def adx_strength(bars, p, side: str, htf=None) -> Result:
    a, _pl, _mi = adx(bars, p.get("period", 14))
    if not a:
        return False, "ADX unavailable"
    ok = a[-1] >= p.get("min", 20)
    return ok, f"ADX {a[-1]:.1f} (needs >= {p.get('min', 20)})"


def atr_expanding(bars, p, side: str, htf=None) -> Result:
    """Volatility rising — a breakout into a contracting range usually fails."""
    a = atr_series(bars, p.get("period", 14))
    n = p.get("window", 20)
    if len(a) < n + 1:
        return False, "not enough ATR history"
    ok = a[-1] >= (sum(a[-n - 1:-1]) / n) * p.get("mult", 1.05)
    return ok, f"ATR {a[-1]:.4f} vs its {n}-bar mean"


def htf_trend(bars, p, side: str, htf=None) -> Result:
    """HIGHER-TIMEFRAME trend agreement — the multi-timeframe requirement.

    `htf` is the bar series of the confirmation timeframe, supplied by the engine. When
    it is absent the confirmation FAILS rather than passing silently: a strategy that
    advertises higher-timeframe confirmation must not trade blind when that timeframe is
    unavailable."""
    if not htf:
        return False, "higher-timeframe bars unavailable"
    e_fast = ema([b.close for b in htf], p.get("fast", 20))
    e_slow = ema([b.close for b in htf], p.get("slow", 50))
    if not e_fast or not e_slow:
        return False, "higher-timeframe EMAs unavailable"
    up = e_fast[-1] > e_slow[-1]
    ok = up if side == "BUY" else not up
    return ok, (f"{p.get('label', 'higher timeframe')} trend is "
                f"{'up' if up else 'down'} ({p.get('fast', 20)}/{p.get('slow', 50)} EMA)")


CONFIRMATIONS: dict[str, Callable] = {
    "volume": volume_surge,
    "rsi": rsi_side,
    "macd": macd_agrees,
    "ema_trend": ema_trend,
    "vwap": vwap_side,
    "adx": adx_strength,
    "atr_expansion": atr_expanding,
    "htf_trend": htf_trend,
}


def check_all(names_and_params: list[tuple[str, dict]], bars, side: str,
              htf=None) -> tuple[bool, list[str]]:
    """Every confirmation must pass. Returns (ok, reasons) — reasons are recorded on the
    signal when it passes and explain the veto when it does not."""
    reasons: list[str] = []
    for name, params in names_and_params or []:
        fn = CONFIRMATIONS.get(name)
        if fn is None:
            continue
        try:
            ok, why = fn(bars, params or {}, side, htf)
        except (IndexError, ValueError, ZeroDivisionError, TypeError, KeyError):
            return False, reasons + [f"{name}: evaluation failed"]
        reasons.append(why)
        if not ok:
            return False, reasons
    return True, reasons


__all__ = ["CONFIRMATIONS", "check_all"]
