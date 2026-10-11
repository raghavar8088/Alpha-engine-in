"""Gold strategy lab: the strategy families, each with a reason it could work and a fixed grid.

A family is `fn(params, ctx) -> target positions` (decided at each day's close; gl_engine executes
them at the next open). Every indicator here is CAUSAL — the value at day t uses data up to day t
only, and drivers that print after gold's close arrive lagged a day (gl_data.driver). Grids are
fixed before a round runs and every variant is registered, whether it passes or not: the
deflated Sharpe ratio is computed against all of them.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from gl_data import driver, load
from gl_engine import DAYS, Market


# ── context: one traded instrument plus what a rule may read ────────────────────


@dataclass
class Ctx:
    m: Market
    cache: dict = field(default_factory=dict)

    @property
    def close(self) -> pd.Series:
        return pd.Series(self.m.close, index=self.m.dates)

    @property
    def high(self) -> pd.Series:
        return pd.Series(self.m.high, index=self.m.dates)

    @property
    def low(self) -> pd.Series:
        return pd.Series(self.m.low, index=self.m.dates)

    def ret(self) -> pd.Series:
        return np.log(self.close).diff()

    def vol(self, L: int) -> pd.Series:
        """Annualised realised vol of daily log returns through day t."""
        k = ("vol", L)
        if k not in self.cache:
            self.cache[k] = self.ret().rolling(L, min_periods=max(10, L // 2)).std() * math.sqrt(DAYS)
        return self.cache[k]

    def drv(self, name: str, col: str = "close", lag: int = 1) -> pd.Series:
        k = ("drv", name, col, lag)
        if k not in self.cache:
            self.cache[k] = driver(name, col=col, lag=lag, on=self.m.dates)
        return self.cache[k]

    def leg(self, name: str) -> Market:
        """Another traded instrument, on this calendar (for multi-leg rules)."""
        k = ("leg", name)
        if k not in self.cache:
            from gl_engine import market
            self.cache[k] = market(name, on=self.m.dates)
        return self.cache[k]

    def leg_close(self, name: str) -> pd.Series:
        """A leg's close as of day t — usable at t only for instruments that close with gold
        (the US-listed ETFs); everything else goes through `drv` (lagged)."""
        lg = self.leg(name)
        return pd.Series(lg.close, index=lg.dates)


def _vol_size(ctx: Ctx, raw: pd.Series, target_vol: float | None, L: int = 63, cap: float = 1.5) -> np.ndarray:
    if not target_vol:
        return raw.fillna(0).to_numpy(float)
    w = (target_vol / ctx.vol(L)).clip(upper=cap)
    return (raw * w).fillna(0).to_numpy(float)


def _mode(sig: pd.Series, mode: str) -> pd.Series:
    """sig in {-1, 0, +1}: long_short keeps it, long_flat drops the shorts, short_flat the longs."""
    if mode == "long_flat":
        return sig.clip(lower=0)
    if mode == "short_flat":
        return sig.clip(upper=0)
    return sig


# ── round 1 families ─────────────────────────────────────────────────────────────


def tsmom(p: dict, ctx: Ctx) -> np.ndarray:
    """Time-series momentum (Moskowitz, Ooi & Pedersen 2012): the sign of the past L-day return.
    Why: slow information diffusion and hedging pressure make futures returns autocorrelated at
    1-12 months, and gold is one of the assets in their sample."""
    c = ctx.close
    sig = np.sign(np.log(c / c.shift(p["L"])))
    return _vol_size(ctx, _mode(sig, p["mode"]), p.get("tv"))


def ma_trend(p: dict, ctx: Ctx) -> np.ndarray:
    """Price above / below its L-day mean (single) or fast mean above / below slow (dual).
    Why: the classic trend filter; Faber (2007) for the 200-day version across asset classes."""
    c = ctx.close
    if p.get("fast"):
        sig = np.sign(c.rolling(p["fast"]).mean() - c.rolling(p["slow"]).mean())
    else:
        sig = np.sign(c - c.rolling(p["L"]).mean())
    return _vol_size(ctx, _mode(sig, p["mode"]), p.get("tv"))


def donchian(p: dict, ctx: Ctx) -> np.ndarray:
    """Turtle-style channel breakout: enter on a close beyond the prior L-day high / low, exit on
    a close beyond the prior M-day opposite extreme. Why: the same trend premium, with a rule
    that holds winners and cuts losers."""
    c, h, lo = ctx.m.close, ctx.high, ctx.low
    hi_L = h.rolling(p["L"]).max().shift(1).to_numpy()
    lo_L = lo.rolling(p["L"]).min().shift(1).to_numpy()
    hi_M = h.rolling(p["M"]).max().shift(1).to_numpy()
    lo_M = lo.rolling(p["M"]).min().shift(1).to_numpy()
    pos = np.zeros(len(c))
    cur = 0.0
    for t in range(len(c)):
        if not (hi_L[t] == hi_L[t]):
            continue
        if cur > 0 and c[t] < lo_M[t]:
            cur = 0.0
        elif cur < 0 and c[t] > hi_M[t]:
            cur = 0.0
        if cur == 0:
            if c[t] > hi_L[t]:
                cur = 1.0
            elif c[t] < lo_L[t] and p["mode"] == "long_short":
                cur = -1.0
        pos[t] = cur
    return pos


def vol_managed(p: dict, ctx: Ctx) -> np.ndarray:
    """Always long, sized by target vol / recent vol (Moreira & Muir 2017). Why: vol clusters but
    returns do not rise with it, so cutting exposure in turbulent spells raises the Sharpe ratio."""
    w = (p["tv"] / ctx.vol(p["L"])).clip(upper=p["cap"])
    return w.fillna(0).to_numpy(float)


def reversal(p: dict, ctx: Ctx) -> np.ndarray:
    """After a day beyond k sigma, take the opposite side (or the same side: 'cont') for H days.
    Why: liquidity-driven overshoots revert (overreaction); or news is under-reacted to (drift)."""
    r = ctx.ret().to_numpy()
    sd = (ctx.vol(63) / math.sqrt(DAYS)).shift(1).to_numpy()
    pos = np.zeros(len(r))
    left, side = 0, 0.0
    for t in range(len(r)):
        if sd[t] == sd[t] and r[t] == r[t] and abs(r[t]) > p["k"] * sd[t]:
            side = -np.sign(r[t]) if p["dir"] == "rev" else np.sign(r[t])
            left = p["H"]
        if left > 0:
            pos[t] = side
            left -= 1
    return pos


def dollar_filter(p: dict, ctx: Ctx) -> np.ndarray:
    """Long gold while the dollar index has FALLEN over L days (lagged a day). Why: gold is priced
    in dollars and trades as the dollar's mirror; a falling dollar trend is gold's tailwind."""
    d = ctx.drv("DXY")
    sig = -np.sign(np.log(d / d.shift(p["L"])))
    return _mode(sig, p["mode"]).fillna(0).to_numpy(float)


def real_yield_filter(p: dict, ctx: Ctx) -> np.ndarray:
    """Long gold while TIPS have RISEN over L days (real yields falling; lagged a day). Why: gold
    pays nothing, so its opportunity cost is the real rate (Erb & Harvey 2013)."""
    tip = ctx.drv("TIP", col="adj_close")
    sig = np.sign(np.log(tip / tip.shift(p["L"])))
    return _mode(sig, p["mode"]).fillna(0).to_numpy(float)


def turn_of_month(p: dict, ctx: Ctx) -> np.ndarray:
    """Long over the last `pre` and first `post` sessions of each month. Why: month-end flows
    (Lakonishok & Smidt 1988; Etula et al. 2020 on month-end funding pressure)."""
    d = ctx.m.dates
    month = d.year * 12 + d.month
    s = pd.Series(np.arange(len(d)), index=d)
    pos_in_month = s.groupby(month).cumcount().to_numpy()
    size = s.groupby(month).transform("size").to_numpy()
    from_end = size - 1 - pos_in_month
    # the target is decided at a close and held over the NEXT session: hold for sessions
    # [-pre .. post-1] around the turn => target set on the session BEFORE each of them
    hold = (from_end < p["pre"]) | (pos_in_month < p["post"])
    tgt = np.r_[hold[1:], False].astype(float)
    return tgt


def high_52w(p: dict, ctx: Ctx) -> np.ndarray:
    """Long while within x of the 52-week high (George & Hwang 2004). Why: anchoring — traders
    under-react near the high, so prices there keep drifting."""
    c = ctx.close
    near = c >= (1 - p["x"]) * c.rolling(252, min_periods=200).max()
    return near.astype(float).to_numpy()


def gvz_trend(p: dict, ctx: Ctx) -> np.ndarray:
    """TSMOM(126) only in the chosen implied-vol regime (GVZ vs its 1-year median, lagged).
    Why: trend signals may be cleaner when uncertainty is high (or low)."""
    c = ctx.close
    sig = np.sign(np.log(c / c.shift(126)))
    g = ctx.drv("GVZ")
    med = g.rolling(252, min_periods=120).median()
    on = (g >= med) if p["regime"] == "high" else (g < med)
    return (sig * on).fillna(0).to_numpy(float)


# ── round 2 families ─────────────────────────────────────────────────────────────


def trend_ensemble(p: dict, ctx: Ctx) -> np.ndarray:
    """The average of TSMOM signs at 1, 3, 6 and 12 months (Hurst, Ooi & Pedersen 2017's
    'diversified trend'): one noisy lookback is replaced by their consensus."""
    c = ctx.close
    sig = sum(np.sign(np.log(c / c.shift(L))) for L in (21, 63, 126, 252)) / 4.0
    if p["mode"] == "long_flat":
        sig = sig.clip(lower=0)
    return _vol_size(ctx, sig, p.get("tv"))


def gsr_reversion(p: dict, ctx: Ctx) -> dict:
    """Gold/silver ratio mean reversion, dollar-neutral (0.5 gold vs 0.5 silver). Why: the two
    metals share drivers, so a stretched ratio tends to close; enter beyond z, exit at z = 0 or
    after 126 sessions. Both legs are US-listed ETFs closing with gold, so day t's close is usable."""
    g, s = ctx.close, ctx.leg_close("SLV")
    lr = np.log(g / s).where(s > 0)
    z = ((lr - lr.rolling(p["L"]).mean()) / lr.rolling(p["L"]).std()).to_numpy()
    side = np.zeros(len(z))
    cur, age = 0.0, 0
    for t in range(len(z)):
        if z[t] != z[t]:
            cur, age = 0.0, 0
        else:
            if cur != 0:
                age += 1
                if (cur < 0 and z[t] <= 0) or (cur > 0 and z[t] >= 0) or age >= 126:
                    cur, age = 0.0, 0
            if cur == 0:
                if z[t] > p["z"]:
                    cur, age = -1.0, 0          # ratio high: gold rich vs silver -> short gold, long silver
                elif z[t] < -p["z"]:
                    cur, age = 1.0, 0
        side[t] = cur
    return {"GLD": 0.5 * side, "SLV": -0.5 * side}


