"""What the desk knows about each stock BEFORE 09:15, built only from sessions that have finished.

Replay and live call the same functions: `aggregate_session` turns one finished session's five-minute bars into a
DayAgg, and `build_symctx` turns the last sessions' DayAggs (plus the official previous close and the F&O list) into
the stock's context for the day. Every number therefore depends only on data that existed before the open.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from statistics import median

from . import costs
from .timeutil import BAR_S, bar_index

# Bar indices (0 = 09:15-09:20) at which same-time cumulative volume is baselined: the 09:20, 09:30, 09:40 and 09:45
# checkpoints and a few later entry bars. RVOL at bar k = today's volume through bar k / median of the same window
# over the previous sessions.
CUM_KS = (0, 2, 4, 5, 8, 11, 17, 23, 35, 47, 59)
ATR_WINDOW = 60          # Wilder ATR(14) seeded on, and computed over, exactly the last 60 sessions (replay == live)


@dataclass
class DayAgg:
    d: date
    o: float
    h: float
    l: float
    c: float
    v: int
    tv: float                   # traded value, Rs (sum of close x volume over the session's bars)
    n: int                      # five-minute bars in the session
    or_h: float | None          # 09:15-09:30 range (first three bars) when all three exist
    or_l: float | None
    cum: dict = field(default_factory=dict)     # k -> cumulative volume through bar k


def aggregate_session(d: date, bars: list) -> DayAgg | None:
    """bars: [(t, o, h, l, c, v), ...] of ONE session, oldest first."""
    if not bars:
        return None
    o = bars[0][1]
    h = max(b[2] for b in bars)
    l = min(b[3] for b in bars)
    c = bars[-1][4]
    v = sum(int(b[5]) for b in bars)
    tv = sum(b[4] * b[5] for b in bars)
    first3 = [b for b in bars if bar_index(b[0]) < 3]
    or_h = max(b[2] for b in first3) if len(first3) == 3 else None
    or_l = min(b[3] for b in first3) if len(first3) == 3 else None
    cum, run, j = {}, 0, 0
    by_k = {bar_index(b[0]): int(b[5]) for b in bars}
    for k in range(max(CUM_KS) + 1):
        run += by_k.get(k, 0)
        if k in CUM_KS:
            cum[k] = run
    return DayAgg(d=d, o=o, h=h, l=l, c=c, v=v, tv=tv, n=len(bars), or_h=or_h, or_l=or_l, cum=cum)


@dataclass
class SymCtx:
    symbol: str
    sector: str
    index: str | None
    prev_close: float
    prev_close_src: str           # "official" (NSE bhavcopy close) | "last bar"
    prev_high: float
    prev_low: float
    atr: float                    # daily ATR(14), Wilder, in rupees
    atr_pct: float                # ATR / previous close, %
    nr7: bool                     # previous session's range was the narrowest of the last 7
    inside: bool                  # previous session inside the one before it
    tv_cr: float                  # 20-session median daily traded value, Rs crore
    slip_bp: float                # modelled slippage per side (band of tv_cr)
    band: str
    cum_base: dict                # k -> median cumulative volume through bar k
    orw_med_pct: float | None     # median 09:15-09:30 range width, % of that day's open
    fno: bool                     # F&O underlying on the previous session: short-eligible (MIS short convention)
    ca_recent: bool               # a probable corporate action (split / bonus) inside the lookback
    sessions: int

    def as_dict(self) -> dict:
        d = asdict(self)
        d["cum_base"] = {str(k): v for k, v in self.cum_base.items()}
        return d


def wilder_atr(aggs: list[DayAgg], n: int = 14) -> float | None:
    """ATR(14) with Wilder smoothing over exactly the given sessions (oldest first)."""
    if len(aggs) < n + 1:
        return None
    trs = []
    for prev, cur in zip(aggs[:-1], aggs[1:]):
        trs.append(max(cur.h - cur.l, abs(cur.h - prev.c), abs(cur.l - prev.c)))
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def build_symctx(symbol: str, aggs: list[DayAgg], official_prev_close: float | None, fno: bool,
                 sector: str, index: str | None, settings) -> SymCtx | None:
    """aggs: the symbol's finished sessions BEFORE the day, oldest first (at least `min_sessions`)."""
    U = settings.universe
    if len(aggs) < U.min_sessions:
        return None
    last = aggs[-1]
    win = aggs[-U.lookback:]
    # The broker's bar history is back-adjusted for later splits and bonuses; NSE's bhavcopy close is not. The
    # official close is used only when it is on the same price basis as the bars (within 2% of the last bar's
    # close); otherwise the last bar's close stands. (Found in development, 22 Nov 2026: HDFCBANK's June 2025 bars
    # read ~Rs 990 after its later 1:1 bonus while the bhavcopy said Rs 1,978.9 - a fake -50% gap.)
    off = float(official_prev_close) if official_prev_close and official_prev_close > 0 else None
    if off is not None and last.c > 0 and abs(off / last.c - 1) <= 0.02:
        prev_close, src = off, "official"
    else:
        prev_close, src = last.c, ("last bar (official close on another price basis)" if off else "last bar")
    atr = wilder_atr(aggs[-ATR_WINDOW:])
    if atr is None or prev_close <= 0:
        return None
    ranges = [a.h - a.l for a in aggs[-7:]]
    nr7 = len(ranges) == 7 and ranges[-1] <= min(ranges[:-1])
    inside = len(aggs) >= 2 and last.h <= aggs[-2].h and last.l >= aggs[-2].l
    tv_cr = median(a.tv for a in win) / 1e7
    cum_base = {}
    for k in CUM_KS:
        vals = [a.cum.get(k, 0) for a in win if a.cum.get(k, 0) > 0]
        cum_base[k] = median(vals) if len(vals) >= max(5, U.lookback // 2) else None
    orw = [(a.or_h - a.or_l) / a.o * 100 for a in win if a.or_h is not None and a.o > 0]
    ca = False
    for prev, cur in zip(aggs[-U.lookback - 1:-1], aggs[-U.lookback:]):
        if prev.c > 0 and abs(cur.o / prev.c - 1) > U.ca_gap:
            ca = True
            break
    slip = costs.slippage_bp(tv_cr, settings.costs.bands, settings.costs.stress)
    return SymCtx(symbol=symbol, sector=sector, index=index, prev_close=prev_close, prev_close_src=src,
                  prev_high=last.h, prev_low=last.l, atr=atr, atr_pct=atr / prev_close * 100,
                  nr7=nr7, inside=inside, tv_cr=tv_cr, slip_bp=slip, band=costs.band_name(tv_cr),
                  cum_base=cum_base, orw_med_pct=median(orw) if len(orw) >= 10 else None,
                  fno=fno, ca_recent=ca, sessions=len(aggs))


def choose_universe(ctxs: dict[str, SymCtx], settings) -> tuple[list[str], dict[str, str]]:
    """Top N by traded value among stocks that pass the eligibility checks. Returns (members, excluded reasons)."""
    U = settings.universe
    excluded, ok = {}, []
    for sym, c in ctxs.items():
        if c.prev_close < U.min_price:
            excluded[sym] = f"price below Rs {U.min_price:.0f}"
        elif c.ca_recent:
            excluded[sym] = "probable corporate action in the last 20 sessions (prices not adjusted)"
        elif c.cum_base.get(2) is None:
            excluded[sym] = "too few sessions with opening volume for a baseline"
        else:
            ok.append(sym)
    ok.sort(key=lambda s: (-ctxs[s].tv_cr, s))
    members = ok[:U.size]
    for s in ok[U.size:]:
        excluded[s] = f"outside the top {U.size} by traded value"
    return members, excluded
