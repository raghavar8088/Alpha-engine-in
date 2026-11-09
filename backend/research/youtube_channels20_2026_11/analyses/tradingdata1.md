# Trading Data (@tradingdata1, UCV9hkwgSFkAwS4hN_0oxinA)

English; 2026 indicator-strategy videos on gold, Bitcoin and EURUSD (TradingView). Tags: **[E]** stated, **[I]** inferred,
**[A]** assumption. The win rates the channel quotes ("68 of 100", "65%") are claims, not evidence.

## TD-01 9/20 EMA cross taken only at a tested level or a flip zone, with the trend and premium/discount: X62sKUpgZaQ
"I Tested The 9 20 EMA Strategy: Here Is The Truth" (2026-09-17, 11:22), https://youtu.be/X62sKUpgZaQ
- The trigger is EMA 9 crossing EMA 20. On its own the author calls it "a coin flip" (it fails in chop) [E 00:57-04:08].
- Trade it only at a level: support/resistance touched twice before (enter on the third touch), or a flip zone (a level
  broken, then retested from the other side) [E 04:08-08:12]. If price cuts through the zone, no trade [E].
- Entry at the close of the cross candle. Stop beyond the zone. Target 1:1.5, or the last swing [E 05:44-08:12].
- Step three: trade with the swing trend (lower highs and lows mean sells only). Sell from premium (above 50% of the last
  leg) and buy from discount (below 50%) [E 09:36-11:00].
- Code [A]:
  - XAUUSD and BTC 5-minute.
  - Zone: two or more confirmed fractal (n=3) swing lows (highs) within 0.3 ATR of each other in the last 200 bars, or a
    swing level that has flipped.
  - The cross must come within 6 bars of a touch (a low within 0.15 ATR of the zone), with the close back above the zone.
  - Trend: the last two confirmed swing highs and lows. Premium/discount: 50% of the last swing leg.
  - Stop = zone edge -/+ 0.1 ATR. Target 1.5R.
- Status: requires documented assumptions.

## TD-02 9/15 EMA cross filtered by the Stochastic Momentum Index (7, 2, 2): QGHtTTQsAU0
"The Best 9 & 15 EMA Trading Strategy I Use Every Day" (2026-07-18, 11:58), https://youtu.be/QGHtTTQsAU0
- EMA 9 above EMA 15, both sloping and separated: longs only. Flat and tangled: no trades [E 02:29-03:55].
- SMI settings: K 7, D 2, EMA 2; levels +-40 [E 01:23-02:29, 03:55-05:22].
- At the moment of the cross the SMI must still be rising and not above +60. A deep reading that is rising hard is
  called "even better". Above +60 and flat: skip [E 08:14-09:54].
- Enter as the candle closes above both EMAs. Stop below the low of the candle before entry. Exit: "we let it run"
  [E 09:54-11:00].
- Examples: gold 5-minute and BTC 15-minute; 1- and 15-minute charts are also named [E].
- Code [A]:
  - Exit at the opposite 9/15 cross (the video states no exit).
  - "Flat and tangled" = more than one other cross in the last 20 bars: skip.
  - "SMI rising" = SMI above its EMA signal line and above its previous value.
- Status: requires documented assumptions (the exit).

## TD-03 UT Bot (two instances) + Schaff Trend Cycle: SXm1QICK-vE (strategy 1)
"UT Bot Alerts Indicator Best Settings | 2 Powerful Trading Strategies" (2026-06-18, 9:28), https://youtu.be/SXm1QICK-vE
- UT Bot Alerts (QuantNomad) is added twice: key 2 / ATR 300 for buy signals only, and key 2 / ATR 1 for sell signals
  only [E 01:13-02:52].
- STC: length 80, fast 27 [E 02:52]. Buy only when the STC is below the lower line and has turned up ("below the green line
  and turned green"). Sell only when it is above the upper line and has turned down. In the middle zone: skip
  [E 02:52-05:50].
- Stop beyond the recent low (or high). Target 2R [E 03:30-05:00]. Timeframes 5-minute, 15-minute and 1-hour [E 01:13].
- Code [A]:
  - STC slow length 50 (not stated). Lines at 25/75, the script's levels [I].
  - "Recent low" = lowest low of the last 10 bars.
  - BTC and XAUUSD 15-minute.
  - Signals on bar close, as the video insists [E 07:50].
- Status: requires documented assumptions.

## TD-04 UT Bot + linear-regression candles, riding the trend: SXm1QICK-vE (strategy 2)
- Linear regression candles: signal smoothing 6, regression length 8 [E 05:50-07:50].
- Long when a green regression candle closes above the signal line together with a UT Bot buy. Hold until a red
  regression candle closes back below the line; this is "our only exit". Shorts are the mirror [E 06:30-07:40].
- Code [A]:
  - Signal line = simple average of the regression close.
  - A protective stop at 3 x ATR(14), for sizing only (the video has none).
  - BTC and XAUUSD 1-hour.
- Status: requires documented assumptions (the stop).

## TD-05 ADX/DI with a 200 EMA retest (enter before ADX confirms): SbqVSr0Vkz4
"ADX Indicator Strategy | Beat The Lag In Trading" (2026-07-04, 12:13), https://youtu.be/SbqVSr0Vkz4
- ADX and DI (14). DI+ over DI- gives the direction, and a widening gap means conviction. ADX above 20 means strength,
  but it arrives late [E 02:51-08:00].
- EMA 200: trade only when it slopes (flat = skip). Price retests the EMA and holds: several wicks go through, but the
  closes hold [E 08:00-09:45].
- DI+ crosses above DI- while ADX may still be under 20. Enter on the strong candle that closes out of the retest. Stop a
  little below the EMA 200. Take profit at 2R [E 09:45-11:40]. Example: gold 15-minute [E].
- Code [A]:
  - Retest: a low within 0.1 ATR of the EMA 200 in the last 8 bars, with closes holding above it.
  - A DI cross in the last 5 bars, with the gap now wider than at the cross.
  - Breakout: a close above the previous 5 highs.
  - Slope: the EMA 200 has moved at least 0.2 ATR over 20 bars.
  - Stop = EMA 200 - 0.25 ATR.
  - XAUUSD and BTC 15-minute.
- Status: requires documented assumptions.

## Blocked
- **TD-06 A 9/20 EMA cross taken only after the last two crosses worked; a 9/20 EMA pullback with a red-then-green
  trigger.** S15vYdGEm7o, "Top 2 EMA Trading Strategies I'm Using Right Now" (2026-01-24, 12:07). No stop, target or exit
  is given, and "worked" is not defined. Blocked (incomplete).

## Trading Data summary
Coded: TD-01 to TD-05. Blocked: TD-06.