def gsr_trend(p: dict, ctx: Ctx) -> dict:
    """Gold/silver ratio momentum: long gold / short silver while the ratio has risen over L days.
    Why: the ratio rises in risk-off phases (gold's haven role) and those phases persist."""
    g, s = ctx.close, ctx.leg_close("SLV")
    lr = np.log(g / s).where(s > 0)
    side = np.sign(lr - lr.shift(p["L"])).fillna(0).to_numpy()
    return {"GLD": 0.5 * side, "SLV": -0.5 * side}


def safe_haven(p: dict, ctx: Ctx) -> np.ndarray:
    """After an S&P 500 day beyond -k sigma (lagged a day), long gold for H sessions. Why:
    flight-to-quality flows into gold arrive over days after an equity shock (Baur & Lucey 2010)."""
    spx = ctx.drv("SPX")
    r = np.log(spx / spx.shift(1))
    sd = r.rolling(63, min_periods=30).std().shift(1)
    shock = (r < -p["k"] * sd).to_numpy()
    pos = np.zeros(len(shock))
    left = 0
    for t in range(len(shock)):
        if shock[t]:
            left = p["H"]
        if left > 0:
            pos[t] = 1.0
            left -= 1
    return pos


def vix_regime(p: dict, ctx: Ctx) -> np.ndarray:
    """Long gold while the VIX (lagged) sits above its 1-year q-quantile: hold the haven when fear
    is high, stand aside when it is low."""
    v = ctx.drv("VIX")
    thr = v.rolling(252, min_periods=120).quantile(p["q"])
    return (v >= thr).astype(float).where(thr.notna(), 0.0).to_numpy()


