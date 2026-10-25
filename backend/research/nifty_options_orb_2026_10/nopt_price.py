"""The premium model every check and the backtest use (as ../banknifty_2026_10/bn_price.py).

A NIFTY option bought at epoch e on session k is priced off the PREVIOUS session's real smile for
that very expiry (nopt_surface.py, from NSE closes), so nothing from session k's own option prices
leaks into a trade on session k:
    F     = NIFTY now * exp(CARRY * calendar years to expiry)
    vol   = smile_{k-1}(ln K / F_{k-1}): each strike keeps the previous close's vol (sticky strike),
            floored at half the ATM vol, times (India VIX now / VIX at the previous close) ** beta,
            the ratio clamped to [0.5, 2]; beta and the smile rule from nopt_calibrate.py
    T     = variance-clock years (trading minutes + 0.2 session a night)
    price = Black-76, discounted at R.
"""

from __future__ import annotations

import gzip
import json
import math
from bisect import bisect_left
from datetime import date

import numpy as np

import nopt_common as C


class Pricer:
    def __init__(self, beta: float | None = None, smile: str | None = None):
        cal = C.RES / "calibration.json"
        chosen = json.load(open(cal))["chosen"] if cal.exists() else {}
        self.beta = beta if beta is not None else chosen.get("beta", C.VIX_BETA)
        self.smile = smile or chosen.get("smile", C.SMILE)
        with gzip.open(C.DATA / "surface.json.gz", "rt") as f:
            raw = json.load(f)
        self.surf = {int(k): {int(e): v for e, v in s.items()} for k, s in raw.items()}
        self.sk = sorted(self.surf)
        z = np.load(C.DATA / "minutes.npz")
        self.days = [C.dk(date.fromisoformat(str(d))) for d in z["days"]]
        self.row = {k: i for i, k in enumerate(self.days)}
        self.vix = z["vix"]
        self.vix_last = {}
        for k, i in self.row.items():
            v = self.vix[i][~np.isnan(self.vix[i])]
            if len(v):
                self.vix_last[k] = float(v[-1])

    def anchor(self, k: int, ek: int, max_back: int = 5) -> int | None:
        """The latest session before k whose surface holds expiry ek (normally k-1)."""
        i = bisect_left(self.sk, k) - 1
        for j in range(i, max(-1, i - max_back), -1):
            if ek in self.surf[self.sk[j]]:
                return self.sk[j]
        return None

    def vix_at(self, e: int) -> float | None:
        """India VIX at the last complete minute before e."""
        k = C.dkey(e)
        i = self.row.get(k)
        if i is None:
            return None
        m = C.minute_of_day(e) - C.OPEN_MIN - 1
        if m < 0:
            return None
        m = min(m, self.vix.shape[1] - 1)
        v = self.vix[i, m]
        return None if np.isnan(v) else float(v)

    def vol(self, e: int, S: float, K: float, ek: int, kp: int, vix_now: float | None = None) -> float:
        F_kp, _, a, b, c = self.surf[kp][ek][:5]
        F_ref = F_kp if self.smile == "strike" else S * math.exp(C.CARRY * C.T_cal(e, ek))
        x = math.log(K / F_ref)
        iv = max(a + b * x + c * x * x, 0.5 * a)
        v_now = vix_now if vix_now is not None else self.vix_at(e)
        v_prev = self.vix_last.get(kp)
        if v_now and v_prev and self.beta:
            iv *= min(2.0, max(0.5, v_now / v_prev)) ** self.beta
        return iv

    def premium(self, e: int, S: float, K: float, call: bool, ek: int, kp: int, vix_now: float | None = None) -> float:
        Tc = C.T_cal(e, ek)
        F = S * math.exp(C.CARRY * Tc)
        return C.b76(F, K, C.T_years(e, ek), self.vol(e, S, K, ek, kp, vix_now), call, math.exp(-C.R * Tc))
