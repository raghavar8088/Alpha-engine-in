"""The gold channels 21-40 study's strategies (22 Nov 2026), added to the 11-channel registry (yc_strategies) so
yc_run runs them unchanged: the same signal conventions, fill engine, daily limits and forced exits as every channel
book on the paper desk. All trade gold only: XAUUSD in the rules, booked by the desk on Delta Exchange's XAUTUSD.

Every record is version v1: a changed rule or number is a new version, never an edit of v1. readiness "assumptions" =
coded with the A rules of zg_spec.py, which the app shows next to the stated (E) and inferred (I) ones. None was
backtested: paper trading on the desk is their first test.

    import zg_strategies   # registers the records; then yc_run.run(sid, "XAUUSD", m, cache) works for them
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
for _p in (HERE, RESEARCH / "youtube_channels11_2026_11", RESEARCH / "youtube_top20_2026_11",
           RESEARCH / "booming_bulls_2026_11", RESEARCH / "crypto_playlist_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import yc_strategies as YS  # noqa: E402
from yc_strategies import FREE, ONE, YC  # noqa: E402
from yt_engine import Limits  # noqa: E402

import zg_gold as G  # noqa: E402

SOURCE = "youtube_gold"
STUDY = "youtube_gold_2026_11"
A = "assumptions"
L2 = Limits(2, False, False)
L3 = Limits(3, False, False)
PF_LIMITS = Limits(3, False, False, 3)          # PF-01: three a day, none after three stops (her daily loss lock)
GOLD = ("XAUUSD",)


@dataclass
class ZG(YC):
    """A YC record whose channel and video come from this study (the 11-channel PREFIX map does not know them)."""
    video: str = ""
    chan: str = ""

    @property
    def channel(self) -> str:
        return self.chan

    @property
    def channel_name(self) -> str:
        return self.chan


def _r(sid, name, fn, ex, tfs, limits, chan, video, **kw):
    return ZG(sid, name, fn, ex, GOLD, tfs, limits, readiness=A, chan=chan, video=video, **kw)


_NEW = [
    _r("AF-03", "Gold inside-day break: the first 15-minute close beyond the inside day's high (low), stop beyond that "
       "candle, target the mother day's high (low) or 2R", G.af03, G.af03_x, (15, 1440), ONE, "Axia Futures", "Zw-0ImGVUY0"),
    _r("AF-04", "COMEX-hours break of a prior-day high (low) tested at least twice: a fresh 5-minute close beyond it, "
       "stop under the last 30 minutes, target last week's high (low) or 2R", G.af04, G.af04_x, (5, 1440), ONE,
       "Axia Futures", "4nbC_2SoDpM"),
    _r("BO-01", "Anchored VWAP from the last 4-hour swing in a 4-hour trend: a 15-minute candle that retests it against "
       "the trend and closes back, target the last swing or 2R", G.bo01, G.bo01_x, (15, 240), L2,
       "BikoTrading | Futures Trading", "ZQlxKZk0YIY"),
    _r("BO-02", "False breakout of a daily key level (previous day's high / low, last daily swing): back inside within "
       "an hour, entry at the level, stop 2 pips beyond the tail, 4R", G.bo02, G.bo02_x, (15, 1440), L2,
       "BikoTrading | Futures Trading", "mETNGRc9cgU"),
    _r("TO-01", "Daily 9-period MA side; a 1-hour Bollinger Band (20, 2) touch at the previous swing, a $15 stop beyond "
       "it, 1:5 (Delta XAUUSD)", G.to01, G.to01_x, (60, 1440), ONE, "Trading Orbit", "B_rkzkbbYlQ"),
    _r("PF-01", "Claudia's 30-minute engulfing zone: a 5-minute pull back into the candle's body, then two highs "
       "(lows) broken; stop beyond the pull back, target the previous high (low) or 2R", G.pf01, G.pf01_x, (5, 30),
       PF_LIMITS, "PropFirmTrader", "fw9HYrSBVo0"),
    _r("MA-02", "Daily Heikin Ashi direction; a 1-hour Heikin Ashi candle with no wick against it and a bigger body, "
       "beyond the previous day's extreme; held until an opposite-colour candle (swing)", G.ma02, G.ma02_x, (60, 1440),
       FREE, "The Moving Average", "MKJz4yURCEs", overnight=True),
    _r("MA-03", "5-minute scalp: smoothed MAs 21/50/200 fanned out, RSI on the trend's side, a three-line strike; stop "
       "twice the engulfing candle, out on an RSI divergence or after six candles", G.ma03, G.ma03_x, (5,), L3,
       "The Moving Average", "oDOCBTYgCQM"),
    _r("MA-04", "RSI (14) leaves 70 / 30 and closes back inside on 15 minutes: trade toward the middle, stop beyond the "
       "swing it made, 2R", G.ma04, G.ma04_x, (15,), L3, "The Moving Average", "RJH-2TD1fZk"),
    _r("TU-01", "After 8:30 New York an hour sweeps the previous day's high (low) and closes back inside; a 5-minute "
       "fair value gap in the premium (discount); stop on the intermediate high, 2R", G.tu01, G.tu01_x, (5, 60, 1440),
       ONE, "TTrades", "0R61Y6Pn74Q"),
    _r("TU-02", "Fractal model: an hour sweeps the previous hour's high (low) and closes back inside; in the next two "
       "hours a 5-minute close through the run that made the extreme; stop there, 2R (London and New York morning)",
       G.tu02, G.tu02_x, (5, 60), L2, "TTrades", "eywpZT3z6GQ"),
    _r("CA-01", "New York open: the overnight volume profile against the session's at 10:00; when value has moved, a "
       "limit at the overnight point of control, target the session value area's far edge", G.ca01, G.ca01_x, (5,),
       ONE, "Cammy Capital", "J7XAKuYK5O4"),
    _r("CA-02", "Yesterday's premium is today's discount: the session value area low reaches the previous regular "
       "session's value area high (mirror); a limit there, stop at yesterday's point of control", G.ca02, G.ca02_x,
       (5,), ONE, "Cammy Capital", "-_1Pf652IJk"),
    _r("HF-01", "Sweep, break, retest in the 1-hour trend: a 5-minute sweep of the last swing, a close through the swing "
       "on the other side, a limit at half of that leg; target the last 1-hour swing or 2R (kill zones)", G.hf01,
       G.hf01_x, (5, 60), L2, "HANNAH FOREX", "zt9TmyI5-z0"),
    _r("RU-10", "Donchian Channel (20) with the 200 EMA on 30 minutes: the upper band's new high after the lower band's "
       "new low (mirror), stop just beyond the other band, 1.5R", G.ru10, G.ru10_x, (30,), FREE, "TRADING RUSH",
       "icYe2SS3-4M"),
    _r("TQ-05", "Triple Supertrend (12/3, 11/2, 10/1) with the Stochastic RSI and the 200 EMA on 1 hour: a cross out of "
       "20 (80) with two Supertrends agreeing, stop at the second line, 1.5R", G.tq05, G.tq05_x, (60,), FREE,
       "Trade Pro", "HpNZ2VpZzSE"),
]
NEW = [r.sid for r in _NEW]
VIDEO = {r.sid: r.video for r in _NEW}

for _rec in _NEW:
    _rec.version = "v1"
    if _rec.sid in YS.STRATEGIES and YS.STRATEGIES[_rec.sid] is not _rec:
        raise RuntimeError(f"{_rec.sid} is already registered by another study")
    YS.STRATEGIES[_rec.sid] = _rec