def copper_gold(p: dict, ctx: Ctx) -> np.ndarray:
    """Long gold while the copper / gold ratio has FALLEN over L days (lagged). Why: a falling
    copper/gold ratio prices slowing growth and falling real rates — gold's macro tailwind."""
    cu = ctx.drv("HG")
    au = ctx.drv("GC")
    ratio = np.log(cu / au)
    sig = -np.sign(ratio - ratio.shift(p["L"]))
    return _mode(sig, p["mode"]).fillna(0).to_numpy(float)


def oil_inflation(p: dict, ctx: Ctx) -> np.ndarray:
    """Long gold while crude has RISEN over L days (lagged): rising oil feeds inflation
    expectations, gold's oldest driver."""
    o = ctx.drv("CL")
    sig = np.sign(np.log(o.where(o > 0) / o.where(o > 0).shift(p["L"])))
    return _mode(sig, p["mode"]).fillna(0).to_numpy(float)


def trend_plus_shock(p: dict, ctx: Ctx) -> np.ndarray:
    """Round 1's two best near-misses combined: TSMOM(126) long/flat at 15% target vol, plus the
    5-day continuation after a 2.5-sigma day, capped at 1.5x."""
    a = tsmom({"L": 126, "mode": "long_flat", "tv": 0.15}, ctx)
    b = reversal({"k": 2.5, "H": 5, "dir": "cont"}, ctx)
    return np.clip(a * p["w_trend"] + b * p["w_shock"], -1.5, 1.5)


