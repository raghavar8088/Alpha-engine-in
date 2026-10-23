"""Phase 3 structures (AMENDMENT_A3.md): calendars, ratios, generic delta-hedged positions with an
optional hedge band, rolled strangles. Fill / fee / margin conventions as engine.run_trade."""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), os.path.join(HERE, "..", "..", "..", "shared")):
    sys.path.insert(0, p)
import b76  # noqa: E402
import engine as E  # noqa: E402
import engine2 as E2  # noqa: E402
from tradingai_shared.mcx_option_fees import mcx_option_leg  # noqa: E402


def _slip(px, tick, pct, mult=1.0):
    return max(tick, pct * px) * mult


def _leg_series(c, cp, k):
    i = E._row(c, cp, k)
    return None if i is None else (c.close[cp][i], c.traded[cp][i])


def _margin(family, F, mult, n_short):
    return n_short * E.SHORT_OPTION_FACTOR * E.MARGIN_RATE[family] * F * mult


def _result(c, j0, j1, legs_txt, credit, gross, fees, capital, reason="time", stale=0, extra=None):
    out = {"expiry": c.expiry, "entry": c.dates[j0], "exit": c.dates[j1], "reason": reason, "F0": c.F[j0],
           "straddle0": c.straddle[j0], "iv0": c.iv[j0], "rv0": c.rv20[j0], "legs": legs_txt, "credit": credit,
           "gross": gross, "fees": fees, "pnl": gross - fees, "capital": capital,
           "roc": (gross - fees) / capital if capital > 0 else np.nan, "stale_exit_legs": stale}
    out.update(extra or {})
    return out


# ---------------------------------------------------------------------------- calendars
def run_calendar(cf, cb, j0, kind, mult, family, tick, slip, texit):
    """Sell the front month at a strike, buy the next month at the SAME strike; exit at the front's
    expiry close (or texit days before), selling the back leg there too."""
    d0 = cf.dates[j0]
    if d0 not in cb.dates:
        return None
    jb0 = cb.dates.index(d0)
    if kind == "straddle":
        k = cf.katm[j0]
        types = ("CE", "PE")
    else:
        cp = "PE" if kind == "put" else "CE"
        k = E2.pick_delta(cf, cp, j0, 0.25)
        types = (cp,)
    if k is None or not np.isfinite(k):
        return None
    j1 = len(cf.dates) - 1 - texit
    if j1 <= j0 or cf.dates[j1] not in cb.dates:
        return None
    jb1 = cb.dates.index(cf.dates[j1])
    gross, fees, credit, paid, stale = 0.0, 0.0, 0.0, 0.0, 0
    for cp in types:
        fs, bs = _leg_series(cf, cp, k), _leg_series(cb, cp, k)
        if fs is None or bs is None or not fs[1][j0] or not bs[1][jb0]:
            return None
        sell_in = fs[0][j0] - _slip(fs[0][j0], tick, slip)
        buy_in = bs[0][jb0] + _slip(bs[0][jb0], tick, slip)
        if sell_in <= 0:
            return None
        buy_out = fs[0][j1] + _slip(fs[0][j1], tick, slip, 1.0 if fs[1][j1] else 3.0)
        sell_out = max(bs[0][jb1] - _slip(bs[0][jb1], tick, slip, 1.0 if bs[1][jb1] else 3.0), 0.0)
        stale += (not fs[1][j1]) + (not bs[1][jb1])
        gross += ((sell_in - buy_out) + (sell_out - buy_in)) * mult
        credit += (sell_in - buy_in) * mult
        paid += buy_in * mult
        fees += (mcx_option_leg(sell_in, mult, sell=True)["total"] + mcx_option_leg(buy_in, mult, sell=False)["total"]
                 + mcx_option_leg(buy_out, mult, sell=False)["total"]
                 + (mcx_option_leg(sell_out, mult, sell=True)["total"] if sell_out > 0 else 0))
    capital = _margin(family, cf.F[j0], mult, len(types)) + paid
    return _result(cf, j0, j1, f"cal{kind}@{k:g}", credit, gross, fees, capital, stale=stale)


