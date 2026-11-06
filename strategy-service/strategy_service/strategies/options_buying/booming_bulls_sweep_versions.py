"""Versions of Booming Bulls D9 (`bb_liquidity_sweep`): each is the original with ONE rule changed.

The original class in booming_bulls.py is untouched. `LiquiditySweepVersion` (not registered) is the
engine behind every version. It is a subclass of the original that adds switches for:
- the level set and the confirmation;
- the target, a breakeven stop and an entry time window;
- the video's breakout-and-retest entry.

With every switch at its default it reproduces the original signal for signal; that is checked over
2016-2026 by backend/research/liquidity_sweep_2026_11/ls_versions_verify.py. The versions and the test
that scores them are fixed in backend/research/liquidity_sweep_2026_11/PREREGISTRATION_VERSIONS.md.
"""

import math
from datetime import timezone
from typing import Literal

from pydantic import Field

from strategy_service.strategies.options_buying._base import OptionBuyStrategy, buy_meta
from strategy_service.strategies.options_buying.booming_bulls import _IST, BbLiquiditySweep, _Level
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import SignalAction, Timeframe

_LEVEL_TYPE = {"PDH": "pdhl", "PDL": "pdhl", "PDC": "pdc", "EQH": "eq", "EQL": "eq",
               "1H high": "1h", "1H low": "1h", "R100": "round"}
_ROUND = "R100"
Confirm = Literal["close", "next", "retest", "mss"]
TargetMode = Literal["rr", "opposite", "none"]
Mode = Literal["sweep", "break_retest", "both"]