# ── round 3 families ─────────────────────────────────────────────────────────────


def dual_momentum(p: dict, ctx: Ctx) -> np.ndarray:
    """Antonacci's dual momentum on gold: long while gold's L-day return beats cash and (if
    `rel`) the S&P 500's over the same span (lagged). Why: capital rotates to the asset class
    that is winning; gold is held only when it is the leader."""
    c = ctx.close
    rg = np.log(c / c.shift(p["L"]))
    rf_l = (ctx.drv("IRX") / 100.0 * p["L"] / 252.0).fillna(0)
    ok = rg > rf_l
    if p["rel"]:
        spx = ctx.drv("SPX")
        ok &= rg > np.log(spx / spx.shift(p["L"]))
    return ok.astype(float).where(rg.notna(), 0.0).to_numpy()


def miners_lead(p: dict, ctx: Ctx) -> np.ndarray:
    """Gold miners (GDX) outperforming gold over L days is read as a lead (equity investors price
    the metal's outlook first). GDX closes with GLD, so day t's close is usable."""
    g, m = ctx.close, ctx.leg_close("GDX")
    rel = np.log((m / g).where(m > 0))
    sig = np.sign(rel - rel.shift(p["L"]))
    return _mode(sig, p["mode"]).fillna(0).to_numpy(float)


def metals_breadth(p: dict, ctx: Ctx) -> np.ndarray:
    """A commodity-wide trend: count of positive 6-month trends among gold (own close), silver,
    platinum, palladium and copper (futures, lagged). Long gold at >= `n` of 5; short at <= 5-n
    when long_short. Why: a broad metals bull is a monetary / inflation regime, gold's best."""
    c = ctx.close
    votes = np.sign(np.log(c / c.shift(126))).fillna(0)
    for name in ("SI", "PL", "PA", "HG"):
        s = ctx.drv(name)
        votes = votes + np.sign(np.log(s.where(s > 0) / s.where(s > 0).shift(126))).fillna(0)
    up = (votes + 5) / 2                       # number of the 5 trending up
    sig = (up >= p["n"]).astype(float)
    if p["mode"] == "long_short":
        sig = sig - (up <= 5 - p["n"]).astype(float)
    return sig.to_numpy()


def capitulation(p: dict, ctx: Ctx) -> np.ndarray:
    """Buy gold after a forced-selling sell-off: its 20-day return below -k (20-day-scaled)
    sigma while fear (VIX, lagged) is in its top quintile; hold H sessions. Why: in liquidity
    crises gold is sold to meet margin calls, then recovers (2008, 2013, March 2020)."""
    c = ctx.close
    r20 = np.log(c / c.shift(20))
    sd20 = ctx.vol(252) * math.sqrt(20 / DAYS)
    v = ctx.drv("VIX")
    fear = v >= v.rolling(252, min_periods=120).quantile(0.8)
    trig = ((r20 < -p["k"] * sd20) & fear).to_numpy()
    pos = np.zeros(len(trig))
    left = 0
    for t in range(len(trig)):
        if trig[t]:
            left = p["H"]
        if left > 0:
            pos[t] = 1.0
            left -= 1
    return pos


def _shock_hold(sig_side: np.ndarray, H: int) -> np.ndarray:
    pos = np.zeros(len(sig_side))
    left, side = 0, 0.0
    for t in range(len(sig_side)):
        if sig_side[t] != 0:
            side, left = sig_side[t], H
        if left > 0:
            pos[t] = side
            left -= 1
    return pos


