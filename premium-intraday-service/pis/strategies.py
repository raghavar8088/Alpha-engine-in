"""The desk's new strategies (N01-N06), written so a second developer can reproduce any trade from the definition.

COMMON TO ALL
  Universe    pis.context.choose_universe: top 150 NSE stocks by 20-session median traded value, price >= Rs 50,
              no probable corporate action in the last 20 sessions. Shorts only in F&O underlyings (the app's MIS
              short convention).
  Bars        five-minute, session-anchored (bar k covers 09:15+5k .. 09:20+5k); a decision is made when a bar
              CLOSES and uses only bars that have closed.
  Workflow    09:30 screen -> 09:40 persistence check -> 09:45 plan. Nothing enters before the plan: the first bar
              that can trigger is 09:45-09:50. No new entries after a bar closing at 14:30; square-off 15:05.
  Entry       at the close of the trigger bar, only if that close is inside the setup's acceptable entry range; a
              close beyond the range is a MISSED setup, recorded as such. Fill = close +/- slippage (pis.costs).
  Stop/target computed from the trigger bar's close; the planned stop distance must lie inside the strategy's band
              or the setup is skipped (a stop that is too tight is mostly costs; too wide breaks the risk budget).
              Target = entry +/- target_R x stop distance (walk-forward chooses target_R from {1.5, 2, 3}).
  Ladder      L0 rule alone; L1 + sector confirmation; L2 + 09:40 checkpoint confirmation (and the strategy's
              allowed market conditions); L3 + news (NSE announcements with exchange timestamps; Nov 2025 onward).
              The registered version of each strategy is its PRIMARY level (see PRIMARY); the others are the
              ablations the brief asks for.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .timeutil import OPEN_MIN

TARGETS = (1.5, 2.0, 3.0)
LEVELS = ("L0", "L1", "L2", "L3")


def close_min(k: int) -> int:
    """Minute of day at which bar k closes."""
    return OPEN_MIN + (k + 1) * 5


@dataclass
class Setup:
    strategy: str
    variant: str
    level: str
    symbol: str
    side: int                         # +1 long, -1 short
    sector: str
    score: float
    reason: str
    facts: dict
    trigger: dict                     # {"type": "close_above"/"close_below", "level": x} or {"type": "vwap_pullback"}
    entry_lo: float | None
    entry_hi: float | None
    risk_min_pct: float
    risk_max_pct: float
    target_R: float
    win_from_min: int                 # first trigger-bar close minute
    win_to_min: int                   # last trigger-bar close minute (expiry)
    time_exit_min: int
    stop_rule: dict
    target_cap: float | None = None   # an absolute price the target may not pass (gap fill)
    min_reward_R: float | None = None
    invalidate: dict | None = None
    oco: str | None = None
    status: str = "armed"
    events: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.strategy}|{self.variant}|{self.level}|{self.symbol}|{self.side}"

    def public(self) -> dict:
        return {
            "strategy": self.strategy, "variant": self.variant, "level": self.level, "symbol": self.symbol,
            "side": "LONG" if self.side > 0 else "SHORT", "sector": self.sector, "score": round(self.score, 3),
            "reason": self.reason, "facts": self.facts, "trigger": self.trigger,
            "entry_range": [self.entry_lo, self.entry_hi], "stop_rule": self.stop_rule,
            "risk_band_pct": [self.risk_min_pct, self.risk_max_pct], "target_R": self.target_R,
            "target_cap": self.target_cap, "window": [_hm(self.win_from_min), _hm(self.win_to_min)],
            "time_exit": _hm(self.time_exit_min), "invalidate": self.invalidate, "oco": self.oco,
            "status": self.status,
        }


def _hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


class Strategy:
    id = ""
    name = ""
    family = ""
    version = "1"
    sides = (1, -1)
    allowed = {1: ("bull_trend", "mixed", "range"), -1: ("bear_trend", "mixed", "range")}
    uses_news = False                 # True when the RULE itself needs announcements (N06)
    primary = "L2"

    def __init__(self, level: str | None = None, target_R: float = 2.0):
        self.level = level or self.primary
        self.target_R = target_R

    @property
    def variant(self) -> str:
        return f"R{self.target_R:g}"

    def lv(self, name: str) -> bool:
        return LEVELS.index(self.level) >= LEVELS.index(name)

    # Subclasses implement:
    def screen(self, S, k: int) -> list[dict]:        # 09:30 provisional list
        return []

    def confirm(self, S, k: int, cands: list[dict]) -> tuple[list[dict], list[dict]]:   # 09:40
        return cands, []

    def plan(self, S, k: int, cands: list[dict]) -> list[Setup]:    # 09:45
        return []

    def on_bar(self, setup: Setup, S, k: int):
        """None, or ("enter", ref_price, stop_price, target_price, note), ("invalid", why), ("expire", why),
        ("missed", why)."""
        return default_on_bar(setup, S, k)

    def describe(self) -> dict:
        return {"id": self.id, "name": self.name, "family": self.family, "version": self.version,
                "level": self.level, "variant": self.variant, "allowed": {"LONG": list(self.allowed[1]),
                                                                           "SHORT": list(self.allowed[-1])}}


# ── shared trigger logic ───────────────────────────────────────────────────────────────────────────────────────

def _levels(setup: Setup, ref: float, stop: float):
    risk = (ref - stop) * setup.side
    if risk <= 0:
        return None, "stop on the wrong side of the entry"
    rp = risk / ref * 100
    if rp < setup.risk_min_pct:
        return None, f"stop {rp:.2f}% from entry is inside the {setup.risk_min_pct:.2f}% minimum (costs would dominate)"
    if rp > setup.risk_max_pct:
        return None, f"stop {rp:.2f}% from entry is beyond the {setup.risk_max_pct:.2f}% maximum"
    tdist = setup.target_R * risk
    if setup.target_cap is not None:
        cap = (setup.target_cap - ref) * setup.side
        if setup.min_reward_R is not None and cap < setup.min_reward_R * risk:
            return None, (f"only {cap / risk:.2f}R of room to {setup.target_cap:.2f} "
                          f"(needs {setup.min_reward_R:.1f}R)")
        tdist = min(tdist, cap)
    return (stop, ref + setup.side * tdist), None


def default_on_bar(setup: Setup, S, k: int):
    """Close-confirmed breakout through trigger.level, inside the window, inside the entry range."""
    m = close_min(k)
    b = S.state.bar(setup.symbol, k)
    if b is None:
        return None
    c = b[4]
    inv = setup.invalidate
    if inv:
        lvl = inv["level"]
        if (inv["type"] == "close_below" and c < lvl) or (inv["type"] == "close_above" and c > lvl):
            return ("invalid", inv["why"])
    if m < setup.win_from_min:
        return None
    if m > setup.win_to_min:
        return ("expire", f"no trigger by {_hm(setup.win_to_min)}")
    lvl = setup.trigger["level"]
    fired = c > lvl if setup.trigger["type"] == "close_above" else c < lvl
    if not fired:
        return None
    lo, hi = setup.entry_lo, setup.entry_hi
    if not (lo <= c <= hi):
        return ("missed", f"closed at {c:.2f}, beyond the permitted entry range {lo:.2f}-{hi:.2f}")
    stop = _stop_price(setup, S, k, c, b)
    lv, why = _levels(setup, c, stop)
    if lv is None:
        return ("skip", why)
    return ("enter", c, lv[0], lv[1], f"bar {_hm(m - 5)}-{_hm(m)} closed {c:.2f} beyond {lvl:.2f}")


def _stop_price(setup: Setup, S, k: int, ref: float, bar) -> float:
    r = setup.stop_rule
    if r["type"] == "price":
        stop = r["price"]
    elif r["type"] == "vwap":
        vw = S.state.vwap(setup.symbol, k) or ref
        stop = vw * (1 - setup.side * r.get("buf", 0.001))
    elif r["type"] == "pullback":
        vw = S.state.vwap(setup.symbol, k) or ref
        ext = min(bar[3], vw) if setup.side > 0 else max(bar[2], vw)
        stop = ext * (1 - setup.side * r.get("buf", 0.0015))
    else:
        raise ValueError(r)
    floor = r.get("floor_pct")       # widen a too-close stop to this distance instead of skipping
    if floor is not None and (ref - stop) * setup.side < ref * floor / 100:
        stop = ref * (1 - setup.side * floor / 100)
    return stop


# ── N01 Sector-confirmed opening-range breakout ────────────────────────────────────────────────────────────────

class SectorORB(Strategy):
    id, name, family = "N01", "Sector-confirmed opening-range breakout", "Sector-confirmed ORB"
    allowed = {1: ("bull_trend", "mixed"), -1: ("bear_trend", "mixed")}
    primary = "L2"

    def screen(self, S, k):
        out = []
        for sym in S.members:
            c = S.ctx[sym]
            orr = S.state.or15(sym)
            if not orr or not S.state.complete(sym, k):
                continue
            H, L, O, C = orr
            w = (H - L) / O * 100
            if not (0.40 <= w <= 2.50):
                continue
            rv = S.state.rvol(sym, k, c.cum_base)
            vw = S.state.vwap(sym, k)
            rel = S.stock_rel(sym, k)
            if rv is None or rv < 1.5 or rel is None:
                continue
            side = 1 if C > O else -1 if C < O else 0
            if side == 0 or (side < 0 and not c.fno):
                continue
            if (C - vw) * side <= 0 or rel * side <= 0:
                continue
            sec = S.sector_row(c.sector, k)
            if self.lv("L1") and not (sec and (sec["strong"] if side > 0 else sec["weak"])):
                continue
            out.append({"symbol": sym, "side": side, "score": rv * abs(rel), "or": orr, "orw": w, "rvol": rv,
                        "rel": rel, "sector_rank": sec["rank"] if sec else None})
        return out

    def confirm(self, S, k, cands):
        if not self.lv("L2"):
            return _top(cands, 3), []
        keep, drop = [], []
        cond = S.market(k)["condition"]
        for x in cands:
            sym, side = x["symbol"], x["side"]
            sec = S.sector_row(S.ctx[sym].sector, k)
            H, L, O, C = x["or"]
            mid = (H + L) / 2
            c = S.state.close(sym, k)
            vw = S.state.vwap(sym, k)
            if cond not in self.allowed[side]:
                drop.append({**x, "why": f"market is {cond}, not one this setup is validated for"})
            elif not sec or sec["rank"] is None or (sec["rank"] > 3 if side > 0 else sec["rank"] < len(S.sectors(k)) - 2):
                drop.append({**x, "why": "sector leadership did not persist to 09:40"})
            elif (sec["up_open"] < 0.55 if side > 0 else sec["up_open"] > 0.45) or sec["narrow"]:
                drop.append({**x, "why": "sector participation narrowed by 09:40"})
            elif c is None or (c - mid) * side <= 0 or (c - vw) * side <= 0:
                drop.append({**x, "why": "stock back through its opening-range midpoint or VWAP"})
            else:
                keep.append(x)
        return _top(keep, 3), drop

    def plan(self, S, k, cands):
        out = []
        for x in cands:
            sym, side = x["symbol"], x["side"]
            H, L, O, C = x["or"]
            rng, mid = H - L, (H + L) / 2
            trig = H if side > 0 else L
            chase = max(0.30 * rng, trig * 0.001)
            lo, hi = (trig, trig + chase) if side > 0 else (trig - chase, trig)
            out.append(Setup(
                strategy=self.id, variant=self.variant, level=self.level, symbol=sym, side=side,
                sector=S.ctx[sym].sector, score=x["score"],
                reason=(f"{'leader' if side > 0 else 'laggard'} in {S.ctx[sym].sector} (sector rank "
                        f"{x['sector_rank']}), opening range {x['orw']:.2f}% wide, {x['rvol']:.1f}x same-time "
                        f"volume, {x['rel']:+.2f}% vs its sector"),
                facts={"or_high": H, "or_low": L, "or_open": O, "or_close": C, "rvol_0930": x["rvol"],
                       "rel_sector_0930": x["rel"]},
                trigger={"type": "close_above" if side > 0 else "close_below", "level": trig},
                entry_lo=lo, entry_hi=hi, risk_min_pct=0.35, risk_max_pct=1.50, target_R=self.target_R,
                win_from_min=9 * 60 + 50, win_to_min=11 * 60 + 30, time_exit_min=15 * 60,
                stop_rule={"type": "price", "price": mid},
                invalidate={"type": "close_below" if side > 0 else "close_above", "level": mid,
                            "why": "closed back through the opening-range midpoint before triggering"}))
        return _news_filter(self, S, out, want=True)


# ── N02 Relative-strength leaders and laggards ────────────────────────────────────────────────────────────────

class RelativeStrength(Strategy):
    id, name, family = "N02", "Relative-strength leaders and laggards", "Relative strength"
    allowed = {1: ("bull_trend", "mixed", "range"), -1: ("bear_trend", "mixed", "range")}
    primary = "L2"
    TOP = 8

    def _rank(self, S, k):
        rows = []
        n = S.state.ret_open("NIFTY", k)
        if n is None:
            return []
        for sym in S.members:
            c = S.ctx[sym]
            r = S.state.ret_open(sym, k)
            rel = S.stock_rel(sym, k)
            rv = S.state.rvol(sym, k, c.cum_base)
            vw = S.state.vwap(sym, k)
            if r is None or rel is None or rv is None or vw is None:
                continue
            rows.append({"symbol": sym, "rs_sec": rel, "rs_mkt": r - n, "rs": 0.5 * rel + 0.5 * (r - n),
                         "rvol": rv, "above_vwap": S.state.close(sym, k) > vw})
        return rows

    def screen(self, S, k):
        rows = self._rank(S, k)
        longs = [x for x in rows if x["rs_sec"] > 0 and x["rs_mkt"] > 0 and x["rvol"] >= 1.3 and x["above_vwap"]]
        shorts = [x for x in rows if x["rs_sec"] < 0 and x["rs_mkt"] < 0 and x["rvol"] >= 1.3 and not x["above_vwap"]
                  and S.ctx[x["symbol"]].fno]
        longs.sort(key=lambda x: (-x["rs"], x["symbol"]))
        shorts.sort(key=lambda x: (x["rs"], x["symbol"]))
        out = []
        for side, xs in ((1, longs[:self.TOP]), (-1, shorts[:self.TOP])):
            for x in xs:
                sec = S.sector_row(S.ctx[x["symbol"]].sector, k)
                if self.lv("L1"):
                    if not sec or sec["rel"] is None:
                        continue
                    if side > 0 and (sec["weak"] or sec["rel"] < 0):
                        continue
                    if side < 0 and (sec["strong"] or sec["rel"] > 0):
                        continue
                out.append({**x, "side": side, "score": abs(x["rs"]) * min(x["rvol"], 3)})
        return out

    def confirm(self, S, k, cands):
        if not self.lv("L2"):
            return cands, []
        cond = S.market(k)["condition"]
        rows = {x["symbol"]: x for x in self._rank(S, k)}
        ranked_l = sorted((x for x in rows.values() if x["rs_sec"] > 0 and x["rs_mkt"] > 0), key=lambda x: -x["rs"])
        ranked_s = sorted((x for x in rows.values() if x["rs_sec"] < 0 and x["rs_mkt"] < 0), key=lambda x: x["rs"])
        top_l = {x["symbol"] for x in ranked_l[:self.TOP]}
        top_s = {x["symbol"] for x in ranked_s[:self.TOP]}
        keep, drop = [], []
        for x in cands:
            sym, side = x["symbol"], x["side"]
            now = rows.get(sym)
            if cond not in self.allowed[side]:
                drop.append({**x, "why": f"market is {cond}"})
            elif now is None or sym not in (top_l if side > 0 else top_s):
                drop.append({**x, "why": f"no longer a top-{self.TOP} {'leader' if side > 0 else 'laggard'} at 09:40"})
            elif now["rvol"] < 1.3:
                drop.append({**x, "why": "relative volume faded below 1.3x by 09:40"})
            else:
                keep.append({**x, "rs_0940": now["rs"]})
        return keep, drop

    def plan(self, S, k, cands):
        out = []
        for x in sorted(cands, key=lambda x: -x["score"])[:4]:
            sym, side = x["symbol"], x["side"]
            hi = S.state.high(sym, k)
            lo_ = S.state.low(sym, k)
            trig = hi if side > 0 else lo_
            chase = trig * 0.0025
            lo, hi2 = (trig, trig + chase) if side > 0 else (trig - chase, trig)
            vw = S.state.vwap(sym, k)
            out.append(Setup(
                strategy=self.id, variant=self.variant, level=self.level, symbol=sym, side=side,
                sector=S.ctx[sym].sector, score=x["score"],
                reason=(f"{'leads' if side > 0 else 'lags'} its sector by {x['rs_sec']:+.2f}% and NIFTY by "
                        f"{x['rs_mkt']:+.2f}% at 09:30, still top-{self.TOP} at 09:40, {x['rvol']:.1f}x volume"),
                facts={"rs_sec_0930": x["rs_sec"], "rs_mkt_0930": x["rs_mkt"], "rvol_0930": x["rvol"],
                       "day_extreme_0945": trig, "vwap_0945": vw},
                trigger={"type": "close_above" if side > 0 else "close_below", "level": trig},
                entry_lo=lo, entry_hi=hi2, risk_min_pct=0.40, risk_max_pct=1.50, target_R=self.target_R,
                win_from_min=9 * 60 + 50, win_to_min=12 * 60 + 30, time_exit_min=15 * 60,
                stop_rule={"type": "vwap", "buf": 0.001, "floor_pct": 0.40},
                invalidate={"type": "close_below" if side > 0 else "close_above", "level": vw,
                            "why": "closed through VWAP before triggering"}))
        return _news_filter(self, S, out, want=True)

    def on_bar(self, setup, S, k):
        inv = setup.invalidate
        if inv is not None:                          # VWAP moves: re-read it at this bar
            vw = S.state.vwap(setup.symbol, k)
            if vw is not None:
                inv["level"] = vw
        return default_on_bar(setup, S, k)


# ── N03 Trend-day VWAP pullback ───────────────────────────────────────────────────────────────────────────────

class TrendDayVWAP(Strategy):
    id, name, family = "N03", "Trend-day VWAP pullback", "VWAP pullback on trend days"
    allowed = {1: ("bull_trend",), -1: ("bear_trend",)}
    primary = "L2"

    def _always_beyond_vwap(self, S, sym, k, side):
        for j in range(k + 1):
            c, vw = S.state.close(sym, j), S.state.vwap(sym, j)
            if c is None or vw is None or (c - vw) * side <= 0:
                return False
        return True

    def screen(self, S, k):
        out = []
        for sym in S.members:
            c = S.ctx[sym]
            r = S.state.ret_open(sym, k)
            rv = S.state.rvol(sym, k, c.cum_base)
            if r is None or rv is None or rv < 1.2 or abs(r) < 0.5:
                continue
            side = 1 if r > 0 else -1
            if side < 0 and not c.fno:
                continue
            if not self._always_beyond_vwap(S, sym, k, side):
                continue
            sec = S.sector_row(c.sector, k)
            if self.lv("L1") and not (sec and sec["rel"] is not None and sec["rel"] * side > 0
                                      and not (sec["weak"] if side > 0 else sec["strong"])):
                continue
            out.append({"symbol": sym, "side": side, "score": abs(r) * min(rv, 3), "ret": r, "rvol": rv})
        return out

    def confirm(self, S, k, cands):
        keep, drop = [], []
        cond = S.market(k)["condition"]
        for x in cands:
            sym, side = x["symbol"], x["side"]
            r = S.state.ret_open(sym, k)
            if self.lv("L2") and cond not in self.allowed[side]:
                drop.append({**x, "why": f"market is {cond}: not a {'bull' if side > 0 else 'bear'} trend day at 09:40"})
            elif r is None or r * side < 0.5 or not self._always_beyond_vwap(S, sym, k, side):
                drop.append({**x, "why": "lost its side of VWAP or its move by 09:40"})
            else:
                keep.append(x)
        return _top(keep, 5), drop

    def plan(self, S, k, cands):
        out = []
        for x in cands:
            sym, side = x["symbol"], x["side"]
            out.append(Setup(
                strategy=self.id, variant=self.variant, level=self.level, symbol=sym, side=side,
                sector=S.ctx[sym].sector, score=x["score"],
                reason=(f"{x['ret']:+.2f}% since the open with every close {'above' if side > 0 else 'below'} VWAP "
                        f"and {x['rvol']:.1f}x volume on a {'bull' if side > 0 else 'bear'} trend morning; "
                        f"waits for a pullback to VWAP"),
                facts={"ret_open_0930": x["ret"], "rvol_0930": x["rvol"]},
                trigger={"type": "vwap_pullback", "touch_pct": 0.10, "max_above_pct": 0.60},
                entry_lo=None, entry_hi=None, risk_min_pct=0.35, risk_max_pct=1.20, target_R=self.target_R,
                win_from_min=10 * 60, win_to_min=13 * 60 + 30, time_exit_min=15 * 60,
                stop_rule={"type": "pullback", "buf": 0.0015},
                invalidate={"type": "vwap_break", "pct": 0.20,
                            "why": "closed 0.20% through VWAP: the trend broke before a pullback entry"}))
        return _news_filter(self, S, out, want=True)

    def on_bar(self, setup, S, k):
        m = close_min(k)
        b = S.state.bar(setup.symbol, k)
        vw = S.state.vwap(setup.symbol, k)
        if b is None or vw is None:
            return None
        t, o, h, l, c, v = b
        s = setup.side
        if (c - vw * (1 - s * 0.002)) * s < 0:
            return ("invalid", setup.invalidate["why"])
        if m < setup.win_from_min:
            return None
        if m > setup.win_to_min:
            return ("expire", f"no pullback entry by {_hm(setup.win_to_min)}")
        touched = (l <= vw * 1.001) if s > 0 else (h >= vw * 0.999)
        reclaimed = (c > vw and c > o) if s > 0 else (c < vw and c < o)
        if not (touched and reclaimed):
            return None
        if (c - vw * (1 + s * 0.006)) * s > 0:
            return ("missed", f"pullback bar closed {abs(c / vw - 1) * 100:.2f}% from VWAP (limit 0.60%)")
        stop = _stop_price(setup, S, k, c, b)
        lv, why = _levels(setup, c, stop)
        if lv is None:
            return ("skip", why)
        return ("enter", c, lv[0], lv[1], f"bar {_hm(m - 5)}-{_hm(m)} touched VWAP {vw:.2f} and closed back at {c:.2f}")


# ── N04 Failed-gap reversal ───────────────────────────────────────────────────────────────────────────────────

class FailedGap(Strategy):
    id, name, family = "N04", "Failed-gap reversal (no news)", "Failed-gap reversal"
    # a gap-up that fails is a SHORT (side -1); a gap-down that fails is a LONG
    allowed = {1: ("range", "mixed", "bull_trend"), -1: ("range", "mixed", "bear_trend")}
    primary = "L2"

    def screen(self, S, k):
        out = []
        for sym in S.members:
            c = S.ctx[sym]
            orr = S.state.or15(sym)
            o = S.state.open(sym)
            if not orr or not o or not S.state.complete(sym, k):
                continue
            gap = (o / c.prev_close - 1) * 100
            if abs(gap) < max(1.0, 0.5 * c.atr_pct):
                continue
            side = -1 if gap > 0 else 1
            if side < 0 and not c.fno:
                continue
            H, L, O, C = orr
            rv = S.state.rvol(sym, k, c.cum_base)
            if rv is None or rv > 2.5:
                continue
            last = S.state.close(sym, k)
            if (C - O) * side <= 0 or (last - o) * side <= 0:
                continue                                  # opening range must turn against the gap
            sec = S.sector_row(c.sector, k)
            if self.lv("L1"):
                # the gap must not be sector-wide: a sector moving with the gap is information, not a stock shock
                if not sec or sec["up_open"] is None or (sec["up_open"] >= 0.5 if gap > 0 else sec["up_open"] <= 0.5):
                    continue
            out.append({"symbol": sym, "side": side, "gap": gap, "or": orr, "rvol": rv,
                        "score": abs(gap) / max(c.atr_pct, 0.1)})
        return out

    def confirm(self, S, k, cands):
        if not self.lv("L2"):
            return _top(cands, 3), []
        cond = S.market(k)["condition"]
        keep, drop = [], []
        for x in cands:
            sym, side = x["symbol"], x["side"]
            c, vw, o = S.state.close(sym, k), S.state.vwap(sym, k), S.state.open(sym)
            if cond not in self.allowed[side]:
                drop.append({**x, "why": f"market is {cond}: a trend day in the gap's direction"})
            elif c is None or (c - o) * side <= 0 or (c - vw) * side <= 0:
                drop.append({**x, "why": "price recovered its open or VWAP by 09:40: the gap did not fail"})
            else:
                keep.append(x)
        return _top(keep, 3), drop

    def plan(self, S, k, cands):
        out = []
        for x in cands:
            sym, side = x["symbol"], x["side"]
            H, L, O, C = x["or"]
            trig = L if side < 0 else H
            lo, hi = (trig * (1 - 0.003), trig) if side < 0 else (trig, trig * 1.003)
            pc = S.ctx[sym].prev_close
            out.append(Setup(
                strategy=self.id, variant=self.variant, level=self.level, symbol=sym, side=side,
                sector=S.ctx[sym].sector, score=x["score"],
                reason=(f"gapped {x['gap']:+.2f}% on {x['rvol']:.1f}x volume, the opening range turned against the "
                        f"gap and price is back {'below' if side < 0 else 'above'} the open"),
                facts={"gap_pct": x["gap"], "or_high": H, "or_low": L, "prev_close": pc, "rvol_0930": x["rvol"]},
                trigger={"type": "close_below" if side < 0 else "close_above", "level": trig},
                entry_lo=lo, entry_hi=hi, risk_min_pct=0.40, risk_max_pct=2.00, target_R=self.target_R,
                win_from_min=9 * 60 + 50, win_to_min=11 * 60, time_exit_min=13 * 60 + 30,
                stop_rule={"type": "price", "price": H if side < 0 else L},
                target_cap=pc, min_reward_R=1.0,
                invalidate={"type": "close_above" if side < 0 else "close_below", "level": H if side < 0 else L,
                            "why": "price retook the far side of the opening range: the gap held"}))
        return _news_filter(self, S, out, want=False)


# ── N05 Compression -> expansion (NR7 / inside day opening-range breakout) ─────────────────────────────────────

class CompressionORB(Strategy):
    id, name, family = "N05", "Volatility compression then expansion", "Compression breakout"
    allowed = {1: ("bull_trend", "mixed", "range"), -1: ("bear_trend", "mixed", "range")}
    primary = "L2"

    def screen(self, S, k):
        out = []
        for sym in S.members:
            c = S.ctx[sym]
            if not (c.nr7 or c.inside) or c.orw_med_pct is None:
                continue
            orr = S.state.or15(sym)
            if not orr:
                continue
            H, L, O, C = orr
            w = (H - L) / O * 100
            if not (0.25 <= w <= 0.70 * c.orw_med_pct):
                continue
            rv = S.state.rvol(sym, k, c.cum_base)
            if rv is None or rv < 0.8:
                continue
            sides = [1, -1] if c.fno else [1]
            sec = S.sector_row(c.sector, k)
            if self.lv("L1"):
                if not sec or sec["rel"] is None or sec["rel"] == 0:
                    continue
                sides = [s for s in sides if s * sec["rel"] > 0]
            for side in sides:
                out.append({"symbol": sym, "side": side, "or": orr, "orw": w, "rvol": rv, "nr7": c.nr7,
                            "inside": c.inside, "score": c.orw_med_pct / max(w, 0.05)})
        return out

    def confirm(self, S, k, cands):
        if not self.lv("L2"):
            return cands, []
        cond = S.market(k)["condition"]
        keep, drop = [], []
        for x in cands:
            sym = x["symbol"]
            H, L, _, _ = x["or"]
            c = S.state.close(sym, k)
            if cond not in self.allowed[x["side"]]:
                drop.append({**x, "why": f"market is {cond}"})
            elif c is None or not (L <= c <= H):
                drop.append({**x, "why": "price already left the opening range before the plan"})
            else:
                keep.append(x)
        return keep, drop

    def plan(self, S, k, cands):
        out = []
        syms = sorted({x["symbol"] for x in cands}, key=lambda s: -max(y["score"] for y in cands if y["symbol"] == s))
        for sym in syms[:4]:
            for x in (y for y in cands if y["symbol"] == sym):
                side = x["side"]
                H, L, O, C = x["or"]
                c = S.state.close(sym, k)
                if c is not None and not (L <= c <= H):
                    continue
                trig = H if side > 0 else L
                chase = 0.25 * (H - L) + trig * 0.001
                lo, hi = (trig, trig + chase) if side > 0 else (trig - chase, trig)
                out.append(Setup(
                    strategy=self.id, variant=self.variant, level=self.level, symbol=sym, side=side,
                    sector=S.ctx[sym].sector, score=x["score"],
                    reason=(f"{'NR7' if x['nr7'] else 'inside day'} yesterday and a {x['orw']:.2f}% opening range "
                            f"(under 70% of its usual), {x['rvol']:.1f}x volume: two-sided breakout"),
                    facts={"or_high": H, "or_low": L, "or_width_pct": x["orw"], "nr7": x["nr7"],
                           "inside": x["inside"], "rvol_0930": x["rvol"]},
                    trigger={"type": "close_above" if side > 0 else "close_below", "level": trig},
                    entry_lo=lo, entry_hi=hi, risk_min_pct=0.35, risk_max_pct=1.20, target_R=self.target_R,
                    win_from_min=9 * 60 + 50, win_to_min=12 * 60, time_exit_min=15 * 60,
                    stop_rule={"type": "price", "price": L if side > 0 else H, "floor_pct": 0.35},
                    oco=f"N05|{sym}"))
        return _news_filter(self, S, out, want=True)


# ── N06 News-catalyst continuation ────────────────────────────────────────────────────────────────────────────

class NewsCatalyst(Strategy):
    id, name, family = "N06", "News-catalyst continuation", "News-catalyst continuation"
    allowed = {1: ("bull_trend", "mixed", "range"), -1: ("bear_trend", "mixed", "range")}
    uses_news = True
    primary = "L3"

    def screen(self, S, k):
        out = []
        for sym in S.members:
            c = S.ctx[sym]
            orr = S.state.or15(sym)
            o = S.state.open(sym)
            if not orr or not o:
                continue
            gap = (o / c.prev_close - 1) * 100
            if abs(gap) < 1.0:
                continue
            side = 1 if gap > 0 else -1
            if side < 0 and not c.fno:
                continue
            H, L, O, C = orr
            rv = S.state.rvol(sym, k, c.cum_base)
            vw = S.state.vwap(sym, k)
            last = S.state.close(sym, k)
            if rv is None or rv < 2.0 or vw is None or last is None:
                continue
            holds = (L > c.prev_close) if side > 0 else (H < c.prev_close)
            if not holds or (last - vw) * side <= 0:
                continue
            sec = S.sector_row(c.sector, k)
            if self.lv("L1") and sec and (sec["weak"] if side > 0 else sec["strong"]):
                continue
            out.append({"symbol": sym, "side": side, "gap": gap, "or": orr, "rvol": rv, "score": abs(gap) * min(rv, 4)})
        return out

    def confirm(self, S, k, cands):
        if not self.lv("L2"):
            return _top(cands, 3), []
        keep, drop = [], []
        cond = S.market(k)["condition"]
        for x in cands:
            sym, side = x["symbol"], x["side"]
            H, L, _, _ = x["or"]
            mid = (H + L) / 2
            c, vw = S.state.close(sym, k), S.state.vwap(sym, k)
            if cond not in self.allowed[side]:
                drop.append({**x, "why": f"market is {cond}"})
            elif c is None or (c - vw) * side <= 0 or (c - mid) * side <= 0:
                drop.append({**x, "why": "lost VWAP or the opening-range midpoint by 09:40"})
            else:
                keep.append(x)
        return _top(keep, 3), drop

    def plan(self, S, k, cands):
        out = []
        for x in cands:
            sym, side = x["symbol"], x["side"]
            H, L, O, C = x["or"]
            trig = H if side > 0 else L
            lo, hi = (trig, trig * 1.004) if side > 0 else (trig * 0.996, trig)
            out.append(Setup(
                strategy=self.id, variant=self.variant, level=self.level, symbol=sym, side=side,
                sector=S.ctx[sym].sector, score=x["score"],
                reason=(f"gapped {x['gap']:+.2f}% and held it through the opening range on {x['rvol']:.1f}x "
                        f"volume"),
                facts={"gap_pct": x["gap"], "or_high": H, "or_low": L, "rvol_0930": x["rvol"]},
                trigger={"type": "close_above" if side > 0 else "close_below", "level": trig},
                entry_lo=lo, entry_hi=hi, risk_min_pct=0.40, risk_max_pct=2.00, target_R=self.target_R,
                win_from_min=9 * 60 + 50, win_to_min=11 * 60, time_exit_min=15 * 60,
                stop_rule={"type": "price", "price": L if side > 0 else H, "floor_pct": 0.40},
                invalidate={"type": "close_below" if side > 0 else "close_above", "level": (H + L) / 2,
                            "why": "closed back through the opening-range midpoint before triggering"}))
        if self.lv("L3"):
            return _news_filter(self, S, out, want=True, force=True)
        return out


def _top(xs: list[dict], n: int) -> list[dict]:
    """Best n per side by score (ties by symbol)."""
    out = []
    for side in (1, -1):
        out += sorted((x for x in xs if x["side"] == side), key=lambda x: (-x["score"], x["symbol"]))[:n]
    return out


def _news_filter(strat: Strategy, S, setups: list[Setup], want: bool, force: bool = False) -> list[Setup]:
    """L3 (news): continuation rules keep only stocks WITH a material catalyst since the previous close; the
    reversal rule keeps only stocks WITHOUT one. Applied only where the day's announcements are available."""
    if not (strat.lv("L3") or force):
        return setups
    if not S.news_available:
        return []                        # no announcements for the day: an L3 rule cannot be decided, so no setup
    # N06 needs the catalyst BEFORE the open (it explains the gap); the L3 filters use everything known at 09:45
    cats = S.preopen_catalysts if force else S.catalysts
    out = []
    for s in setups:
        has = bool(cats.get(s.symbol))
        if has == want:
            s.facts["catalysts"] = [{"desc": c["desc"], "at": c.get("at")} for c in cats.get(s.symbol, [])][:3]
            s.facts["news_rule"] = ("material announcement before the open" if force else
                                    ("has" if want else "has no") + " material announcement since the previous close")
            out.append(s)
    return out


REGISTRY = {cls.id: cls for cls in (SectorORB, RelativeStrength, TrendDayVWAP, FailedGap, CompressionORB, NewsCatalyst)}
