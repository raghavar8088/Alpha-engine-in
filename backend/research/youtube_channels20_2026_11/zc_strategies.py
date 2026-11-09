"""The strategies of the 20-channel study (November 2026), one record each, added to the 11-channel registry
(yc_strategies.STRATEGIES / CHANNELS / PREFIX) so yc_run runs them unchanged: same signal conventions, fill engine,
book rules and forced exits as the books already trading on the paper desk.

Every record is version v1. A changed rule or number is a new version, never an edit of v1 (and its paper account is a
new one). readiness: "ready" = every rule explicit; "assumptions" = coded with documented research assumptions (the
"Code [A]" lines of analyses/<channel>.md). Blocked strategies (incomplete rules or data the desk lacks) and
duplicates of the existing library are listed in BLOCKED / DUPLICATES and never trade.

    import zc_strategies   # registers the records; then yc_run.run(sid, market, m, cache) works for them
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "youtube_channels11_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import yc_strategies as YS  # noqa: E402
from yc_common import BTC_X, GOLD_X, NIFTY_X  # noqa: E402,F401
from yc_strategies import FREE, ONE, YC  # noqa: E402
from yt_engine import Limits  # noqa: E402

import zc_global_a as GA  # noqa: E402
import zc_global_b as GB  # noqa: E402
import zc_india as ZI  # noqa: E402

SOURCE = "youtube_channels20"
STUDY = "youtube_channels20_2026_11"

CHANNELS = {
    "dhanhq": "Dhan", "abhishekxtrades": "AbhishekXTrades", "upsurgeclub": "Upsurge Club",
    "deltaexchange": "Delta Exchange", "tradewithpat": "Trade with Pat", "datatraders": "Data Trader",
    "tradinglabofficial": "TradingLab", "officialjesserogers": "Jesse Rogers (Casper Trading)", "devanshrai": "Devansh Rai",
    "stockinvestmentacademy": "Stock Investment Academy (Amar Bhatia)", "thetradingschooltrafi": "The Trading School",
    "holdwithpriyank": "HOLD with Priyank", "tradingrush": "TRADING RUSH", "tradbuilder": "TradBuilder",
    "protradingschool6692": "Pro Trading School", "transparentfxacademy": "Transparent Fx Academy",
    "tradingdata1": "Trading Data", "vijaythakkar": "Vijay Thakkar (MastersInOne)", "faizsmcfx": "Faiz SMC",
    "mulhamtrading": "Mulham Trading",
}
CHANNEL_IDS = {
    "dhanhq": "UCEzHCpvFWoF85UabbzKTkOQ", "abhishekxtrades": "UCUJmHX01pQAsP8yQ_TfsmZw", "upsurgeclub": "UCQQojT_AmVWGb4Eg-QniuBA",
    "deltaexchange": "UCaw-1cUd74wvEatvZna0TzQ", "tradewithpat": "UC04-HvUvHG4hpMnQx07ObYQ", "datatraders": "UCwIsRM8qBXobpAnzVJ0c4IQ",
    "tradinglabofficial": "UCCbv0qixG-cyokxEY3kELtg", "officialjesserogers": "UCEAq-8Ih0WI6R7wYoCFiWmA", "devanshrai": "UCRem0cxZp0CNrJaFGRB2Tpw",
    "stockinvestmentacademy": "UCPtgdNLXi2QglhJBidB6QNw", "thetradingschooltrafi": "UCUzGUWt1zx8krC5i3Lzv7rA",
    "holdwithpriyank": "UCRI4NNcBZzBdVzfSlXdGwCw", "tradingrush": "UCgY_eHY4NCTcRnU6CCZXWng", "tradbuilder": "UCIaCP4uF4NpYXnx1Nq7JK-Q",
    "protradingschool6692": "UCB5dISM93_Vr5i5AvZgTGFg", "transparentfxacademy": "UC-vGMbd-jPqGpsuaObDHvmA",
    "tradingdata1": "UCV9hkwgSFkAwS4hN_0oxinA", "vijaythakkar": "UCHvscyzKoKxhLcaz1LQ6mHg", "faizsmcfx": "UC9N9JnSg9aL2w4D0kITQcaw",
    "mulhamtrading": "UCJFDZ3Xab4vXDSQJrvaFXIw",
}
PREFIX = {"DH": "dhanhq", "AX": "abhishekxtrades", "UP": "upsurgeclub", "DE": "deltaexchange", "TP": "tradewithpat",
          "DT": "datatraders", "TL": "tradinglabofficial", "JR": "officialjesserogers", "DR": "devanshrai",
          "AB": "stockinvestmentacademy", "TS": "thetradingschooltrafi", "PV": "holdwithpriyank", "RU": "tradingrush",
          "TB": "tradbuilder", "PT": "protradingschool6692", "TF": "transparentfxacademy", "TD": "tradingdata1",
          "VT": "vijaythakkar", "FZ": "faizsmcfx", "MH": "mulhamtrading"}

NY16 = ("ny", 16 * 60)
G, BT = ("XAUUSD",), ("BTCUSD",)
GB_ = ("XAUUSD", "BTCUSD")
BG_ = ("BTCUSD", "XAUUSD")
A = "assumptions"


def _r(sid, name, fn, ex, markets, tfs, limits=FREE, **kw):
    return YC(sid, name, fn, ex, markets, tfs, limits, **kw)


_NEW = [
    # ── Dhan ──
    _r("DH-01", "VWAP pullback with an engulfing turn after a sweep", ZI.dh01, ZI.dh01_x, ("NIFTY",), (5, 60), Limits(2), readiness=A),
    _r("DH-02", "9:20 top movers: VWAP pullback, inside bar, engulfing break", ZI.dh02, ZI.dh02_x, ("NSE5",), (5,), ONE,
       needs=("movers",), readiness=A),
    _r("DH-03", "3-minute Heikin Ashi pullback scalp with EMA 100", ZI.dh03, ZI.dh03_x, ("NIFTY",), (3,), readiness=A),
    _r("DH-04", "First 30 minutes range: break, pullback, confirmation", ZI.dh04, ZI.dh04_x, ("NIFTY",), (5,), Limits(2), readiness=A),
    _r("DH-05", "9:15-9:20 opening range breakout, RSI 55, rising ADX, Supertrend trail", ZI.dh05, ZI.dh05_x, ("NSE5",), (5,), ONE,
       readiness=A),
    _r("DH-06", "9:20 BYR: buy the 9:20 high of a 1-4% gainer, +0.65%", ZI.dh06, ZI.dh06_x, ("NSE5",), (5,), ONE, readiness=A),
    _r("DH-07", "Supertrend + Fisher Transform near zero + rising ADX (option buying, index proxy)", ZI.dh07, ZI.dh07_x,
       ("NIFTY",), (5,), readiness=A),
    _r("DH-08", "1-minute box breakout with OCO stop orders", ZI.dh08, ZI.dh08_x, ("NIFTY",), (1,), Limits(6, False, False), readiness=A),
    # ── AbhishekXTrades ──
    _r("AX-01", "EMA 5/20 cross, break of the counter candle within 3 bars", ZI.ax01, ZI.ax01_x, ("NIFTY", "BANKNIFTY"), (5,),
       Limits(2, False, False, 1), readiness=A),
    _r("AX-02", "Previous-day high/low bias, close through the counter candle's open (option buying, index proxy)", ZI.ax02,
       ZI.ax02_x, ("NIFTY",), (15,), Limits(3, False, False), readiness=A),
    _r("AX-03", "9:30-10:00 range break, fixed 25-point scalp", ZI.ax03, ZI.ax03_x, ("NIFTY",), (15,), ONE, readiness=A),
    _r("AX-04", "All-touch candle (EMA 5/9/15 + SMA 20) before 10:00, 1:1, one reversal (options, index proxy)", ZI.ax04,
       ZI.ax04_x, ("NIFTY",), (15,), Limits(3, True, True, 2), readiness=A),
    _r("AX-05", "CPR relationship bias, touch and close, 1:2, one reversal", ZI.ax05, ZI.ax05_x, ("NIFTY",), (15,), Limits(2),
       readiness=A),
    _r("AX-06", "Bitcoin 20-20 EMA (15-minute and 1-hour EMA 20)", GA.ax06, GA.ax06_x, BT, (15, 60), readiness=A),
    # ── Stock Investment Academy ──
    _r("AB-01", "Gap day: next day's 5-minute close through the gap day's far side", ZI.ab01, ZI.ab01_x, ("NSE5",), (5,), ONE,
       readiness=A),
    _r("AB-02", "First two 15-minute candles one colour, the second beyond VWAP", ZI.ab02, ZI.ab02_x, ("NSE15",), (15,), ONE,
       readiness=A),
    _r("AB-03", "EMA 9/21 cross + healthy confirmation candle (15-minute)", ZI.ab03, ZI.ab03_x, ("NSE15",), (15,), ONE, readiness=A),
    _r("AB-04", "1-hour close 0.5% above the EMA 50 (BTST / swing)", ZI.ab04, ZI.ab04_x, ("NSE5",), (60,), overnight=True,
       readiness=A),
    _r("AB-06", "EMA 9/15 cross + confirmation candle, Bank Nifty agreeing (options, index proxy)", ZI.ab06, ZI.ab06_x,
       ("NIFTY",), (5,), needs=("BANKNIFTY",), readiness=A),
    # ── The Trading School ──
    _r("TS-01", "First 1-hour candle wick zones: break or reject, 5-minute confirmation", ZI.ts01, ZI.ts01_x,
       ("NIFTY", "BANKNIFTY"), (5,), Limits(2), readiness=A),
    _r("TS-02", "First 1-hour range sweep fade on 1-hour candles", ZI.ts02, ZI.ts02_x, ("NIFTY", "BANKNIFTY"), (60,), ONE),
    _r("TS-03", "Two-day squeeze breakout on volume (stocks)", ZI.ts03, ZI.ts03_x, ("NSE15",), (15,), ONE, readiness=A),
    _r("TS-04", "Gold: previous-day wick zones, 15-minute sweep and close-through", GB.ts04, GA.r2_x, G, (15,), Limits(2), readiness=A),
    _r("TS-05", "Bitcoin 1-minute Fibonacci 0.5-0.786 pullback, 1:1", GB.ts05, GB.r1_x, BT, (1,), Limits(5, False, False),
       readiness=A),
    # ── HOLD with Priyank ──
    _r("PV-02", "EMA 21 continuation: buy the down-close candle's high", ZI.pv02, ZI.pv02_x, ("NIFTY", "NSE5"), (5,),
       Limits(2, False, False), readiness=A),
    _r("PV-03", "RSI divergence, enter on the close through the middle swing", ZI.pv03, ZI.pv03_x, ("NIFTY",), (5,),
       Limits(3, False, False), readiness=A),
    _r("PV-04", "No-bias SMC scalp: daily levels, two 1-hour candles, 15-minute sweep and break", GB.pv04, GB.pv04_x, BT, (15, 60),
       ONE, readiness=A),
    # ── Upsurge Club ──
    _r("UP-01", "The 9:15 open-price cross, out by 9:30 (options, index proxy)", ZI.up01, ZI.up01_x, ("NIFTY", "BANKNIFTY"), (1,),
       ONE, clock=("ist", 9 * 60 + 29), readiness=A),
    _r("UP-02", "Gap trap: first hour back across VWAP, fade the VWAP retest (stock options, stock proxy)", ZI.up02, ZI.up02_x,
       ("NSE5",), (5,), ONE, readiness=A),
    _r("UP-03", "15-minute ADX curve: ADX rising through the DI lines", ZI.up03, ZI.up03_x, ("NSE15",), (15,), ONE, readiness=A),
    _r("UP-04", "Daily Heikin Ashi side, EMA 200 band, Squeeze turning light, Supertrend (5, 1) (options, index proxy)",
       ZI.up04, ZI.up04_x, ("NIFTY",), (5,), readiness=A),
    _r("UP-05", "0.9% stretch from the 20 average, then EMA 20/50 cross back", ZI.up05, ZI.up05_x, ("NIFTY",), (2,), readiness=A),
    _r("UP-06", "Band-and-oscillator reversal scalp (stated approximation of a private indicator)", ZI.up06, ZI.up06_x,
       ("NIFTY",), (3,), readiness=A),
    # ── Vijay Thakkar ──
    _r("VT-01", "33 EMA band on 9 minutes + RSI 55/45 + VWAP (option buying, index proxy)", ZI.vt01, ZI.vt01_x,
       ("NIFTY", "BANKNIFTY"), (9,), Limits(99, True, False, 2), readiness=A),
    _r("VT-02", "Weekly Supertrend (10, 3) king-candle breakout (stocks)", ZI.vt02, ZI.vt02_x, ("NSED",), (1,), readiness=A),
    _r("VT-03", "Rule-based swing: above EMA 20/50/200, 50-day breakout, 9 EMA exit", ZI.vt03, ZI.vt03_x, ("NSED",), (1,),
       readiness=A),
    # ── TradBuilder ──
    _r("TB-01", "15-minute two-colour pair breakdown, short only, 1:3", ZI.tb01, ZI.tb01_x, ("NIFTY",), (15,), ONE),
    _r("TB-02", "Range of the 2nd and 3rd 5-minute candles, reverse once, hold to the close (index proxy)", ZI.tb02, ZI.tb02_x,
       ("NIFTY",), (5,), Limits(2, False, True)),
    _r("TB-04", "Nifty daily EMA 9/20 cross, long only", ZI.tb04, ZI.tb04_x, ("NIFTY_D",), (1,)),
    # ── Delta Exchange ──
    _r("DE-01", "EMA 9/30 cross with a strong candle, 3-minute", GA.de01, GA.de01_x, BT, (3,), readiness=A),
    _r("DE-02", "EMA 20/50/100 stack + Williams fractal, 1-minute, 4-hour side", GA.de02, GA.de02_x, BT, (1, 240), readiness=A),
    _r("DE-03", "Neela Peela: EMA 57/111 first retest, 1/3/5-minute agreement", GA.de03, GA.de03_x, BT, (1, 3, 5),
       clock=("ist", 12 * 60), readiness=A),
    _r("DE-04", "Gold 4-hour Supertrend (10, 4), long only, 30% add on a 40-bar breakout", GA.de04_trades, None, G, (240,),
       kind="trades", overnight=True),
    _r("DE-07", "The 7:30 PM IST bitcoin candle in the 4-hour trend, 1:1", GA.de07, GA.de07_x, BT, (30, 240), ONE,
       clock=("utc", 16 * 60), readiness=A),
    # ── Trade with Pat ──
    _r("TP-01", "Gold range + impulsive FVG + discount + EMA 200 (5-minute)", GA.tp01, GA.tp01_x, G, (5,), readiness=A),
    _r("TP-01H", "Gold range + impulsive FVG + discount + EMA 200 (1-hour)", GA.tp01h, GA.tp01_x, G, (60,), overnight=True,
       readiness=A),
    _r("TP-02", "Gold sweep of a tested level + minor trend-line break, EMA 200 side", GA.tp02, GA.tp02_x, G, (5,), readiness=A),
    _r("TP-03", "Asian range, London push, New York reversal on the 9:30 displacement ORB", GA.tp03, GA.tp03_x, GB_, (5,), ONE,
       clock=NY16, readiness=A),
    _r("TP-04", "New York 15-minute ORB, limit at edge / midline / far side by impulse", GA.tp04, GA.tp04_x, GB_, (5,), ONE,
       clock=NY16, readiness=A),
    _r("TP-05", "9:30 displacement ORB without the session filter", GA.tp05, GA.tp03_x, GB_, (5,), ONE, clock=NY16, readiness=A),
    # ── Data Trader ──
    _r("DT-01", "MACD cross in the EMA 100 trend, swing stop, 1.5R (1-hour)", GA.dt01, GA.r15_x, BG_, (60,), overnight=True,
       readiness=A),
    _r("DT-02", "MACD + Parabolic SAR + EMA 200, stop at the dot, 1:1 (30-minute)", GA.dt02, GA.r1_x, BG_, (30,), overnight=True,
       readiness=A),
    _r("DT-03", "Stochastic oversold, RSI 50, MACD cross, 1.5R (30-minute)", GA.dt03, GA.r15_x, BG_, (30,), readiness=A),
    _r("DT-04", "Bitcoin daily Ichimoku lead lines, long only", GA.dt04, GA.dt04_x, BT, (1440,), overnight=True),
    _r("DT-05", "15-minute Chaikin Money Flow side + MACD cross, 1.5R", GA.dt05, GA.r15_x, BT, (15,), readiness=A),
    _r("DT-06", "First New York 4-hour range fakeout fade, 2R", GA.dt06, GA.r2_x, BG_, (5,), readiness=A),
    _r("DT-07", "SLC: 4-hour structure, fresh 5-minute zone, stochastic hook, 2R", GA.dt07, GA.r2_x, BG_, (5, 240), readiness=A),
    _r("DT-08", "Manipulation: swing sweep + inverse FVG, 2R", GA.dt08, GA.r2_x, BG_, (5, 15), readiness=A),
    # ── TradingLab ──
    _r("TL-01", "MACD cross beyond zero in the EMA 200 trend, stop past the EMA 200, 1.5R", GA.tl01, GA.r15_x, BG_, (60,),
       overnight=True, readiness=A),
    _r("TL-02", "Bollinger (30, 2) + RSI (13) mean reversion to the middle band", GB.tl02, GB.tgt_x, BG_, (15,), readiness=A),
    _r("TL-03", "DEMA 200 + Supertrend (12, 3), exit on the opposite signal", GA.tl03, GA.tl03_x, BT, (15,), overnight=True),
    _r("TL-04", "EMA 200 + RSI 50 + engulfing, stop two candles, 2R", GA.tl04, GA.r2_x, BG_, (15,), readiness=A),
    # ── Jesse Rogers ──
    _r("JR-01", "First Candle Rule: 9:30-9:45 range, FVG limit, candle-1 stop, 2R", GA.jr01, GA.r2_x, BG_, (5,), ONE, clock=NY16),
    _r("JR-02", "First Candle Value: value-area failure fade (bitcoin volume)", GA.jr02, GA.jr02_x, BT, (5,), ONE, clock=NY16,
       readiness=A),
    _r("JR-03", "9:30-9:35 range, 1-minute FVG break, market entry, 2R", GA.jr03, GA.r2_x, BG_, (1,), ONE, clock=NY16, readiness=A),
    _r("JR-04", "9:30-9:35 range, retest close outside, stop at the midpoint, 2R", GA.jr04, GA.r2_x, BG_, (5,), ONE, clock=NY16),
    _r("JR-05", "9:30-9:35 range, 1-minute FVG pullback + engulfing, 3R", GA.jr05, GA.r3_x, BG_, (1,), ONE, clock=NY16),
    # ── Devansh Rai ──
    _r("DR-01", "EMA 200 side + counter-trend-line breakout, 1:2 (15-minute)", GB.dr01, GA.r2_x, BG_, (15,), overnight=True,
       readiness=A),
    _r("DR-02", "Gold 1-minute EMA 200 reclaim with the 15-minute side, 1:2", GB.dr02, GA.r2_x, GB_, (1, 15),
       Limits(6, False, False), readiness=A),
    _r("DR-03", "5 EMA untouched candle, close beyond it, 1:2 (bitcoin 15-minute)", GB.dr03, GA.r2_x, BT, (15,), overnight=True),
    _r("DR-04", "Ether: 2% 15-minute momentum candle, then 1-minute trend-line breaks", GB.dr04, GA.r2_x, ("ETHUSD",), (1, 15),
       clock=BTC_X, readiness=A),
    # ── TRADING RUSH ──
    _r("RU-01", "MACD crossover beyond zero in the EMA 200 trend, swing stop, 1.5R (1-hour)", GB.ru01, GA.r15_x, BG_, (60,),
       overnight=True, readiness=A),
    _r("RU-02", "Stochastic below 20, then a MACD cross, 1.5R (30-minute)", GB.ru02, GA.r15_x, BG_, (30,), readiness=A),
    _r("RU-03", "Opposite RSI: RSI through 70/30 with ADX 25 in the EMA 200 trend, 1.5R", GB.ru03, GA.r15_x, BG_, (30,), readiness=A),
    _r("RU-04", "Williams fractal breakout in the 200 MA trend, 1.5R", GB.ru04, GA.r15_x, BG_, (30,), readiness=A),
    # ── Pro Trading School ──
    _r("PT-01", "Gold stop hunt at a tested level with the 1-hour trend, 2R", GB.pt01, GA.r2_x, G, (5, 60), readiness=A),
    _r("PT-02", "Gold RSI divergence + engulfing with the 1-hour trend, 2R", GB.pt02, GA.r2_x, G, (5, 60), readiness=A),
    _r("PT-03", "Sweep and flip: Asian range swept at the London open (15-minute)", GB.pt03, GB.tgt_x, GB_, (15, 60), ONE,
       clock=("utc", 16 * 60), readiness=A),
    _r("PT-04", "4-hour inside-bar breakout in the trend, 2R", GB.pt04, GA.r2_x, BG_, (240,), overnight=True, readiness=A),
    # ── Transparent Fx Academy ──
    _r("TF-01", "Fibonacci confluence continuation, -0.272 target (15-minute)", GB.tf01, GB.tgt_x, GB_, (15,), readiness=A),
    # ── Trading Data ──
    _r("TD-01", "9/20 EMA cross at a tested level with trend and discount, 1.5R", GB.td01, GA.r15_x, GB_, (5,), readiness=A),
    _r("TD-02", "9/15 EMA cross filtered by the SMI (7, 2, 2)", GB.td02, GB.td02_x, GB_, (5, 15), readiness=A),
    _r("TD-03", "UT Bot pair + Schaff Trend Cycle, 2R (15-minute)", GB.td03, GA.r2_x, BG_, (15,), readiness=A),
    _r("TD-04", "UT Bot + linear-regression candles trend ride (1-hour)", GB.td04, GB.td04_x, BG_, (60,), overnight=True, readiness=A),
    _r("TD-05", "ADX/DI with a 200 EMA retest, 2R (15-minute)", GB.td05, GA.r2_x, GB_, (15,), readiness=A),
    # ── Faiz SMC ──
    _r("FZ-01", "Gold 8 PM / 9 PM New York Midas model (15-minute sweep, 1-minute shift)", GB.fz01, GB.fz01_x, G, (1, 15),
       readiness=A),
    _r("FZ-02", "Gold London first FVG inversion (15-minute)", GB.fz02, GB.fz01_x, G, (15,), readiness=A),
    # ── Mulham Trading ──
    _r("MH-01", "Gold 8 PM New York hourly candle: reversal or continuation", GB.mh01, GA.r2_x, G, (60,), ONE, readiness=A),
    _r("MH-02", "15-minute fake-out with a 1-minute flip entry", GB.mh02, GB.tgt_x, GB_, (1, 15), readiness=A),
    _r("MH-03", "Asian liquidity sweep into a PD array, 1-minute FVG entry", GB.mh03, GB.tgt_x, GB_, (1, 15, 60, 240), ONE,
       readiness=A),
]

# the videos each strategy's rules come from (evidence; the first is the main source)
VIDEOS = {
    "DH-01": ("pUg_7sPauQA",), "DH-02": ("M50LMwoqgVE",), "DH-03": ("JchD2CK6dM0",), "DH-04": ("rd3Rnh_5i9g",),
    "DH-05": ("gr7J_LwPP60",), "DH-06": ("7_VhduccinA",), "DH-07": ("rgVCDtx1yLc",), "DH-08": ("fn7wWaVZ3so",),
    "AX-01": ("AgDZVDuxrec",), "AX-02": ("slAtZyGfAlI",), "AX-03": ("UKxK6uY2WRg",), "AX-04": ("YbQa2rX8w80", "90ALPU-qFdU"),
    "AX-05": ("d14BGHrCZDk", "90ALPU-qFdU"), "AX-06": ("-2EWviNvQrI",),
    "AB-01": ("ENIKnSEKXDA",), "AB-02": ("Eet1sXyCmbQ",), "AB-03": ("OrYAGL9_0MU",), "AB-04": ("NNAKTSXc5lU",), "AB-06": ("cHsrNhr5yZ4",),
    "TS-01": ("XWxaZBrx3QU",), "TS-02": ("-w0LCfL5Eqs",), "TS-03": ("3jIJJu_vTfg",), "TS-04": ("ctLHzjrH3Rk",), "TS-05": ("qz3UPcGbnMk",),
    "PV-02": ("eKmr9Y8-bw0",), "PV-03": ("m4yNIVL7ktw",), "PV-04": ("6qZh8gZrCF4",),
    "UP-01": ("GAr-2Cw4LIQ",), "UP-02": ("1IgiogVjyq0",), "UP-03": ("b7-oxVP8tBc",), "UP-04": ("MtBcbuYR8Wg",),
    "UP-05": ("es1kMDAiaYs",), "UP-06": ("u8zTNH3lJbU",),
    "VT-01": ("i6h9Swn2X2Y",), "VT-02": ("8WOYvhvvXo0", "OH9EvJMmaW4"), "VT-03": ("hH7VfOq0120",),
    "TB-01": ("5g3nGHlhpv0",), "TB-02": ("tOaifCp0K-A",), "TB-04": ("-bWn7r2t2PQ",),
    "DE-01": ("QElRfGfoxjI",), "DE-02": ("LfqOU_dM6IU",), "DE-03": ("HfZjaGM7c_U",), "DE-04": ("FZ7YFTl_xF4",), "DE-07": ("UjNHWEHxAuU",),
    "TP-01": ("kbacCLdZs7w",), "TP-01H": ("kbacCLdZs7w",), "TP-02": ("QCJZc3iAKgk",), "TP-03": ("Bdgev1or-7M", "E3McKlAp3qk"),
    "TP-04": ("deymRD3kSD0", "OkwrhkWfFC0"), "TP-05": ("DmRFA0cZ0C8",),
    "DT-01": ("Yj0yEBxwLVw",), "DT-02": ("sbKTRVWppZY",), "DT-03": ("hh3BKTFE1dc",), "DT-04": ("8blv0NdYeRc",), "DT-05": ("8blv0NdYeRc",),
    "DT-06": ("O5eC5lY7ZXY",), "DT-07": ("ExvoIqNglOk",), "DT-08": ("vK28i-qy8Ec",),
    "TL-01": ("rf_EQvubKlk",), "TL-02": ("pCmJ8wsAS_w",), "TL-03": ("g-PLctW8aU0",), "TL-04": ("XBcMiYK7qYY",),
    "JR-01": ("Qxlu8v_6G3Y",), "JR-02": ("sXR8HQyXdhc", "Ub_dil32xZY"), "JR-03": ("mzFXoK2pbNE",), "JR-04": ("nBOLIrNX_PU",),
    "JR-05": ("8v-Z5oyKVG0",),
    "DR-01": ("yT9sjaAhJSQ", "NdX3p3jA7KY"), "DR-02": ("0cGQXcAzCjA",), "DR-03": ("vwiGS-tx3oM",), "DR-04": ("xS5gPyyQSpw",),
    "RU-01": ("nmffSjdZbWQ", "2NI44nAh3co"), "RU-02": ("ifekTKhtCKU",), "RU-03": ("uSkGE0ujyn4",), "RU-04": ("f5ZW47Wlaek",),
    "PT-01": ("Zr91ZaZmwqI", "nxPWdziVMbw"), "PT-02": ("Zr91ZaZmwqI",), "PT-03": ("IhmkHi-pa-I",), "PT-04": ("KRil3B78hoQ",),
    "TF-01": ("ujcOxEsqSyo",),
    "TD-01": ("X62sKUpgZaQ",), "TD-02": ("QGHtTTQsAU0",), "TD-03": ("SXm1QICK-vE",), "TD-04": ("SXm1QICK-vE",), "TD-05": ("SbqVSr0Vkz4",),
    "FZ-01": ("KP9RnSnr4kg", "4ZY5OTWt3vU"), "FZ-02": ("rXUDahzLjZM",),
    "MH-01": ("rZlRz-dg5LE",), "MH-02": ("Y1r7fTJ0FZ8",), "MH-03": ("Qts-UF2MdZY",),
}

# the videos' own vehicle when the desk trades a proxy (Indian options are traded on the index / the stock: the desk
# has no intraday option premiums)
PROXY = {
    "DH-07": "NIFTY ATM call / put in the video; the desk trades the NIFTY index signal",
    "AX-02": "NIFTY options in the video; the desk trades the NIFTY index signal",
    "AX-04": "NIFTY options in the video; the desk trades the NIFTY index signal",
    "AB-06": "NIFTY ATM / ITM options in the video; the desk trades the NIFTY index signal",
    "UP-01": "ATM options (or F&O stocks) in the video; the desk trades the index signal",
    "UP-02": "stock options just beyond ATM in the video; the desk trades the stock",
    "UP-04": "NIFTY ATM / slightly ITM options in the video; the desk trades the NIFTY index signal",
    "VT-01": "index options in the video; the desk trades the index signal",
    "TB-02": "a sold NIFTY put / call in the video; the desk trades the NIFTY index signal",
}
OPTIONS_SECTION = set(PROXY)

BLOCKED = [
    # (id, name, channel slug, videos, section, reason)
    ("DE-05", "BTC daily-expiry short strangle at 23:30 IST", "deltaexchange", ("dK3FCfA6PcI",), "crypto",
     "needs Delta BTC option premiums by strike (history and live); the desk has no option-price path"),
    ("DE-06", "BTC short strangle at 21:00 IST, 70% decay target", "deltaexchange", ("nI3xJ1SZuJ0",), "crypto",
     "needs Delta BTC option premiums by strike; the desk has no option-price path"),
    ("DE-08", "Tokyo close / New York open session strategy", "deltaexchange", ("fWtaHzVCln0",), "crypto",
     "trend and levels come from adaptive community indicators whose formulas are not given; levels chosen by eye"),
    ("TL-05", "Chandelier Exit + BJ SuperScript + RSI 25/SMA 150 + EMA 200", "tradinglabofficial", ("cxZOD1iOKVc",), "crypto",
     "the entry needs the 'BJ SuperScript' community indicator, whose formula is not given"),
    ("UP-07", "Change-in-OI PCR after 11:00, entry at the option's VWAP", "upsurgeclub", ("u_TGW73x9Uk",), "india_options",
     "needs the NSE option chain (open interest by strike) and option premium bars, history and live"),
    ("TB-03", "NIFTY weekly call sold at 09:25 (premium near Rs 30)", "tradbuilder", ("H6snDCl6iR0",), "india_options",
     "premium-based option selling: needs NIFTY option premiums by strike"),
    ("TB-05", "SENSEX weekly call bought at 14:30 (premium >= Rs 100)", "tradbuilder", ("gXhm3UI0aT8",), "india_options",
     "premium-based: needs SENSEX option premiums"),
    ("TB-06", "NIFTY ADX above 50 before 10:00, long ATM straddle", "tradbuilder", ("v0IUgWuqn-g",), "india_options",
     "a straddle priced in premiums: needs NIFTY option premiums"),
    ("TB-07", "Intraday rolling short straddle with leg re-entries", "tradbuilder", ("U0df-RTI5tg",), "india_options",
     "option selling on premiums: needs NIFTY option premiums"),
    ("PV-01", "Opening-gap two-sided fill theory", "holdwithpriyank", ("_mBknFCgnoQ",), "india_intraday",
     "a level concept with no entry trigger, stop or timeframe"),
    ("TF-02", "Daily pivot points, two trades a day", "transparentfxacademy", ("4QB6f7LvbbI",), "gold",
     "the author calls it concepts, not a complete strategy: no stop, the entry is a rejection read by eye"),
    ("TF-03", "Gold 10/20 EMA zone retests with COT net positioning", "transparentfxacademy", ("njjug8HxiUM",), "gold",
     "an 'idea' with no stop or target; direction from weekly CFTC COT data the desk does not have"),
    ("TF-04", "Gold point-of-control scalps with COT", "transparentfxacademy", ("c6cayyYx9bM",), "gold",
     "a hand-picked daily swing, no exchange volume for spot gold, rules left to the viewer"),
    ("TD-06", "9/20 EMA cross after two working crosses; 9/20 EMA pullback", "tradingdata1", ("S15vYdGEm7o",), "gold",
     "no stop, target or exit given; 'worked' is not defined"),
    ("FZ-03", "Turtle soup inside 4-hour order flow", "faizsmcfx", ("oPxktw8-NM4",), "gold",
     "4-hour order blocks picked by eye and no target rule; the sweep-and-shift core is CP-26 (turtle soup)"),
]

DUPLICATES = [
    # (video, channel slug, what it teaches, the library strategy it duplicates)
    ("KSCBybE9dVw", "stockinvestmentacademy", "5 EMA alert candle (AB-05)", "YT-01 (5 EMA alert candle)"),
    ("MjN06gyjKK8", "protradingschool6692", "ICT candle range theory", "BG-08 (gold CRT) / NJ-32 (BTC CRT 2.0)"),
    ("YmOrNIX2B78", "faizsmcfx", "ICT Silver Bullet with the draw on liquidity", "CP-28 / YT-04 / BG-07"),
    ("oiArTaTBEkI", "mulhamtrading", "ICT Silver Bullet (10:00-11:00 NY)", "YT-04 / BG-07 / CP-28"),
]
MERGED = [
    # (video, merged into, why)
    ("E3McKlAp3qk", "TP-03", "the same displacement ORB with the session read"),
    ("OkwrhkWfFC0", "TP-04", "the same 15-minute ORB with a level entry"),
    ("Ub_dil32xZY", "JR-02", "the same value-area failure fade"),
    ("OH9EvJMmaW4", "VT-02", "the same weekly Supertrend system (2023 interview)"),
    ("nxPWdziVMbw", "PT-01", "the same stop hunt with candle confirmations"),
    ("4ZY5OTWt3vU", "FZ-01", "the 2024 version of the Midas model (80/20 exit)"),
    ("NdX3p3jA7KY", "DR-01", "the same 200 EMA trend-line system on gold"),
    ("2NI44nAh3co", "RU-01", "the same MACD strategy tested on bitcoin"),
    ("90ALPU-qFdU", "AX-04 / AX-05", "a stop-and-reverse overlay without an entry rule"),
    ("EGyyxeQgLfw", "DR-01", "a trade recap of the same system"),
]
NOT_STRATEGIES = [
    ("26s8e-92AzY", "tradingrush", "a Fibonacci retracement study with no trading rules"),
    ("ioDiVekuOTs", "holdwithpriyank", "a stock-selection routine (sector strength), no entry or exit"),
]


def section_of(sid: str) -> str:
    """india_intraday | india_options | crypto | gold | crypto_gold (cards show in both)."""
    st = NEW[sid]
    mk = set(st.markets)
    if sid in OPTIONS_SECTION:
        return "india_options"
    if mk & {"NIFTY", "BANKNIFTY", "NSE5", "NSE15", "NSED", "NIFTY_D"}:
        return "india_intraday"
    crypto = bool(mk & {"BTCUSD", "ETHUSD"})
    gold = "XAUUSD" in mk
    return "crypto_gold" if (crypto and gold) else ("gold" if gold else "crypto")


NEW = {s.sid: s for s in _NEW}
assert len(NEW) == len(_NEW), "duplicate strategy id"
_OURS = ("zc_india", "zc_global_a", "zc_global_b")
_clash = {k for k in NEW if k in YS.STRATEGIES and getattr(YS.STRATEGIES[k].fn, "__module__", "") not in _OURS}
assert not _clash, f"id clash with the library: {_clash}"
_pclash = {k for k in PREFIX if k in YS.PREFIX and YS.PREFIX[k] != PREFIX[k]}
assert not _pclash, f"prefix clash with the library: {_pclash}"
assert all(s in VIDEOS for s in NEW), "a strategy without its videos"

# register into the 11-channel registry (in place: yc_run and the desk read these dicts)
YS.STRATEGIES.update(NEW)
YS.CHANNELS.update(CHANNELS)
YS.PREFIX.update(PREFIX)
