"""The 103 strategies of the 11-channel study, one record each: where its rules are coded, the desk markets it trades,
the bars it needs, its forced exit, its daily limits and how its book is run.

kind
  signals   fn(m, B, p, cache) -> signals; exits(m, B, p, cache) -> Exits; run by yc_engine.run_book_x
  trades    fn(m, B, p, cache, eng, k_end_of_day, sid) -> trades (two-sided books: SS-04, PR-04)
  room      fn(m, B, p, cache, eng, sid, since_k) -> trades (IT-02's two-lot trade)
  ladder    fn(m, B, p, cache, eng, risk_pct, since_k, sid) -> trades (PR-12 / PR-13: one trade per leg)
  basket    fn(markets, sid) -> {symbol: trades} (NJ-25: the whole NSE daily pool at once)
needs: "nifty_gap" (NJ-01), "nj20" / "ss03" (pool contexts), "ETHUSD" (NJ-33's second coin), "box" (TH-04)
markets: NIFTY, BANKNIFTY (index minutes), NSE5 / NSE15 (the 5-minute stock pool on 5- or 15-minute bars), NSED (the
daily stock pool), NIFTY_D (daily NIFTY), BTCUSD, XAUUSD, EURUSD, GBPUSD, NAS100.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
for _p in (HERE, RESEARCH / "youtube_top20_2026_11", RESEARCH / "booming_bulls_2026_11", RESEARCH / "crypto_playlist_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import yc_channels as C  # noqa: E402
import yc_more as M  # noqa: E402
import yc_nj_crypto as NC  # noqa: E402
import yc_nj_india as NI  # noqa: E402
from yc_common import BTC_X, END_X, GOLD_X, NAS_X, NIFTY_X  # noqa: E402
from yt_engine import Limits  # noqa: E402

CHANNELS = {
    "neerajjoshi": "Neeraj Joshi", "thetradinggeek": "Brad Goh (The Trading Geek)", "tanishagarg101": "Tanisha Garg",
    "thetagainers": "Theta Gainers", "conorkenny": "Conor Kenny", "stockburnerofficial": "Stock Burner",
    "pushkarrajthakurofficial": "Pushkar Raj Thakur", "iitiantrader": "IITian Trader",
    "thetraderoomsss": "The Trade Room (Mayank Raj)", "coachsagarsinha": "Sagar Sinha", "sayacrypto": "saya crypto",
}
PREFIX = {"NJ": "neerajjoshi", "BG": "thetradinggeek", "TG": "tanishagarg101", "TH": "thetagainers",
          "SB": "stockburnerofficial", "PR": "pushkarrajthakurofficial", "IT": "iitiantrader", "TR": "thetraderoomsss",
          "SS": "coachsagarsinha", "SY": "sayacrypto"}

ONE = Limits(1)                          # one trade a day
FREE = Limits(99, False, False)          # one position at a time, no daily cap
FX_X = GOLD_X
INTRADAY_CLOCK = {"NIFTY": NIFTY_X, "BANKNIFTY": NIFTY_X, "NSE5": NIFTY_X, "NSE15": NIFTY_X, "BTCUSD": BTC_X,
                  "XAUUSD": GOLD_X, "EURUSD": FX_X, "GBPUSD": FX_X, "NAS100": NAS_X}
OVERNIGHT_MARKETS = ("NSED", "NIFTY_D")


@dataclass
class YC:
    sid: str
    name: str
    fn: object
    exits: object
    markets: tuple
    tfs: tuple
    limits: Limits = field(default_factory=lambda: FREE)
    kind: str = "signals"
    overnight: bool = False              # positions may stay open across sessions (the book replays its whole period)
    clock: tuple | None = None           # the forced exit; None = the market's intraday default (or the data's end)
    needs: tuple = ()
    reverse: bool = False                # stop and reverse on the opposite signal (PR-09)

    @property
    def channel(self) -> str:
        return PREFIX[self.sid.split("-")[0]]

    @property
    def channel_name(self) -> str:
        return CHANNELS[self.channel]

    def exit_clock(self, market: str) -> tuple:
        if self.clock is not None:
            return self.clock
        if self.overnight or market in OVERNIGHT_MARKETS:
            return END_X
        return INTRADAY_CLOCK[market]

    def is_overnight(self, market: str) -> bool:
        return self.overnight or market in OVERNIGHT_MARKETS


def _btc(sid, name, fn, ex, tfs, limits=FREE, **kw):
    return YC(sid, name, fn, ex, ("BTCUSD",), tfs, limits, overnight=kw.pop("overnight", True), **kw)


_ALL = [
    # ── Neeraj Joshi: India ──
    YC("NJ-01", "9:20 VWAP + EMA 7 first-candle breakout", NI.nj01, NI.nj01_x, ("NSE5",), (5,), ONE, needs=("nifty_gap",)),
    YC("NJ-02", "Pivot points with a narrow CPR, trade the open's side", NI.nj02, NI.nj02_x, ("NSE5", "NIFTY"), (5,), ONE),
    YC("NJ-03", "EMA 9 + ADX above 25 and rising", NI.nj03, NI.nj03_x, ("NIFTY",), (5,)),
    YC("NJ-04", "EMA 10 failed-pullback breakout (Anant Ladha)", NI.nj04, NI.nj04_x, ("NIFTY",), (5,)),
    YC("NJ-05", "EMA 50/100 + Stochastic scalp, 1 minute", NI.nj05, NI.nj05_x, ("BANKNIFTY",), (1,), Limits(3, False, False, 2)),
    YC("NJ-06", "Bollinger squeeze breakout", NI.nj06, NI.nj06_x, ("NSE15",), (15,), ONE),
    YC("NJ-07", "Bollinger band turn + MACD cross + volume", NI.nj07, NI.nj07_x, ("NSE5",), (5,)),
    YC("NJ-08", "RSI 50 + EMA 14 cross", NI.nj08, NI.nj08_x, ("NIFTY",), (5,)),
    YC("NJ-09", "MACD signal-line cross", NI.nj09, NI.nj09_x, ("NIFTY",), (5,)),
    YC("NJ-10", "Heikin Ashi doji turn", NI.nj10, NI.nj10_x, ("NIFTY",), (15,)),
    YC("NJ-11", "Renko 1-back / 2-back continuation", NI.nj11, NI.nj11_x, ("NIFTY",), (5,)),
    YC("NJ-12", "PVT cross of its EMA 20", NI.nj12, NI.nj12_x, ("NSE5",), (5,), Limits(3, False, False)),
    YC("NJ-13", "Hammer after a fall, with volume", NI.nj13, NI.nj13_x, ("NSE15",), (15,), ONE),
    YC("NJ-14", "Supertrend 21/1 flip with RSI and its average", NI.nj14, NI.nj14_x, ("NSE5",), (5,), Limits(3, False, False)),
    YC("NJ-15", "Three-touch level breakout with volume", NI.nj15, NI.nj15_x, ("NSE5",), (5,), ONE),
    YC("NJ-16", "Double bottom / double top neckline break", NI.nj16, NI.nj16_x, ("BANKNIFTY",), (5,)),
    YC("NJ-17", "Day Sniper: gap, limit at the first 15-minute close", NI.nj17, NI.nj17_x, ("NSE15",), (15,), ONE),
    YC("NJ-18", "Gap of 0.3% + first 15-minute range breakout", NI.nj18, NI.nj18_x, ("NSE15",), (15,), ONE),
    YC("NJ-19", "EMA 50/200 golden cross with volume, daily", NI.nj19, NI.nj19_x, ("NSED",), (1,)),
    YC("NJ-20", "200-DMA cross candidates from the top 100 by turnover", NI.nj20, NI.nj20_x, ("NSE5",), (5,), ONE, needs=("nj20",)),
    YC("NJ-21", "EMA 5/20 cross scalp, 10-minute time stop", NI.nj21, NI.nj21_x, ("NIFTY",), (1,), Limits(6, False, False, 3)),
    YC("NJ-22", "MACD + Stochastic 50 + Parabolic SAR", NI.nj22, NI.nj22_x, ("BANKNIFTY",), (5,), Limits(4, False, False)),
    YC("NJ-23", "Harami with a confirmation candle", NI.nj23, NI.nj23_x, ("NIFTY",), (5,)),
    YC("NJ-24", "Ascending triangle breakout, daily", NI.nj24, NI.nj24_x, ("NSED",), (1,)),
    YC("NJ-25", "BTST momentum basket", NI.nj25_trades, None, ("NSED",), (1,), kind="basket"),
    YC("NJ-26", "EMA 50 cross on Heikin Ashi with volume and RSI", NI.nj26, NI.nj26_x, ("NSED",), (1,)),
    YC("NJ-46", "EMA 10/20 cross with a Marubozu candle (Anant Ladha)", NI.nj46, NI.nj46_x, ("NSED",), (1,)),
    # ── Neeraj Joshi: bitcoin ──
    _btc("NJ-27", "20-candle channel breakout with EMA 200 and ATR stops, 4 hours", NC.nj27, NC.nj27_x, (240,)),
    _btc("NJ-28", "Fibonacci OTE: a 0.618 tap with an FVG", NC.nj28, NC.nj28_x, (15, 60)),
    _btc("NJ-29", "Order block retest with a 5-minute CISD", NC.nj29, NC.nj29_x, (5, 60)),
    _btc("NJ-30", "Fair value gap 50% limit entry", NC.nj30, NC.nj30_x, (15,)),
    _btc("NJ-31", "4-hour swing sweep + 5-minute engulfing", NC.nj31, NC.nj31_x, (5, 240)),
    _btc("NJ-32", "Candle range theory 2.0", NC.nj32, NC.nj32_x, (5, 60)),
    _btc("NJ-33", "BTC/ETH SMT divergence", NC.nj33, NC.nj33_x, (5,), needs=("ETHUSD",)),
    _btc("NJ-34", "Hidden breakeven liquidity re-entry", NC.nj34, NC.nj34_x, (5,)),
    _btc("NJ-35", "Manipulation model at the New York open", NC.nj35, NC.nj35_x, (5,), ONE, overnight=False, clock=("utc", 18 * 60)),
    _btc("NJ-36", "The two-hour New York range sweep", NC.nj36, NC.nj36_x, (5,), ONE, overnight=False, clock=("ny", 16 * 60)),
    _btc("NJ-37", "The New York open fair value gap", NC.nj37, NC.nj37_x, (15,)),
    _btc("NJ-38", "Golden-hour 15-minute range breakout", NC.nj38, NC.nj38_x, (5,)),
    _btc("NJ-39", "Long-wick rejection at a 1-hour support or resistance", NC.nj39, NC.nj39_x, (60,)),
    _btc("NJ-40", "Ichimoku triple confirmation, 1 hour", NC.nj40, NC.nj40_x, (60,)),
    _btc("NJ-41", "Richard Dennis zone breakout, 4 hours", NC.nj41, NC.nj41_x, (240,)),
    _btc("NJ-42", "EMA 200 + double-tested level + MACD cross", NC.nj42, NC.nj42_x, (15,)),
    _btc("NJ-43", "Williams Alligator pullback to the teeth", NC.nj43, NC.nj43_x, (60,)),
    _btc("NJ-44", "4-hour fractal sweep, entered on the close back inside", NC.nj44, NC.nj44_x, (5, 240)),
    _btc("NJ-45", "Two-candle turn level breakout", NC.nj45, NC.nj45_x, (15,), Limits(4, False, False)),
    _btc("NJ-47", "Smoothed Heikin Ashi retest, 1:3", NC.nj47, NC.nj47_x, (60,)),
    # ── Tanisha Garg ──
    YC("TG-01", "Failed breakout: trade the trap", C.tg01, C.tg01_x, ("NIFTY",), (15,), Limits(2, False, False)),
    YC("TG-02", "RSI 21 roof (60) and floor (40) break", C.tg02, C.tg02_x, ("NIFTY",), (15,), Limits(2, False, False)),
    YC("TG-03", "Candle outside the Bollinger Band, back inside", C.tg03, C.tg03_x, ("NIFTY",), (15,)),
    YC("TG-04", "Engulfing of several candles, daily swing", C.tg04, C.tg04_x, ("NSED",), (1,)),
    _btc("TG-05", "EMA 20 cross with a held pullback candle, 1:4", C.tg05, C.tg05_x, (15,)),
    YC("TG-06", "Gann special numbers: the nearer level pulls the next session", C.tg06, C.tg06_x, ("NIFTY",), (5,), ONE,
       overnight=True),
    # ── IITian Trader ──
    YC("IT-01", "BankNifty first 5-minute candle theory", C.it01, C.it01_x, ("BANKNIFTY",), (5,), ONE),
    _btc("IT-02", "The room strategy: EMA 45 trend, EMA 9/11 entry, a second lot one room away", C.it02_trades, None, (15,),
         kind="room"),
    # ── The Trade Room ──
    YC("TR-01", "EMA 9/15 scalp on three entry candles", C.tr01, C.tr01_x, ("BANKNIFTY",), (5,), Limits(4, False, False, 2)),
    # ── Sagar Sinha ──
    YC("SS-01", "Bollinger Band + Heikin Ashi alert candle, daily (Kushal Varshney)", C.ss01, C.ss01_x, ("NIFTY_D",), (1,)),
    _btc("SS-02", "EMA 5/13 cross at the previous day's high or low", C.ss02, C.ss02_x, (15,)),
    YC("SS-03", "Lowest-volume opposite candle (Kushal Varshney)", C.ss03, C.ss03_x, ("NSE5",), (5,), ONE, needs=("ss03",)),
    YC("SS-04", "The same 5-minute candle every day (Power of Stocks)", C.ss04_trades, None, ("BANKNIFTY",), (5,), kind="trades"),
    YC("SS-05", "BTST: Heikin Ashi close vs the real close at 15:15 (Kushal Varshney)", C.ss05, C.ss05_x, ("NIFTY",), (5,), ONE,
       overnight=True),
    _btc("SS-06", "EMA 30/50/100 stacked, enter at EMA 30 (Priyank)", C.ss06, C.ss06_x, (15,)),
    # ── saya crypto ──
    _btc("SY-01", "Higher-timeframe structure, 1-hour trend break entered on 15 minutes", C.sy01, C.sy01_x, (15, 60)),
    # ── Brad Goh (The Trading Geek) ──
    YC("BG-01", "Gold: 1-hour structure, 15-minute sweep at the point of interest", C.bg01, C.bg01_x, ("XAUUSD",), (15, 60)),
    YC("BG-02", "The liquidation candle scalp, 2R", C.bg02, C.bg02_x, ("XAUUSD",), (5,)),
    YC("BG-03", "1-minute scalp: 15-minute point of interest, 1-minute sweep zone retest", C.bg03, C.bg03_x, ("XAUUSD",), (1, 15)),
    YC("BG-04", "Asia range sweep at the London open", C.bg04, C.bg04_x, ("GBPUSD",), (5,), ONE),
    YC("BG-05", "Gold supply/demand zone with an EMA 8 cross and an engulfing", C.bg05, C.bg05_x, ("XAUUSD",), (15, 60)),
    YC("BG-06", "EMA 8/14 cross with an engulfing candle", C.bg06, C.bg06_x, ("NAS100",), (5,)),
    YC("BG-07", "Silver bullet, his golden-bullet version", C.bg07, C.bg07_x, ("NAS100",), (5,)),
    YC("BG-08", "Candle range theory on 15 minutes", C.bg08, C.bg08_x, ("XAUUSD",), (5, 15)),
    YC("BG-09", "Break and retest with a confirmation candle, 1:3", C.bg09, C.bg09_x, ("EURUSD",), (15,)),
    YC("BG-10", "Consolidation breakout on a momentum candle", C.bg10, C.bg10_x, ("EURUSD",), (15,)),
    # ── Pushkar Raj Thakur ──
    YC("PR-01", "Brahmastra: Supertrend (20, 2) + MACD + VWAP", M.pr01, M.pr01_x, ("NSE5",), (5,), ONE),
    YC("PR-02", "9:20 opening range: wait for the retest, 1:3", M.pr02, M.pr02_x, ("BANKNIFTY",), (1,), ONE),
    YC("PR-03", "9:20 gap against the trend, opposite first candle", M.pr03, M.pr03_x, ("BANKNIFTY",), (5,), ONE),
    YC("PR-04", "The third 5-minute candle, exit at 15:00", M.pr04_trades, None, ("NIFTY",), (5,), kind="trades",
       clock=("ist", 14 * 60 + 59)),
    YC("PR-05", "Ghanshyam Tech's window strategy", M.pr05, M.pr05_x, ("BANKNIFTY",), (1,), ONE, clock=("ist", 10 * 60 + 14)),
    YC("PR-06", "Ghanshyam Yadav's 2:20 candle", M.pr06, M.pr06_x, ("BANKNIFTY",), (5,), ONE, clock=("ist", 14 * 60 + 59)),
    YC("PR-07", "Ghanshyam Yadav's Fibonacci 0.71 buy", M.pr07, M.pr07_x, ("BANKNIFTY",), (5,), ONE),
    YC("PR-08", "Pivot points: sell the rally to the pivot", M.pr08, M.pr08_x, ("NSE5",), (5,), ONE),
    YC("PR-09", "Golden crossover: EMA 10 / 30 on 3 minutes", M.pr09, M.pr09_x, ("NIFTY",), (3,), Limits(6, False, False),
       reverse=True),
    YC("PR-10", "RSI divergence with a close-line trigger", M.pr10, M.pr10_x, ("NIFTY",), (15,)),
    YC("PR-11", "52-week-high stocks bought on a pullback to the Alligator's teeth", M.pr11, M.pr11_x, ("NSED",), (1,)),
    YC("PR-12", "Gold: 4-hour Supertrend ladder with counter-scalps", M.pr12_trades, None, ("XAUUSD",), (), kind="ladder",
       overnight=True),
    _btc("PR-13", "Bitcoin: the same ladder with a 10% take-profit", M.pr13_trades, None, (), kind="ladder"),
    # ── Stock Burner ──
    YC("SB-01", "9/20 EMA: ride the trend from the first pullback", M.sb01, M.sb01_x, ("NSE5",), (5,), ONE),
    _btc("SB-02", "9/20 EMA rejected pullback, 15 minutes", M.sb02, M.sb02_x, (15,)),
    YC("SB-03", "9 EMA rejection scalp", M.sb03, M.sb03_x, ("NIFTY",), (5,)),
    _btc("SB-04", "200 EMA retest with a confirmation candle", M.sb04, M.sb04_x, (15,)),
    YC("SB-05", "The first 5-minute candle breakout, one trade a day", M.sb05, M.sb05_x, ("NIFTY",), (5,), ONE,
       clock=("ist", 13 * 60 + 59)),
    YC("SB-06", "Gold liquidity sweep at a tested level, pause-candle or rejection trigger", M.sb06, M.sb06_x, ("XAUUSD",), (15, 60)),
    _btc("SB-07", "Pre-breakout: buy under a tested resistance while the lows rise", M.sb07, M.sb07_x, (30,)),
    _btc("SB-08", "Bollinger Band breakout on 1-hour bitcoin, 2% stop, 5% target", M.sb08, M.sb08_x, (60,)),
    # ── Theta Gainers ──
    _btc("TH-01", "Bitcoin 6 PM session: anchored VWAP + EMA 25, the N pattern", M.th01, M.th01_x, (5, 15), Limits(2, False, False)),
    YC("TH-02", "Standard pivots R1 / S1 with a fast Supertrend (7, 3)", M.th02, M.th02_x, ("NIFTY",), (5,), Limits(3, False, False),
       clock=("ist", 14 * 60 + 59)),
    YC("TH-03", "Renko + Ichimoku dual system, gold", M.th03, M.th03_x, ("XAUUSD",), (), overnight=True),
    _btc("TH-04", "Renko + Ichimoku dual system, bitcoin", M.th04, M.th04_x, (), needs=("box",)),
    _btc("TH-05", "EMA 50/200 trend, pullback to EMA 50 with RSI 40-55", M.th05, M.th05_x, (15,)),
    _btc("TH-06", "Bitcoin 07:15-07:30 IST range breakout, stop at mid-range", M.th06, M.th06_x, (15,), ONE, overnight=False),
    _btc("TH-07", "Three-way confirmation on 30 minutes", M.th07, M.th07_x, (30,)),
    _btc("TH-08", "EMA 288 trend, Supertrend signal, base break, swing trail", M.th08, M.th08_x, (5,)),
    YC("TH-09", "Darvas box at 52-week highs", M.th09, M.th09_x, ("NSED",), (1,)),
]

STRATEGIES = {s.sid: s for s in _ALL}
assert len(STRATEGIES) == len(_ALL), "duplicate strategy id"


def market_of(sid: str) -> tuple:
    return STRATEGIES[sid].markets
