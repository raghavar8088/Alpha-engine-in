"""Intraday Stocks v2 — strategies that decide on REAL intraday bars.

WHAT CHANGED FROM THE FIRST CATALOG (intraday_strategies.py, still used by Live Intraday)
The first catalog's "intraday" strategies decided on DAILY bars plus one live quote, with
daily-ATR targets: 9.6% of its trades reached target, all 150 strategies fired in the first
minute of the session, and the tournament lost Rs 21 lakh gross before costs over four
sessions (audit 2026-10-02). Every rule here reads closed 15m / 45m / 1h bars of the
liquid universe from `intraday_store`, sizes its stop and target in THAT timeframe's ATR,
and is evaluated once, at the close of each of its bars.

THE SESSION RULES (enforced by the engine, stated here because they shape the rules)
- No entries before 09:45. The first half hour is where the old desk bled most (429
  trades, Rs -18.75 lakh gross), and it is when spreads and the opening auction's noise
  are widest. The 30-minute opening range (09:15–09:45) becomes INFORMATION instead.
- No entries at or after 14:30; flat by 15:05 in closing-auction stocks, 15:12 in others.
- Two-sided: shorts are MIS intraday shorts, allowed in every EQ-series stock.
- Trend families trade only WITH the market's direction on the day (NIFTY's return since
  the open — the "market intraday momentum" effect of Gao, Han, Li & Zhou). The paper's
  own trade, holding the index through the last half hour, cannot be taken in NSE cash
  since the closing auction began (CAS stocks stop continuous trading at 15:15 and Angel
  squares MIS at 15:10), so the effect is used as a direction filter instead.
- Mean-reversion families skip names that are "in play" (relative volume high): fading a
  stock that the whole market is trading is fading information, not noise.

THE CATALOG: 16 bar families x 3 timeframes, plus 4 day-level setups = 52 strategies.
Deliberately not 150: every extra strategy raises the bar the promotion gate must set
against luck (Bonferroni over N), and the old catalog's 150 were ~30 ideas with parameter
variants that mostly measured the same thing.

DAY-LEVEL SETUPS
- ORB on stocks in play (Zarattini, Barbon & Aziz 2024): the 20 highest-relative-volume
  names at 09:45, a STOP ENTRY at the 30-minute range's high (if that range closed up) or
  low (if it closed down), stop at a fraction of the 14-session ATR, held to the close.
  Two stop sizes: the paper's 10% of ATR and a wider 25%.
- Gap-and-go and gap-fade on the 09:45 read.

Every function returns a V2Signal or None and never looks past the last closed bar it is
handed; the engine and the Phase 3 backtest call the same functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.services.nifty_scalp_strategies import (Series, adx_di, atr, cci, ema, macd, rsi,
                                                 sma, stdev, stoch, supertrend)

IST = timezone(timedelta(hours=5, minutes=30))
TF_SECONDS = {"15m": 900, "45m": 2700, "1h": 3600}
MAX_BARS = {"15m": 8, "45m": 4, "1h": 3}       # time stop: ~2-3 hours, never past the close
ENTRY_FROM, ENTRY_UNTIL = "09:45", "14:30"


@dataclass(frozen=True)
class V2Spec:
    strategy_id: str
    name: str
    family: str
    tf: str                 # "15m" | "45m" | "1h" | "day"
    kind: str               # trend | reversion | breakout | orb | gap
    category: str           # momentum | mean_reversion  (both square off same day)
    rationale: str
    params: dict = field(default_factory=dict)
    max_hold_days: int = 0

    # Read by the tournament's /strategies route, written for the first catalog.
    @property
    def timeframe(self) -> str:
        return "day (15m data)" if self.tf == "day" else self.tf

    @property
    def risk_pct(self) -> float:
        return 1.0 / SLOTS_PER_STRATEGY


SLOTS_PER_STRATEGY = 5     # concurrent positions per strategy; each takes 1/5 of its capital


@dataclass
class V2Signal:
    side: str                       # "BUY" | "SELL"
    entry: float                    # reference price: the signal bar's close (or trigger)
    stop_dist: float                # absolute price distance to the stop
    target_dist: float | None       # absolute distance to the target, or None (time/EOD exit)
    max_bars: int                   # time stop in bars of the strategy's timeframe (0 = EOD)
    priority: float                 # ranks competing signals when slots are scarce
    rationale: str
    trigger: float | None = None    # stop-entry level (ORB): fill only once price crosses it
    target_price: float | None = None  # absolute target (VWAP, mean) when the rule has one


@dataclass
class Ctx:
    symbol: str
    tf: str
    now: datetime
    s: Series                  # closed bars of `tf`, oldest first (prior sessions included)
    i0: int                    # index in `s` of today's first bar (len(s) if none yet)
    s15: Series                # closed 15m bars (for VWAP, opening range, day stats)
    j0: int                    # index in `s15` of today's first bar
    atr: float                 # ATR(14) of `tf`
    atr_day: float | None      # 14-session daily ATR (from 15m bars)
    vwap: list[float]          # session VWAP after each of today's 15m bars
    prev_close: float | None
    pdh: float | None
    pdl: float | None
    day_open: float | None
    or_high: float | None      # 09:15-09:45 range (two 15m bars)
    or_low: float | None
    or_open: float | None
    or_close: float | None
    rvol: float | None         # relative volume, today's closed 15m bars vs 14 sessions
    rvol_rank: int | None      # 1 = most in play in the universe right now
    nifty_ret: float | None    # NIFTY % change since today's open, as of `now`
    avg_vol: float | None = None


# ── context ──────────────────────────────────────────────────────────────────────


def _day(stamp) -> object:
    return datetime.fromisoformat(str(stamp)).date()


_DAY_CACHE: dict[int, object] = {}


def _epoch_day(epoch: int):
    k = (epoch + 19800) // 86400
    d = _DAY_CACHE.get(k)
    if d is None:
        d = _DAY_CACHE[k] = datetime.fromtimestamp(k * 86400, timezone.utc).date()
    return d


def today_index(s: Series, day) -> int:
    ep = getattr(s, "epochs", None)
    if ep is not None:
        from bisect import bisect_left
        start = int(datetime(day.year, day.month, day.day, tzinfo=IST).timestamp())
        return bisect_left(ep, start)
    for i in range(len(s) - 1, -1, -1):
        if _day(s.ts[i]) != day:
            return i + 1
    return 0


def session_vwap(s15: Series, j0: int) -> list[float]:
    out, pv, vv = [], 0.0, 0.0
    for i in range(j0, len(s15)):
        tp = (s15.h[i] + s15.l[i] + s15.c[i]) / 3
        pv += tp * s15.v[i]; vv += s15.v[i]
        out.append(pv / vv if vv else s15.c[i])
    return out


def daily_atr(s15: Series, day, n: int = 14) -> float | None:
    days: dict = {}
    order = []
    ep = getattr(s15, "epochs", None)
    for i in range(len(s15)):
        d = _epoch_day(ep[i]) if ep is not None else _day(s15.ts[i])
        if d >= day:
            break
        if d not in days:
            days[d] = [s15.h[i], s15.l[i], s15.c[i]]
            order.append(d)
        else:
            x = days[d]; x[0] = max(x[0], s15.h[i]); x[1] = min(x[1], s15.l[i]); x[2] = s15.c[i]
    order = order[-(n + 1):]
    if len(order) < n + 1:
        return None
    trs = []
    for a, b in zip(order, order[1:]):
        pc = days[a][2]; hi, lo = days[b][0], days[b][1]
        trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    return sum(trs) / len(trs)


_ATR_DAY: dict = {}       # (symbol, date) -> 14-session daily ATR; changes once a day


def build_ctx(symbol: str, tf: str, now: datetime, s: Series, s15: Series,
              rvol: float | None = None, rvol_rank: int | None = None,
              nifty_ret: float | None = None, prev_close: float | None = None) -> Ctx | None:
    """Everything a rule may read, computed from closed bars only."""
    if len(s) < 30 or len(s15) < 30:
        return None
    day = now.astimezone(IST).date()
    i0, j0 = today_index(s, day), today_index(s15, day)
    a = atr(s, 14)[-1]
    if a <= 0:
        return None
    pdh = pdl = None
    ep15 = getattr(s15, "epochs", None)
    dayof = (lambda i: _epoch_day(ep15[i])) if ep15 is not None else (lambda i: _day(s15.ts[i]))
    if j0:
        k, prev_day = j0 - 1, dayof(j0 - 1)
        pdh, pdl = s15.h[k], s15.l[k]
        while k > 0 and dayof(k - 1) == prev_day:
            k -= 1
            pdh, pdl = max(pdh, s15.h[k]), min(pdl, s15.l[k])
    key = (symbol, day)
    if key not in _ATR_DAY:
        if len(_ATR_DAY) > 2000:
            _ATR_DAY.clear()
        _ATR_DAY[key] = daily_atr(s15, day)
    pc = prev_close if prev_close else (s15.c[j0 - 1] if j0 else None)
    today15 = len(s15) - j0
    or_ok = today15 >= 2
    vols = s.v[-21:-1]
    return Ctx(
        symbol=symbol, tf=tf, now=now, s=s, i0=i0, s15=s15, j0=j0, atr=a,
        atr_day=_ATR_DAY[key], vwap=session_vwap(s15, j0), prev_close=pc,
        pdh=pdh, pdl=pdl, day_open=s15.o[j0] if today15 else None,
        or_high=max(s15.h[j0:j0 + 2]) if or_ok else None,
        or_low=min(s15.l[j0:j0 + 2]) if or_ok else None,
        or_open=s15.o[j0] if or_ok else None, or_close=s15.c[j0 + 1] if or_ok else None,
        rvol=rvol, rvol_rank=rvol_rank, nifty_ret=nifty_ret,
        avg_vol=sum(vols) / len(vols) if vols else None)


# ── shared conditions ────────────────────────────────────────────────────────────


def _aligned(ctx: Ctx, side: str) -> bool:
    """Trend entries go with the market's direction on the day. Unknown NIFTY -> no trade
    (a filter that silently passes when its input is missing is not a filter)."""
    if ctx.nifty_ret is None:
        return False
    return ctx.nifty_ret > 0 if side == "BUY" else ctx.nifty_ret < 0


def _not_in_play(ctx: Ctx, limit: float = 1.8) -> bool:
    return ctx.rvol is not None and ctx.rvol <= limit


def _today_bars(ctx: Ctx) -> int:
    return len(ctx.s) - ctx.i0


def _vol_ok(ctx: Ctx, mult: float = 1.2) -> bool:
    return bool(ctx.avg_vol) and ctx.s.v[-1] >= mult * ctx.avg_vol


def _sig(ctx: Ctx, side: str, stop_atr: float, tgt_atr: float | None, why: str,
         priority: float | None = None, target_price: float | None = None) -> V2Signal:
    return V2Signal(side=side, entry=ctx.s.c[-1], stop_dist=stop_atr * ctx.atr,
                    target_dist=tgt_atr * ctx.atr if tgt_atr else None,
                    max_bars=MAX_BARS.get(ctx.tf, 0),
                    priority=priority if priority is not None else (ctx.rvol or 0.0),
                    rationale=why, target_price=target_price)


# ── trend / breakout families (bar close) ────────────────────────────────────────


def f_donchian(ctx: Ctx, p: dict):
    s, n = ctx.s, p.get("n", 20)
    if len(s) < n + 2:
        return None
    hi, lo = max(s.h[-n - 1:-1]), min(s.l[-n - 1:-1])
    c = s.c[-1]
    if c > hi and s.c[-2] <= hi and _vol_ok(ctx) and _aligned(ctx, "BUY"):
        return _sig(ctx, "BUY", 1.0, 2.0, f"close {c:.2f} broke the {n}-bar high {hi:.2f} on volume, NIFTY up on the day")
    if c < lo and s.c[-2] >= lo and _vol_ok(ctx) and _aligned(ctx, "SELL"):
        return _sig(ctx, "SELL", 1.0, 2.0, f"close {c:.2f} broke the {n}-bar low {lo:.2f} on volume, NIFTY down on the day")
    return None


def f_ema_pullback(ctx: Ctx, p: dict):
    s = ctx.s
    e9, e21, e50 = (s.cached(("ema", k), lambda k=k: ema(s.c, k)) for k in (9, 21, 50))
    c, o = s.c[-1], s.o[-1]
    if e9[-1] > e21[-1] > e50[-1] and s.l[-2] <= e21[-2] and c > e9[-1] and c > o and _aligned(ctx, "BUY"):
        return _sig(ctx, "BUY", 1.0, 1.8, "EMA 9>21>50 uptrend; pulled back to EMA21 and closed back above EMA9")
    if e9[-1] < e21[-1] < e50[-1] and s.h[-2] >= e21[-2] and c < e9[-1] and c < o and _aligned(ctx, "SELL"):
        return _sig(ctx, "SELL", 1.0, 1.8, "EMA 9<21<50 downtrend; rallied to EMA21 and closed back below EMA9")
    return None


def f_macd_trend(ctx: Ctx, p: dict):
    s = ctx.s
    _, _, hist = s.cached(("macd",), lambda: macd(s.c, 12, 26, 9))
    e50 = s.cached(("ema", 50), lambda: ema(s.c, 50))
    if hist[-2] <= 0 < hist[-1] and s.c[-1] > e50[-1] and _aligned(ctx, "BUY"):
        return _sig(ctx, "BUY", 1.2, 2.0, "MACD histogram turned positive above EMA50")
    if hist[-2] >= 0 > hist[-1] and s.c[-1] < e50[-1] and _aligned(ctx, "SELL"):
        return _sig(ctx, "SELL", 1.2, 2.0, "MACD histogram turned negative below EMA50")
    return None


def f_keltner(ctx: Ctx, p: dict):
    s = ctx.s
    mid = s.cached(("ema", 20), lambda: ema(s.c, 20))
    a10 = atr(s, 10)
    up = [m + 2 * x for m, x in zip(mid, a10)]
    dn = [m - 2 * x for m, x in zip(mid, a10)]
    if s.c[-1] > up[-1] and s.c[-2] <= up[-2] and _aligned(ctx, "BUY"):
        return _sig(ctx, "BUY", 1.0, 2.0, "closed above the upper Keltner band (EMA20 + 2 ATR)")
    if s.c[-1] < dn[-1] and s.c[-2] >= dn[-2] and _aligned(ctx, "SELL"):
        return _sig(ctx, "SELL", 1.0, 2.0, "closed below the lower Keltner band (EMA20 - 2 ATR)")
    return None


def f_supertrend(ctx: Ctx, p: dict):
    s = ctx.s
    d = s.cached(("st", 10, 3.0), lambda: supertrend(s, 10, 3.0))
    if d[-2] < 0 < d[-1] and _aligned(ctx, "BUY"):
        return _sig(ctx, "BUY", 1.5, 2.5, "Supertrend(10,3) flipped up")
    if d[-2] > 0 > d[-1] and _aligned(ctx, "SELL"):
        return _sig(ctx, "SELL", 1.5, 2.5, "Supertrend(10,3) flipped down")
    return None


def f_adx_dmi(ctx: Ctx, p: dict):
    s = ctx.s
    adx, pdi, ndi = s.cached(("adx", 14), lambda: adx_di(s, 14))
    if adx[-2] < 25 <= adx[-1]:
        if pdi[-1] > ndi[-1] and _aligned(ctx, "BUY"):
            return _sig(ctx, "BUY", 1.2, 2.4, f"ADX rose through 25 ({adx[-1]:.0f}) with +DI leading")
        if ndi[-1] > pdi[-1] and _aligned(ctx, "SELL"):
            return _sig(ctx, "SELL", 1.2, 2.4, f"ADX rose through 25 ({adx[-1]:.0f}) with -DI leading")
    return None


def f_rsi_momentum(ctx: Ctx, p: dict):
    s = ctx.s
    r = s.cached(("rsi", 14), lambda: rsi(s.c, 14))
    e50 = s.cached(("ema", 50), lambda: ema(s.c, 50))
    if r[-2] < 60 <= r[-1] and s.c[-1] > e50[-1] and _aligned(ctx, "BUY"):
        return _sig(ctx, "BUY", 1.0, 2.0, f"RSI14 crossed up through 60 ({r[-1]:.0f}) above EMA50")
    if r[-2] > 40 >= r[-1] and s.c[-1] < e50[-1] and _aligned(ctx, "SELL"):
        return _sig(ctx, "SELL", 1.0, 2.0, f"RSI14 crossed down through 40 ({r[-1]:.0f}) below EMA50")
    return None


def f_vwap_trend(ctx: Ctx, p: dict):
    v = ctx.vwap
    if len(v) < 4 or ctx.rvol is None or ctx.rvol < 1.0:
        return None
    s = ctx.s
    rising, falling = v[-1] > v[-3], v[-1] < v[-3]
    if s.c[-2] < v[-1] < s.c[-1] and rising and _aligned(ctx, "BUY"):
        return _sig(ctx, "BUY", 1.0, 1.8, f"reclaimed a rising session VWAP {v[-1]:.2f} (rvol {ctx.rvol:.1f})")
    if s.c[-2] > v[-1] > s.c[-1] and falling and _aligned(ctx, "SELL"):
        return _sig(ctx, "SELL", 1.0, 1.8, f"lost a falling session VWAP {v[-1]:.2f} (rvol {ctx.rvol:.1f})")
    return None


def f_pdh_pdl(ctx: Ctx, p: dict):
    if ctx.pdh is None or _today_bars(ctx) < 1:
        return None
    s = ctx.s
    # The first close beyond yesterday's extreme today (an earlier bar may not have closed there)
    if s.c[-1] > ctx.pdh and max(s.c[ctx.i0:-1] or [0]) <= ctx.pdh and _vol_ok(ctx) and _aligned(ctx, "BUY"):
        return _sig(ctx, "BUY", 1.0, 2.0, f"first close above the previous day's high {ctx.pdh:.2f}")
    if s.c[-1] < ctx.pdl and min(s.c[ctx.i0:-1] or [1e18]) >= ctx.pdl and _vol_ok(ctx) and _aligned(ctx, "SELL"):
        return _sig(ctx, "SELL", 1.0, 2.0, f"first close below the previous day's low {ctx.pdl:.2f}")
    return None


def f_or_close_break(ctx: Ctx, p: dict):
    if ctx.or_high is None or ctx.rvol is None or ctx.rvol < 1.2:
        return None
    s = ctx.s
    prior = s.c[ctx.i0:-1]
    if s.c[-1] > ctx.or_high and all(c <= ctx.or_high for c in prior) and _aligned(ctx, "BUY"):
        return _sig(ctx, "BUY", 1.0, 2.0, f"first close above the 30-min range high {ctx.or_high:.2f} (rvol {ctx.rvol:.1f})")
    if s.c[-1] < ctx.or_low and all(c >= ctx.or_low for c in prior) and _aligned(ctx, "SELL"):
        return _sig(ctx, "SELL", 1.0, 2.0, f"first close below the 30-min range low {ctx.or_low:.2f} (rvol {ctx.rvol:.1f})")
    return None


# ── mean-reversion families (bar close; never in names that are in play) ─────────


def f_vwap_reversion(ctx: Ctx, p: dict):
    v = ctx.vwap
    if len(v) < 3 or not _not_in_play(ctx):
        return None
    s = ctx.s
    c, k = s.c[-1], p.get("k", 1.5)
    z = (c - v[-1]) / ctx.atr
    rng = s.h[-1] - s.l[-1]
    if z <= -k and rng and (c - s.l[-1]) / rng >= 0.3:
        return _sig(ctx, "BUY", 1.0, None, f"{-z:.1f} ATR below session VWAP {v[-1]:.2f}, closed off the low",
                    priority=-z, target_price=v[-1])
    if z >= k and rng and (s.h[-1] - c) / rng >= 0.3:
        return _sig(ctx, "SELL", 1.0, None, f"{z:.1f} ATR above session VWAP {v[-1]:.2f}, closed off the high",
                    priority=z, target_price=v[-1])
    return None


def f_rsi2(ctx: Ctx, p: dict):
    if not _not_in_play(ctx):
        return None
    s = ctx.s
    r2 = s.cached(("rsi", 2), lambda: rsi(s.c, 2))
    e50 = s.cached(("ema", 50), lambda: ema(s.c, 50))
    if r2[-1] < 5 and s.c[-1] > e50[-1]:
        return _sig(ctx, "BUY", 1.2, 1.0, f"RSI(2) {r2[-1]:.0f} — a sharp dip inside an uptrend", priority=5 - r2[-1])
    if r2[-1] > 95 and s.c[-1] < e50[-1]:
        return _sig(ctx, "SELL", 1.2, 1.0, f"RSI(2) {r2[-1]:.0f} — a sharp pop inside a downtrend", priority=r2[-1] - 95)
    return None


def f_bollinger_snap(ctx: Ctx, p: dict):
    if not _not_in_play(ctx):
        return None
    s = ctx.s
    m = s.cached(("sma", 20), lambda: sma(s.c, 20))
    sd = s.cached(("sd", 20), lambda: stdev(s.c, 20))
    lo = [a - 2 * b for a, b in zip(m, sd)]
    hi = [a + 2 * b for a, b in zip(m, sd)]
    if s.c[-2] < lo[-2] and s.c[-1] > lo[-1]:
        return _sig(ctx, "BUY", 1.0, None, "closed back inside the lower Bollinger band", target_price=m[-1])
    if s.c[-2] > hi[-2] and s.c[-1] < hi[-1]:
        return _sig(ctx, "SELL", 1.0, None, "closed back inside the upper Bollinger band", target_price=m[-1])
    return None


def f_zscore(ctx: Ctx, p: dict):
    if not _not_in_play(ctx):
        return None
    s = ctx.s
    adx, _, _ = s.cached(("adx", 14), lambda: adx_di(s, 14))
    if adx[-1] >= 25:
        return None
    m = s.cached(("sma", 20), lambda: sma(s.c, 20))
    sd = s.cached(("sd", 20), lambda: stdev(s.c, 20))
    if not sd[-1]:
        return None
    z = (s.c[-1] - m[-1]) / sd[-1]
    if z <= -2.5:
        return _sig(ctx, "BUY", 1.2, None, f"z-score {z:.1f} in a range (ADX {adx[-1]:.0f})", priority=-z, target_price=m[-1])
    if z >= 2.5:
        return _sig(ctx, "SELL", 1.2, None, f"z-score {z:.1f} in a range (ADX {adx[-1]:.0f})", priority=z, target_price=m[-1])
    return None


def f_stoch_range(ctx: Ctx, p: dict):
    if not _not_in_play(ctx):
        return None
    s = ctx.s
    adx, _, _ = s.cached(("adx", 14), lambda: adx_di(s, 14))
    if adx[-1] >= 20:
        return None
    k, d = s.cached(("stoch", 14, 3), lambda: stoch(s, 14, 3))
    if k[-2] <= d[-2] and k[-1] > d[-1] and k[-1] < 20:
        return _sig(ctx, "BUY", 1.0, 1.0, f"stochastic turned up below 20 in a range (ADX {adx[-1]:.0f})")
    if k[-2] >= d[-2] and k[-1] < d[-1] and k[-1] > 80:
        return _sig(ctx, "SELL", 1.0, 1.0, f"stochastic turned down above 80 in a range (ADX {adx[-1]:.0f})")
    return None


def f_cci_extreme(ctx: Ctx, p: dict):
    if not _not_in_play(ctx):
        return None
    s = ctx.s
    c = s.cached(("cci", 20), lambda: cci(s, 20))
    if c[-2] < -200 <= c[-1]:
        return _sig(ctx, "BUY", 1.2, 1.0, "CCI(20) came back up through -200")
    if c[-2] > 200 >= c[-1]:
        return _sig(ctx, "SELL", 1.2, 1.0, "CCI(20) came back down through +200")
    return None


# ── day-level setups (evaluated once, on the 09:45 read of 15m bars) ─────────────


def f_orb_in_play(ctx: Ctx, p: dict):
    """Stocks-in-play ORB (Zarattini, Barbon & Aziz 2024), on NSE's 30-minute range."""
    if ctx.or_high is None or ctx.atr_day is None or ctx.rvol is None:
        return None
    if ctx.rvol < 1.0 or ctx.rvol_rank is None or ctx.rvol_rank > p.get("top", 20):
        return None
    if ctx.or_close == ctx.or_open:
        return None
    stop = p["stop_atr"] * ctx.atr_day
    if ctx.or_close > ctx.or_open:
        return V2Signal("BUY", ctx.or_high, stop, None, 0, ctx.rvol,
                        f"in play (rvol {ctx.rvol:.1f}, #{ctx.rvol_rank}); 30-min range closed up — "
                        f"buy stop at {ctx.or_high:.2f}, stop {p['stop_atr']:.0%} of daily ATR", trigger=ctx.or_high)
    return V2Signal("SELL", ctx.or_low, stop, None, 0, ctx.rvol,
                    f"in play (rvol {ctx.rvol:.1f}, #{ctx.rvol_rank}); 30-min range closed down — "
                    f"sell stop at {ctx.or_low:.2f}, stop {p['stop_atr']:.0%} of daily ATR", trigger=ctx.or_low)


