"""The strategies of the channel-shortlist study (Nov 2026): the owner's three pasted lists of YouTube channels (127
unique), one or more videos per channel read in full from their captions, each distinct method a record added to the
11-channel registry (yc_strategies) so yc_run runs it unchanged: the same signal conventions, fill engine (fill-order
books), daily limits and forced exits as the books already on the paper desk.

Every record is version v1; a changed rule or number is a new version, never an edit of v1. readiness: "ready" = every
rule stated in the video; "assumptions" = coded with the card's 'A' rules (cards/<video>.txt). Cards that teach no
testable rule (concept_only / not_testable) or need data the desk lacks are listed in BLOCKED; strategies that repeat
the library are in DUPLICATES; neither trades.

    import ze_strategies   # registers the records; then yc_run.run(sid, market, m, cache) works for them
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "youtube_intraday4_2026_11", HERE.parent / "youtube_channels20_2026_11",
           HERE.parent / "youtube_channels11_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ze_common as E  # noqa: E402  (sets the import paths first)

import yc_run as R  # noqa: E402
import yc_strategies as YS  # noqa: E402
from yc_strategies import FREE, ONE, YC  # noqa: E402
from yt_engine import Limits  # noqa: E402

import ze_cardlib as CL  # noqa: E402
import ze_global as G  # noqa: E402
import ze_india as N  # noqa: E402
import ze_more as X  # noqa: E402
import ze_more2 as X2  # noqa: E402

SOURCE = "youtube_shortlist"
STUDY = "youtube_shortlist_2026_11"
A = "assumptions"


@dataclass
class ZE(YC):
    """A YC record whose channel comes from its own video."""
    video: str = ""
    chan: str = ""

    @property
    def channel(self) -> str:
        return self.chan

    @property
    def channel_name(self) -> str:
        return self.chan


def _r(sid, name, fn, ex, markets, tfs, limits=FREE, **kw):
    return ZE(sid, name, fn, ex, markets, tfs, limits, **kw)


L2 = Limits(2, False, False)
L3 = Limits(3, False, False)
L4 = Limits(4, False, False)
IX = ("NIFTY", "BANKNIFTY")
FX = ("EURUSD", "GBPUSD")

_NEW = [
    # ── Indian index (Nifty, Bank Nifty; option-buying videos trade the index as a labelled proxy) ──
    _r("DF-02", "RSI(14) back through 30/70 on 5 minutes, swing stop with a points filter, VWAP then 200 EMA", N.df02,
       N.df02_x, IX, (5,), L3, readiness=A),
    _r("PW-01", "Previous close's last swing (or last-three-candle range) break, no gap entries, 1:1 (index proxy)",
       N.pw01, N.pw01_x, IX, (1, 15), L3, readiness=A),
    _r("DH-09", "BB Trend (100, 250) side + fresh MACD (48, 104, 36) cross, part at a fixed target, EMA 5/15 trail",
       N.dh09, N.dh09_x, IX, (5,), L3, readiness=A),
    _r("DH-10", "9:15-9:30 opening range edges + Hull MA colour flips, one minute", N.dh10, N.dh10_x, IX, (1,), L3,
       readiness=A),
    _r("CK-01", "Connors RSI (3, 2, 100) 80/20 signals in the direction of RSI(14) above 60 / below 40, 5 minutes",
       N.ck01, N.ck01_x, IX, (5,), L4, readiness=A),
    _r("EC-01", "Supertrend signals only at pivot support or on a resistance break, Heikin Ashi candles", N.ec01,
       N.ec01_x, IX, (5,), L3, readiness=A),
    _r("PC-01", "Trending day, pin bar at a sloping 20 MA, candle stop, quick exit", N.pc01, N.pc01_x, IX, (5,), L3,
       readiness=A),
    _r("PC-02", "Rejection candle at the previous day's high or low, next-candle exit", N.pc02, N.pc02_x, IX, (5,), L2,
       readiness=A),
    _r("PC-03", "Wide CPR: reversal candle at the central pivot after a fall into it, next-candle exit", N.pc03,
       N.pc03_x, IX, (5,), ONE, readiness=A),
    # ── NSE stocks (intraday pools) ──
    _r("TW-01", "15-minute opening range breakout on a volume expansion, VWAP side, session-low stop", N.tw01, N.tw01_x,
       ("NSE15",), (15,), ONE, readiness=A),
    _r("DF-01", "Ten strongest movers on Nifty's side, Point & Figure double-top buy / double-bottom sell", N.df01,
       N.df01_x, ("NSE5",), (5,), Limits(3, False, False, 2), needs=("ze_rank930", "ze_nifty930"),
       clock=("ist", 15 * 60 + 9), readiness=A),
    _r("VB-01", "High-activity stock, first 15-minute high/low break on 5 minutes before 2 PM, entry-candle stop",
       N.vb01, N.vb01_x, ("NSE5",), (5,), ONE, readiness=A),
    _r("VB-02", "Session VWAP and 15-minute Supertrend agreeing", N.vb02, N.vb02_x, ("NSE15",), (15,), ONE, readiness=A),
    _r("DH-11", "15-minute Bollinger Band exhaustion + RSI 70/30, first opposite candle, 1% target", N.dh11, N.dh11_x,
       ("NSE15",), (15,), ONE, readiness=A),
    _r("CK-02", "Previous-day high/low break with a 0.5% buffer, day-extreme stop, 2R target, out at 3 PM (high-beta)",
       N.ck02, N.ck02_x, ("NSE5",), (5,), ONE, clock=("ist", 14 * 60 + 59), readiness=A),
    _r("EC-02", "9:15 candle on 2x closing volume: big candle side, second candle closes beyond it, 2R", N.ec02,
       N.ec02_x, ("NSE15",), (15,), ONE, readiness=A),
    # ── NSE stocks (daily, long only) ──
    _r("TW-02", "Strong gap out of a range with RSI holding 40 (bullish range), range-low stop, long only on daily bars",
       N.tw02, N.tw02_x, ("NSED",), (1,), readiness=A),
    _r("MV-02", "Regular RSI divergence 3-10 bars apart, confirmation candle, target the middle swing, RR at least 1:3",
       N.mv02, N.mv02_x, ("NSED",), (1,), readiness=A),
    _r("OF-01", "Williams %R (10) bullish divergence with RSI below 30 on daily candles", N.of01, N.of01_x, ("NSED",),
       (1,), readiness=A),
    # ── bitcoin, gold, forex, Nasdaq ──
    _r("CC-01", "Clean double close through a level (failed flip), limit at the level, thrust-candle stop", G.cc01,
       G.cc01_x, ("BTCUSD",) + FX, (60,), L2, readiness=A),
    _r("BN-01", "EMA 20/50/100 fanned trend, retest of EMA 20/50 with engulfing or pin bar + Stoch RSI cross, 2-3R",
       G.bn01, G.bn01_x, ("BTCUSD",), (15,), L3, readiness=A),
    _r("TC-01", "4-hour breakout, dirty retest back into the pattern, 15-minute break of the retest", G.tc01, G.tc01_x,
       FX + ("BTCUSD",), (240, 15), ONE, readiness=A),
    _r("TC-02", "Trend day, Asian grind back into the daily pivot, London-open 5-minute breakout to S1/R1", G.tc02,
       G.tc02_x, FX, (5,), ONE, clock=("ny", 11 * 60 + 30), readiness=A),
    _r("UK-01", "First one-minute candle bracket at the cash open, out at the close of minute five", G.uk01, G.uk01_x,
       ("NAS100",), (1,), ONE, clock=("ny", 9 * 60 + 34), readiness=A),
    _r("UK-02", "Biggest VWAP excursion in 3 days, first VWAP test outside the first/last hour, 1/3 stop, 3:1", G.uk02,
       G.uk02_x, ("NAS100", "BTCUSD"), (15,), ONE, readiness=A),
    _r("AF-01", "Early drive away from VWAP (gap day), buy the first VWAP test that holds, exit at a new high", G.af01,
       G.af01_x, ("NAS100",), (5,), ONE, readiness=A),
    _r("MA-01", "One-minute impulse that breaks structure, limit at the 0.618, stop past the origin, target the impulse end",
       G.ma01, G.ma01_x, FX, (1,), L4, readiness=A),
    _r("RU-05", "RSI through 70 (30) with Supertrend agreeing, Supertrend stop, 1.5R", G.ru05, G.ru05_x,
       ("BTCUSD", "XAUUSD"), (30,), readiness=A),
    _r("RU-06", "Zero-lag MACD cross below/above zero in the 200 EMA trend, pullback stop, 1.5R", G.ru06, G.ru06_x,
       ("BTCUSD", "XAUUSD"), (30,), readiness=A),
    _r("NK-01", "Close outside the Bollinger Band (20, 2), stop at the middle line, 2R (1-hour)", G.nk01, G.nk01_x, FX,
       (60,), readiness=A),
    _r("KA-01", "Break of the previous hour/day high or low after a staircase approach, two closes, swing stop, 1R",
       G.ka01, G.ka01_x, ("BTCUSD",), (15,), L3, readiness=A),
    # ── second batch (13 Nov 2026: cards read after the first deploy; ze_more) ──
    _r("MC-01", "Supertrend (7, 3) stop and reverse on 5 minutes", X.mc01, X.mc01_x, IX, (5,), reverse=True, readiness=A),
    _r("MC-02", "Zero-lag EMA (20) vs EMA (20) cross on 15 minutes, stop and reverse, 1 ATR stop", X.mc02, X.mc02_x, IX,
       (15,), reverse=True, readiness=A),
    _r("AO-01", "CCI (20) beyond -100/+100, then a divergence, close back over the EMA 9, 1:1 (one minute)", X.ao01,
       X.ao01_x, IX, (1,), L3, readiness=A),
    _r("KT-01", "200 EMA band (high/close/low) dip, close back outside + fresh MACD cross, break of the candle, 2R",
       X.kt01, X.kt01_x, IX, (1,), L4, readiness=A),
    _r("KG-01", "Weekly + daily CPR side, R1 + previous-day-high break, midpoint stop, R1-R2 midpoint then R2", X.kg01,
       X.kg01_x, IX, (5, 60), ONE, readiness=A),
    _r("KG-02", "Trend reversal CPR: open on the wrong side of a descending (ascending) CPR, fade to it or break it",
       X.kg02, X.kg02_x, IX, (5,), ONE, readiness=A),
    _r("AO-02", "First 5-minute candle full breakout, stop at its far side, out on a close through the EMA 9 (stocks)",
       X.ao02, X.ao02_x, ("NSE5",), (5,), ONE, readiness=A),
    _r("CR-02", "VWAP bounce / rejection after an hour clear of the VWAP, stop entry past the touch candle, 2R",
       X.cr02, X.cr02_x, ("NSE5",), (5,), ONE, readiness=A),
    _r("QC-03", "Gap down beyond -3 standard deviations of the last hour's closes: buy the open, out at 10:00",
       X.qc03, X.qc03_x, ("NSE5",), (5,), ONE, readiness=A),
    _r("CT-03", "Close above the daily VWAP and the day's open = long (below both = short), 1.5 ATR trailing stop",
       X.ct03, X.ct03_x, ("NSE15", "BTCUSD"), (15,), L3, reverse=True, readiness=A),
    _r("KS-01", "SMA 30/40/50/60 tangled, close above the 20-day high, 20-day-low stop, 2R, 30 days (daily, long)",
       X.ks01, X.ks01_x, ("NSED",), (1,), readiness=A),
    _r("DE-09", "Heikin Ashi candle entirely beyond the smoothed MA (5): stop entry at its far end, out on a colour turn",
       X.de09, X.de09_x, ("BTCUSD",), (5,), readiness=A),
    _r("CT-02", "VWAP bounce: 15 bodies on one side of the VWAP, a candle within 0.2% of it, 0.8 ATR stop, 2.5R",
       X.ct02, X.ct02_x, ("BTCUSD",), (15,), readiness=A),
    _r("CT-01", "VWAP trend (15 bodies one side) + close outside the Bollinger band (14, 2) + RSI (16) 45/55, 1.5R",
       X.ct01, X.ct01_x, FX, (5,), readiness=A),
    _r("SK-01", "Exhaustive four-candle leg past the previous impulse's level, limit back at the level with the 20 MA, 2R",
       X.sk01, X.sk01_x, ("XAUUSD",), (5,), L2, readiness=A),
    _r("CH-01", "Trend-day VWAP retest after a one-minute reclaim, 2R, two-bar trailing stop", X.ch01, X.ch01_x,
       ("NAS100",), (1,), ONE, readiness=A),
    _r("CH-02", "15-minute opening range break on a one-minute close with the VWAP side and slope, 1.5 x range target",
       X.ch02, X.ch02_x, ("NAS100",), (1,), ONE, readiness=A),
    _r("QC-01", "30-minute opening range breakout, far-side stop, out at 13:30 New York (Nasdaq proxy for Tesla)",
       X.qc01, X.qc01_x, ("NAS100",), (1,), ONE, clock=("ny", 13 * 60 + 30), readiness=A),
    _r("CV-01", "15-minute opening range stop orders both sides (OCO), 10-point stop and target", X.cv01, X.cv01_x,
       ("NAS100",), (1,), ONE, readiness=A),
    _r("KR-01", "Open in range and in value: fade a hold at the previous value-area edge back to the naked POC", X.kr01,
       X.kr01_x, ("NAS100",), (5,), ONE, readiness=A),
    _r("TN-02", "15-minute opening range double break: reclaim on the VWAP side, target the far edge", X.tn02, X.tn02_x,
       ("NAS100",), (5,), ONE, readiness=A),
    _r("AC-02", "Day type from the 3-minute range vs the VWAP; VWAP 1-3 SD bands + RSI 70/30 fades and trend pullbacks",
       X.ac02, X.ac02_x, ("NAS100",), (3,), L3, readiness=A),
    _r("CR-01", "Drop, base, rally on one-minute candles in a 30-minute uptrend: limit at the base top, 3R (long)",
       X.cr01, X.cr01_x, ("NAS100",), (1, 30), L2, readiness=A),
    # ── third batch (13 Nov 2026: cards read after the second deploy; ze_more2) ──
    _r("FY-01", "VWAP flow shift: price on one side of the VWAP (14), Chaikin oscillator (3, 10) crossing zero, EMA 10 exit",
       X2.fy01, X2.fy01_x, ("NIFTY",), (5,), ONE, readiness=A),
    _r("FY-02", "11:00-11:15 range breakout on one-minute Nifty, first close beyond, far-side stop, out at 15:24",
       X2.fy02, X2.fy02_x, ("NIFTY",), (1,), ONE, clock=("ist", 15 * 60 + 24), readiness=A),
    _r("AO-03", "EMA 9/21 cross, a steep 9 EMA, pullback touching it, break of a bullish candle, candle stop, 1:2",
       X2.ao03, X2.ao03_x, IX, (1,), L3, readiness=A),
    _r("US-01", "CCI (200) above 100 with a Supertrend (10, 2) trailing stop, 150 points (long)", X2.us01, X2.us01_x,
       ("BANKNIFTY",), (5,), L3, readiness=A),
    _r("US-02", "Pivot levels of each 15-minute candle: below its pivot sell at R1 (stop R2, target S1), mirror for buys",
       X2.us02, X2.us02_x, IX, (15,), L4, readiness=A),
    _r("KS-02", "EMA 10 / EMA 13 cross on 15 minutes, stop and reverse", X2.ks02, X2.ks02_x, IX, (15,), reverse=True,
       readiness=A),
    _r("VV-01", "Heikin Ashi doji, then an open = high (low) candle, break of its low (high), 0.25% stop, HA trail",
       X2.vv01, X2.vv01_x, IX, (15,), L3, readiness=A),
    _r("VV-02", "09:15 five-minute candle on the VWAP side, VWAP crosses with a follow-up candle, Supertrend agreeing, 1:1",
       X2.vv02, X2.vv02_x, IX, (5,), L3, readiness=A),
    _r("BJ-01", "5 EMA vs 200 EMA side, the cross and each close back over the 5 EMA of lows (highs) with RSI 40-50",
       X2.bj01, X2.bj01_x, IX, (15,), L3, readiness=A),
    _r("KT-02", "VWAP pullback on the lowest volume after a run away from it, break of that candle, half at 1R, swing trail",
       X2.kt02, X2.kt02_x, ("NSE5",), (5,), ONE, clock=("ist", 14 * 60 + 59), readiness=A),
    _r("BJ-02", "One-hour middle-band side, 15-minute band pullback, five-minute strong close on 1.5x volume, 2R",
       X2.bj02, X2.bj02_x, ("NSE5",), (5, 15, 60), ONE, readiness=A),
    _r("CD-01", "05:30 IST VWAP reclaim: 20 EMA vs VWAP side, engulfing or star at the VWAP, pattern stop, 2R", X2.cd01,
       X2.cd01_x, ("BTCUSD",), (15,), L3, readiness=A),
    _r("DE-10", "Session VWAP bounce, rejection and break-and-retest on five minutes, no flat VWAP, 2R", X2.de10,
       X2.de10_x, ("BTCUSD",), (5,), L4, readiness=A),
    _r("CD-02", "200 EMA side and slope, pullback touching the EMA, engulfing close, 2R (one minute, Asia session)",
       X2.cd02, X2.cd02_x, ("XAUUSD",), (1,), L4, clock=("utc", 8 * 60 + 30), readiness=A),
    _r("RT-01", "Above the 200-day MA, close below the lower Bollinger Band (20, 2.5), buy limit 3% lower, RSI(2) exit",
       X2.rt01, X2.rt01_x, ("NSED",), (1,), readiness=A),
]

NEW = [r.sid for r in _NEW]

# Data the desk does not have (not a judgment of the video): no account.
DATA_BLOCKED = {
    "DF-03": "every entry and stop is read from the ATM option's own one-minute premium chart (its Camarilla levels and "
             "200 EMA channel); the desk has no intraday option premiums",
    "AF-02": "a news-release fade read from 5-second charts and the order ladder; the desk has neither the release "
             "timing nor sub-minute data",
}


def _from_cards():
    """(blocked {sid: reason}, duplicates {sid: (of, why)}, attach video/channel) from the cards."""
    by, blocked, dups = {}, {}, {}
    for c in CL.all_cards():
        meta = CL.video_meta(c["video"])
        for s in c["strategies"]:
            by[s["sid"]] = (c["video"], meta.get("channel") or "")
            if s["duplicate"]:
                dups[s["sid"]] = (s["duplicate"]["of"], s["duplicate"]["why"])
            elif s["sid"] not in NEW:
                blocked[s["sid"]] = DATA_BLOCKED.get(s["sid"]) or "; ".join(s["reasons"]) or s["status"]
    return by, blocked, dups


_BY, BLOCKED, DUPLICATES = _from_cards()
for _rec in _NEW:
    _rec.video, _rec.chan = _BY.get(_rec.sid, ("", ""))
    _rec.version = "v1"
    if _rec.sid in YS.STRATEGIES and YS.STRATEGIES[_rec.sid] is not _rec:
        raise RuntimeError(f"{_rec.sid} is already registered by another study")
    YS.STRATEGIES[_rec.sid] = _rec

# the pool contexts this study's books read, added to the desk's own (yc_run.contexts)
_orig_contexts = R.contexts


def _contexts(needs, *, nifty=None, nsed=None, pool=None, since=None, symbols=None):
    out = _orig_contexts(needs, nifty=nifty, nsed=nsed, pool=pool, since=since, symbols=symbols)
    zn = {n for n in needs if str(n).startswith("ze_")}
    if zn:
        out.update(E.ze_contexts(zn, pool=pool, nifty=nifty))
    return out


if getattr(R.contexts, "__name__", "") != "_contexts" or getattr(R.contexts, "__module__", "") != __name__:
    _contexts.__module__ = __name__
    R.contexts = _contexts
