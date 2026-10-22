"""Black-76 (options on futures) - prices, implied volatility and delta, numpy only.

MCX crude and natural-gas options are European options on the same month's futures, so the
futures price is the forward and Black-76 is the textbook model. Only used for MEASURING
(implied vol, delta, the volatility risk premium); every backtest P&L uses traded prices.
"""
from __future__ import annotations

import math

import numpy as np

R = 0.065          # INR money-market rate; a month of discounting moves a premium ~0.5%


def erf(x):
    """Abramowitz & Stegun 7.1.26, |error| < 1.5e-7 - plenty for vol and delta."""
    x = np.asarray(x, dtype=float)
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
               + 0.254829592) * t * np.exp(-a * a)
    return s * y


def ncdf(x):
    return 0.5 * (1.0 + erf(np.asarray(x, dtype=float) / math.sqrt(2.0)))


def price(F, K, T, vol, is_call, r=R):
    F, K, T, vol = (np.asarray(v, dtype=float) for v in (F, K, T, vol))
    T = np.maximum(T, 1e-6)
    sd = vol * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    disc = np.exp(-r * T)
    call = disc * (F * ncdf(d1) - K * ncdf(d2))
    put = disc * (K * ncdf(-d2) - F * ncdf(-d1))
    return np.where(np.asarray(is_call, dtype=bool), call, put)


def implied_vol(px, F, K, T, is_call, r=R, lo=0.01, hi=6.0, iters=70):
    """Vectorised bisection. NaN where the price is below intrinsic or above the cap."""
    px, F, K, T = (np.asarray(v, dtype=float) for v in (px, F, K, T))
    is_call = np.asarray(is_call, dtype=bool)
    lo_a = np.full(px.shape, lo)
    hi_a = np.full(px.shape, hi)
    p_lo = price(F, K, T, lo_a, is_call, r)
    p_hi = price(F, K, T, hi_a, is_call, r)
    ok = (px > p_lo) & (px < p_hi)
    for _ in range(iters):
        mid = 0.5 * (lo_a + hi_a)
        p_mid = price(F, K, T, mid, is_call, r)
        up = p_mid < px
        lo_a = np.where(up, mid, lo_a)
        hi_a = np.where(up, hi_a, mid)
    out = 0.5 * (lo_a + hi_a)
    return np.where(ok, out, np.nan)


def delta(F, K, T, vol, is_call, r=R):
    F, K, T, vol = (np.asarray(v, dtype=float) for v in (F, K, T, vol))
    T = np.maximum(T, 1e-6)
    sd = vol * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sd * sd) / sd
    disc = np.exp(-r * T)
    return np.where(np.asarray(is_call, dtype=bool), disc * ncdf(d1), -disc * ncdf(-d1))


if __name__ == "__main__":
    # self-check: price -> implied vol round trip, and put-call parity
    F = np.array([100.0, 100.0, 9150.0, 330.0])
    K = np.array([90.0, 110.0, 9300.0, 300.0])
    T = np.array([30, 30, 21, 9]) / 365
    v = np.array([0.3, 0.45, 0.42, 0.85])
    c = price(F, K, T, v, True)
    p = price(F, K, T, v, False)
    assert np.allclose(implied_vol(c, F, K, T, True), v, atol=1e-6), implied_vol(c, F, K, T, True)
    assert np.allclose(implied_vol(p, F, K, T, False), v, atol=1e-6)
    assert np.allclose(c - p, np.exp(-R * T) * (F - K), atol=1e-8)
    assert abs(float(ncdf(1.959964)) - 0.975) < 2e-7
    print("b76 self-check ok", np.round(c, 4), np.round(p, 4))
