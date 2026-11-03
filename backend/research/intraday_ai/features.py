"""Point-in-time features of one signal, computed from the context the rule itself read.

Everything here is known at the signal bar's close: `ctx` holds only closed bars (the rules'
own guarantee). Signed features are multiplied by the trade's side, so "+" always means "in the
trade's direction". The outcome fields come from the backtest's simulated trade (pessimistic
reading, measured costs) and are the labels — never inputs.
"""
from __future__ import annotations

from datetime import timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_OPEN_MIN = 9 * 60 + 15
SIX = ["iv2_donchian_45m", "iv2_donchian_1h", "iv2_vwap_trend_1h", "iv2_macd_trend_1h",
       "iv2_rsi_momentum_45m", "iv2_bollinger_snap_1h"]     # the rules with a real edge before costs


def _r(x, nd: int = 6):
    return None if x is None else round(float(x), nd)


def _pct(a, b):
    return (a - b) / b if a is not None and b else None


def extract(spec, sig, ctx, t_signal: int, tr) -> dict:
    s, i, s15, j, j0 = ctx.s, ctx.i, ctx.s15, ctx.j, ctx.j0
    px = s15.c[j]
    side = 0 if getattr(sig, "oco", None) else (1 if sig.side == "BUY" else -1)
    now = ctx.now.astimezone(IST)
    day_hi, day_lo = max(s15.h[j0:j + 1]), min(s15.l[j0:j + 1])
    vwap = ctx.vwap[-1] if ctx.vwap else None
    stop_dist = sig.stop_dist if sig.stop_price is None else abs(sig.entry - sig.stop_price)
    tgt_dist = (abs(sig.target_price - sig.entry) if sig.target_price is not None else sig.target_dist)
    back5 = max(0, j0 - 1 - 4 * 25)                    # ~5 sessions back (25 bars a session)
    f = {
        "sid": spec.strategy_id, "family": spec.family, "tf": spec.tf, "kind": spec.kind, "sym": ctx.symbol,
        "t": int(t_signal), "day": now.date().isoformat(), "dow": now.weekday(),
        "mins": now.hour * 60 + now.minute - SESSION_OPEN_MIN, "side": side,
        # the signal itself (raw, for re-simulating other fills)
        "entry": _r(sig.entry), "stop_dist": _r(stop_dist), "target_dist": _r(sig.target_dist),
        "target_price": _r(sig.target_price), "stop_price": _r(sig.stop_price), "trigger": _r(sig.trigger),
        "max_bars": sig.max_bars, "prio": _r(sig.priority),
        # shape of the trade, as fractions of price
        "stop_pct": _r(stop_dist / px if px else None), "tgt_pct": _r(tgt_dist / px if px and tgt_dist else None),
        "rr": _r(tgt_dist / stop_dist if tgt_dist and stop_dist else None, 3),
        "atr_pct": _r(ctx.atr / px if px else None), "atr_day_pct": _r(ctx.atr_day / px if ctx.atr_day and px else None),
        # where the stock is today, signed by side
        "day_ret": _r(side * (_pct(px, ctx.day_open) or 0.0)) if ctx.day_open else None,
        "gap": _r(side * (_pct(ctx.day_open, ctx.prev_close) or 0.0)) if ctx.day_open and ctx.prev_close else None,
        "vwap_dist": _r(side * (_pct(px, vwap) or 0.0)) if vwap else None,
        "range_pos": _r(((px - day_lo) / (day_hi - day_lo) if side >= 0 else (day_hi - px) / (day_hi - day_lo))
                        if day_hi > day_lo else None, 3),
        "day_range_pct": _r((day_hi - day_lo) / px if px else None),
        "or_range_pct": _r((ctx.or_high - ctx.or_low) / px if ctx.or_high and ctx.or_low and px else None),
        "pdh_dist": _r(side * (_pct(px, ctx.pdh) or 0.0)) if ctx.pdh else None,
        "pdl_dist": _r(side * (_pct(px, ctx.pdl) or 0.0)) if ctx.pdl else None,
        "bar_ret": _r(side * (_pct(s.c[i], s.o[i]) or 0.0)),
        "ret_3": _r(side * (_pct(s.c[i], s.c[i - 3]) or 0.0)) if i >= 3 else None,
        "ret_5d": _r(side * (_pct(px, s15.c[back5]) or 0.0)) if j0 > 0 else None,
        # participation and the market
        "rvol": _r(ctx.rvol, 4), "rvol_rank": ctx.rvol_rank,
        "nifty": _r(side * ctx.nifty_ret if ctx.nifty_ret is not None else None, 4),
        "nifty_raw": _r(ctx.nifty_ret, 4),
    }
    if tr is not None:
        notional = tr[5] * tr[7]
        f.update({"filled": 1, "entry_t": tr[2], "exit_t": tr[3], "ep": tr[5], "xp": tr[6], "qty": tr[7],
                  "gross": tr[8], "fees": tr[9], "net": tr[10], "reason": tr[11],
                  "gross_bp": _r(tr[8] / notional * 1e4, 3) if notional else None,
                  "net_bp": _r(tr[10] / notional * 1e4, 3) if notional else None,
                  "hold_min": round((tr[3] - tr[2]) / 60)})
    else:
        f["filled"] = 0
    return f