# ---------------------------------------------------------------------------- ratios
def run_ratio(c, j0, cp, a, b, mult, family, tick, slip, sl):
    """Buy 1 at |delta| a, sell 2 at |delta| b (same type). Stop: loss >= sl x the short legs' entry premium."""
    kl, ks = E2.pick_delta(c, cp, j0, a), E2.pick_delta(c, cp, j0, b)
    if kl is None or ks is None or kl == ks:
        return None
    if (cp == "PE" and ks >= kl) or (cp == "CE" and ks <= kl):
        return None
    L, S = _leg_series(c, cp, kl), _leg_series(c, cp, ks)
    buy_in = L[0][j0] + _slip(L[0][j0], tick, slip)
    sell_in = S[0][j0] - _slip(S[0][j0], tick, slip)
    if sell_in <= 0:
        return None
    short_prem = 2 * sell_in
    entry_cash = 2 * sell_in - buy_in                       # may be negative: a debit
    last = len(c.dates) - 1
    j1, reason = last, "time"
    if sl is not None:
        for j in range(j0 + 1, last + 1):
            value_now = L[0][j] - 2 * S[0][j]               # what closing would bring in (before slippage)
            if entry_cash + value_now <= -sl * short_prem:
                j1, reason = j, "stop"
                break
    sell_out = max(L[0][j1] - _slip(L[0][j1], tick, slip, 1.0 if L[1][j1] else 3.0), 0.0)
    buy_out = S[0][j1] + _slip(S[0][j1], tick, slip, 1.0 if S[1][j1] else 3.0)
    gross = (entry_cash + sell_out - 2 * buy_out) * mult
    fees = (mcx_option_leg(buy_in, mult, sell=False)["total"] + mcx_option_leg(sell_in, 2 * mult, sell=True)["total"]
            + mcx_option_leg(buy_out, 2 * mult, sell=False)["total"]
            + (mcx_option_leg(sell_out, mult, sell=True)["total"] if sell_out > 0 else 0))
    capital = _margin(family, c.F[j0], mult, 2) + buy_in * mult
    return _result(c, j0, j1, f"ratio{cp}+1@{kl:g}-2@{ks:g}", entry_cash * mult, gross, fees, capital, reason,
                   stale=int(not L[1][j1]) + int(not S[1][j1]))


# ---------------------------------------------------------------------------- delta-hedged, generic
def run_dh(c, j0, strikes, lots, mult, family, tick, slip, band=1):
    """Short `lots` of each (cp, k) in `strikes`; hold round(sum of their deltas x lots) futures, re-hedged at
    a close only when the target differs from the hedge by >= `band` lots; everything closed at expiry."""
    series = []
    for cp, k in strikes:
        s = _leg_series(c, cp, k)
        if s is None or not s[1][j0]:
            return None
        series.append((cp, k, s[0], s[1]))
    last = len(c.dates) - 1
    sell_in = [cl[j0] - _slip(cl[j0], tick, slip) for _, _, cl, _ in series]
    if min(sell_in) <= 0:
        return None
    fees = sum(mcx_option_leg(x, mult * lots, sell=True)["total"] for x in sell_in)
    hedge, hpnl, max_h = 0, 0.0, 0
    for j in range(j0, last + 1):
        if j > j0 and np.isfinite(c.F[j]) and np.isfinite(c.F[j - 1]):
            hpnl += hedge * (c.F[j] - c.F[j - 1]) * mult
        if j == last:
            break
        F = c.F[j]
        if not np.isfinite(F):
            continue
        T = max((c.expiry - c.dates[j]).days, 0.5) / 365.0
        px = np.array([cl[j] for _, _, cl, _ in series])
        ks = np.array([k for _, k, _, _ in series])
        is_call = np.array([cp == "CE" for cp, _, _, _ in series])
        iv = b76.implied_vol(px, np.full(len(px), F), ks, np.full(len(px), T), is_call)
        if not np.isfinite(iv).all():
            continue
        dl = b76.delta(np.full(len(px), F), ks, np.full(len(px), T), iv, is_call)
        target = int(round(float(dl.sum()) * lots))
        if abs(target - hedge) >= band:
            ch = target - hedge
            fees += E2.fut_cost(abs(ch), F, mult, buy=ch > 0)
            hedge = target
            max_h = max(max_h, abs(hedge))
    if hedge and np.isfinite(c.F[last]):
        fees += E2.fut_cost(abs(hedge), c.F[last], mult, buy=hedge < 0)
    buy_out, stale = [], 0
    for _, _, cl, tr in series:
        buy_out.append(cl[last] + _slip(cl[last], tick, slip, 1.0 if tr[last] else 3.0))
        stale += 0 if tr[last] else 1
    fees += sum(mcx_option_leg(x, mult * lots, sell=False)["total"] for x in buy_out)
    opt = (sum(sell_in) - sum(buy_out)) * mult * lots
    margin = _margin(family, c.F[j0], mult, len(series)) * lots
    hedge_m = max_h * E.MARGIN_RATE[family] * c.F[j0] * mult
    legs = ";".join(f"S{lots}x{cp}{k:g}" for cp, k, _, _ in series) + f"+hedge(band{band})"
    return _result(c, j0, last, legs, sum(sell_in) * mult * lots, opt + hpnl, fees, margin + hedge_m, stale=stale,
                   extra={"max_hedge_lots": max_h})