def volume_shock(p: dict, ctx: Ctx) -> np.ndarray:
    """Shock continuation only when GLD traded at least m x its 50-day median volume that day.
    Why: a big move on heavy volume is information arriving, not noise."""
    r = ctx.ret()
    sd = (ctx.vol(63) / math.sqrt(DAYS)).shift(1)
    vol = load("GLD")["volume"].reindex(ctx.m.dates)
    heavy = vol >= p["m"] * vol.rolling(50, min_periods=30).median().shift(1)
    side = (np.sign(r) * ((r.abs() > p["k"] * sd) & heavy)).fillna(0).to_numpy()
    return _shock_hold(side, p["H"])


def shock_with_trend(p: dict, ctx: Ctx) -> np.ndarray:
    """Shock continuation only when the shock agrees with the 6-month trend."""
    c = ctx.close
    r = ctx.ret()
    sd = (ctx.vol(63) / math.sqrt(DAYS)).shift(1)
    trend = np.sign(np.log(c / c.shift(126)))
    hit = (r.abs() > p["k"] * sd) & (np.sign(r) == trend)
    side = (np.sign(r) * hit).fillna(0).to_numpy()
    return _shock_hold(side, p["H"])


def gap_cont(p: dict, ctx: Ctx) -> np.ndarray:
    """After an overnight gap beyond k sigma (Asian / London news, known by day t's close), hold in
    its direction for H sessions. Why: overseas news is under-reacted to in New York."""
    g = pd.Series(ctx.m.gap, index=ctx.m.dates)
    sd = g.rolling(63, min_periods=30).std().shift(1)
    side = (np.sign(g) * (g.abs() > p["k"] * sd)).fillna(0).to_numpy()
    return _shock_hold(side, p["H"])


def trend_vol_brake(p: dict, ctx: Ctx) -> np.ndarray:
    """TSMOM(126) long/flat at 15% target vol, switched off while 21-day vol is above its 1-year
    q-quantile. Why: trend rules give back most in turbulent reversals."""
    base = tsmom({"L": 126, "mode": "long_flat", "tv": 0.15}, ctx)
    v = ctx.vol(21)
    calm = (v <= v.rolling(252, min_periods=120).quantile(p["q"])).to_numpy()
    return base * calm


def multi_signal(p: dict, ctx: Ctx) -> np.ndarray:
    """An equal-weight blend fixed in advance: diversified trend (long/flat, 15% vol) + 2-sigma
    shock continuation (5 days) [+ turn of month], capped at 1.5x."""
    a = trend_ensemble({"mode": "long_flat", "tv": 0.15}, ctx)
    b = reversal({"k": 2.0, "H": 5, "dir": "cont"}, ctx)
    parts = [a, b]
    if p["tom"]:
        parts.append(turn_of_month({"pre": 2, "post": 3}, ctx))
    return np.clip(sum(parts) / len(parts) * p["scale"], -1.5, 1.5)


# ── round 4 families ─────────────────────────────────────────────────────────────


def autumn_effect(p: dict, ctx: Ctx) -> np.ndarray:
    """Baur (2013, 'The autumn effect of gold'): gold's returns are significantly positive in
    September and November (1981-2010). Pre-registered from the paper: long in those months only.
    2011 onwards is out of sample for the claim."""
    d = ctx.m.dates
    nxt = np.r_[d[1:].month, d[-1].month]          # the session the target is held over
    return np.isin(nxt, p["months"]).astype(float)


def trend_pullback(p: dict, ctx: Ctx) -> np.ndarray:
    """In an uptrend (6-month return > 0), buy after a 3-day drop beyond k (3-day-scaled) sigma;
    hold H sessions. Why: dips inside a trend are liquidity, not information."""
    c = ctx.close
    up = np.log(c / c.shift(126)) > 0
    r3 = np.log(c / c.shift(3))
    sd3 = ctx.vol(63) * math.sqrt(3 / DAYS)
    trig = (up & (r3 < -p["k"] * sd3)).to_numpy()
    side = trig.astype(float)
    return _shock_hold(side, p["H"])


def rsi2(p: dict, ctx: Ctx) -> np.ndarray:
    """Connors' RSI(2) pullback: above the 200-day mean, buy when RSI(2) < lo, exit when > 70."""
    c = ctx.close
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).to_numpy()
    above = (c > c.rolling(200).mean()).to_numpy()
    pos = np.zeros(len(c))
    cur = 0.0
    for t in range(len(c)):
        if cur > 0 and rsi[t] > 70:
            cur = 0.0
        if cur == 0 and above[t] and rsi[t] < p["lo"]:
            cur = 1.0
        pos[t] = cur
    return pos