class LiquiditySweepVersion(BbLiquiditySweep):
    """The engine behind every version (not registered itself). Defaults = the original D9."""

    class Params(BbLiquiditySweep.Params):
        level_types: str = Field(default="pdhl,pdc,eq,1h", description="liquidity kinds used: pdhl, pdc, eq, 1h, round")
        round_step: float = Field(default=100.0, gt=0, description="round-number spacing ('round' levels)")
        round_band_pct: float = Field(default=1.0, gt=0, description="round numbers within this % of the open")
        confirm: Confirm = Field(default="close", description="close | next (next candle) | retest | mss (structure shift)")
        mss_lookback: int = Field(default=6, ge=1, description="candles before the sweep that set the structure ('mss')")
        confirm_window_minutes: int = Field(default=30, ge=1, description="how long a 'retest' / 'mss' setup waits")
        min_reject_frac: float = Field(default=0.0, ge=0, le=1, description="entry candle must close this fraction of its range from its extreme")
        first_entry_minute: int = Field(default=0, ge=0, description="IST minute an entry candle must close at/after (0 = none)")
        target_mode: TargetMode = Field(default="rr", description="rr (reward_risk) | opposite (next opposite liquidity, 1-4R) | none")
        breakeven_r: float = Field(default=0.0, ge=0, description=">0: stop to entry after a candle closes having reached +breakeven_r R")
        mode: Mode = Field(default="sweep", description="sweep | break_retest (the video's breakout-and-retest) | both")

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._types = {t.strip() for t in self.params.level_types.split(",") if t.strip()}
        self._pending: dict | None = None   # a swept level waiting for next / retest / mss confirmation
        self._watch: list[dict] = []        # broken levels waiting for a retest (break_retest / both)

    def on_bar(self, ctx: StrategyContext):
        signal = OptionBuyStrategy.on_bar(self, ctx)
        if signal is not None and self._pos is not None and signal.signal in (SignalAction.BUY, SignalAction.SELL):
            signal.stop_loss = round(self._pos["stop"], 2)
            signal.target = None if self._pos["target"] is None else round(self._pos["target"], 2)
        return signal

    # -- the candle loop: the original's, with entries routed through _decide ----------

    def _step(self, bar, live: bool) -> int | None:
        p = self.params
        self._last_ts = bar.ts
        ts = bar.ts if bar.ts.tzinfo else bar.ts.replace(tzinfo=timezone.utc)
        t = ts.astimezone(_IST)
        minute = t.hour * 60 + t.minute
        end = minute + p.bar_minutes
        if t.date() != self._day:
            self._new_session(t.date(), bar.open)
        self._n += 1
        n = self._n
        self._hi, self._lo, self._close = max(self._hi, bar.high), min(self._lo, bar.low), bar.close
        self._bars.append((n, self._sn, bar.high, bar.low))
        self._update_ema(bar.close)

        swept = self._run_levels(bar)
        self._find_swings(minute, end, bar)

        if self._pos is not None:
            return self._manage(bar, n, end)
        if not live:
            return 0
        return self._decide(bar, n, minute, end, swept)

    # -- levels ------------------------------------------------------------------------

    def _new_session(self, day, open_price: float) -> None:
        if "round" in self._types:          # round numbers are day levels, like PDH/PDL/PDC
            for lv in self._levels:
                lv.src = [s for s in lv.src if s[0] != _ROUND]
            self._levels = [lv for lv in self._levels if lv.src]
            for lv in self._levels:
                lv.reprice()
        super()._new_session(day, open_price)
        self._pending = None
        self._watch = []
        if "round" in self._types:
            p = self.params
            band = open_price * p.round_band_pct / 100
            k = math.ceil((open_price - band) / p.round_step)
            while k * p.round_step <= open_price + band:
                level = k * p.round_step
                if level != open_price:
                    self._add(+1 if level > open_price else -1, _ROUND, level)
                k += 1

    def _add(self, kind: int, name: str, price: float) -> None:
        if _LEVEL_TYPE.get(name) in self._types:
            super()._add(kind, name, price)

    def _run_levels(self, bar) -> list[_Level]:
        before = self._levels
        swept = super()._run_levels(bar)
        if self.params.mode != "sweep":
            for lv in before:
                if lv.state == "broken":    # accepted beyond for the full window: watch for its retest
                    self._watch.append({"kind": lv.kind, "level": lv.price, "names": lv.names, "n": self._n})
        return [] if self.params.mode == "break_retest" else swept

    # -- entries -----------------------------------------------------------------------

    def _decide(self, bar, n: int, minute: int, end: int, swept: list[_Level]) -> int:
        if self._pending is not None:
            side = self._try_pending(bar, n, minute, end)
            if side:
                return side
        if self._watch:
            side = self._try_watch(bar, n, minute, end)
            if side:
                return side
        if not swept:
            return 0
        if self.params.confirm == "close":
            return self._enter_v(bar, n, minute, end, swept)
        return self._arm(bar, n, minute, end, swept)

    def _enter_v(self, bar, n: int, minute: int, end: int, levels: list[_Level]) -> int:
        """The original entry (sizing, risk band, EMA, 2-a-day) behind the versions' extra filters."""
        p = self.params
        if p.first_entry_minute and end < p.first_entry_minute:
            return 0
        kinds = {lv.kind for lv in levels}
        if p.min_reject_frac > 0 and len(kinds) == 1:
            kind = next(iter(kinds))
            rng = bar.high - bar.low
            away = (bar.high - bar.close) if kind > 0 else (bar.close - bar.low)
            if rng <= 0 or away < p.min_reject_frac * rng:
                return 0
        side = super()._enter(bar, n, minute, end, levels)
        if side:
            pos = self._pos
            pos["risk"] = abs(pos["entry"] - pos["stop"])
            if p.target_mode != "rr":
                self._retarget(pos)
        return side

    def _retarget(self, pos: dict) -> None:
        side, entry, risk = pos["side"], pos["entry"], pos["risk"]
        if self.params.target_mode == "none":
            target, label = None, "no target: stop or square-off"
        else:   # the nearest live opposite-side level at least 1R away, capped at 4R
            far = entry + side * 4 * risk
            near = [lv.price for lv in self._levels
                    if lv.state == "armed" and lv.kind == side and side * (lv.price - entry) >= risk]
            if near:
                best = min(near) if side > 0 else max(near)
                target = best if side * (best - far) <= 0 else far
            else:
                target = far
            label = f"target {target:.2f} = opposite liquidity, {abs(target - entry) / risk:.1f}R"
        pos["target"] = target
        self.last_plan["target"] = target
        self.why = self.why.rsplit(", target ", 1)[0] + f", {label}"

    def _arm(self, bar, n: int, minute: int, end: int, swept: list[_Level]) -> int:
        """A sweep closed back inside: hold it for the version's extra confirmation."""
        p = self.params
        kinds = {lv.kind for lv in swept}
        if len(kinds) != 1:
            return 0
        kind = kinds.pop()
        high_side = kind > 0
        pend = {"kind": kind, "levels": swept, "n": n, "close": bar.close,
                "level": min(lv.price for lv in swept) if high_side else max(lv.price for lv in swept),
                "extreme": max(lv.extreme for lv in swept) if high_side else min(lv.extreme for lv in swept),
                "until": n + (1 if p.confirm == "next" else max(1, math.ceil(p.confirm_window_minutes / p.bar_minutes)))}
        if p.confirm == "mss":
            breach_n = n - max(lv.beyond for lv in swept)          # the first candle beyond the level
            base = self._bars[0][0]
            prior = self._bars[max(0, breach_n - p.mss_lookback - base): max(0, breach_n - base)]
            if not prior:
                return 0
            pend["ref"] = min(b[3] for b in prior) if high_side else max(b[2] for b in prior)
            if (bar.close < pend["ref"]) if high_side else (bar.close > pend["ref"]):
                return self._enter_v(bar, n, minute, end, swept)   # the confirming candle already broke structure
        self._pending = pend
        return 0

    def _try_pending(self, bar, n: int, minute: int, end: int) -> int:
        pend = self._pending
        if n <= pend["n"]:
            return 0
        if n > pend["until"]:
            self._pending = None
            return 0
        high_side = pend["kind"] > 0
        level = pend["level"]
        if (bar.close > level) if high_side else (bar.close < level):
            self._pending = None            # closed beyond the level again: accepted, setup cancelled
            return 0
        pend["extreme"] = max(pend["extreme"], bar.high) if high_side else min(pend["extreme"], bar.low)
        mode = self.params.confirm
        if mode == "next":
            ok = (bar.close < pend["close"]) if high_side else (bar.close > pend["close"])
        elif mode == "retest":
            ok = (bar.high >= level and bar.close < level) if high_side else (bar.low <= level and bar.close > level)
        else:   # mss
            ok = (bar.close < pend["ref"]) if high_side else (bar.close > pend["ref"])
        if not ok:
            if mode == "next":
                self._pending = None
            return 0
        self._pending = None
        for lv in pend["levels"]:
            lv.extreme = pend["extreme"]
        return self._enter_v(bar, n, minute, end, pend["levels"])

    def _try_watch(self, bar, n: int, minute: int, end: int) -> int:
        """The video's breakout-and-retest: a level that broke and held, retested and respected."""
        keep, traded = [], 0
        for w in self._watch:
            if traded or n <= w["n"]:
                keep.append(w)
                continue
            broke_up = w["kind"] > 0         # a high that broke upward is support now: long on its retest
            level = w["level"]
            if (bar.close <= level) if broke_up else (bar.close >= level):
                continue                     # closed back through: the breakout failed, watch dropped
            if not ((bar.low <= level) if broke_up else (bar.high >= level)):
                keep.append(w)
                continue
            # the retest happened (touched, closed on the breakout side): traded or not, this watch is done
            probe = _Level(-w["kind"], f"{w['names']} retest", level, self._sn)
            probe.state, probe.extreme = "swept", (bar.low if broke_up else bar.high)
            side = self._enter_v(bar, n, minute, end, [probe])
            if side:
                traded = side
                pos = self._pos
                tgt = "no target" if pos["target"] is None else f"target {pos['target']:.2f}"
                self.why = (f"{w['names']} {level:.2f} broke and held; retest to {probe.extreme:.2f} closed "
                            f"{'above' if broke_up else 'below'} at {bar.close:.2f}: "
                            f"{'long (buy CE)' if side > 0 else 'short (buy PE)'}, stop {pos['stop']:.2f}, {tgt}")
        self._watch = keep
        return traded

    # -- exits -------------------------------------------------------------------------

    def _manage(self, bar, n: int, end: int) -> int | None:
        p = self.params
        pos = self._pos
        if p.breakeven_r <= 0 and pos["target"] is not None:
            return super()._manage(bar, n, end)
        if n == pos["n"]:
            return None
        short = pos["side"] < 0
        stop_hit = bar.high >= pos["stop"] if short else bar.low <= pos["stop"]
        target_hit = pos["target"] is not None and (bar.low <= pos["target"] if short else bar.high >= pos["target"])
        if stop_hit:
            why = f"{'breakeven ' if pos.get('be') else ''}stop {pos['stop']:.2f} hit"
        elif target_hit:
            why = f"target {pos['target']:.2f} reached"
        elif end >= p.square_off_minute:
            why = f"square-off at {bar.close:.2f}"
        else:
            if p.breakeven_r > 0 and not pos.get("be"):
                trigger = pos["entry"] + pos["side"] * p.breakeven_r * pos["risk"]
                if (bar.low <= trigger) if short else (bar.high >= trigger):
                    pos["stop"], pos["be"] = pos["entry"], True   # from the next candle on
            return None
        self._pos = None
        self.why = why
        return 0


