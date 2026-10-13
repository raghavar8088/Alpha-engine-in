"""The one premium model every BANKNIFTY replay uses (and bn_model_check.py validates).

A contract bought at epoch e on session k is priced off the PREVIOUS session's real smile for
that very expiry (bn_surface.py, from NSE closes) - so nothing from session k's own option
closes leaks into a trade on session k:
    F    = spot * exp(CARRY * calendar years to expiry)
    vol  = smile_{k-1}(ln K/F_{k-1}) - each strike keeps the previous close's vol (sticky strike) -
           floored at half the ATM vol, times (India VIX now / VIX at the previous close) ** 0.4,
           the ratio clamped to [0.5, 2]. Both choices calibrated on EXPLORE only (bn_calibrate.py).
    T    = variance-clock years (trading minutes + 0.2 session a night)
    price = Black-76, discounted at R.
"""

import gzip
import json
import math
import os
from bisect import bisect_left
from datetime import date

import bn_common as C


class Pricer:
    def __init__(self, vix: "C.Sessions | None" = None, spot: "C.Sessions | None" = None):
        with gzip.open(os.path.join(C.DATA, "surface.json.gz"), "rt") as f:
            raw = json.load(f)
        self.surf = {int(k): {int(e): v for e, v in s.items()} for k, s in raw.items()}
        self.sk = sorted(self.surf)
        self.vix = vix or C.Sessions("INDIAVIX", start=date(2015, 12, 1))
        self.spot = spot or C.Sessions("NIFTYBANK", start=date(2015, 6, 1))
        self._f_prev: dict = {}

    def forward_at_prev_close(self, kp: int, ek: int) -> float:
        """The forward at the anchor session's close - where a sticky-strike smile is read."""
        key = (kp, ek)
        if key not in self._f_prev:
            e = C.at(kp, C.CLOSE_MIN)
            S = self.spot.last_close(kp) or self.surf[kp][ek][6] or self.surf[kp][ek][0]
            self._f_prev[key] = S * math.exp(C.CARRY * C.T_cal(e, ek))
        return self._f_prev[key]

    def prev_session(self, k: int) -> int | None:
        i = bisect_left(self.sk, k) - 1
        return self.sk[i] if i >= 0 else None

    def monthlies(self, k: int) -> list[int]:
        kp = self.prev_session(k)
        return sorted(self.surf[kp]) if kp is not None else []

    def contract_for(self, k: int, min_left: int = C.MIN_SESSIONS_LEFT) -> tuple[int, int] | None:
        """(expiry, anchor session): the nearest monthly with >= min_left sessions left."""
        kp = self.prev_session(k)
        if kp is None:
            return None
        for ek in sorted(self.surf[kp]):
            if C.trading_sessions_left(k, ek) >= min_left:
                return ek, kp
        return None

    def vol(self, e: int, S: float, K: float, ek: int, kp: int) -> float:
        row = self.surf[kp][ek]
        a, b, c = row[2], row[3], row[4]
        F = self.forward_at_prev_close(kp, ek) if C.SMILE == "strike" else S * math.exp(C.CARRY * C.T_cal(e, ek))
        x = math.log(K / F)
        iv = max(a + b * x + c * x * x, 0.5 * a)
        v_now, v_prev = self.vix.close_before(e), self.vix.last_close(kp)
        if v_now and v_prev:
            iv *= min(2.0, max(0.5, v_now / v_prev)) ** C.VIX_BETA
        return iv

    def premium(self, e: int, S: float, K: float, call: bool, ek: int, kp: int) -> float:
        Tc = C.T_cal(e, ek)
        F = S * math.exp(C.CARRY * Tc)
        return C.b76(F, K, C.T_years(e, ek), self.vol(e, S, K, ek, kp), call, math.exp(-C.R * Tc))