def weekly_tsmom(p: dict, ctx: Ctx) -> np.ndarray:
    """TSMOM decided on the last session of each week and held for the week (lower turnover)."""
    c = ctx.close
    sig = np.sign(np.log(c / c.shift(p["W"] * 5))).clip(lower=0)
    sized = pd.Series(_vol_size(ctx, sig, 0.15), index=ctx.m.dates)
    wk = ctx.m.dates.to_period("W")
    last = pd.Series(wk, index=ctx.m.dates) != pd.Series(wk, index=ctx.m.dates).shift(-1)
    return sized.where(last).ffill().fillna(0).to_numpy()


def shock_scaled(p: dict, ctx: Ctx) -> np.ndarray:
    """Shock continuation sized by the shock: |z| / k units (capped), held H sessions."""
    r = ctx.ret()
    sd = (ctx.vol(63) / math.sqrt(DAYS)).shift(1)
    z = (r / sd).fillna(0).to_numpy()
    pos = np.zeros(len(z))
    left, size = 0, 0.0
    for t in range(len(z)):
        if abs(z[t]) > p["k"]:
            size, left = np.sign(z[t]) * min(abs(z[t]) / p["k"], p["cap"]), p["H"]
        if left > 0:
            pos[t] = size
            left -= 1
    return pos


def volume_breakout(p: dict, ctx: Ctx) -> np.ndarray:
    """A close at a new L-day high on >= 1.5x median volume: long for 10 sessions."""
    c, h = ctx.close, ctx.high
    vol = load("GLD")["volume"].reindex(ctx.m.dates)
    heavy = vol >= 1.5 * vol.rolling(50, min_periods=30).median().shift(1)
    trig = ((c > h.rolling(p["L"]).max().shift(1)) & heavy).to_numpy().astype(float)
    return _shock_hold(trig, 10)


def breakeven(p: dict, ctx: Ctx) -> np.ndarray:
    """Long gold while breakeven inflation is rising: TIPS (TIP) beating nominal Treasuries (IEF)
    over L days, lagged a day. Why: gold's oldest role is the inflation hedge."""
    tip, ief = ctx.drv("TIP", col="adj_close"), ctx.drv("IEF", col="adj_close")
    rel = np.log(tip / ief)
    sig = np.sign(rel - rel.shift(p["L"]))
    return _mode(sig, p["mode"]).fillna(0).to_numpy(float)


# ── round 5 families ─────────────────────────────────────────────────────────────


def range_expansion(p: dict, ctx: Ctx) -> np.ndarray:
    """A wide-range day (high - low > k x the 20-day average range) that closes in its top / bottom
    quarter: hold in that direction H sessions. Why: a wide bar closing at an extreme is buyers
    (sellers) in control — the bar-shape version of shock continuation."""
    h, lo, c = ctx.high, ctx.low, ctx.close
    rng = h - lo
    avg = rng.rolling(20, min_periods=10).mean().shift(1)
    wide = rng > p["k"] * avg
    pos_in = ((c - lo) / rng.replace(0, np.nan)).fillna(0.5)
    side = (wide & (pos_in >= 0.75)).astype(float) - (wide & (pos_in <= 0.25)).astype(float)
    return _shock_hold(side.to_numpy(), p["H"])


def macro_residual(p: dict, ctx: Ctx) -> np.ndarray:
    """Fade gold's deviation from its macro fair value: GLD's daily return regressed (rolling 126
    sessions) on the dollar (UUP), real yields (TIP) and stocks (S&P 500) — all closing with GLD —
    and the 20-day sum of residuals z-scored; short above +z0, long below -z0, for H sessions."""
    g = ctx.ret()
    X = pd.concat({n: np.log(ctx.leg_close(n) / ctx.leg_close(n).shift(1)) for n in ("UUP", "TIP", "SPX")}, axis=1)
    df = pd.concat([g.rename("g"), X], axis=1)
    W = 126
    resid = np.full(len(df), np.nan)
    arr = df.to_numpy()
    for t in range(W, len(df)):
        win = arr[t - W + 1:t + 1]
        ok = ~np.isnan(win).any(axis=1)
        if ok.sum() < W * 0.8:
            continue
        y, xm = win[ok, 0], np.column_stack([np.ones(ok.sum()), win[ok, 1:]])
        beta = np.linalg.lstsq(xm, y, rcond=None)[0]
        if not np.isnan(arr[t]).any():
            resid[t] = arr[t, 0] - np.r_[1.0, arr[t, 1:]] @ beta
    rs = pd.Series(resid, index=df.index)
    cum = rs.rolling(20, min_periods=15).sum()
    z = (cum / (rs.rolling(126, min_periods=60).std() * math.sqrt(20))).to_numpy()
    side = np.where(z > p["z0"], -1.0, np.where(z < -p["z0"], 1.0, 0.0))
    side = np.nan_to_num(side)
    return _shock_hold(side, p["H"])


