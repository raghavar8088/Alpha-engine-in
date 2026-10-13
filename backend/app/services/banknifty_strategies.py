"""BANKNIFTY option-BUYING strategy families (written 2026-10-11, before any of their results).

ONE implementation, run by both the research replay (backend/research/banknifty_2026_10) and
the live paper desk (banknifty_desk.py), so what was tested is what trades. Pure Python, no
app imports: everything a rule may know is handed to it.

INTRADAY rules decide on CLOSED 5-minute bars of NIFTY BANK (09:15-anchored), at most one trade
per session each. An `Entry` says which side (+1 = buy the ATM CE, -1 = buy the ATM PE), an
optional index stop / target, and the minute it must be out by (never later than 15:15).
DAILY rules decide once a session, at 15:20, what to hold overnight: "CE", "PE", "STRADDLE"
or nothing.

The parameter grids below are the complete set tested; nothing was added after seeing results.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

OPEN_MIN = 9 * 60 + 15
SQUARE_OFF_MIN = 15 * 60 + 15
NO_ENTRY_AFTER_MIN = 15 * 60
DAILY_DECISION_MIN = 15 * 60 + 20

# a bar is [start_epoch, open, high, low, close]


def bar_minute(start_epoch: int) -> int:
    return ((start_epoch + 19800) % 86400) // 60


def bar_end_minute(bar) -> int:
    return bar_minute(int(bar[0])) + 5


@dataclass
class Entry:
    side: int                         # +1 buy CE, -1 buy PE
    stop: float | None = None         # index level
    target: float | None = None       # index level
    exit_min: int = SQUARE_OFF_MIN    # out by this minute of the day
    why: str = ""


@dataclass
class Day:
    """What an intraday rule may know when a 5m bar has just closed."""
    bars: list                        # today's closed NIFTY BANK 5m bars, oldest first
    hist: list                        # previous sessions' 5m bars (list of lists), oldest first, >= 20
    nifty: list | None = None         # today's closed NIFTY 5m bars (same stamps), for cross-index rules

    @property
    def prev_close(self) -> float:
        return self.hist[-1][-1][4]

    @property
    def prev_high(self) -> float:
        return max(b[2] for b in self.hist[-1])

    @property
    def prev_low(self) -> float:
        return min(b[3] for b in self.hist[-1])


@dataclass
class IntradayRule:
    id: str
    family: str
    params: dict
    label: str
    fn: object = field(repr=False, default=None)

    def decide(self, day: Day) -> Entry | None:
        if not day.bars or not day.hist:
            return None
        if bar_end_minute(day.bars[-1]) > NO_ENTRY_AFTER_MIN:
            return None
        return self.fn(day, **self.params)


# ── intraday families ───────────────────────────────────────────────────────────


def _orb(day: Day, w: int, stop: str, cutoff: int, target: str | None) -> Entry | None:
    end = bar_end_minute(day.bars[-1])
    if end <= OPEN_MIN + w or end > cutoff:
        return None
    rng = [b for b in day.bars if bar_minute(int(b[0])) < OPEN_MIN + w]
    if len(rng) < w // 5:
        return None
    hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
    c = day.bars[-1][4]
    if c > hi:
        st = lo if stop == "opp" else (hi + lo) / 2
        tg = c + 2 * (c - st) if target == "2R" else None
        return Entry(1, st, tg, why=f"close {c:.0f} broke the {w}-minute range high {hi:.0f}")
    if c < lo:
        st = hi if stop == "opp" else (hi + lo) / 2
        tg = c - 2 * (st - c) if target == "2R" else None
        return Entry(-1, st, tg, why=f"close {c:.0f} broke the {w}-minute range low {lo:.0f}")
    return None


def _close_at(bars, end_min: int) -> float | None:
    for b in bars:
        if bar_end_minute(b) == end_min:
            return b[4]
    return None


def _momentum(day: Day, t1: int, t2: int, theta: float) -> Entry | None:
    if bar_end_minute(day.bars[-1]) != t2:
        return None
    c1 = _close_at(day.bars, t1)
    if c1 is None:
        return None
    r1 = c1 / day.prev_close - 1
    if abs(r1) < theta:
        return None
    side = 1 if r1 > 0 else -1
    return Entry(side, why=f"{r1 * 100:+.2f}% from the previous close by {t1 // 60:02d}:{t1 % 60:02d}")


def _gap(day: Day, g: float, mode: str, exit_min: int) -> Entry | None:
    if bar_end_minute(day.bars[-1]) != OPEN_MIN + 15:
        return None
    o, c = day.bars[0][1], day.bars[-1][4]
    gap = o / day.prev_close - 1
    if abs(gap) < g or c == o:
        return None
    gs, ms = (1 if gap > 0 else -1), (1 if c > o else -1)
    if mode == "go" and ms == gs:
        return Entry(gs, exit_min=exit_min, why=f"gap {gap * 100:+.2f}% held through the first 15 minutes")
    if mode == "fade" and ms == -gs:
        return Entry(-gs, exit_min=exit_min, why=f"gap {gap * 100:+.2f}% reversed in the first 15 minutes")
    return None


def _prev_day_break(day: Day, flt: str, stop: str | None) -> Entry | None:
    end = bar_end_minute(day.bars[-1])
    if end < OPEN_MIN + 15 or end > 13 * 60 + 30:
        return None
    ph, pl, pc = day.prev_high, day.prev_low, day.prev_close
    o, c = day.bars[0][1], day.bars[-1][4]
    if flt == "inside" and not (pl <= o <= ph):
        return None
    if c > ph:
        return Entry(1, pc if stop == "pc" else None, why=f"close {c:.0f} above the previous high {ph:.0f}")
    if c < pl:
        return Entry(-1, pc if stop == "pc" else None, why=f"close {c:.0f} below the previous low {pl:.0f}")
    return None


def _trend_day(day: Day, theta: float, stop: str | None) -> Entry | None:
    if bar_end_minute(day.bars[-1]) != OPEN_MIN + 60:
        return None
    o, c = day.bars[0][1], day.bars[-1][4]
    hi, lo = max(b[2] for b in day.bars), min(b[3] for b in day.bars)
    if hi <= lo:
        return None
    r, pos = c / o - 1, (c - lo) / (hi - lo)
    mid = (hi + lo) / 2
    if r >= theta and pos >= 0.75:
        return Entry(1, mid if stop == "mid" else None, why=f"first hour {r * 100:+.2f}%, closing near its high")
    if r <= -theta and pos <= 0.25:
        return Entry(-1, mid if stop == "mid" else None, why=f"first hour {r * 100:+.2f}%, closing near its low")
    return None


_SD30_CACHE: dict = {}


def _sd30(hist) -> float | None:
    key = (len(hist), int(hist[-1][-1][0]))
    if key in _SD30_CACHE:
        return _SD30_CACHE[key]
    if len(_SD30_CACHE) > 4096:
        _SD30_CACHE.clear()
    _SD30_CACHE[key] = _sd30_calc(hist)
    return _SD30_CACHE[key]


def _sd30_calc(hist) -> float | None:
    rs = []
    for s in hist[-20:]:
        cl = [b[4] for b in s]
        rs += [cl[i] / cl[i - 6] - 1 for i in range(6, len(cl), 6)]
    return statistics.pstdev(rs) if len(rs) > 30 else None


def _extreme_reversal(day: Day, z: float, hold: int) -> Entry | None:
    end = bar_end_minute(day.bars[-1])
    if end < 10 * 60 or end > 14 * 60 or len(day.bars) < 7:
        return None
    sd = _sd30(day.hist)
    if not sd:
        return None
    r30 = day.bars[-1][4] / day.bars[-7][4] - 1
    if abs(r30) < z * sd:
        return None
    side = -1 if r30 > 0 else 1
    return Entry(side, exit_min=min(SQUARE_OFF_MIN, end + hold),
                 why=f"30-minute move {r30 * 100:+.2f}% = {r30 / sd:+.1f} sd, faded")


def _relative(day: Day, t: int, theta: float, mode: str) -> Entry | None:
    if bar_end_minute(day.bars[-1]) != t or not day.nifty:
        return None
    nf = [b for b in day.nifty if bar_end_minute(b) <= t]
    if not nf:
        return None
    rb = day.bars[-1][4] / day.bars[0][1] - 1
    rn = nf[-1][4] / nf[0][1] - 1
    rel = rb - rn
    if abs(rel) < theta:
        return None
    lagging = rel < 0
    side = (1 if lagging else -1) if mode == "catchup" else (-1 if lagging else 1)
    return Entry(side, why=f"BANKNIFTY {rb * 100:+.2f}% vs NIFTY {rn * 100:+.2f}% since the open ({mode})")


def _compression_break(day: Day, kind: str) -> Entry | None:
    end = bar_end_minute(day.bars[-1])
    if end < OPEN_MIN + 15 or end > 13 * 60 + 30 or len(day.hist) < 8:
        return None
    rngs = [(max(b[2] for b in s), min(b[3] for b in s)) for s in day.hist[-8:]]
    yh, yl = rngs[-1]
    if kind == "nr7":
        ok = (yh - yl) < min(h - l for h, l in rngs[-7:-1])
    else:
        ok = yh <= rngs[-2][0] and yl >= rngs[-2][1]
    if not ok:
        return None
    c, mid = day.bars[-1][4], (yh + yl) / 2
    if c > yh:
        return Entry(1, mid, why=f"broke out above an {kind} day's high {yh:.0f}")
    if c < yl:
        return Entry(-1, mid, why=f"broke down below an {kind} day's low {yl:.0f}")
    return None


def _hm(m: int) -> str:
    return f"{m // 60:02d}{m % 60:02d}"


def intraday_rules() -> list[IntradayRule]:
    out: list[IntradayRule] = []
    for w in (15, 30, 60):
        for stop in ("opp", "mid"):
            for cutoff in (11 * 60 + 30, 13 * 60 + 30):
                for target in (None, "2R"):
                    out.append(IntradayRule(
                        f"bn_orb_{w}m_{stop}_{_hm(cutoff)}_{target or 'eod'}", "Opening-range breakout",
                        {"w": w, "stop": stop, "cutoff": cutoff, "target": target},
                        f"ORB {w}m, stop at the range {'opposite side' if stop == 'opp' else 'midpoint'}, "
                        f"entries until {cutoff // 60}:{cutoff % 60:02d}, {'target 2R' if target else 'held to 15:15'}", _orb))
    for t1 in (9 * 60 + 45, 10 * 60 + 15, 11 * 60 + 15):
        for t2 in (13 * 60 + 15, 14 * 60 + 15):
            for theta in (0.0025, 0.005):
                out.append(IntradayRule(
                    f"bn_mom_{_hm(t1)}_{_hm(t2)}_{int(theta * 1e4)}bp", "Intraday momentum",
                    {"t1": t1, "t2": t2, "theta": theta},
                    f"Previous close to {t1 // 60}:{t1 % 60:02d} up/down at least {theta * 100:.2f}% -> "
                    f"buy that way at {t2 // 60}:{t2 % 60:02d}, out 15:15", _momentum))
    for g in (0.004, 0.008):
        for mode in ("go", "fade"):
            for exit_min in (12 * 60, SQUARE_OFF_MIN):
                out.append(IntradayRule(
                    f"bn_gap_{mode}_{int(g * 1e4)}bp_{_hm(exit_min)}", "Opening gap",
                    {"g": g, "mode": mode, "exit_min": exit_min},
                    f"Gap of {g * 100:.1f}%+ {'continuing' if mode == 'go' else 'reversing'} in the first 15 minutes, "
                    f"out {exit_min // 60}:{exit_min % 60:02d}", _gap))
    for flt in ("any", "inside"):
        for stop in ("pc", None):
            out.append(IntradayRule(
                f"bn_pdbreak_{flt}_{stop or 'nostop'}", "Previous-day high/low break",
                {"flt": flt, "stop": stop},
                f"Close beyond the previous session's high/low ({'any open' if flt == 'any' else 'opened inside it'}), "
                f"{'stop at the previous close' if stop else 'no stop'}", _prev_day_break))
    for theta in (0.004, 0.007):
        for stop in ("mid", None):
            out.append(IntradayRule(
                f"bn_trendday_{int(theta * 1e4)}bp_{stop or 'nostop'}", "Trend day",
                {"theta": theta, "stop": stop},
                f"First hour {theta * 100:.1f}%+ closing in its top/bottom quarter, "
                f"{'stop at its midpoint' if stop else 'no stop'}", _trend_day))
    for z in (2.5, 3.5):
        for hold in (30, 60):
            out.append(IntradayRule(
                f"bn_revert_{str(z).replace('.', 'p')}sd_{hold}m", "Extreme-move reversal",
                {"z": z, "hold": hold},
                f"Fade a 30-minute move of {z} sd, hold {hold} minutes", _extreme_reversal))
    for t in (10 * 60 + 15, 11 * 60 + 15):
        for theta in (0.003, 0.006):
            for mode in ("catchup", "follow"):
                out.append(IntradayRule(
                    f"bn_rel_{mode}_{_hm(t)}_{int(theta * 1e4)}bp", "BANKNIFTY vs NIFTY",
                    {"t": t, "theta": theta, "mode": mode},
                    f"BANKNIFTY {theta * 100:.1f}%+ apart from NIFTY by {t // 60}:{t % 60:02d}, "
                    f"{'bet on the gap closing' if mode == 'catchup' else 'follow the leader'}", _relative))
    for kind in ("nr7", "inside"):
        out.append(IntradayRule(f"bn_compress_{kind}", "Compression breakout", {"kind": kind},
                                f"Break of an {kind} day's range, stop at its midpoint", _compression_break))
    return out


# ── daily families (decided at 15:20, held overnight, priced on real closes) ────


@dataclass
class DailyBar:
    k: int            # day key (days since 1970-01-01, IST)
    o: float
    h: float
    l: float
    c: float          # for TODAY: the 15:20 price (the decision is taken before the close)


@dataclass
class DailyRule:
    id: str
    family: str
    params: dict
    label: str
    fn: object = field(repr=False, default=None)
    max_hold: int = 20               # sessions
    stop_pct: float | None = 0.40    # of premium, checked on closes
    target_pct: float | None = 0.80

    def target(self, days: list[DailyBar], ctx: dict) -> str | None:
        return self.fn(days, ctx, **self.params)


def _sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _donchian(days, ctx, n):
    if len(days) < n + 2:
        return ctx.get("holding")
    hi = max(d.h for d in days[-n - 1:-1])
    lo = min(d.l for d in days[-n - 1:-1])
    c, held = days[-1].c, ctx.get("holding")
    if c > hi:
        return "CE"
    if c < lo:
        return "PE"
    m = n // 2
    if held == "CE" and c < min(d.l for d in days[-m - 1:-1]):
        return None
    if held == "PE" and c > max(d.h for d in days[-m - 1:-1]):
        return None
    return held


def _ma_cross(days, ctx, fast, slow):
    cl = [d.c for d in days]
    f, s = _sma(cl, fast), _sma(cl, slow)
    if f is None or s is None:
        return None
    return "CE" if f > s else "PE"


def _tsmom(days, ctx, n):
    if len(days) <= n:
        return None
    return "CE" if days[-1].c > days[-1 - n].c else "PE"


def _rsi(cl, n=2):
    if len(cl) <= n:
        return None
    g = [max(0.0, cl[i] - cl[i - 1]) for i in range(len(cl) - n, len(cl))]
    l = [max(0.0, cl[i - 1] - cl[i]) for i in range(len(cl) - n, len(cl))]
    ag, al = sum(g) / n, sum(l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def _rsi2(days, ctx, lo, hi):
    cl = [d.c for d in days]
    if len(cl) < 201:
        return None
    r, ma = _rsi(cl), _sma(cl, 200)
    held = ctx.get("holding")
    if held == "CE" and r > 70:
        return None
    if held == "PE" and r < 30:
        return None
    if held:
        return held
    if r < lo and cl[-1] > ma:
        return "CE"
    if r > hi and cl[-1] < ma:
        return "PE"
    return None


def _nr7_straddle(days, ctx, hold):
    held, age = ctx.get("holding"), ctx.get("age", 0)
    if held:
        return held if age < hold else None
    if len(days) < 8:
        return None
    rng = [d.h - d.l for d in days[-7:]]
    return "STRADDLE" if rng[-1] < min(rng[:-1]) else None


def _event_ramp(days, ctx, before, through):
    """Straddle bought `before` sessions ahead of a scheduled event (RBI policy, Union Budget),
    sold at the close of the session before it - or, `through`, the day before and sold after."""
    s = ctx.get("sessions_to_event")          # 0 = the event session itself
    if s is None:
        return None
    if through:
        return "STRADDLE" if s == 1 else None
    return "STRADDLE" if 2 <= s <= before else None


def _cheap_vol(days, ctx, ratio, hold):
    held, age = ctx.get("holding"), ctx.get("age", 0)
    if held:
        return held if age < hold else None
    iv, cl = ctx.get("atm_iv"), [d.c for d in days]
    if iv is None or len(cl) < 22:
        return None
    rets = [math.log(cl[i] / cl[i - 1]) for i in range(len(cl) - 20, len(cl))]
    rv = statistics.pstdev(rets) * math.sqrt(252)
    return "STRADDLE" if rv > 0 and iv < ratio * rv else None


def daily_rules() -> list[DailyRule]:
    out: list[DailyRule] = []
    for n in (10, 20, 55):
        out.append(DailyRule(f"bn_d_donchian_{n}", "Daily breakout", {"n": n},
                             f"{n}-day high/low breakout, out on the {n // 2}-day opposite break", _donchian))
    for fast, slow in ((5, 20), (10, 50), (20, 100)):
        out.append(DailyRule(f"bn_d_ma_{fast}_{slow}", "Daily moving-average trend", {"fast": fast, "slow": slow},
                             f"{fast}/{slow}-day average trend, always in", _ma_cross))
    for n in (20, 60):
        out.append(DailyRule(f"bn_d_tsmom_{n}", "Time-series momentum", {"n": n},
                             f"Sign of the {n}-day return, always in", _tsmom))
    out.append(DailyRule("bn_d_rsi2", "Daily mean reversion", {"lo": 10, "hi": 90},
                         "RSI(2) below 10 above the 200-day average (calls) / above 90 below it (puts)", _rsi2, max_hold=5))
    for hold in (1, 3):
        out.append(DailyRule(f"bn_d_nr7_straddle_{hold}d", "Volatility compression", {"hold": hold},
                             f"Straddle after an NR7 day, held {hold} session(s)", _nr7_straddle,
                             max_hold=hold, stop_pct=None, target_pct=None))
    for before in (3, 5):
        out.append(DailyRule(f"bn_d_event_ramp_{before}", "Event volatility", {"before": before, "through": False},
                             f"Straddle {before} sessions before RBI policy / Budget, sold the session before",
                             _event_ramp, max_hold=before, stop_pct=None, target_pct=None))
    out.append(DailyRule("bn_d_event_through", "Event volatility", {"before": 1, "through": True},
                         "Straddle the session before RBI policy / Budget, sold at the event's close",
                         _event_ramp, max_hold=1, stop_pct=None, target_pct=None))
    for ratio in (0.9, 1.0):
        out.append(DailyRule(f"bn_d_cheapvol_{int(ratio * 100)}", "Cheap volatility", {"ratio": ratio, "hold": 5},
                             f"Straddle when ATM IV < {ratio:.1f} x 20-day realised vol, held 5 sessions",
                             _cheap_vol, max_hold=5, stop_pct=None, target_pct=None))
    return out


# Scheduled events for the event family: RBI monetary-policy decisions (announced ~10:00 IST
# on the date) and Union Budgets. Each date is checked in the research against BANKNIFTY's own
# 10:00-11:00 range before use.
RBI_POLICY = [
    "2016-02-02", "2016-04-05", "2016-06-07", "2016-08-09", "2016-10-04", "2016-12-07",
    "2017-02-08", "2017-04-06", "2017-06-07", "2017-08-02", "2017-10-04", "2017-12-06",
    "2018-02-07", "2018-04-05", "2018-06-06", "2018-08-01", "2018-10-05", "2018-12-05",
    "2019-02-07", "2019-04-04", "2019-06-06", "2019-08-07", "2019-10-04", "2019-12-05",
    "2020-02-06", "2020-03-27", "2020-05-22", "2020-08-06", "2020-10-09", "2020-12-04",
    "2021-02-05", "2021-04-07", "2021-06-04", "2021-08-06", "2021-10-08", "2021-12-08",
    "2022-02-10", "2022-04-08", "2022-05-04", "2022-06-08", "2022-08-05", "2022-09-30", "2022-12-07",
    "2023-02-08", "2023-04-06", "2023-06-08", "2023-08-10", "2023-10-06", "2023-12-08",
    "2024-02-08", "2024-04-05", "2024-06-07", "2024-08-08", "2024-10-09", "2024-12-06",
    "2025-02-07", "2025-04-09", "2025-06-06", "2025-08-06", "2025-10-01", "2025-12-05",
    "2026-02-06", "2026-04-08", "2026-06-05", "2026-08-05",
]
UNION_BUDGET = ["2016-02-29", "2017-02-01", "2018-02-01", "2019-02-01", "2019-07-05", "2020-02-01",
                "2021-02-01", "2022-02-01", "2023-02-01", "2024-02-01", "2024-07-23", "2025-02-01", "2026-02-01"]
