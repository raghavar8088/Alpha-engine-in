"""The strategies of the four-topic intraday study (Nov 2026): NIFTY intraday option buying, NSE stock intraday,
bitcoin intraday and MCX commodity intraday, one record each, added to the 11-channel registry (yc_strategies) so
yc_run runs them unchanged: the same signal conventions, fill engine (fill-order books), daily limits and forced exits
as the books already on the paper desk.

Every record is version v1; a changed rule or number is a new version, never an edit of v1. readiness: "ready" = every
rule stated in the video; "assumptions" = coded with the card's 'A' rules (cards/<video>.txt). Blocked strategies (data
the desk does not have, or no testable rule) and duplicates of the library are listed in BLOCKED / DUPLICATES and never
trade. Option-buying videos trade the NIFTY index as a labelled proxy (no intraday option premiums on the desk).

    import zd_strategies   # registers the records; then yc_run.run(sid, market, m, cache) works for them
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "youtube_channels20_2026_11", HERE.parent / "youtube_channels11_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import zd_common as Z  # noqa: E402  (sets the import paths first)

import yc_run as R  # noqa: E402
import yc_strategies as YS  # noqa: E402
from yc_common import END_X  # noqa: E402,F401
from yc_strategies import FREE, ONE, YC  # noqa: E402
from yt_engine import Limits  # noqa: E402

import zd_btc as ZB  # noqa: E402
import zd_cardlib as CL  # noqa: E402
import zd_mcx as ZM  # noqa: E402
import zd_nifty as ZN  # noqa: E402
import zd_stocks as ZS  # noqa: E402

SOURCE = "youtube_intraday4"
STUDY = "youtube_intraday4_2026_11"
TOPICS = {"OB": "nifty_option_buying", "SI": "stock_intraday", "BI": "btc_intraday", "CI": "commodity_intraday"}
TOPIC_LABEL = {"nifty_option_buying": "NIFTY intraday option buying", "stock_intraday": "Indian stock intraday",
               "btc_intraday": "Bitcoin intraday", "commodity_intraday": "MCX commodity intraday"}
A = "assumptions"


@dataclass
class ZD(YC):
    """A YC record whose channel comes from its own video (this study is organised by topic, not by channel)."""
    video: str = ""
    chan: str = ""

    @property
    def channel(self) -> str:
        return self.chan

    @property
    def channel_name(self) -> str:
        return self.chan


def _r(sid, name, fn, ex, markets, tfs, limits=FREE, **kw):
    return ZD(sid, name, fn, ex, markets, tfs, limits, **kw)


L2 = Limits(2)                       # a second trade only after a stop, none after a target
L3 = Limits(3, False, False)         # up to three trades a day, one at a time
STOP_DAY = Limits(99, False, False, 1)   # any number of trades until the first stop of the day
NOON = ("ist", 12 * 60)
TWO_PM = ("ist", 14 * 60)

_NEW = [
    # ── NIFTY intraday option buying (index proxy) ──
    _r("OB-01", "NIFTY 9:30 premium-180 breakout (index proxy, delta 0.6)", ZN.ob01, ZN.ob01_x, ("NIFTY",), (1,), ONE, readiness=A),
    _r("OB-03", "Williams %R (280) overbought on 60, 20 and 5 minutes (index proxy)", ZN.ob03, ZN.ob03_x, ("NIFTY",), (5, 20, 60),
       ONE, readiness=A),
    _r("OB-04", "NIFTY 14:55 five-minute candle breakout, out at 15:15", ZN.ob04, ZN.ob04_x, ("NIFTY",), (5,), ONE, readiness=A),
    _r("OB-06", "ADX turning up + breakout + big candle, 15 minutes (index proxy)", ZN.ob06, ZN.ob06_x, ("NIFTY",), (15,), ONE,
       readiness=A),
    _r("OB-08", "Supertrend (10, 1) + (10, 3) fresh flip with a strong candle, 5 minutes", ZN.ob08, ZN.ob08_x, ("NIFTY",), (5,),
       readiness=A),
    _r("OB-09", "2-minute EMA 10/20 pullback after a stop hunt, star or engulfing", ZN.ob09, ZN.ob09_x, ("NIFTY",), (2,), L3,
       clock=NOON, readiness=A),
    _r("OB-10", "VWAP + EMA 5/13 cross + RSI 50, EMA 5 trail, 5 minutes", ZN.ob10, ZN.ob10_x, ("NIFTY",), (5,), L3, readiness=A),
    # ── Indian stock intraday ──
    _r("SI-01", "9:25 top-mover body-range breakout, no-gap stocks, half at 1%", ZS.si01, ZS.si01_x, ("NSE5",), (5,), ONE,
       needs=("zd_movers925", "zd_nifty"), readiness=A),
    _r("SI-02", "Fixed watchlist: opening-range break on the VWAP side, pullback engulfing", ZS.si02, ZS.si02_x, ("NSE5",), (5,),
       ONE, needs=("zd_turnover",), readiness=A),
    _r("SI-04", "NIFTY first-candle colour, top three movers, second 15-minute candle break", ZS.si04, ZS.si04_x, ("NSE15",),
       (15,), ONE, needs=("zd_movers930", "zd_nifty"), readiness=A),
    _r("SI-06", "SMMA 11/21 cross on the side of the 15-minute SMA 21", ZS.si06, ZS.si06_x, ("NSE5", "NIFTY"), (5, 3, 15),
       readiness=A),
    _r("SI-08", "Previous afternoon range around VWAP: break, pullback, engulfing", ZS.si08, ZS.si08_x, ("NSE5", "NIFTY"), (5,),
       ONE, needs=("zd_turnover",), readiness=A),
    _r("SI-10", "Breadth side, previous-day high/low broken by two same-colour candles", ZS.si10, ZS.si10_x, ("NSE5",), (5,), ONE,
       needs=("zd_movers925",), readiness=A),
    _r("SI-11", "9:30 open-equals-low gainer: first 15-minute candle breakout, out 14:00", ZS.si11, ZS.si11_x, ("NSE5",), (5,),
       ONE, needs=("zd_ol930",), clock=TWO_PM, readiness=A),
    _r("SI-12", "Top mover's 9:20 candle on the VWAP side, 1.5R then 2R", ZS.si12, ZS.si12_x, ("NSE5",), (5,), ONE,
       needs=("zd_movers925", "zd_nifty"), readiness=A),
    _r("SI-13", "First-hour (9:15-10:15) range breakout, opposite-side stop, out at 15:15", ZN.si13, ZN.si13_x,
       ("NIFTY", "BANKNIFTY"), (1, 60), ONE),
    # ── bitcoin intraday ──
    _r("BI-01", "Bitcoin 4-hour opening range (05:30-09:30 IST), 15-minute breakout, 2 ATR stop", ZB.bi01, ZB.bi01_x,
       ("BTCUSD",), (15, 240), ONE, readiness=A),
    _r("BI-02", "Fresh 15-minute zone inside a 4-hour supply/demand zone, reversal candle", ZB.bi02, ZB.bi02_x, ("BTCUSD",),
       (15, 240), readiness=A),
    _r("BI-04", "Bollinger W/M fakeout and neckline break, 5 minutes", ZB.bi04, ZB.bi04_x, ("BTCUSD",), (5,), readiness=A),
    _r("BI-06", "Two-candle turn through EMA 6, 1 hour, 3R", ZB.bi06, ZB.bi06_x, ("BTCUSD",), (60,), STOP_DAY, readiness=A),
    _r("BI-07", "Three-candle zone retest with a rejection candle, 5 minutes, 3R", ZB.bi07, ZB.bi07_x, ("BTCUSD",), (5,),
       readiness=A),
    _r("BI-08", "5-minute multi-touch level, 1-minute structure breakout", ZB.bi08, ZB.bi08_x, ("BTCUSD",), (1, 5), L3,
       readiness=A),
    _r("BI-09", "SMA 100 + 15-minute Heikin Ashi + MACD cross, 5 minutes, 2R", ZB.bi09, ZB.bi09_x, ("BTCUSD",), (5, 15),
       readiness=A),
    # ── MCX commodity intraday ──
    _r("CI-01", "Crude oil 1-hour MACD side, fresh 15-minute MACD crosses", ZM.ci01, ZM.ci01_x, ("MCXCRUDE",), (15, 60),
       overnight=True, readiness=A),
    _r("CI-02", "Crude oil 66 average slope + Stochastic 75/35 re-cross, 1:2", ZM.ci02, ZM.ci02_x, ("MCXCRUDE",), (15,),
       readiness=A),
    _r("CI-03", "Crude oil 17:30 IST 30-minute candle, 50% side, 3-minute break, 1:2", ZM.ci03, ZM.ci03_x, ("MCXCRUDE",),
       (3, 30), L2, readiness=A),
    _r("CI-04", "Crude oil Donchian-200 extreme on 20 minutes, 5-minute EMA 9 reversal", ZM.ci04, ZM.ci04_x, ("MCXCRUDE",),
       (5, 20), readiness=A),
    _r("CI-05", "Crude oil two-candle rejection after 12:00 IST, 15 minutes, 1.5R", ZM.ci05, ZM.ci05_x, ("MCXCRUDE",), (15,), L2,
       readiness=A),
    _r("CI-06", "Crude oil RSI 60/40 cross on the SMA 89 side, 18:00-22:00 IST", ZM.ci06, ZM.ci06_x, ("MCXCRUDE",), (15,),
       readiness=A),
    _r("CI-07", "Natural gas MFI(140) zone + Supertrend + EMA 9/26 cross, 1 hour", ZM.ci07, ZM.ci07_x, ("MCXNG",), (60,),
       overnight=True, readiness=A),
    _r("CI-08", "Crude oil 6.5% stretch from the 200 average + slow Stochastic RSI", ZM.ci08, ZM.ci08_x, ("MCXCRUDE",), (15,),
       overnight=True, readiness=A),
    _r("CI-10", "Silver Micro 18:30 IST candle breakout, stop and reverse once, 1:2", ZM.ci10, ZM.ci10_x, ("MCXSILVER",), (5, 30),
       L2, readiness=A),
    _r("CI-12", "Crude oil first bald green candle after a red series, 15-minute scalp", ZM.ci12, ZM.ci12_x, ("MCXCRUDE",), (15,),
       readiness=A),
]

# blocked: no account. The reasons are the desk's data, not the video's quality.
BLOCKED = {
    "OB-02": "a BTST on NIFTY weekly option premiums (Rs 62.5 strike selection, +50% premium trigger, next-morning exit): needs "
             "NIFTY option premiums by strike, intraday and overnight; the desk has no option-price path",
    "OB-07": "the buy/sell day filter and both triggers are read from the intraday ATM straddle premium chart (call + put), "
             "which the desk does not have",
    "OB-11": "expiry-day 'gamma blast' on sub-Rs 10 options chosen by their theta: needs option premiums and Greeks by strike",
    "SI-05": "stock selection by intraday futures open-interest build-up, which the desk does not have; the entry candle is "
             "not defined beyond an EMA stack",
    "CI-11": "the entry confirmation is not given and the auto-captions are too garbled to recover exact rules",
}

NEW = [r.sid for r in _NEW]


def _attach_cards():
    by = {}
    for c in CL.all_cards():
        meta = CL.video_meta(c["video"])
        for s in c["strategies"]:
            by[s["sid"]] = (c["video"], meta.get("channel") or "")
    for r in _NEW:
        r.video, r.chan = by.get(r.sid, ("", ""))
        r.version = "v1"


_attach_cards()
for _rec in _NEW:
    if _rec.sid in YS.STRATEGIES:
        raise RuntimeError(f"{_rec.sid} is already registered by another study")
    YS.STRATEGIES[_rec.sid] = _rec
for _mk in Z.MCX_MARKETS:
    YS.INTRADAY_CLOCK.setdefault(_mk, Z.MCX_X)


def duplicates() -> dict:
    """{sid: (library strategy it repeats, why)} from the cards."""
    out = {}
    for c in CL.all_cards():
        for s in c["strategies"]:
            if s["duplicate"]:
                out[s["sid"]] = (s["duplicate"]["of"], s["duplicate"]["why"])
    return out


DUPLICATES = duplicates()

# the pool contexts this study's books read, added to the desk's own (yc_run.contexts)
_orig_contexts = R.contexts


def _contexts(needs, *, nifty=None, nsed=None, pool=None, since=None, symbols=None):
    out = _orig_contexts(needs, nifty=nifty, nsed=nsed, pool=pool, since=since, symbols=symbols)
    zn = {n for n in needs if str(n).startswith("zd_")}
    if zn:
        out.update(Z.zd_contexts(zn, pool=pool, nifty=nifty))
    return out


if getattr(R.contexts, "__name__", "") != "_contexts":
    R.contexts = _contexts