def gsr_short(p: dict, ctx: Ctx) -> dict:
    """Short-horizon gold/silver spread reversion: z over L sessions beyond 2, exit at 0 or after
    20 sessions; dollar-neutral 0.5 / 0.5."""
    g, s = ctx.close, ctx.leg_close("SLV")
    lr = np.log(g / s).where(s > 0)
    z = ((lr - lr.rolling(p["L"]).mean()) / lr.rolling(p["L"]).std()).to_numpy()
    side = np.zeros(len(z))
    cur, age = 0.0, 0
    for t in range(len(z)):
        if z[t] != z[t]:
            cur, age = 0.0, 0
        else:
            if cur != 0:
                age += 1
                if (cur < 0 and z[t] <= 0) or (cur > 0 and z[t] >= 0) or age >= 20:
                    cur, age = 0.0, 0
            if cur == 0:
                if z[t] > p["z"]:
                    cur, age = -1.0, 0
                elif z[t] < -p["z"]:
                    cur, age = 1.0, 0
        side[t] = cur
    return {"GLD": 0.5 * side, "SLV": -0.5 * side}


def shock_stop(p: dict, ctx: Ctx) -> np.ndarray:
    """Shock continuation held up to 10 sessions, cut early when the trade's close-to-close
    P&L since entry falls below -1 daily sigma (a stop on closes)."""
    r = ctx.ret().fillna(0).to_numpy()
    sd = (ctx.vol(63) / math.sqrt(DAYS)).shift(1).to_numpy()
    pos = np.zeros(len(r))
    side, left, pnl = 0.0, 0, 0.0
    for t in range(len(r)):
        if side != 0:
            pnl += side * r[t]
            if pnl < -sd[t]:
                side, left = 0.0, 0
        if sd[t] == sd[t] and abs(r[t]) > p["k"] * sd[t]:
            side, left, pnl = np.sign(r[t]), 10, 0.0
        if left > 0 and side != 0:
            pos[t] = side
            left -= 1
        else:
            side = 0.0
    return pos


FAMILIES = {
    "range_expansion": range_expansion, "macro_residual": macro_residual, "gsr_short": gsr_short,
    "shock_stop": shock_stop,
    "autumn_effect": autumn_effect, "trend_pullback": trend_pullback, "rsi2": rsi2,
    "weekly_tsmom": weekly_tsmom, "shock_scaled": shock_scaled, "volume_breakout": volume_breakout,
    "breakeven": breakeven,
    "dual_momentum": dual_momentum, "miners_lead": miners_lead, "metals_breadth": metals_breadth,
    "capitulation": capitulation, "volume_shock": volume_shock, "shock_with_trend": shock_with_trend,
    "gap_cont": gap_cont, "trend_vol_brake": trend_vol_brake, "multi_signal": multi_signal,
    "tsmom": tsmom, "ma_trend": ma_trend, "donchian": donchian, "vol_managed": vol_managed,
    "reversal": reversal, "dollar_filter": dollar_filter, "real_yield_filter": real_yield_filter,
    "turn_of_month": turn_of_month, "high_52w": high_52w, "gvz_trend": gvz_trend,
    "trend_ensemble": trend_ensemble, "gsr_reversion": gsr_reversion, "gsr_trend": gsr_trend,
    "safe_haven": safe_haven, "vix_regime": vix_regime, "copper_gold": copper_gold,
    "oil_inflation": oil_inflation, "trend_plus_shock": trend_plus_shock,
}

# ── the grid of round 1 (fixed before it ran) ────────────────────────────────────


def _grid(**axes) -> list[dict]:
    keys = list(axes)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(axes[k] for k in keys))]