def f_gap_go(ctx: Ctx, p: dict):
    if None in (ctx.prev_close, ctx.or_high, ctx.rvol, ctx.atr_day) or ctx.rvol < 2.0:
        return None
    gap = (ctx.day_open - ctx.prev_close) / ctx.prev_close
    c = ctx.or_close
    if gap >= 0.01 and ctx.or_low > ctx.prev_close and c > ctx.or_open:
        stop = max(c - ctx.or_low, 0.15 * ctx.atr_day)
        return V2Signal("BUY", c, stop, 2 * stop, 0, ctx.rvol,
                        f"gapped up {gap:.1%} on rvol {ctx.rvol:.1f} and held above yesterday's close through 09:45")
    if gap <= -0.01 and ctx.or_high < ctx.prev_close and c < ctx.or_open:
        stop = max(ctx.or_high - c, 0.15 * ctx.atr_day)
        return V2Signal("SELL", c, stop, 2 * stop, 0, ctx.rvol,
                        f"gapped down {-gap:.1%} on rvol {ctx.rvol:.1f} and held below yesterday's close through 09:45")
    return None


def f_gap_fade(ctx: Ctx, p: dict):
    if None in (ctx.prev_close, ctx.or_high, ctx.rvol, ctx.atr_day) or ctx.rvol >= 1.2:
        return None
    gap = (ctx.day_open - ctx.prev_close) / ctx.prev_close
    c = ctx.or_close
    if gap >= 0.015 and ctx.prev_close < c < ctx.or_open:
        stop = max(ctx.or_high - c, 0.15 * ctx.atr_day)
        return V2Signal("SELL", c, stop, min(c - ctx.prev_close, 2 * stop), 0, gap * 100,
                        f"gapped up {gap:.1%} on thin volume (rvol {ctx.rvol:.1f}) and sold off in the first half hour",
                        target_price=None)
    if gap <= -0.015 and ctx.or_open < c < ctx.prev_close:
        stop = max(c - ctx.or_low, 0.15 * ctx.atr_day)
        return V2Signal("BUY", c, stop, min(ctx.prev_close - c, 2 * stop), 0, -gap * 100,
                        f"gapped down {-gap:.1%} on thin volume (rvol {ctx.rvol:.1f}) and was bought in the first half hour")
    return None


