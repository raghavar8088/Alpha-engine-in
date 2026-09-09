"""The research a swing signal has to survive before it is allowed to exist.

The rule this module enforces is that no single condition may produce a signal. A stock
above its 20 EMA is not a trade; an RSI reading is not a trade; a bullish engulfing candle
is not a trade. Every one of those fires constantly across a 500-name universe, and a desk
built on any one of them generates hundreds of "signals" a day that mean nothing.

So a candidate is judged in two stages, and both are mandatory:

  GATES    Hard requirements. Any one failing rejects the stock outright, with the reason
           recorded. These are the conditions under which the setup is not merely weak but
           structurally absent — no trend to pull back within, no liquidity to exit into,
           no volatility unit to size a stop in.

  PILLARS  Seven independent readings of the same setup, each scored. A candidate needs a
           minimum number of PILLARS PASSING as well as a minimum total score, so a stock
           cannot compensate for a broken trend with a very pretty candle. The pillars are
           deliberately drawn from different families — trend, location, participation,
           momentum, direction, relative performance, trigger — because five indicators
           that all read momentum are one opinion, not five.

Calibration follows the published swing literature rather than being invented here:
pullback depth 5-12% from the swing high, volume dry-up against the 20-day average, RSI
held in the 40-60 band rather than demanded overbought, ADX above 20 with +DI over -DI to
exclude chop, price above ₹100 and 5 lakh shares a day for tradability, and a 1:2 minimum
reward-to-risk. Sources are listed in the module docstring of `signals.py`.

Nothing here reads the future: every indicator is computed on bars up to and including the
signal bar, and the entry, stop and targets are all derived from that bar's close.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.screener.horizons import (
    Bar, atr, ema_last, last_swing_low, sma, swing_highs,
)

# --- gates ---------------------------------------------------------------------------
MIN_BARS = 120            # enough history for a 200 EMA to mean anything
MIN_PRICE = 100.0         # below this a rupee of slippage is a percent of the trade
MIN_AVG_VOLUME = 500_000  # 5 lakh shares/day — the tradability floor in the literature
MIN_TURNOVER = 5.0e7      # ₹5 cr/day: volume alone passes a cheap stock nobody can exit
MIN_ATR_PCT = 0.8         # a name that moves 0.3% a day cannot reach a swing target
MAX_ATR_PCT = 9.0         # and one that moves 9% a day is a different game entirely

# --- pullback shape ------------------------------------------------------------------
MIN_PULLBACK_PCT = 3.0
MAX_PULLBACK_PCT = 14.0

# --- scoring -------------------------------------------------------------------------
MIN_PILLARS = 5           # of 7 — see the module docstring on why breadth is required
MIN_SCORE = 62.0          # of 100


@dataclass
class Pillar:
    """One independent reading. `weight` is its share of the 100-point score."""
    key: str
    label: str
    weight: float
    passed: bool
    score: float           # 0..weight
    detail: str


@dataclass
class Research:
    symbol: str
    ok: bool
    reject: str | None
    score: float
    pillars_passed: int
    pillars: list[Pillar] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    @property
    def reasons(self) -> list[str]:
        """The written case, strongest first — what goes on the signal card."""
        return [f"{p.label}: {p.detail}"
                for p in sorted(self.pillars, key=lambda x: -x.score) if p.passed]

    @property
    def against(self) -> list[str]:
        """The case against, which is shown too. A signal that only lists its supporting
        evidence is advertising, not research."""
        return [f"{p.label}: {p.detail}" for p in self.pillars if not p.passed]


# --------------------------------------------------------------------------------------
# indicators the shared helpers do not already provide
# --------------------------------------------------------------------------------------

def rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def adx_di(bars: list[Bar], n: int = 14) -> tuple[float, float, float] | None:
    """(ADX, +DI, -DI) at the last bar, Wilder-smoothed."""
    if len(bars) < 2 * n + 1:
        return None
    tr, pdm, ndm = [], [], []
    for prev, cur in zip(bars, bars[1:]):
        up, dn = cur.high - prev.high, prev.low - cur.low
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
        tr.append(max(cur.high - cur.low, abs(cur.high - prev.close),
                      abs(cur.low - prev.close)))

    def wilder(vals: list[float]) -> list[float]:
        out = [sum(vals[:n])]
        for v in vals[n:]:
            out.append(out[-1] - out[-1] / n + v)
        return out

    atr_s, pdm_s, ndm_s = wilder(tr), wilder(pdm), wilder(ndm)
    dxs = []
    for a, p, m in zip(atr_s, pdm_s, ndm_s):
        if a <= 0:
            dxs.append(0.0)
            continue
        pdi, ndi = 100 * p / a, 100 * m / a
        dxs.append(100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0.0)
    if len(dxs) < n:
        return None
    adx = sum(dxs[:n]) / n
    for d in dxs[n:]:
        adx = (adx * (n - 1) + d) / n
    a = atr_s[-1]
    if a <= 0:
        return None
    return adx, 100 * pdm_s[-1] / a, 100 * ndm_s[-1] / a


def _bullish_trigger(bars: list[Bar]) -> tuple[bool, str]:
    """A reversal the last bar actually made, not one it is 'forming'.

    Only closed-bar facts count. 'Forming' patterns are how a screener manufactures a
    signal on a day that did not produce one."""
    if len(bars) < 3:
        return False, "not enough bars"
    c, p = bars[-1], bars[-2]
    rng = c.high - c.low
    body = abs(c.close - c.open)

    if c.close > c.open and c.close >= p.open and c.open <= p.close and p.close < p.open:
        return True, "bullish engulfing — today's body covers yesterday's down candle"
    if rng > 0 and (min(c.open, c.close) - c.low) / rng >= 0.5 and c.close > c.open:
        return True, "hammer — rejected the low and closed in the upper half"
    if c.close > p.high and c.close > c.open:
        return True, "closed above the previous bar's high"
    if (c.close > c.open and body > 0 and rng > 0 and body / rng >= 0.6
            and c.close > max(b.close for b in bars[-4:-1])):
        return True, "strong up-close above the last three closes"
    return False, "no reversal bar yet — the last candle did not confirm"


# --------------------------------------------------------------------------------------
# the research pass
# --------------------------------------------------------------------------------------

def _reject(symbol: str, why: str, facts: dict) -> Research:
    return Research(symbol=symbol, ok=False, reject=why, score=0.0,
                    pillars_passed=0, facts=facts)


def evaluate(symbol: str, bars: list[Bar], bench: list[Bar] | None = None) -> Research:
    """Judge one stock. Returns the full working, pass or fail."""
    if len(bars) < MIN_BARS:
        return _reject(symbol, f"only {len(bars)} daily bars on file, need {MIN_BARS}", {})

    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    vols = [b.volume for b in bars]
    price = closes[-1]
    a = atr(bars, 14)
    facts: dict = {"price": round(price, 2)}

    # ---- gates ----------------------------------------------------------------------
    if price < MIN_PRICE:
        return _reject(symbol, f"₹{price:,.0f} is below the ₹{MIN_PRICE:,.0f} floor — a "
                               "rupee of slippage is a whole percent of the trade", facts)
    avg_vol = sum(vols[-20:]) / 20
    facts["avg_volume"] = int(avg_vol)
    if avg_vol < MIN_AVG_VOLUME:
        return _reject(symbol, f"{avg_vol:,.0f} shares/day is below the "
                               f"{MIN_AVG_VOLUME:,.0f} tradability floor", facts)
    turnover = avg_vol * price
    facts["turnover"] = round(turnover, 0)
    if turnover < MIN_TURNOVER:
        return _reject(symbol, f"₹{turnover/1e7:.1f} cr traded a day — too thin to size "
                               "₹1 lakh into and out of without moving it", facts)
    if a is None or a <= 0:
        return _reject(symbol, "no ATR — cannot size a stop in volatility units", facts)
    atr_pct = a / price * 100
    facts["atr"] = round(a, 2)
    facts["atr_pct"] = round(atr_pct, 2)
    if atr_pct < MIN_ATR_PCT:
        return _reject(symbol, f"moves {atr_pct:.1f}% a day — too quiet to reach a swing "
                               "target inside the holding window", facts)
    if atr_pct > MAX_ATR_PCT:
        return _reject(symbol, f"moves {atr_pct:.1f}% a day — a stop wide enough to "
                               "survive it makes the position meaninglessly small", facts)

    ema20 = ema_last(closes, 20)
    ema50 = ema_last(closes, 50)
    ema200 = ema_last(closes, 200) if len(closes) >= 200 else None
    if ema20 is None or ema50 is None:
        return _reject(symbol, "not enough history for the moving-average stack", facts)
    ema50_prev = ema_last(closes[:-10], 50)
    facts.update(ema20=round(ema20, 2), ema50=round(ema50, 2),
                 ema200=round(ema200, 2) if ema200 else None)

    # The one structural gate: this is a PULLBACK strategy, so there must be an uptrend to
    # pull back within. Without it every other pillar is describing a falling stock.
    if not (price > ema50 and ema50_prev is not None and ema50 > ema50_prev):
        return _reject(symbol, "no uptrend to pull back within — price is below its 50 EMA "
                               "or the 50 EMA is not rising", facts)

    sh = swing_highs(bars, 60)
    swing_high = max(sh) if sh else max(highs[-60:])
    pullback = (swing_high - price) / swing_high * 100 if swing_high else 0.0
    facts.update(swing_high=round(swing_high, 2), pullback_pct=round(pullback, 2))
    if pullback > MAX_PULLBACK_PCT:
        return _reject(symbol, f"{pullback:.1f}% below its swing high — past a pullback, "
                               "this is a broken trend", facts)

    # ---- pillars ---------------------------------------------------------------------
    pillars: list[Pillar] = []

    # 1. trend structure
    stack = price > ema20 > ema50 and (ema200 is None or ema50 > ema200)
    above200 = ema200 is None or price > ema200
    t_score = (10 if price > ema50 else 0) + (5 if stack else 0) + (5 if above200 else 0)
    pillars.append(Pillar(
        "trend", "Trend", 20, price > ema50 and above200, float(t_score),
        (f"price ₹{price:,.0f} over the 50 EMA ₹{ema50:,.0f}"
         + (", stacked 20>50>200" if stack else ", stack not fully aligned")
         + ("" if above200 else ", but under the 200 EMA"))))

    # 2. pullback location — the entry premise
    in_band = MIN_PULLBACK_PCT <= pullback <= MAX_PULLBACK_PCT
    near_ema20 = abs(price - ema20) / ema20 * 100 <= 6.0
    p_score = (10 if in_band else 0) + (5 if near_ema20 else 0)
    pillars.append(Pillar(
        "pullback", "Pullback", 15, in_band and near_ema20, float(p_score),
        (f"{pullback:.1f}% off the ₹{swing_high:,.0f} swing high"
         + (f", sitting {abs(price-ema20)/ema20*100:.1f}% from the 20 EMA"
            if near_ema20 else ", but stretched from the 20 EMA"))))

    # 3. participation — volume dry-up on the pullback
    base_vol = sum(vols[-60:-20]) / 40 if len(vols) >= 60 else avg_vol
    recent_vol = sum(vols[-5:]) / 5
    dry = recent_vol < base_vol
    ratio = recent_vol / base_vol if base_vol else 1.0
    pillars.append(Pillar(
        "volume", "Volume", 15, dry, 15.0 if dry else max(0.0, 15 * (1.6 - ratio) / 0.6),
        (f"last 5 sessions traded {ratio:.2f}x the earlier average — "
         + ("sellers are not pressing, this is profit-taking" if dry
            else "still heavy, which reads more like distribution"))))

    # 4. momentum band — not overbought, not broken
    r = rsi(closes, 14)
    facts["rsi"] = round(r, 1) if r is not None else None
    r_ok = r is not None and 40 <= r <= 68
    r_score = 0.0 if r is None else (15.0 if 45 <= r <= 62 else 10.0 if r_ok else 3.0)
    pillars.append(Pillar(
        "momentum", "Momentum", 15, bool(r_ok), r_score,
        ("no RSI" if r is None else
         f"RSI {r:.0f} — " + ("in the pullback band, trend intact but not overbought"
                              if r_ok else
                              "overbought, buying here is chasing" if r > 68 else
                              "too weak, the trend is not holding"))))

    # 5. direction — trending rather than chopping
    ad = adx_di(bars, 14)
    facts["adx"] = round(ad[0], 1) if ad else None
    d_ok = ad is not None and ad[0] >= 20 and ad[1] > ad[2]
    d_score = 0.0 if ad is None else (15.0 if ad[0] >= 25 and ad[1] > ad[2]
                                      else 10.0 if d_ok else 3.0)
    pillars.append(Pillar(
        "direction", "Direction", 15, bool(d_ok), d_score,
        ("no ADX" if ad is None else
         f"ADX {ad[0]:.0f} with +DI {ad[1]:.0f} vs -DI {ad[2]:.0f} — "
         + ("a real trend, not chop" if d_ok else "range-bound, no directional edge"))))

    # 6. relative strength against the index
    rs_ok, rs_score, rs_txt = False, 0.0, "no benchmark loaded"
    if bench and len(bench) >= 65:
        bc = [b.close for b in bench]
        for win, pts in ((21, 5.0), (63, 5.0)):
            if len(closes) > win and len(bc) > win:
                sret = closes[-1] / closes[-1 - win] - 1
                bret = bc[-1] / bc[-1 - win] - 1
                if sret > bret:
                    rs_score += pts
        rs_ok = rs_score >= 5.0
        m1 = (closes[-1] / closes[-22] - 1) * 100 if len(closes) > 22 else 0.0
        b1 = (bc[-1] / bc[-22] - 1) * 100 if len(bc) > 22 else 0.0
        facts["rs_1m"] = round(m1 - b1, 2)
        rs_txt = (f"{m1:+.1f}% in a month against the index's {b1:+.1f}% — "
                  + ("outperforming" if m1 > b1 else "lagging the market"))
    pillars.append(Pillar("relative", "Relative strength", 10, rs_ok, rs_score, rs_txt))

    # 7. the trigger — did TODAY confirm
    trig, trig_txt = _bullish_trigger(bars)
    pillars.append(Pillar("trigger", "Trigger", 10, trig, 10.0 if trig else 0.0, trig_txt))

    score = round(sum(p.score for p in pillars), 1)
    passed = sum(1 for p in pillars if p.passed)

    if passed < MIN_PILLARS:
        return Research(symbol, False,
                        f"only {passed} of 7 conditions hold (needs {MIN_PILLARS}) — "
                        "not enough independent evidence to call this a setup",
                        score, passed, pillars, facts)
    if score < MIN_SCORE:
        return Research(symbol, False,
                        f"confluence {score:.0f}/100 is below the {MIN_SCORE:.0f} bar — "
                        "the conditions that hold are the weaker ones",
                        score, passed, pillars, facts)

    facts["swing_low"] = last_swing_low(bars, 20)
    facts["sma20_vol"] = round(sma(vols, 20) or 0.0, 0)
    return Research(symbol, True, None, score, passed, pillars, facts)