ROUND1: list[tuple[str, dict]] = (
    [("tsmom", p) for p in _grid(L=[21, 63, 126, 252], mode=["long_short", "long_flat"], tv=[None, 0.15])]
    + [("ma_trend", p) for p in _grid(L=[50, 100, 200], mode=["long_short", "long_flat"])]
    + [("ma_trend", p) for p in _grid(fast=[20, 50], slow=[100, 200], mode=["long_short", "long_flat"])
       if p["fast"] < p["slow"] and (p["fast"], p["slow"]) in ((20, 100), (50, 200))]
    + [("donchian", p) for p in _grid(L=[20, 55, 100], mode=["long_short", "long_flat"])
       for p in [{**p, "M": {20: 10, 55: 20, 100: 50}[p["L"]]}]]
    + [("vol_managed", p) for p in _grid(L=[21, 63], cap=[1.0, 1.5], tv=[0.15])]
    + [("reversal", p) for p in _grid(k=[2.0, 2.5], H=[1, 5], dir=["rev", "cont"])]
    + [("dollar_filter", p) for p in _grid(L=[21, 63], mode=["long_short", "long_flat"])]
    + [("real_yield_filter", p) for p in _grid(L=[21, 63], mode=["long_short", "long_flat"])]
    + [("turn_of_month", {"pre": 2, "post": 3})]
    + [("high_52w", p) for p in _grid(x=[0.05, 0.10])]
    + [("gvz_trend", p) for p in _grid(regime=["high", "low"])]
)


ROUND2: list[tuple[str, dict]] = (
    [("reversal", p) for p in _grid(k=[2.0, 2.5, 3.0], H=[3, 10, 20], dir=["cont"])]
    + [("reversal", {"k": 3.0, "H": 5, "dir": "cont"})]
    + [("trend_ensemble", p) for p in _grid(mode=["long_short", "long_flat"], tv=[None, 0.15])]
    + [("gsr_reversion", p) for p in _grid(L=[63, 126, 252], z=[1.5, 2.0])]
    + [("gsr_trend", p) for p in _grid(L=[63, 126, 252])]
    + [("safe_haven", p) for p in _grid(k=[2.0, 2.5], H=[5, 10])]
    + [("vix_regime", p) for p in _grid(q=[0.5, 0.8])]
    + [("copper_gold", p) for p in _grid(L=[63, 126], mode=["long_short", "long_flat"])]
    + [("oil_inflation", p) for p in _grid(L=[63, 126], mode=["long_flat"])]
    + [("trend_plus_shock", p) for p in _grid(w_trend=[1.0], w_shock=[0.5, 1.0])]
)


ROUND3: list[tuple[str, dict]] = (
    [("dual_momentum", p) for p in _grid(L=[126, 252], rel=[False, True])]
    + [("miners_lead", p) for p in _grid(L=[5, 21, 63], mode=["long_short", "long_flat"])]
    + [("metals_breadth", p) for p in _grid(n=[3, 4], mode=["long_flat"])]
    + [("metals_breadth", {"n": 4, "mode": "long_short"})]
    + [("capitulation", p) for p in _grid(k=[1.5, 2.0], H=[10, 20])]
    + [("volume_shock", p) for p in _grid(k=[2.0, 2.5], m=[1.5, 2.0], H=[5])]
    + [("shock_with_trend", p) for p in _grid(k=[2.0, 2.5], H=[5, 10])]
    + [("gap_cont", p) for p in _grid(k=[2.0, 3.0], H=[3, 5])]
    + [("trend_vol_brake", p) for p in _grid(q=[0.8, 0.9])]
    + [("multi_signal", p) for p in _grid(tom=[False, True], scale=[1.5])]
)


ROUND4: list[tuple[str, dict]] = (
    [("autumn_effect", {"months": [9, 11]})]
    + [("trend_pullback", p) for p in _grid(k=[1.0, 1.5], H=[5, 10])]
    + [("rsi2", p) for p in _grid(lo=[5, 10])]
    + [("weekly_tsmom", p) for p in _grid(W=[13, 26, 52])]
    + [("shock_scaled", p) for p in _grid(k=[2.0, 2.5], H=[5], cap=[2.0])]
    + [("volume_breakout", p) for p in _grid(L=[20, 55])]
    + [("breakeven", p) for p in _grid(L=[21, 63], mode=["long_flat", "long_short"])]
)


ROUND5: list[tuple[str, dict]] = (
    [("range_expansion", p) for p in _grid(k=[1.5, 2.0], H=[3, 5])]
    + [("macro_residual", p) for p in _grid(z0=[1.5, 2.0], H=[5, 10])]
    + [("gsr_short", p) for p in _grid(L=[20, 40], z=[2.0])]
    + [("shock_stop", p) for p in _grid(k=[2.0, 2.5])]
)


def variant_key(family: str, p: dict) -> str:
    return family + "|" + ",".join(f"{k}={p[k]}" for k in sorted(p))