# ── the catalog ──────────────────────────────────────────────────────────────────

_BAR_FAMILIES: list[tuple[str, str, str, str, Callable, dict, str]] = [
    # key, label, kind, category, fn, params, rationale
    ("donchian", "Donchian 20 Breakout", "breakout", "momentum", f_donchian, {"n": 20},
     "a close through the last 20 bars' extreme on above-average volume, with the market"),
    ("ema_pullback", "EMA Trend Pullback", "trend", "momentum", f_ema_pullback, {},
     "buy the first dip to EMA21 in an aligned 9/21/50 trend (and the mirror for shorts)"),
    ("macd_trend", "MACD Trend Turn", "trend", "momentum", f_macd_trend, {},
     "MACD histogram crossing zero on the right side of EMA50"),
    ("keltner", "Keltner Breakout", "breakout", "momentum", f_keltner, {},
     "a close outside EMA20 ± 2 ATR — volatility expansion in the market's direction"),
    ("supertrend", "Supertrend Flip", "trend", "momentum", f_supertrend, {},
     "Supertrend(10,3) changing direction"),
    ("adx_dmi", "ADX Trend Start", "trend", "momentum", f_adx_dmi, {},
     "ADX rising through 25: a trend starting, traded on the leading DI's side"),
    ("rsi_momentum", "RSI Momentum 60/40", "trend", "momentum", f_rsi_momentum, {},
     "RSI14 crossing 60 (40) on the right side of EMA50"),
    ("vwap_trend", "VWAP Reclaim", "trend", "momentum", f_vwap_trend, {},
     "price crossing a session VWAP that is sloping the same way, in an active name"),
    ("pdh_pdl", "Prior-Day High/Low Break", "breakout", "momentum", f_pdh_pdl, {},
     "the first close beyond yesterday's high or low, on volume"),
    ("or_close_break", "Opening-Range Close Break", "breakout", "momentum", f_or_close_break, {},
     "the first bar CLOSE beyond the 09:15–09:45 range in an active name"),
    ("vwap_reversion", "VWAP Reversion", "reversion", "mean_reversion", f_vwap_reversion, {"k": 1.5},
     "fade a stretch of 1.5 ATR from session VWAP back to VWAP — only in names NOT in play"),
    ("rsi2", "RSI(2) Extreme", "reversion", "mean_reversion", f_rsi2, {},
     "Connors' RSI(2) below 5 / above 95, with the longer trend"),
    ("bollinger_snap", "Bollinger Snap-Back", "reversion", "mean_reversion", f_bollinger_snap, {},
     "a close back inside the 20/2 band after a close outside it; target the middle band"),
    ("zscore", "Z-Score Fade in Range", "reversion", "mean_reversion", f_zscore, {},
     "a 2.5-sigma stretch from the 20-bar mean when ADX says there is no trend"),
    ("stoch_range", "Stochastic Range Turn", "reversion", "mean_reversion", f_stoch_range, {},
     "stochastic turning from an extreme in a range (ADX < 20)"),
    ("cci_extreme", "CCI ±200 Return", "reversion", "mean_reversion", f_cci_extreme, {},
     "CCI(20) coming back inside ±200"),
]