# ── the registered versions (PREREGISTRATION_VERSIONS.md) ─────────────────────────────────

def _meta(sid: str, label: str, change: str):
    return buy_meta(sid, f"Booming Bulls: Liquidity Sweep {label}", "options_intraday",
                    f"{change} Everything else as the original bb_liquidity_sweep (D9).", Timeframe.M5, "range-bound")


@register_strategy
class BbLsV01PdhPdl(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v01_pdh_pdl", "v01 — PDH/PDL only", "Only the previous day's high and low count as liquidity.")

    class Params(LiquiditySweepVersion.Params):
        level_types: str = "pdhl"


@register_strategy
class BbLsV02PdcOnly(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v02_pdc_only", "v02 — PDC only", "Only the previous day's close counts as liquidity.")

    class Params(LiquiditySweepVersion.Params):
        level_types: str = "pdc"


@register_strategy
class BbLsV03EqualHl(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v03_equal_hl", "v03 — equal highs/lows only", "Only equal highs and equal lows count as liquidity.")

    class Params(LiquiditySweepVersion.Params):
        level_types: str = "eq"


@register_strategy
class BbLsV04HourSwings(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v04_1h_swings", "v04 — 1-hour swings only", "Only 1-hour swing highs and lows count as liquidity.")

    class Params(LiquiditySweepVersion.Params):
        level_types: str = "1h"


@register_strategy
class BbLsV05RoundNumbers(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v05_round_numbers", "v05 — plus round numbers",
                     "Adds every multiple of 100 within 1% of the open as a level (the PDF's round-number traps).")

    class Params(LiquiditySweepVersion.Params):
        level_types: str = "pdhl,pdc,eq,1h,round"


@register_strategy
class BbLsV06WickOnly(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v06_wick_only", "v06 — wick sweeps only",
                     "The sweep candle itself must close back inside; a candle closing beyond is a breakout.")

    class Params(LiquiditySweepVersion.Params):
        max_minutes_beyond: int = 5


@register_strategy
class BbLsV07StrongReject(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v07_strong_reject", "v07 — strong rejection candle",
                     "The confirming candle must close in the third of its range furthest from the sweep.")

    class Params(LiquiditySweepVersion.Params):
        min_reject_frac: float = 2 / 3


@register_strategy
class BbLsV08NextCandle(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v08_next_candle", "v08 — next-candle confirmation",
                     "Enter only if the candle after the confirming candle closes further in the trade's direction.")

    class Params(LiquiditySweepVersion.Params):
        confirm: Confirm = "next"


@register_strategy
class BbLsV09RetestEntry(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v09_retest_entry", "v09 — retest-and-reject entry",
                     "After the close back inside, wait up to 30 minutes for a retest of the level that closes back inside again.")

    class Params(LiquiditySweepVersion.Params):
        confirm: Confirm = "retest"


@register_strategy
class BbLsV10Mss(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v10_mss", "v10 — market-structure shift",
                     "Enter on a close past the low (high) of the 6 candles before the sweep, within 30 minutes.")

    class Params(LiquiditySweepVersion.Params):
        confirm: Confirm = "mss"


@register_strategy
class BbLsV11Target1R(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v11_target_1r", "v11 — target 1:1", "Target at 1x the risk instead of 2x.")

    class Params(LiquiditySweepVersion.Params):
        reward_risk: float = 1.0


@register_strategy
class BbLsV12Target3R(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v12_target_3r", "v12 — target 1:3", "Target at 3x the risk instead of 2x.")

    class Params(LiquiditySweepVersion.Params):
        reward_risk: float = 3.0


@register_strategy
class BbLsV13Breakeven(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v13_breakeven", "v13 — breakeven at +1R",
                     "Once a candle closes after price reached +1R, the stop moves to the entry price.")

    class Params(LiquiditySweepVersion.Params):
        breakeven_r: float = 1.0


@register_strategy
class BbLsV14OppositeLiquidity(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v14_opposite_liq", "v14 — target the opposite liquidity",
                     "Target the nearest live level on the other side at least 1R away, capped at 4R.")

    class Params(LiquiditySweepVersion.Params):
        target_mode: TargetMode = "opposite"


@register_strategy
class BbLsV15NoTarget(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v15_no_target", "v15 — no target", "No target: the trade ends at its stop or at 15:15.")

    class Params(LiquiditySweepVersion.Params):
        target_mode: TargetMode = "none"


@register_strategy
class BbLsV16Ema200(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v16_ema200", "v16 — 200-EMA side",
                     "Longs only above the 5-minute 200 EMA, shorts only below it.")

    class Params(LiquiditySweepVersion.Params):
        ema_filter: int = 200


@register_strategy
class BbLsV17BigSweeps(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v17_big_sweeps", "v17 — big sweeps only",
                     "Only trades risking 0.15-0.35% of price (PDF-sized sweeps).")

    class Params(LiquiditySweepVersion.Params):
        min_risk_pct: float = 0.15


@register_strategy
class BbLsV18Morning(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v18_morning", "v18 — morning only", "Entries only from candles closing 09:20-11:15.")

    class Params(LiquiditySweepVersion.Params):
        last_entry_minute: int = 11 * 60 + 15


@register_strategy
class BbLsV19Afternoon(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v19_afternoon", "v19 — afternoon only", "Entries only from candles closing 12:05-14:45.")

    class Params(LiquiditySweepVersion.Params):
        first_entry_minute: int = 12 * 60 + 5


@register_strategy
class BbLsV20OneADay(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v20_one_a_day", "v20 — one trade a day", "At most one trade a day.")

    class Params(LiquiditySweepVersion.Params):
        max_trades_per_day: int = 1


@register_strategy
class BbLsV21BreakRetest(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v21_break_retest", "v21 — breakout and retest",
                     "The video's other entry instead of the sweep: a level broken and held for 30 minutes, then "
                     "retested and respected, traded in the breakout direction.")

    class Params(LiquiditySweepVersion.Params):
        mode: Mode = "break_retest"


@register_strategy
class BbLsV22FullVideo(LiquiditySweepVersion):
    metadata = _meta("bb_ls_v22_full_video", "v22 — full video system",
                     "Both of the video's entries: sweep reversals and breakout-retests, one position at a time.")

    class Params(LiquiditySweepVersion.Params):
        mode: Mode = "both"