# ---------------------------------------------------------------------------- rolled strangle
def run_roll(c, j0, d0, trig, max_rolls, mult, family, tick, slip):
    """Short strangle at |delta| d0; at any close where a short leg's |delta| > trig, buy it back and re-sell that
    side at d0 (if a strike qualifies). At most max_rolls rolls in total; everything closed at expiry."""
    last = len(c.dates) - 1
    open_legs, gross, fees, rolls, stale = {}, 0.0, 0.0, 0, 0
    for cp in ("CE", "PE"):
        k = E2.pick_delta(c, cp, j0, d0)
        if k is None:
            return None
        cl, tr = _leg_series(c, cp, k)
        fill = cl[j0] - _slip(cl[j0], tick, slip)
        if fill <= 0:
            return None
        open_legs[cp] = [k, fill]
        fees += mcx_option_leg(fill, mult, sell=True)["total"]
    credit0 = sum(v[1] for v in open_legs.values()) * mult
    for j in range(j0 + 1, last):
        if rolls >= max_rolls or not np.isfinite(c.F[j]):
            continue
        T = max((c.expiry - c.dates[j]).days, 0.5) / 365.0
        for cp in list(open_legs):
            k, fill = open_legs[cp]
            cl, tr = _leg_series(c, cp, k)
            iv = b76.implied_vol(np.array([cl[j]]), np.array([c.F[j]]), np.array([k]), np.array([T]), np.array([cp == "CE"]))
            if not np.isfinite(iv).all():
                continue
            dl = abs(float(b76.delta(np.array([c.F[j]]), np.array([k]), np.array([T]), iv, np.array([cp == "CE"]))[0]))
            if dl > trig and rolls < max_rolls:
                out = cl[j] + _slip(cl[j], tick, slip, 1.0 if tr[j] else 3.0)
                gross += (fill - out) * mult
                fees += mcx_option_leg(out, mult, sell=False)["total"]
                del open_legs[cp]
                rolls += 1
                k2 = E2.pick_delta(c, cp, j, d0)
                if k2 is not None:
                    cl2, _ = _leg_series(c, cp, k2)
                    f2 = cl2[j] - _slip(cl2[j], tick, slip)
                    if f2 > 0:
                        open_legs[cp] = [k2, f2]
                        fees += mcx_option_leg(f2, mult, sell=True)["total"]
    for cp, (k, fill) in open_legs.items():
        cl, tr = _leg_series(c, cp, k)
        out = cl[last] + _slip(cl[last], tick, slip, 1.0 if tr[last] else 3.0)
        stale += 0 if tr[last] else 1
        gross += (fill - out) * mult
        fees += mcx_option_leg(out, mult, sell=False)["total"]
    capital = _margin(family, c.F[j0], mult, 2)
    return _result(c, j0, last, f"roll d{d0} t{trig} rolls={rolls}", credit0, gross, fees, capital, stale=stale,
                   extra={"rolls": rolls})