_DAY_SETUPS: list[tuple[str, str, str, str, Callable, dict, str]] = [
    ("orb_inplay_10", "ORB Stocks-in-Play (stop 10% ATR)", "orb", "momentum", f_orb_in_play,
     {"stop_atr": 0.10, "top": 20},
     "Zarattini/Barbon/Aziz ORB on the 20 most in-play names, stop at 10% of daily ATR, held to the close"),
    ("orb_inplay_25", "ORB Stocks-in-Play (stop 25% ATR)", "orb", "momentum", f_orb_in_play,
     {"stop_atr": 0.25, "top": 20},
     "the same ORB with a stop at 25% of daily ATR — fewer stop-outs, larger losses when wrong"),
    ("gap_go", "Gap and Go", "gap", "momentum", f_gap_go, {},
     "a gap of 1%+ on heavy volume that holds beyond yesterday's close through 09:45"),
    ("gap_fade", "Gap Fade", "gap", "mean_reversion", f_gap_fade, {},
     "a gap of 1.5%+ on thin volume that reverses in the first half hour, toward yesterday's close"),
]

TIMEFRAMES = ("15m", "45m", "1h")
_TF_LABEL = {"15m": "15 min", "45m": "45 min", "1h": "1 hour"}


def _build() -> list[V2Spec]:
    out = []
    for key, label, kind, cat, _fn, params, why in _BAR_FAMILIES:
        for tf in TIMEFRAMES:
            out.append(V2Spec(f"iv2_{key}_{tf}", f"{label} · {_TF_LABEL[tf]}", key, tf, kind,
                              cat, why, dict(params)))
    for key, label, kind, cat, _fn, params, why in _DAY_SETUPS:
        out.append(V2Spec(f"iv2_{key}", label, key, "day", kind, cat, why, dict(params)))
    return out


CATALOG: list[V2Spec] = _build()
BY_ID: dict[str, V2Spec] = {s.strategy_id: s for s in CATALOG}
_FN: dict[str, Callable] = {row[0]: row[4] for row in _BAR_FAMILIES + _DAY_SETUPS}


def evaluate(spec: V2Spec, ctx: Ctx) -> V2Signal | None:
    """Run one rule. Any arithmetic surprise on odd data is a non-signal, never a crash."""
    try:
        sig = _FN[spec.family](ctx, spec.params)
    except (IndexError, ValueError, ZeroDivisionError, TypeError):
        return None
    if sig is None or sig.stop_dist <= 0 or sig.entry <= 0:
        return None
    return sig


def in_entry_window(now: datetime) -> bool:
    hhmm = now.astimezone(IST).strftime("%H:%M")
    return ENTRY_FROM <= hhmm < ENTRY_UNTIL
