# The four-topic intraday study: strategy rules

Generated from cards/<video>.txt by zd_rules.py. [E] stated in the video, [I] inferred from its examples, [A] a
research assumption added to make it codeable. Coded strategies are v1: a changed rule is a new version.

## NIFTY intraday option buying

### OB-01 NIFTY 9:30 premium-180 breakout: ITM call or put that first breaks Rs 180, stop 20, target 40

Video: "Simple 9:30 AM Nifty Option Buying Strategy for Beginners and Busy Professionals" - A&A Trading Blog, uploaded 2025-08-13, 31 min - https://youtu.be/uvut8SRcFGY (transcript: YouTube auto-captions (en-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY current-week options; no chart needed, only the premium. ([01:32](https://youtu.be/uvut8SRcFGY?t=92), [02:56](https://youtu.be/uvut8SRcFGY?t=176))
- **Session**
  - [E] At exactly 9:25 note NIFTY's price and the at-the-money strike. ([01:32](https://youtu.be/uvut8SRcFGY?t=92), [02:14](https://youtu.be/uvut8SRcFGY?t=134))
- **Setup**
  - [E] Watch the in-the-money call and the in-the-money put whose premiums are closest to Rs 180 (e.g. 165-180). ([02:56](https://youtu.be/uvut8SRcFGY?t=176), [03:39](https://youtu.be/uvut8SRcFGY?t=219), [04:23](https://youtu.be/uvut8SRcFGY?t=263))
- **Entry and confirmation**
  - [E] Around 9:30, whichever of the two first breaks above Rs 180 and sustains is bought immediately. ([05:10](https://youtu.be/uvut8SRcFGY?t=310), [05:54](https://youtu.be/uvut8SRcFGY?t=354))
- **Stop-loss**
  - [E] Stop 20 premium points (exit at 160). ([05:54](https://youtu.be/uvut8SRcFGY?t=354), [06:34](https://youtu.be/uvut8SRcFGY?t=394))
- **Target**
  - [E] Target 40 premium points (220): 1:2; moves to 260-280 are a bonus. ([08:38](https://youtu.be/uvut8SRcFGY?t=518), [09:19](https://youtu.be/uvut8SRcFGY?t=559))
- **Exit**
  - [E] Beginners exit at 9:45 whatever the result if neither stop nor target was hit. ([10:40](https://youtu.be/uvut8SRcFGY?t=640), [11:21](https://youtu.be/uvut8SRcFGY?t=681))
- **Trade management**
  - [E] Experienced: if in profit by 9:40-9:45 move the stop to cost and hold until 10:00 for the target. ([12:04](https://youtu.be/uvut8SRcFGY?t=724), [12:46](https://youtu.be/uvut8SRcFGY?t=766))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk proxy (no intraday option premiums): the premium rule is mapped to NIFTY with delta 0.6 - long when NIFTY rises 15 points above the 9:25 close (about +9 on a 171 premium reaching 180), short when it falls 15 points first; stop 33 index points (20 premium), target 67 (40 premium); one trade a day.
- [A] The stop moves to entry once the trade is 0.5R in profit; everything is closed by 10:00 (the video's experienced-trader version; the beginner 9:45 exit is not coded).

Why the status: The rule is written on option premiums; the desk trades it as a delta-0.6 NIFTY proxy (A)

### OB-02 NIFTY 9:20 Rs 62.5 option, buy on a 50% premium rise, hold overnight (BTST), 50% stop, +75 target

Video: "The 100% Rule-Based Option Buying Strategy: How Pro Buyers Catch Fast 50-Point Index Moves" - Trading Edge by PhonePe Invest, uploaded 2026-11-01, 19 min - https://youtu.be/9IADhg-bMSg (transcript: YouTube auto-captions (hi-orig))
Status: Blocked (no paper account): a BTST on NIFTY weekly option premiums (Rs 62.5 strike selection, +50% premium trigger, next-morning exit): needs NIFTY option premiums by strike, intraday and overnight; the desk has no option-price path.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY weekly-expiry options. ([00:47](https://youtu.be/9IADhg-bMSg?t=47))
- **Setup**
  - [E] At 9:20 mark one call and one put whose premium is nearest Rs 62.5, only within Rs 50-75 (no trade outside that band). ([05:00](https://youtu.be/9IADhg-bMSg?t=300), [05:42](https://youtu.be/9IADhg-bMSg?t=342), [06:25](https://youtu.be/9IADhg-bMSg?t=385))
- **Entry and confirmation**
  - [E] After 9:20, buy whichever marked option first rises 50% above its 9:20 price (e.g. 50 to 75). ([07:05](https://youtu.be/9IADhg-bMSg?t=425), [07:45](https://youtu.be/9IADhg-bMSg?t=465), [08:26](https://youtu.be/9IADhg-bMSg?t=506))
- **Stop-loss**
  - [E] Stop 50% below the entry price. ([08:26](https://youtu.be/9IADhg-bMSg?t=506))
- **Target**
  - [E] Book at +70-75 premium points, today or next morning. ([09:06](https://youtu.be/9IADhg-bMSg?t=546), [09:49](https://youtu.be/9IADhg-bMSg?t=589))
- **Exit**
  - [E] If neither target nor stop is hit, sell at 9:25 the next day (BTST); the strategy is built on overnight moves. ([10:32](https://youtu.be/9IADhg-bMSg?t=632))
- **Position sizing and risk**
  - [E] One lot (about Rs 3,000-4,000 premium); keep about Rs 75,000 for the backtest's Rs 72,000 drawdown. ([10:32](https://youtu.be/9IADhg-bMSg?t=632), [16:08](https://youtu.be/9IADhg-bMSg?t=968))
- **When not to trade**
  - [E] If both the call and the put trigger and stop out in a day, no more trades that day. ([09:49](https://youtu.be/9IADhg-bMSg?t=589))

Why the status: Every rule is explicit; but it is written on option premiums and held overnight, so it needs NIFTY weekly option prices by strike (intraday and next morning)

### OB-03 Williams %R (280) overbought on 60, 20 and 5 minutes: ATM call on the fresh 5-minute signal, +10-12% premium

Video: "Advanced Intraday Option Buying Strategy | Multi-Timeframe Setup" - Dhan ⚡, uploaded 2026-09-08, 12 min - https://youtu.be/J63EL3Xb02g (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Index options (Bank Nifty, Sensex shown) or NIFTY 50 stock options for liquidity; ATM or slightly ITM strike. ([01:30](https://youtu.be/J63EL3Xb02g?t=90))
- **Timeframe**
  - [E] Three timeframes on the underlying: 60 minutes, 20 minutes (one third), 5 minutes; plus the option's 5-minute chart. ([02:10](https://youtu.be/J63EL3Xb02g?t=130))
- **Indicators and settings**
  - [E] Williams %R with length 280 instead of 14 on every chart (fewer but stronger signals). ([02:51](https://youtu.be/J63EL3Xb02g?t=171))
- **Setup**
  - [E] Calls: the 60-minute and 20-minute Williams %R are in the overbought zone; puts: both oversold. ([03:32](https://youtu.be/J63EL3Xb02g?t=212))
- **Entry and confirmation**
  - [E] Enter when the 5-minute Williams %R makes a fresh move into overbought (oversold for puts) inside that phase - not while it is already there. ([04:12](https://youtu.be/J63EL3Xb02g?t=252), [07:05](https://youtu.be/J63EL3Xb02g?t=425))
- **Target**
  - [E] Target 10-12% of the premium within the day (Rs 200 option -> 220). ([08:28](https://youtu.be/J63EL3Xb02g?t=508), [09:14](https://youtu.be/J63EL3Xb02g?t=554))
- **Exit**
  - [E] Intraday; at most 1-2 days for swing; an option not in profit within four days rarely recovers. ([00:48](https://youtu.be/J63EL3Xb02g?t=48))
- **Filters**
  - [E] The option's own 5-minute chart should also show the signal; rising IV (vega) helps, especially for puts. ([08:28](https://youtu.be/J63EL3Xb02g?t=508), [09:59](https://youtu.be/J63EL3Xb02g?t=599))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk proxy on NIFTY (index minutes): an ATM weekly premium is about 0.6% of NIFTY with delta 0.5, so +10-12% premium = +0.12% on NIFTY; overbought = %R above -20, oversold below -80.
- [A] No stop is stated: coded stop 0.12% against the entry (the same 10% of premium), target 0.12%; entries 09:30-14:30, one trade a day, exit 15:15.

Why the status: No stop loss is given (A); the target is on premiums (A: index proxy)

### OB-04 NIFTY 14:55 five-minute candle breakout with a 5-point buffer, out at 15:15

Video: "Best Nifty Option Buying Strategy for Beginners | No Indicator Setup | Sagar Kummar" - Sagar Kummar, uploaded 2026-06-13, 20 min - https://youtu.be/Hn6N3JpOcuA (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY 50 only (tested there); traded through option buying or futures. ([01:28](https://youtu.be/Hn6N3JpOcuA?t=88))
- **Timeframe**
  - [E] 5-minute chart, no indicators. ([01:28](https://youtu.be/Hn6N3JpOcuA?t=88), [02:10](https://youtu.be/Hn6N3JpOcuA?t=130))
- **Setup**
  - [E] Mark the high and low of the 14:55-15:00 IST five-minute candle. ([02:10](https://youtu.be/Hn6N3JpOcuA?t=130), [02:50](https://youtu.be/Hn6N3JpOcuA?t=170))
- **Entry and confirmation**
  - [E] Enter on the side that breaks first in the following candles, with a 4-5 point buffer beyond the level to avoid wick traps. ([03:30](https://youtu.be/Hn6N3JpOcuA?t=210), [10:38](https://youtu.be/Hn6N3JpOcuA?t=638), [12:02](https://youtu.be/Hn6N3JpOcuA?t=722))
- **Stop-loss**
  - [E] Stop at the opposite end of the 14:55 candle, 1-2 points beyond it. ([03:30](https://youtu.be/Hn6N3JpOcuA?t=210), [04:15](https://youtu.be/Hn6N3JpOcuA?t=255))
- **Target**
  - [E] Optional: if 1:2 comes earlier, take it. ([06:25](https://youtu.be/Hn6N3JpOcuA?t=385), [07:10](https://youtu.be/Hn6N3JpOcuA?t=430))
- **Exit**
  - [E] Exit at the close of the 15:10-15:15 candle. ([04:15](https://youtu.be/Hn6N3JpOcuA?t=255), [04:55](https://youtu.be/Hn6N3JpOcuA?t=295), [05:37](https://youtu.be/Hn6N3JpOcuA?t=337))
- **When not to trade**
  - [E] Skip the day if the 14:55 candle is wider than about 50-60 points (stop too big). ([07:50](https://youtu.be/Hn6N3JpOcuA?t=470), [08:31](https://youtu.be/Hn6N3JpOcuA?t=511))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Coded: stop orders 5 points (0.02%) beyond the candle's high and low from 15:00, the first fill wins (OCO), valid until 15:10; stop 2 points beyond the other end; skip if the candle range exceeds 55 points (0.22% of NIFTY); exit at 15:15; no 1:2 early exit in v1.

Why the status: Order life after 15:00 and the optional 1:2 need choices (A)

### OB-05 9:15 open-price cross after 30 seconds, ATM option, out by 9:30 (Rajesh Jain)

Video: "I've Been Using This 9:15 AM Options Buying Strategy for 26 Years!" - Strategy in minutes, uploaded 2026-07-25, 26 min - https://youtu.be/Whb5Nr1iukY (transcript: YouTube auto-captions (hi-orig))
Status: Duplicate of UP-01 - not added again. UP-01 (Upsurge Club, Rajesh Jain, GAr-2Cw4LIQ) already trades this exact 9:15 open-price cross with an ATM option and a 9:30 exit; this is a second interview of the same rule.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] F&O stocks rather than indices (NIFTY 'rarely works'); capital about Rs 40,000-70,000. ([01:21](https://youtu.be/Whb5Nr1iukY?t=81), [05:42](https://youtu.be/Whb5Nr1iukY?t=342))
  - [E] Only ATM strikes, never OTM. ([14:45](https://youtu.be/Whb5Nr1iukY?t=885))
- **Session**
  - [E] Sit at 9:15, enter around 9:15:40-9:16, be out by 9:30. ([00:01](https://youtu.be/Whb5Nr1iukY?t=1), [02:54](https://youtu.be/Whb5Nr1iukY?t=174))
- **Setup**
  - [E] Pick the first stock that appears at the top of the NSE F&O gainers or losers list after 9:15 (he prefers selling losers); avoid slow stocks. ([04:57](https://youtu.be/Whb5Nr1iukY?t=297), [05:42](https://youtu.be/Whb5Nr1iukY?t=342))
- **Entry and confirmation**
  - [E] Wait 30-50 seconds; if price made a high and then breaks back below the open price, buy the ATM put; a red first candle mostly stays red for 15 minutes (mirror for calls). ([06:25](https://youtu.be/Whb5Nr1iukY?t=385), [11:56](https://youtu.be/Whb5Nr1iukY?t=716), [13:21](https://youtu.be/Whb5Nr1iukY?t=801))
- **Stop-loss**
  - [E] A stop-loss is used (about 3 stop days in 20); its level is not given. ([17:29](https://youtu.be/Whb5Nr1iukY?t=1049))
- **Exit**
  - [E] Exit around 9:25-9:30. ([17:29](https://youtu.be/Whb5Nr1iukY?t=1049))

Why the status: Stop level not given

### OB-06 ADX turning up + price breakout + big candle (15 minutes), ATM option, 20% premium stop

Video: "Intraday Options Buying की Simple Strategy" - Kunal Saraogi, uploaded 2023-09-28, 15 min - https://youtu.be/Wu_uvG4cwc8 (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Index options (Bank Nifty shown; any chart can be tested); ATM or one strike ITM. ([03:06](https://youtu.be/Wu_uvG4cwc8?t=186), [08:39](https://youtu.be/Wu_uvG4cwc8?t=519))
- **Timeframe**
  - [E] 15-minute intraday chart (10 or 5 minutes also fine). ([03:47](https://youtu.be/Wu_uvG4cwc8?t=227), [04:29](https://youtu.be/Wu_uvG4cwc8?t=269))
- **Indicators and settings**
  - [E] ADX line only (hide the two DI lines). ([04:29](https://youtu.be/Wu_uvG4cwc8?t=269))
- **Entry and confirmation**
  - [E] Three conditions together: ADX turns up (was falling, now rising), price breaks down (up), and a big red (green) candle: buy the put (call). ([06:38](https://youtu.be/Wu_uvG4cwc8?t=398), [07:19](https://youtu.be/Wu_uvG4cwc8?t=439), [08:39](https://youtu.be/Wu_uvG4cwc8?t=519))
- **Stop-loss**
  - [E] Stop 20% below the premium paid. ([07:19](https://youtu.be/Wu_uvG4cwc8?t=439), [09:19](https://youtu.be/Wu_uvG4cwc8?t=559))
- **Target**
  - [E] A fixed pre-set target on the premium (e.g. doubling); hold while ADX rises and no resistance is near; intraday or 1-2 days. ([08:39](https://youtu.be/Wu_uvG4cwc8?t=519), [09:19](https://youtu.be/Wu_uvG4cwc8?t=559))
- **When not to trade**
  - [E] No option buying while ADX is falling (range trade, time decay). ([05:54](https://youtu.be/Wu_uvG4cwc8?t=354), [11:26](https://youtu.be/Wu_uvG4cwc8?t=686))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk proxy on NIFTY 15-minute bars (ATM premium about 0.5% of NIFTY, delta 0.5): stop 0.2% against entry (20% of premium), target 0.5% (premium doubling would be about 1%; 0.5% = +50%); ADX(14) with Wilder smoothing.
- [A] ADX turn = ADX higher than the bar before after at least 3 falling bars; breakout = close beyond the highest high (lowest low) of the previous 8 bars; big candle = body at least 1.5x the average body of the last 20 bars; entry at the next open, 09:30-14:45; exit if ADX turns down (two falling bars) or at 15:15; one trade a day.

Why the status: 'Breakout', 'big candle' and the target need numbers (A); premium rules mapped to the index (A)

### OB-07 NIFTY ATM straddle-chart day filter: buy options only after the straddle sell stops out, then a 5-minute band breakout on spot

Video: "Options Trading Strategies | The ONE Options Buying Setup Beginners Need" - Virendra Pandey, uploaded 2026-09-20, 21 min - https://youtu.be/GCZOslINAHs (transcript: YouTube auto-captions (hi-orig))
Status: Blocked (no paper account): the buy/sell day filter and both triggers are read from the intraday ATM straddle premium chart (call + put), which the desk does not have.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY 50 options; ATM strike taken at the 9:15 open or 9:30 (e.g. 23350). ([01:27](https://youtu.be/GCZOslINAHs?t=87), [03:34](https://youtu.be/GCZOslINAHs?t=214))
- **Indicators and settings**
  - [E] RSI with levels 60 and 40, and EMA 34 on the straddle chart. ([08:32](https://youtu.be/GCZOslINAHs?t=512), [09:16](https://youtu.be/GCZOslINAHs?t=556))
  - [E] Then on the NIFTY spot 5-minute chart: EMA 5 of highs and SMA 3 of lows form a band. ([15:30](https://youtu.be/GCZOslINAHs?t=930), [19:44](https://youtu.be/GCZOslINAHs?t=1184))
- **Setup**
  - [E] Plot the ATM call + put as one combined (straddle) premium chart on 5 minutes (Insta Options tool); mark its first 15-minute candle. ([04:16](https://youtu.be/GCZOslINAHs?t=256), [04:58](https://youtu.be/GCZOslINAHs?t=298), [07:06](https://youtu.be/GCZOslINAHs?t=426))
  - [E] Buying is allowed only after the straddle sell is stopped (the straddle breaks a previous swing high: premium expanding), often around 10:00-11:00. ([12:47](https://youtu.be/GCZOslINAHs?t=767), [13:27](https://youtu.be/GCZOslINAHs?t=807), [19:02](https://youtu.be/GCZOslINAHs?t=1142))
- **Entry and confirmation**
  - [E] Selling version: sell the straddle on that break, stop at the previous swing high of the straddle chart, trail with EMA 34. ([10:42](https://youtu.be/GCZOslINAHs?t=642))
  - [E] Buy (call) above a candle that closes above the band; buy the put when a candle closes below it; ITM strike. ([16:15](https://youtu.be/GCZOslINAHs?t=975), [16:55](https://youtu.be/GCZOslINAHs?t=1015))
- **Stop-loss**
  - [E] Stop at the previous low (high for puts). ([16:15](https://youtu.be/GCZOslINAHs?t=975), [16:55](https://youtu.be/GCZOslINAHs?t=1015))
- **Target**
  - [E] Targets 1:2, 1:3 or 1:4; exit when a candle closes back inside the band. ([16:15](https://youtu.be/GCZOslINAHs?t=975))
- **When not to trade**
  - [E] If the straddle chart breaks its first 15-minute low with RSI under 40, premium is decaying: a selling day - do not buy options. ([05:38](https://youtu.be/GCZOslINAHs?t=338), [06:22](https://youtu.be/GCZOslINAHs?t=382), [10:42](https://youtu.be/GCZOslINAHs?t=642))
  - [E] Do not run it on Wednesdays (the new weekly contract after Tuesday expiry). ([12:04](https://youtu.be/GCZOslINAHs?t=724))

Why the status: The day filter and both triggers are read from the intraday ATM straddle premium chart, which the paper desk does not have

### OB-08 Supertrend (10, 1) + (10, 3) both bullish with a fresh flip and a strong candle, 10-point stop, 20-point target (5-minute NIFTY)

Video: "Best Option Scalping Strategy (Fully Backtested)" - Pro Trader Aakash, uploaded 2025-10-19, 14 min - https://youtu.be/nVG4mXMcsAA (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY index; trade futures, buy options or sell the opposite option. ([00:04](https://youtu.be/nVG4mXMcsAA?t=4), [10:37](https://youtu.be/nVG4mXMcsAA?t=637))
- **Timeframe**
  - [E] 5-minute chart. ([00:49](https://youtu.be/nVG4mXMcsAA?t=49))
- **Indicators and settings**
  - [E] Two Supertrends: length 10 factor 1, and length 10 factor 3. ([00:04](https://youtu.be/nVG4mXMcsAA?t=4), [02:16](https://youtu.be/nVG4mXMcsAA?t=136))
- **Setup**
  - [E] Buy only when both Supertrends are in buy mode (green). ([02:16](https://youtu.be/nVG4mXMcsAA?t=136), [02:56](https://youtu.be/nVG4mXMcsAA?t=176))
- **Entry and confirmation**
  - [E] ...and one of them has just changed from sell to buy (within the last 5-minute bar): a fresh trend after a pullback; enter at that candle's close. ([02:56](https://youtu.be/nVG4mXMcsAA?t=176), [04:20](https://youtu.be/nVG4mXMcsAA?t=260), [06:26](https://youtu.be/nVG4mXMcsAA?t=386))
  - [E] Sell: both in sell mode, one just flipped from buy to sell, a proper red candle; enter at its close. ([08:33](https://youtu.be/nVG4mXMcsAA?t=513), [09:17](https://youtu.be/nVG4mXMcsAA?t=557))
- **Stop-loss**
  - [E] Stop 10 points on the futures chart. ([07:09](https://youtu.be/nVG4mXMcsAA?t=429), [09:57](https://youtu.be/nVG4mXMcsAA?t=597))
- **Target**
  - [E] Target 20 points (1:2); trades end within about half an hour. ([07:09](https://youtu.be/nVG4mXMcsAA?t=429), [09:57](https://youtu.be/nVG4mXMcsAA?t=597))
- **Filters**
  - [E] The signal candle must be a proper strong candle (big body, not long wicks with a small body). ([04:20](https://youtu.be/nVG4mXMcsAA?t=260), [05:03](https://youtu.be/nVG4mXMcsAA?t=303), [05:44](https://youtu.be/nVG4mXMcsAA?t=344))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Proper candle = body at least 60% of the range and in the trade's direction; 10 and 20 points coded as 0.04% and 0.08% of NIFTY (10/20 points at about 25,000); entries 09:20-15:00, exit 15:15; many trades a day, one at a time.

Why the status: 'Proper candle' needs a number (A); points scaled to the index level (A)

### OB-09 2-minute EMA 10/20 trend pullback after a stop hunt, star or engulfing entry, done by noon (VIX filter)

Video: "The 2-Minute Scalping Strategy That Actually Works | Scalping Trading Strategy | Dhan" - Dhan ⚡, uploaded 2026-07-20, 20 min - https://youtu.be/pvmvkiS1cx4 (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY (preferred), Bank Nifty or Sensex: signals on the spot chart, trades in ITM options 100-200 points in the money (delta 0.55-0.6). ([00:49](https://youtu.be/pvmvkiS1cx4?t=49), [01:30](https://youtu.be/pvmvkiS1cx4?t=90))
- **Timeframe**
  - [E] 2-minute chart (only after mastering 5 minutes). ([01:30](https://youtu.be/pvmvkiS1cx4?t=90))
- **Session**
  - [E] At most three entries a day; stop trading by 11:00-12:00. ([12:23](https://youtu.be/pvmvkiS1cx4?t=743), [17:13](https://youtu.be/pvmvkiS1cx4?t=1033), [18:37](https://youtu.be/pvmvkiS1cx4?t=1117))
- **Indicators and settings**
  - [E] EMA 10 and EMA 20 (exponential), nothing else. ([02:15](https://youtu.be/pvmvkiS1cx4?t=135), [03:45](https://youtu.be/pvmvkiS1cx4?t=225))
- **Setup**
  - [E] Direction: EMA 10 above EMA 20 with price above them = longs only; EMA 10 below EMA 20 with price below = shorts only. ([05:56](https://youtu.be/pvmvkiS1cx4?t=356))
  - [E] The pullback must hunt stops: below the big candle's low or its 50%; better, price comes back to EMA 20 (not just EMA 10). ([06:37](https://youtu.be/pvmvkiS1cx4?t=397), [07:21](https://youtu.be/pvmvkiS1cx4?t=441), [11:38](https://youtu.be/pvmvkiS1cx4?t=698))
- **Entry and confirmation**
  - [E] Entry candles: three-candle morning star (long) / evening star (short), preferred for the first trade, or two-candle bullish / bearish engulfing; enter as the pattern candle closes. ([08:48](https://youtu.be/pvmvkiS1cx4?t=528), [09:31](https://youtu.be/pvmvkiS1cx4?t=571), [10:55](https://youtu.be/pvmvkiS1cx4?t=655))
- **Stop-loss**
  - [E] Stop beyond the pattern; with VIX near 12-13 it should not exceed 15-18 points, otherwise skip. ([11:38](https://youtu.be/pvmvkiS1cx4?t=698), [16:33](https://youtu.be/pvmvkiS1cx4?t=993))
- **When not to trade**
  - [E] Never chase: after a big candle, wait for the pullback. ([04:27](https://youtu.be/pvmvkiS1cx4?t=267), [17:54](https://youtu.be/pvmvkiS1cx4?t=1074))
  - [E] No option-buying scalps when India VIX is above 15-16 (sell or hedge instead). ([13:04](https://youtu.be/pvmvkiS1cx4?t=784))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk proxy on NIFTY 2-minute bars built from index minutes; the VIX filter is not applied (no VIX feed on the desk).
- [A] Coded: a 'big candle' = range at least 2x the 20-bar average range in the trend direction; the pullback must trade below its 50% level (above for shorts) and touch EMA 20 within 15 bars; then a morning/evening star or engulfing closing back in the trend direction; entry at the next open; stop 0.02% beyond the pattern extreme, skipped if more than 18 points (0.07%); target 2R (no target is stated); entries 09:20-11:30, exit 12:00; at most 3 trades.

Why the status: No target is stated (A: 2R); 'big candle' and the stop hunt need numbers (A); VIX filter not available (A)

### OB-10 VWAP side + EMA 5/13 cross + RSI 50, break of the signal candle, EMA 5 trail (5 minutes)

Video: "Powerful Intraday Strategy with Proper Entry & Exit  ( Nifty & BankNifty ) - VWAP RSI EMA CrossOver" - Trader Chitra, uploaded 2022-12-27, 31 min - https://youtu.be/BPF2RjINDeI (transcript: YouTube auto-captions (en-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY, Bank Nifty and stocks; option buyers use ITM strikes (the same setup also works on the option chart). ([00:02](https://youtu.be/BPF2RjINDeI?t=2), [24:03](https://youtu.be/BPF2RjINDeI?t=1443))
- **Timeframe**
  - [E] 5-minute chart, intraday only. ([02:13](https://youtu.be/BPF2RjINDeI?t=133), [07:56](https://youtu.be/BPF2RjINDeI?t=476))
- **Indicators and settings**
  - [E] VWAP (session, typical price, default), EMA 5, EMA 13, RSI with only the 50 line. ([02:13](https://youtu.be/BPF2RjINDeI?t=133), [03:36](https://youtu.be/BPF2RjINDeI?t=216), [04:59](https://youtu.be/BPF2RjINDeI?t=299))
- **Setup**
  - [E] Long: a green candle closing above VWAP, EMA 5 crossed above EMA 13 (bullish crossover in place), RSI above 50. ([06:28](https://youtu.be/BPF2RjINDeI?t=388), [08:36](https://youtu.be/BPF2RjINDeI?t=516))
  - [E] Short: a red candle closing below VWAP, bearish EMA 5/13 crossover, RSI below 50; sell below its low, stop above its high. ([07:56](https://youtu.be/BPF2RjINDeI?t=476), [11:34](https://youtu.be/BPF2RjINDeI?t=694))
- **Entry and confirmation**
  - [E] Enter above that green candle's high. ([08:36](https://youtu.be/BPF2RjINDeI?t=516), [10:52](https://youtu.be/BPF2RjINDeI?t=652))
- **Stop-loss**
  - [E] Stop at the signal candle's low (high for shorts). ([09:21](https://youtu.be/BPF2RjINDeI?t=561), [12:26](https://youtu.be/BPF2RjINDeI?t=746))
- **Exit**
  - [E] Trail with EMA 5: exit when a red candle closes below EMA 5 (green above for shorts), or book by risk-reward. ([05:44](https://youtu.be/BPF2RjINDeI?t=344), [09:21](https://youtu.be/BPF2RjINDeI?t=561))
- **Trade management**
  - [E] Book half after entry moves and keep the rest at cost. ([28:34](https://youtu.be/BPF2RjINDeI?t=1714))
- **When not to trade**
  - [E] No long while price is below VWAP even with a bullish cross; no long when both EMAs are below VWAP. ([11:34](https://youtu.be/BPF2RjINDeI?t=694), [25:33](https://youtu.be/BPF2RjINDeI?t=1533), [26:18](https://youtu.be/BPF2RjINDeI?t=1578))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Coded on NIFTY 5-minute index bars (no volume: VWAP = session average of typical price, as the desk does); 'crossover in place' = EMA 5 above EMA 13 with the cross within the last 6 bars.
- [A] Stop-entry above the signal candle's high valid for the next 2 bars; stop 0.02% beyond its low; exit on a 5-minute close back across EMA 5 or at 15:15; half at 1R then stop to entry for the rest; entries 09:20-14:45; one position at a time, up to 3 trades a day.

Why the status: Crossover recency and order life need numbers (A); NIFTY has no volume, so VWAP is the typical-price average (A)

### OB-11 NIFTY expiry-day 'gamma blast': sub-Rs 10 option on the more-negative-theta side, 14:00-15:00

Video: "Catch Explosive Moves On Expiry days | Gamma Blast Strategy" - Upsurge Club, uploaded 2026-06-24, 14 min - https://youtu.be/jUNSZnP9MVI (transcript: YouTube auto-captions (hi-orig))
Status: Blocked (no paper account): expiry-day 'gamma blast' on sub-Rs 10 options chosen by their theta: needs option premiums and Greeks by strike.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY 50 options, on NIFTY's weekly expiry day only. ([03:37](https://youtu.be/jUNSZnP9MVI?t=217), [04:19](https://youtu.be/jUNSZnP9MVI?t=259))
- **Session**
  - [E] Watch only from 14:00 to 15:00. ([04:19](https://youtu.be/jUNSZnP9MVI?t=259))
- **Setup**
  - [E] In that hour find the call strike and the put strike whose premiums have dropped below Rs 10 (strikes may differ). ([05:01](https://youtu.be/jUNSZnP9MVI?t=301), [05:41](https://youtu.be/jUNSZnP9MVI?t=341))
- **Entry and confirmation**
  - [E] Compare the two options' theta on expiry day: buy the side with the more negative theta (seller trap). ([05:41](https://youtu.be/jUNSZnP9MVI?t=341), [07:11](https://youtu.be/jUNSZnP9MVI?t=431), [07:51](https://youtu.be/jUNSZnP9MVI?t=471))
- **Stop-loss**
  - [E] Stop Rs 500 (half the capital). ([09:16](https://youtu.be/jUNSZnP9MVI?t=556))
- **Target**
  - [E] Target Rs 8,000-10,000; do not book below that. ([09:16](https://youtu.be/jUNSZnP9MVI?t=556), [09:56](https://youtu.be/jUNSZnP9MVI?t=596))
- **Position sizing and risk**
  - [E] Use about Rs 1,000 of capital (as many lots as that buys), not big capital; try for 1-2 months first. ([08:34](https://youtu.be/jUNSZnP9MVI?t=514), [09:16](https://youtu.be/jUNSZnP9MVI?t=556))

Why the status: Needs NIFTY option premiums and option Greeks (theta) by strike on expiry afternoons; the paper desk has no option data

## Indian stock intraday

### SI-01 9:25 F&O top-mover body-range breakout on 3 minutes (no-gap stocks, index-aligned), ATM option buy

Video: "The 9:25 AM Option Buying Strategy That Just Works! | Ft. Neha Gupta" - Upsurge Club, uploaded 2026-11-08, 42 min - https://youtu.be/XhFNkKnr9hk (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NSE F&O stocks, traded through ATM (or near-ATM) calls/puts or futures; purely intraday. ([03:41](https://youtu.be/XhFNkKnr9hk?t=221), [13:50](https://youtu.be/XhFNkKnr9hk?t=830))
- **Session**
  - [E] 9:15-9:25: only observe; Nifty and Bank Nifty above the previous close (any amount, 1-2 minute charts) = positive day, below = negative. ([03:41](https://youtu.be/XhFNkKnr9hk?t=221), [04:28](https://youtu.be/XhFNkKnr9hk?t=268))
- **Setup**
  - [E] Scan the NSE F&O top gainers on a positive day (top losers on a negative day). ([05:11](https://youtu.be/XhFNkKnr9hk?t=311), [07:59](https://youtu.be/XhFNkKnr9hk?t=479))
  - [E] Mark the 9:15-9:25 range from candle bodies (closes), ignoring wicks, on 3-minute candles. ([05:52](https://youtu.be/XhFNkKnr9hk?t=352), [10:51](https://youtu.be/XhFNkKnr9hk?t=651))
- **Entry and confirmation**
  - [E] Enter when a 3-minute candle (from the 9:24-9:27 candle on) closes beyond the range: buy at that close (ATM call for gainers, put for losers). ([06:39](https://youtu.be/XhFNkKnr9hk?t=399), [07:19](https://youtu.be/XhFNkKnr9hk?t=439), [10:05](https://youtu.be/XhFNkKnr9hk?t=605))
- **Stop-loss**
  - [E] Stop below the range / the previous candle with a small buffer. ([11:37](https://youtu.be/XhFNkKnr9hk?t=697), [12:22](https://youtu.be/XhFNkKnr9hk?t=742))
- **Target**
  - [E] Target about 1% of the stock (10-12 points on TCS); then trail with EMA 9 after the first 10 points; book in parts with several lots. ([12:22](https://youtu.be/XhFNkKnr9hk?t=742), [15:59](https://youtu.be/XhFNkKnr9hk?t=959))
- **Filters**
  - [E] If Nifty and Bank Nifty disagree, trade stocks with their own index (Nifty stocks with Nifty, banks with Bank Nifty). ([14:34](https://youtu.be/XhFNkKnr9hk?t=874), [21:00](https://youtu.be/XhFNkKnr9hk?t=1260))
  - [E] Drop stocks that gapped up or down (even 0.5%) and stocks that moved 4-5% in the first 10 minutes (exhausted), unless they then built a range. ([05:11](https://youtu.be/XhFNkKnr9hk?t=311), [05:52](https://youtu.be/XhFNkKnr9hk?t=352))
- **When not to trade**
  - [E] No new trades after 10:30 (open ones may be carried); most trades close by 9:45-10:00; 1-2 trades a day. ([15:59](https://youtu.be/XhFNkKnr9hk?t=959), [16:44](https://youtu.be/XhFNkKnr9hk?t=1004))
  - [E] Avoid banking stocks on RBI press-conference days. ([18:10](https://youtu.be/XhFNkKnr9hk?t=1090))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk proxy: the stock itself on the NSE 5-minute pool's own 5-minute bars (the pool has no 1-minute rows to build 3-minute bars; option premiums are not available); universe = the pool's stocks ranked by change from the previous close at 9:25; gap = |open/prev close - 1| >= 0.5% excluded; more than 4% move by 9:25 excluded.
- [A] Coded: stop 0.05% beyond the body range's far side; half at 1% of the stock price, then the rest exits on a 5-minute close back across EMA 9 (or at 15:15); entries from the first close beyond the range, 09:25-10:30; one trade per stock a day; the three biggest qualifying movers on NIFTY's side are eligible.

Why the status: Option premiums replaced by the stock (A); target and trail mix need numbers (A)

### SI-02 Fixed watchlist: 9:15-9:30 range break on the VWAP side, pullback engulfing entry, stop beyond VWAP

Video: "Fixed Watchlist Intraday Trading Strategy | ORB + VWAP Pullback Setup" - Dhan ⚡, uploaded 2026-10-14, 9 min - https://youtu.be/9hWKM8bAWl4 (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] A fixed list of 5-6 (at most 10) liquid NIFTY 50 F&O stocks, one per sector, used for at least two months; no scanners. ([01:26](https://youtu.be/9hWKM8bAWl4?t=86), [02:07](https://youtu.be/9hWKM8bAWl4?t=127))
- **Indicators and settings**
  - [E] VWAP (default) and the opening-range indicator set to 9:15-9:30 (15 minutes). ([02:07](https://youtu.be/9hWKM8bAWl4?t=127), [02:48](https://youtu.be/9hWKM8bAWl4?t=168))
- **Setup**
  - [E] Around 9:20-9:30 sort the list into trending-up and trending-down stocks; trade only a stock whose opening range has broken. ([02:48](https://youtu.be/9hWKM8bAWl4?t=168), [03:33](https://youtu.be/9hWKM8bAWl4?t=213))
- **Entry and confirmation**
  - [E] Wait for a pullback toward VWAP / the averages and enter on a bearish engulfing (bullish engulfing for longs); the closer to VWAP the better; no trade without a pullback. ([03:33](https://youtu.be/9hWKM8bAWl4?t=213), [04:16](https://youtu.be/9hWKM8bAWl4?t=256), [07:02](https://youtu.be/9hWKM8bAWl4?t=422))
- **Stop-loss**
  - [E] Stop above VWAP for shorts (below for longs). ([04:16](https://youtu.be/9hWKM8bAWl4?t=256), [04:56](https://youtu.be/9hWKM8bAWl4?t=296))
- **Position sizing and risk**
  - [E] Divide the daily risk by the 3-4 trades the list can give (e.g. Rs 5,000 a day = Rs 1,000-1,250 a stock). ([04:56](https://youtu.be/9hWKM8bAWl4?t=296), [06:19](https://youtu.be/9hWKM8bAWl4?t=379))
- **Filters**
  - [E] Short only with price below VWAP after a downside break (long only above VWAP after an upside break). ([02:48](https://youtu.be/9hWKM8bAWl4?t=168), [03:33](https://youtu.be/9hWKM8bAWl4?t=213))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk version: the 6 most liquid NIFTY 50 stocks of the NSE 5-minute pool by the previous month's turnover, fixed for a month; break = a 5-minute close beyond the 9:15-9:30 range on the VWAP side; pullback = a later bar trading within 0.2% of VWAP; engulfing as in yc_common; entry at the next open, 09:35-13:30.
- [A] No target is stated: coded 2R; stop 0.05% beyond VWAP at the signal bar (at least 0.3% from entry); one trade per stock per day; exit 15:15.

Why the status: No target is given (A); the list is the trader's own choice (A: top 6 by turnover)

### SI-03 NIFTY second-and-third 15-minute candle range (9:30-10:00), first break in the running candle

Video: "Perfect Entry & Exit Strategy for Intraday Trading (₹1,00,000 Course FREE!) 🚀" - AbhishekXTrades, uploaded 2025-03-21, 19 min - https://youtu.be/Pv1K3OwPIuc (transcript: YouTube auto-captions (hi-orig))
Status: Duplicate of AX-03 - not added again. AX-03 (AbhishekXTrades, 20-channel study) already trades this 9:30-10:00 range break on NIFTY 15-minute candles (with a fixed 25-point scalp); TB-02 is the 5-minute version.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY on 15-minute candles. ([04:12](https://youtu.be/Pv1K3OwPIuc?t=252))
- **Session**
  - [E] Wait for the first three 15-minute candles (until 9:45-10:00); forget the 9:15-9:30 candle. ([04:12](https://youtu.be/Pv1K3OwPIuc?t=252), [04:55](https://youtu.be/Pv1K3OwPIuc?t=295))
- **Setup**
  - [E] Mark the highest high and lowest low of the second and third candles: the trigger range. ([05:37](https://youtu.be/Pv1K3OwPIuc?t=337))
- **Entry and confirmation**
  - [E] Enter on the side whose line breaks first, inside the running candle (no close needed). ([06:18](https://youtu.be/Pv1K3OwPIuc?t=378), [07:03](https://youtu.be/Pv1K3OwPIuc?t=423))
- **Stop-loss**
  - [E] Stop at the opposite line. ([06:18](https://youtu.be/Pv1K3OwPIuc?t=378))

Why the status: No target is given in this part; stop-and-reverse and risk rules promised separately

### SI-04 NIFTY first 15-minute candle colour picks the side; top three movers, break of their second 15-minute candle, 1:2

Video: "Best Intraday Stock Trading Strategy By Jabalpur Share Bazar ||High-accuracy intraday entry strategy" - Jabalpur Share Bazar, uploaded 2025-12-09, 9 min - https://youtu.be/HeZUP-j1tN8 (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NSE stocks from the NSE website's advance/decline (top gainers/losers) lists; a 52-week high/low list is also mentioned. ([00:42](https://youtu.be/HeZUP-j1tN8?t=42), [02:45](https://youtu.be/HeZUP-j1tN8?t=165))
- **Timeframe**
  - [E] 15-minute candles. ([01:22](https://youtu.be/HeZUP-j1tN8?t=82), [02:45](https://youtu.be/HeZUP-j1tN8?t=165))
- **Setup**
  - [E] NIFTY's first 15-minute candle: red = pick stocks from the decliners and sell; green = from the advancers and buy. ([01:22](https://youtu.be/HeZUP-j1tN8?t=82), [02:03](https://youtu.be/HeZUP-j1tN8?t=123))
  - [E] Take the first three stocks of that list around 9:20-9:25. ([03:27](https://youtu.be/HeZUP-j1tN8?t=207), [06:16](https://youtu.be/HeZUP-j1tN8?t=376))
- **Entry and confirmation**
  - [E] On each stock skip the first 15-minute candle; mark the second 15-minute candle's high and low; for sells enter when its low breaks (high for buys); a break the other way is not traded. ([04:49](https://youtu.be/HeZUP-j1tN8?t=289), [05:32](https://youtu.be/HeZUP-j1tN8?t=332), [06:56](https://youtu.be/HeZUP-j1tN8?t=416))
- **Stop-loss**
  - [E] Stop at the other end of the second candle. ([05:32](https://youtu.be/HeZUP-j1tN8?t=332), [07:38](https://youtu.be/HeZUP-j1tN8?t=458))
- **Target**
  - [E] Target 1:2 or 1:3. ([07:38](https://youtu.be/HeZUP-j1tN8?t=458))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk version: the NSE 5-minute pool on 15-minute bars; movers = the three pool stocks with the largest fall (rise) from the previous close at 9:30 on the chosen side.
- [A] Stop-entry at the second candle's low (high) from 09:45, valid until 11:00; stop 0.05% beyond its other end; target 2R; one trade per stock; exit 15:15.

Why the status: The 52-week list's role is unclear; order life not stated (A)

### SI-05 Futures OI-gainer selection + long build-up check + EMA 20/50/200 stack (5 minutes)

Video: "How To Select Stocks For Intraday Trading in 2026 (Best Strategy)" - Dhan ⚡, uploaded 2026-04-18, 10 min - https://youtu.be/1EPFJY4Mhws (transcript: YouTube auto-captions (hi-orig))
Status: Blocked (no paper account): stock selection by intraday futures open-interest build-up, which the desk does not have; the entry candle is not defined beyond an EMA stack.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Indicators and settings**
  - [E] 5-minute chart with EMA 20, 50 and 200. ([04:26](https://youtu.be/1EPFJY4Mhws?t=266), [07:16](https://youtu.be/1EPFJY4Mhws?t=436))
- **Setup**
  - [E] Pick large companies from the futures OI-gainers list with a large OI, a large OI change and a large percentage OI change. ([02:14](https://youtu.be/1EPFJY4Mhws?t=134), [03:41](https://youtu.be/1EPFJY4Mhws?t=221))
- **Entry and confirmation**
  - [E] Buy when EMA 20 is above EMA 50 and EMA 50 above EMA 200 and the build-up does not oppose; hold while the stack holds. ([05:08](https://youtu.be/1EPFJY4Mhws?t=308), [05:50](https://youtu.be/1EPFJY4Mhws?t=350))
- **Filters**
  - [E] Check the intraday OI build-up: for longs there must be no short build-up (long build-up, short covering or long unwinding are fine). ([02:56](https://youtu.be/1EPFJY4Mhws?t=176), [04:26](https://youtu.be/1EPFJY4Mhws?t=266), [05:50](https://youtu.be/1EPFJY4Mhws?t=350))
- **When not to trade**
  - [E] No new intraday trades after 14:30. ([06:33](https://youtu.be/1EPFJY4Mhws?t=393))

Why the status: Needs intraday stock-futures open interest and OI build-up by interval, which the desk does not have; the entry trigger is not defined beyond the EMA stack

### SI-06 SMMA 11/21 crossover on the side of the higher-timeframe 21 average (5-minute stocks / 3-minute index)

Video: "This INTRADAY Trading Strategy Helped Me Quit My Job | Ft. Pawan Sharma" - Upsurge Club, uploaded 2026-01-23, 32 min - https://youtu.be/-KUnWt8PqAY (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Any instrument (NIFTY, Bank Nifty, stocks, commodities); intraday on 3 minutes for indices, at least 5 minutes for stocks; 15 minutes for swings. ([05:41](https://youtu.be/-KUnWt8PqAY?t=341), [20:07](https://youtu.be/-KUnWt8PqAY?t=1207))
- **Indicators and settings**
  - [E] Two smoothed moving averages (SMMA) of 11 and 21 on the trading chart. ([07:42](https://youtu.be/-KUnWt8PqAY?t=462), [08:22](https://youtu.be/-KUnWt8PqAY?t=502))
  - [E] A 21-period moving average from the higher timeframe (15 minutes for a 5-minute chart; 30 or 60 minutes for a 15-minute chart), plotted with TradingView's 'Moving Average HTF'. ([09:48](https://youtu.be/-KUnWt8PqAY?t=588), [10:27](https://youtu.be/-KUnWt8PqAY?t=627))
- **Entry and confirmation**
  - [E] Buy on SMMA 11 crossing above SMMA 21 only while price is above the higher-timeframe MA; sell on the bearish cross only below it; ignore every cross against that side. ([09:07](https://youtu.be/-KUnWt8PqAY?t=547), [13:14](https://youtu.be/-KUnWt8PqAY?t=794), [14:38](https://youtu.be/-KUnWt8PqAY?t=878))
  - [E] Enter on the confirmation candle after the cross (the second candle), with price above all three averages; up to 4-5 candles after the cross is acceptable, not when price has already run 15-16 candles. ([16:41](https://youtu.be/-KUnWt8PqAY?t=1001), [17:24](https://youtu.be/-KUnWt8PqAY?t=1044))
- **Stop-loss**
  - [E] Entered after the setup matures the stop is about 30-35 NIFTY points (10-15 in options). ([19:27](https://youtu.be/-KUnWt8PqAY?t=1167))
- **Target**
  - [E] Book 50% at the expected result and let the rest run. ([23:38](https://youtu.be/-KUnWt8PqAY?t=1418))
- **When not to trade**
  - [E] Ignore crosses between 9:15 and 9:30; no new trades after 14:30 (open trades continue). ([18:47](https://youtu.be/-KUnWt8PqAY?t=1127), [20:07](https://youtu.be/-KUnWt8PqAY?t=1207))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk version: the NSE 5-minute stock pool with the higher-timeframe MA = SMA 21 of completed 15-minute bars, plus NIFTY on 3-minute bars with the same 15-minute filter; SMMA = Wilder (RMA) smoothing of closes.
- [A] Entry at the next open after the first close beyond all three averages within 4 bars of the cross; stop below the lowest low of the last 6 bars (above the highest high for shorts), at least 0.15% and at most 0.6%; half at 2R, the rest exits on the opposite SMMA cross or at 15:15.

Why the status: Stop and target are only approximate in the video (A)

### SI-07 Lowest-volume opposite candle after a three-candle move (Kushal Varshney)

Video: "Intraday Secret Strategy | सबसे छोटा Stoploss सबसे बड़ा Target? | Kushal Varshney | Sagar Kummar" - Sagar Kummar, uploaded 2026-05-09, 37 min - https://youtu.be/rOBS_fgFIZE (transcript: YouTube auto-captions (hi-orig))
Status: Duplicate of SS-03 - not added again. SS-03 (Kushal Varshney via Sagar Sinha, 11-channel study) already trades the lowest-volume opposite candle with a stop at its far end.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Session**
  - [E] No trades from 9:15 to 9:25 (let the first two 5-minute candles absorb volatility). ([04:20](https://youtu.be/rOBS_fgFIZE?t=260), [05:01](https://youtu.be/rOBS_fgFIZE?t=301))
- **Setup**
  - [E] After at least three candles of a move, wait for the first opposite-colour candle (a red candle in a rise = stoppage). ([05:42](https://youtu.be/rOBS_fgFIZE?t=342), [06:26](https://youtu.be/rOBS_fgFIZE?t=386))
- **Entry and confirmation**
  - [E] If that opposite candle has the lowest volume of the move's candles, buy above its high (sell below its low in a fall). ([07:06](https://youtu.be/rOBS_fgFIZE?t=426), [07:50](https://youtu.be/rOBS_fgFIZE?t=470), [08:33](https://youtu.be/rOBS_fgFIZE?t=513))
- **Stop-loss**
  - [E] Stop at that candle's low (high for sells). ([08:33](https://youtu.be/rOBS_fgFIZE?t=513), [09:17](https://youtu.be/rOBS_fgFIZE?t=557))

Why the status: Stock selection and target are explained later in the video (not coded here)

### SI-08 Previous afternoon (14:00-15:30) range around VWAP: break, pullback, engulfing entry, 1:2 (fixed list)

Video: "VWAP + Price Action: The Intraday Setup That Works!" - Dhan ⚡, uploaded 2026-04-10, 14 min - https://youtu.be/kAF642I922g (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] A fixed list of about 10 liquid NIFTY 50 stocks (Titan, Trent, Bajaj Finance, Bajaj Finserv, Maruti, HDFC Bank, SBI...) plus NIFTY / Bank Nifty; avoid easily manipulated stocks. ([00:46](https://youtu.be/kAF642I922g?t=46), [01:28](https://youtu.be/kAF642I922g?t=88))
- **Indicators and settings**
  - [E] VWAP, default settings (resets every day; flat in sideways markets). ([02:51](https://youtu.be/kAF642I922g?t=171), [03:35](https://youtu.be/kAF642I922g?t=215))
- **Setup**
  - [E] A consolidation range around VWAP: best the previous day's 14:00-15:30 range (or a range built today). ([04:18](https://youtu.be/kAF642I922g?t=258), [07:12](https://youtu.be/kAF642I922g?t=432), [11:21](https://youtu.be/kAF642I922g?t=681))
- **Entry and confirmation**
  - [E] When price breaks out of (down from) the range, do not enter on the break: wait for a pullback and enter on a bullish (bearish) engulfing or a close above (below) the first candle after the pullback. ([05:02](https://youtu.be/kAF642I922g?t=302), [05:43](https://youtu.be/kAF642I922g?t=343), [07:12](https://youtu.be/kAF642I922g?t=432))
- **Stop-loss**
  - [E] Stop beyond the range (above the range high for shorts) or below the pullback candle. ([05:02](https://youtu.be/kAF642I922g?t=302), [06:26](https://youtu.be/kAF642I922g?t=386))
- **Target**
  - [E] Target 1:2 or 1:3. ([05:02](https://youtu.be/kAF642I922g?t=302), [05:43](https://youtu.be/kAF642I922g?t=343))
- **Position sizing and risk**
  - [E] Buy in two halves (half on the pullback, half on the breakout) if desired. ([06:26](https://youtu.be/kAF642I922g?t=386))
- **When not to trade**
  - [E] No new trades after 14:00; no trade when candles are messy inside the range. ([10:40](https://youtu.be/kAF642I922g?t=640), [12:02](https://youtu.be/kAF642I922g?t=722))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk version: the 10 most liquid NIFTY 50 stocks of the NSE 5-minute pool (previous month's turnover) and NIFTY; range = the previous session's 14:00-15:30 high and low, used only if it is narrower than 1.2% and VWAP moved less than 0.3% in that window.
- [A] Break = a 5-minute close beyond the range from 09:20; pullback = a later bar trading back within 0.15% of the broken level; entry at the next open after an engulfing in the break direction; stop 0.05% beyond the pullback's extreme, at least 0.2%; target 2R; entries until 14:00; exit 15:15; one trade per stock per day.

Why the status: The range and the pullback need numbers (A)

### SI-09 First 15-minute candle breakout on 5 minutes, stop at the far side, 1:2, nothing after 10:00, no Tuesdays

Video: "9.15 AM Intraday strategy | Intraday strategy for beginners | Intraday trading for beginners |" - Anant Ladha, uploaded 2024-10-30, 11 min - https://youtu.be/g0xJhdy4asQ (transcript: YouTube auto-captions (hi-orig))
Status: Duplicate of BB-02 - not added again. BB-02 (Booming Bulls) already trades the NIFTY 15-minute opening-range breakout on 5 minutes with the opposite-side stop; this version adds a 10:00 cut-off and a Tuesday skip, which change no rule of the core setup.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY intraday (directional / option buying). ([01:33](https://youtu.be/g0xJhdy4asQ?t=93))
- **Setup**
  - [E] Mark the first 15-minute candle's high and low including the wicks. ([01:33](https://youtu.be/g0xJhdy4asQ?t=93), [02:14](https://youtu.be/g0xJhdy4asQ?t=134))
- **Entry and confirmation**
  - [E] On the 5-minute chart, buy the break above the high, sell the break below the low. ([02:14](https://youtu.be/g0xJhdy4asQ?t=134), [02:54](https://youtu.be/g0xJhdy4asQ?t=174))
- **Stop-loss**
  - [E] Stop at the 15-minute candle's other end. ([02:54](https://youtu.be/g0xJhdy4asQ?t=174))
- **Target**
  - [E] Target 1:2 (always keep at least 1:2). ([02:54](https://youtu.be/g0xJhdy4asQ?t=174), [04:14](https://youtu.be/g0xJhdy4asQ?t=254))
- **Trade management**
  - [E] If the target comes within minutes, book 50% and trail the rest with the 5-minute 10-period moving average. ([04:14](https://youtu.be/g0xJhdy4asQ?t=254))
- **When not to trade**
  - [E] If there is no break before 10:00, skip the day. ([03:34](https://youtu.be/g0xJhdy4asQ?t=214))
  - [E] Avoid Tuesdays (currently range-bound). ([03:34](https://youtu.be/g0xJhdy4asQ?t=214))

Why the status: Every rule is stated (the trail is optional)

### SI-10 Breadth-chosen sector, previous-day high/low break with two same-colour 5-minute candles, half at 1:2, rest to 15:15

Video: "Intraday Trading का Secret! Best Sectorial Strategy for Big Profits | @primetechnicalindiapvtltd  | BKM |" - Bazaar Ke Mahir, uploaded 2025-01-28, 25 min - https://youtu.be/ibO1Sp1bess (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Session**
  - [E] At 9:20-9:25 check NIFTY 50 advances vs declines on the NSE site: more declines = short the weakest sector; more advances = buy the strongest. ([05:05](https://youtu.be/ibO1Sp1bess?t=305), [06:28](https://youtu.be/ibO1Sp1bess?t=388))
- **Setup**
  - [E] Rank the 11 sector indices (metal, PSU banks, financial services, FMCG, private banks, auto, IT, media, energy, realty, pharma) by % change; take the top (or bottom) sector's stocks from a prepared watchlist. ([06:28](https://youtu.be/ibO1Sp1bess?t=388), [07:49](https://youtu.be/ibO1Sp1bess?t=469))
  - [E] Use the previous day's high and low; a stock inside that range is not traded; for shorts it must break the previous day's low. ([09:11](https://youtu.be/ibO1Sp1bess?t=551), [09:59](https://youtu.be/ibO1Sp1bess?t=599))
- **Entry and confirmation**
  - [E] 5-minute chart: a 'master' red candle closes below the previous day's low, the next 'confirmation' candle is also red; sell below the confirmation candle (low). ([10:39](https://youtu.be/ibO1Sp1bess?t=639), [11:28](https://youtu.be/ibO1Sp1bess?t=688), [12:53](https://youtu.be/ibO1Sp1bess?t=773))
  - [E] Longs: a master green candle closing above the previous day's high, a green confirmation candle, buy above it, same 3% and 1% rules. ([13:36](https://youtu.be/ibO1Sp1bess?t=816), [14:18](https://youtu.be/ibO1Sp1bess?t=858))
- **Stop-loss**
  - [E] Stop at the confirmation candle's high; the stop may be at most 1% of the stock price. ([12:11](https://youtu.be/ibO1Sp1bess?t=731), [12:53](https://youtu.be/ibO1Sp1bess?t=773))
- **Target**
  - [E] Book half at 1:2 and hold the rest until 15:15. ([13:36](https://youtu.be/ibO1Sp1bess?t=816))
- **When not to trade**
  - [E] Ignore the setup if the first (master) candle is bigger than 3%. ([11:28](https://youtu.be/ibO1Sp1bess?t=688))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk version: breadth = pool stocks up vs down from the previous close at 9:25 (the NIFTY 50 list itself is not stored); the sector ranking is dropped (no sector map in the pool) - every pool stock on the chosen side may trade; documented as a simplification.
- [A] Sell-stop at the confirmation candle's low valid for 2 bars; stop 0.02% beyond its high; skip if the stop exceeds 1% or the master candle exceeds 3%; half at 2R, rest to 15:15; entries 09:20-13:30; each stock is its own book (the video's few-stocks-a-day limit is not coded).

Why the status: The sector ranking cannot be coded on the desk pool (A: dropped); order life not stated (A)

### SI-11 9:30 open-equals-low gainer (open-equals-high loser): first 15-minute candle breakout, stop at the open

Video: "One Setup, One Trade Every Day | Ft. Rajesh Jain" - Upsurge Club, uploaded 2026-08-20, 26 min - https://youtu.be/nlXGU_7xxjA (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] NIFTY 50 stocks from the NSE top gainers / losers list (equity, futures, or an option whose own open equals its low). ([02:08](https://youtu.be/nlXGU_7xxjA?t=128), [02:51](https://youtu.be/nlXGU_7xxjA?t=171))
- **Session**
  - [E] Check at 9:28-9:30, after the first 15-minute candle completes. ([02:51](https://youtu.be/nlXGU_7xxjA?t=171), [03:32](https://youtu.be/nlXGU_7xxjA?t=212))
- **Setup**
  - [E] Gainers: open equals low (e.g. Persistent 5335.80 open and low); losers: open equals high. ([02:51](https://youtu.be/nlXGU_7xxjA?t=171), [03:32](https://youtu.be/nlXGU_7xxjA?t=212))
- **Entry and confirmation**
  - [E] Buy when the first 15-minute candle's high breaks (sell when the low breaks for open = high). ([03:32](https://youtu.be/nlXGU_7xxjA?t=212), [04:15](https://youtu.be/nlXGU_7xxjA?t=255))
- **Stop-loss**
  - [E] Stop at the low (= the open) for buys; at the high for sells. ([03:32](https://youtu.be/nlXGU_7xxjA?t=212), [09:16](https://youtu.be/nlXGU_7xxjA?t=556))
- **Target**
  - [E] Target equal to the stop distance (40 points of risk = 40 points of target), or hold until 14:00 while the stop holds. ([09:16](https://youtu.be/nlXGU_7xxjA?t=556), [10:00](https://youtu.be/nlXGU_7xxjA?t=600))
- **Exit**
  - [E] Otherwise exit by 14:00. ([00:02](https://youtu.be/nlXGU_7xxjA?t=2), [09:16](https://youtu.be/nlXGU_7xxjA?t=556))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk version: every stock of the NSE 5-minute pool (the pool stands in for the NIFTY 50 list); gainer = up from the previous close at 9:30 and the 9:15-9:30 low within 0.02% of the open; loser mirror.
- [A] Buy-stop 0.02% above the 9:15-9:30 high from 9:30 until 10:30; stop at the open minus 0.02%; target 1R; exit 14:00; at most 2 stocks a day, the two biggest movers that qualify.

Why the status: 'Open equals low' needs a tolerance on 5-minute data (A); order life not stated (A)

### SI-12 Leading sector's top mover: 9:20 five-minute candle on the VWAP side, break of it, 1:1.5 then 1:2

Video: "Stock intraday strategy by Radhe The Trader | Vwap Strategy" - Radhe The Trader, uploaded 2026-06-04, 8 min - https://youtu.be/aW9LEPh43Go (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Timeframe**
  - [E] 5-minute chart with VWAP (centre line only). ([02:07](https://youtu.be/aW9LEPh43Go?t=127))
- **Setup**
  - [E] At 9:20-9:25 open the NSE heatmap (sectoral indices); pick the most bearish (bullish) sector and its weakest (strongest) stock, e.g. TCS in a weak IT sector. ([00:02](https://youtu.be/aW9LEPh43Go?t=2), [00:44](https://youtu.be/aW9LEPh43Go?t=44), [01:25](https://youtu.be/aW9LEPh43Go?t=85))
- **Entry and confirmation**
  - [E] Bearish: the 9:20-9:25 candle closes red below VWAP; sell only when its low breaks (no red candle or no break = no trade). ([02:47](https://youtu.be/aW9LEPh43Go?t=167), [03:29](https://youtu.be/aW9LEPh43Go?t=209))
  - [E] Bullish: the 9:20 candle green above VWAP; buy when its high breaks; stop at its low (same cap). ([04:53](https://youtu.be/aW9LEPh43Go?t=293), [05:36](https://youtu.be/aW9LEPh43Go?t=336))
- **Stop-loss**
  - [E] Stop at that candle's high, but at most 0.6% (if the candle is bigger, use 0.6%). ([03:29](https://youtu.be/aW9LEPh43Go?t=209), [04:09](https://youtu.be/aW9LEPh43Go?t=249))
- **Target**
  - [E] First target 1:1.5 for half, then stop to cost, rest at 1:2. ([04:09](https://youtu.be/aW9LEPh43Go?t=249))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Desk version: the NSE 5-minute pool; the sector step is dropped (no sector map); the stock = the pool's largest loser (gainer) from the previous close at 9:25 on the side of NIFTY's change; VWAP from the stock's own volume.
- [A] Stop-entry at the 9:20 candle's low (high) from 9:25 until 10:30; stop at its other end, capped at 0.6%; half at 1.5R then stop to entry, rest at 2R; exit 15:15; one trade a day.

Why the status: The sector ranking cannot be coded on the desk pool (A: dropped); order life not stated (A)

### SI-13 First-hour (9:15-10:15) range breakout, touch entry, opposite-side stop, out at 15:15, one trade a day

Video: "This strategy works in INTRADAY: Everything about Opening Range Breakout (ORB) Day trading strategy" - Nataraj Malavade - Trading, uploaded 2023-04-03, 21 min - https://youtu.be/wch7m96yZ2M (transcript: YouTube auto-captions (en-orig))
Status: Coded as v1 (every core rule stated).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Volatile and liquid instruments: Bank Nifty preferred over NIFTY; high-beta liquid stocks. ([08:32](https://youtu.be/wch7m96yZ2M?t=512), [09:13](https://youtu.be/wch7m96yZ2M?t=553))
- **Setup**
  - [E] Opening range = the first hour's high and low (9:15-10:15), because the day's high/low is set in the first hour on about 64% (NIFTY) / 70% (Bank Nifty) of days. ([04:57](https://youtu.be/wch7m96yZ2M?t=297), [05:37](https://youtu.be/wch7m96yZ2M?t=337))
- **Entry and confirmation**
  - [E] Long when price breaks the range high, short when it breaks the low; he prefers a touch entry (closing entry also tested). ([06:46](https://youtu.be/wch7m96yZ2M?t=406), [07:04](https://youtu.be/wch7m96yZ2M?t=424), [16:24](https://youtu.be/wch7m96yZ2M?t=984))
- **Stop-loss**
  - [E] Stop at the opposite side of the range (ATR or percent stops are optional variations). ([07:04](https://youtu.be/wch7m96yZ2M?t=424), [17:08](https://youtu.be/wch7m96yZ2M?t=1028))
- **Exit**
  - [E] Square off at 15:15-15:20 if the stop is not hit; no target. ([07:48](https://youtu.be/wch7m96yZ2M?t=468), [14:22](https://youtu.be/wch7m96yZ2M?t=862))
- **Filters**
  - [E] One trade per instrument per day. ([09:13](https://youtu.be/wch7m96yZ2M?t=553), [09:55](https://youtu.be/wch7m96yZ2M?t=595))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Coded on NIFTY and BANKNIFTY index minutes: stop orders at the 9:15-10:15 high and low from 10:15 (OCO, first touch wins), valid until 15:00; stop at the opposite side; exit 15:15.

Why the status: Every rule is stated (touch entry, opposite stop, 15:15 exit, one trade)

## Bitcoin intraday

### BI-01 Bitcoin 05:30-09:30 IST four-hour opening range, 15-minute breakout, 2 ATR stop from the range line

Video: "The 5:30 AM Rule That Makes ORB Work for Bitcoin | Crypto Intraday Strategy | CoinDCX" - CoinDCX, uploaded 2025-10-28, 21 min - https://youtu.be/3XW9lCrMnmg (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Bitcoin (BTC futures on CoinDCX). ([05:35](https://youtu.be/3XW9lCrMnmg?t=335))
- **Timeframe**
  - [E] Trades are taken on the 15-minute chart, only after 09:30 IST (a vertical line marks 09:30). ([06:21](https://youtu.be/3XW9lCrMnmg?t=381), [11:54](https://youtu.be/3XW9lCrMnmg?t=714))
- **Session**
  - [E] The range is the high and low of the first 4-hour candle of the day, 05:30-09:30 IST: the chart resets at 00:00 GMT = 05:30 IST. ([02:47](https://youtu.be/3XW9lCrMnmg?t=167), [06:21](https://youtu.be/3XW9lCrMnmg?t=381))
- **Indicators and settings**
  - [E] ATR, default length 14, read on the 15-minute chart. ([04:52](https://youtu.be/3XW9lCrMnmg?t=292))
- **Setup**
  - [E] A break above the range high allows longs only; a break below the range low allows shorts only. ([06:21](https://youtu.be/3XW9lCrMnmg?t=381))
  - [E] The breakout candle must close strongly: at least 40-50% of its body beyond the range line (body, not wicks). ([06:21](https://youtu.be/3XW9lCrMnmg?t=381), [07:01](https://youtu.be/3XW9lCrMnmg?t=421))
- **Entry and confirmation**
  - [E] Entry: a stop order 0.03% beyond the breakout candle's extreme (below its low for shorts, above its high for longs); 0.01% for aggressive traders. ([07:01](https://youtu.be/3XW9lCrMnmg?t=421), [12:36](https://youtu.be/3XW9lCrMnmg?t=756), [14:48](https://youtu.be/3XW9lCrMnmg?t=888))
  - [E] If the breakout candle's extreme is not taken out, there is no trade from it; a later prominent close or follow-up candle beyond the line gives the new trigger (its extreme plus the buffer). ([12:36](https://youtu.be/3XW9lCrMnmg?t=756), [13:20](https://youtu.be/3XW9lCrMnmg?t=800))
- **Stop-loss**
  - [E] Stop: 2 x ATR of the 15-minute breakout candle, measured from the broken range line (above the range low for shorts, below the range high for longs), not from the candle. ([07:41](https://youtu.be/3XW9lCrMnmg?t=461), [13:20](https://youtu.be/3XW9lCrMnmg?t=800), [17:37](https://youtu.be/3XW9lCrMnmg?t=1057))
- **Target**
  - [E] Trade two lots: book 50% at 1:1, move the stop on the rest to cost, book the rest at 1:2 (for the first 100 trades). ([07:41](https://youtu.be/3XW9lCrMnmg?t=461), [15:31](https://youtu.be/3XW9lCrMnmg?t=931))
- **Trade management**
  - [E] After 100 trades: the second half may run to 1:3-1:4 or be trailed (ATR, swing, previous two candles); trailing is not detailed. ([08:23](https://youtu.be/3XW9lCrMnmg?t=503), [15:31](https://youtu.be/3XW9lCrMnmg?t=931))
- **Position sizing and risk**
  - [E] Quantity is split into two equal halves (dual lots). ([07:41](https://youtu.be/3XW9lCrMnmg?t=461))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Exit at the end of the bitcoin day (23:55 UTC, 05:25 IST) if neither target nor stop is reached (the video lets a trade run into the next morning).
- [A] At most one trade a day: every qualifying 15-minute candle places its own stop order (live until 23:55 UTC) and the first to fill is the day's trade.
- [A] "At least 40-50% of the body beyond the line" coded as: the 15-minute close beyond the line and at least 40% of the candle's body beyond it.

Why the status: No exit time or trade cap is stated (A); body threshold given as a range (40-50%)

### BI-02 Fresh zone inside a zone: 4-hour supply/demand refined to the two outermost untouched 15-minute zones, reversal-candle entry

Video: "High Accuracy 15-Min Zone Trading Strategy for Intraday Traders | 4-Hour to 15-Min Setup" - CoinDCX, uploaded 2026-11-03, 28 min - https://youtu.be/2Ff07pvp4jE (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Shown on XAU/USDT on CoinDCX; the method is presented for all demand/supply trading on the platform (crypto). ([08:32](https://youtu.be/2Ff07pvp4jE?t=512), [09:16](https://youtu.be/2Ff07pvp4jE?t=556))
- **Timeframe**
  - [E] Higher timeframe 4 hours for the big zone, lower timeframe 15 minutes for the precise zones (cheat sheet: weekly/4h, daily/1h, 4h/15m, 15m/1m). ([05:38](https://youtu.be/2Ff07pvp4jE?t=338), [06:21](https://youtu.be/2Ff07pvp4jE?t=381))
- **Session**
  - [E] Trades are taken only after the 4-hour zone is complete (a vertical line after its last candle). ([21:54](https://youtu.be/2Ff07pvp4jE?t=1314), [24:40](https://youtu.be/2Ff07pvp4jE?t=1480))
- **Setup**
  - [E] Supply zone: the last green candle before price fell hard with red candles; demand zone: the last red candle before strong green candles; the box extends right. ([09:16](https://youtu.be/2Ff07pvp4jE?t=556))
  - [E] Inside the 4-hour zone, mark the 15-minute zones built the same way; a 15-minute zone counts as inside if more than 50% of it overlaps the 4-hour zone. ([10:38](https://youtu.be/2Ff07pvp4jE?t=638), [11:20](https://youtu.be/2Ff07pvp4jE?t=680))
  - [E] Only the two outermost 15-minute zones are valid: the top two in a supply zone, the bottom two in a demand zone (smaller stop, better risk-reward). ([12:04](https://youtu.be/2Ff07pvp4jE?t=724), [12:46](https://youtu.be/2Ff07pvp4jE?t=766), [27:25](https://youtu.be/2Ff07pvp4jE?t=1645))
- **Entry and confirmation**
  - [E] No blind limit orders: enter only when price comes into a valid 15-minute zone and forms one of six patterns: bullish/bearish engulfing, morning/evening star, hammer/inverted hammer. ([25:21](https://youtu.be/2Ff07pvp4jE?t=1521), [26:05](https://youtu.be/2Ff07pvp4jE?t=1565))
- **Stop-loss**
  - [E] Stop above the supply zone's highest point (below the demand zone's lowest point). ([12:46](https://youtu.be/2Ff07pvp4jE?t=766), [26:05](https://youtu.be/2Ff07pvp4jE?t=1565))
- **Target**
  - [E] Book 50% at 1:1, move the rest to cost and aim for 1:2-1:3 or the opposite zone. ([26:45](https://youtu.be/2Ff07pvp4jE?t=1605))
- **Position sizing and risk**
  - [E] Risk 1-2% of capital per trade even on strong zones. ([04:58](https://youtu.be/2Ff07pvp4jE?t=298))
- **Filters**
  - [E] Zones must be fresh: never touched by price after they formed (both the 4-hour and the 15-minute zone); a touched zone is dropped and the next one counts instead. ([13:27](https://youtu.be/2Ff07pvp4jE?t=807), [14:07](https://youtu.be/2Ff07pvp4jE?t=847), [23:18](https://youtu.be/2Ff07pvp4jE?t=1398))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Strong move from a base coded as: the two candles after the base candle move at least 1.5 ATR(14) away from it (closing beyond the base candle's far side); the zone is the base candle's full range.
- [A] Pattern coded as: a bearish engulfing / evening star / shooting star (inverted hammer) closing inside or after touching a valid supply zone (mirror for demand); entry at the next 15-minute open.
- [A] Stop 0.05% beyond the 15-minute zone's far side; the second half's target 2R.
- [A] Coded on bitcoin only: exit at 23:55 UTC if neither stop nor target is reached; one position at a time; a 4-hour zone is watched for ten days or until a 15-minute close beyond its far side.

Why the status: 'Strong move' and the pattern shapes need numbers (A); entry on the next open after the pattern

### BI-03 EMA 9/20 crossover at a twice-touched support or resistance, 5-minute bitcoin

Video: "🔥Ultimate Bitcoin Scalping Trading Strategy" - Trading Techstreet, uploaded 2025-11-29, 13 min - https://youtu.be/WOWeE7XuWOM (transcript: YouTube auto-captions (hi-orig))
Status: Duplicate of TD-01 - not added again. TD-01 (Trading Data) already trades a 9/20 EMA cross at a tested level with a 1.5R target; this video's version only drops TD-01's trend and discount filters.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Bitcoin only (later also gold and ether). ([06:33](https://youtu.be/WOWeE7XuWOM?t=393))
- **Timeframe**
  - [E] 5-minute chart only. ([06:33](https://youtu.be/WOWeE7XuWOM?t=393))
- **Indicators and settings**
  - [E] EMA 9 and EMA 20 on close. ([02:59](https://youtu.be/WOWeE7XuWOM?t=179), [03:41](https://youtu.be/WOWeE7XuWOM?t=221))
- **Setup**
  - [E] Mark support (demand) and resistance (supply) levels from the last 2-6 days; a level touched twice counts. ([05:47](https://youtu.be/WOWeE7XuWOM?t=347), [06:33](https://youtu.be/WOWeE7XuWOM?t=393), [07:17](https://youtu.be/WOWeE7XuWOM?t=437))
- **Entry and confirmation**
  - [E] Buy when EMA 9 crosses above EMA 20 at a support/demand level; sell when it crosses below at resistance/supply; enter on the crossing candle at once, without waiting for its close. ([05:07](https://youtu.be/WOWeE7XuWOM?t=307), [06:33](https://youtu.be/WOWeE7XuWOM?t=393), [08:43](https://youtu.be/WOWeE7XuWOM?t=523))
- **Stop-loss**
  - [E] Stop at the recent swing (a candle or two beyond). ([08:01](https://youtu.be/WOWeE7XuWOM?t=481), [08:43](https://youtu.be/WOWeE7XuWOM?t=523))
- **Target**
  - [E] Target at least 1:1.5 (book profit if 1.4 is all that comes); toward 1:2-1:3 take 70% out with the stop at cost and trail the rest. ([08:43](https://youtu.be/WOWeE7XuWOM?t=523))
- **When not to trade**
  - [E] A level break without a crossover is not a trade. ([09:30](https://youtu.be/WOWeE7XuWOM?t=570))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Level: a 5-minute swing high (low) confirmed by 2 bars each side, touched again within 0.15% at least once in the previous 3 days; the cross must happen within 0.15% of the level.
- [A] Target 1.5R; stop 0.05% beyond the latest confirmed 5-minute swing on the far side; exit at 23:55 UTC.

Why the status: Level and swing need numbers (A)

### BI-04 Bollinger W/M fakeout: first swing outside the band, fakeout of it, neckline break (5-minute bitcoin)

Video: "Bitcoin & Crypto Scalping Strategy |  5-Minute Chart Entry Setup | Powerful Strategy For Intraday" - HOLD with Priyank Live, uploaded 2026-09-01, 17 min - https://youtu.be/e3R9bi_coug (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Bitcoin against the dollar; the same works in stocks. ([01:26](https://youtu.be/e3R9bi_coug?t=86))
- **Timeframe**
  - [E] 5-minute chart (1 or 15 minutes also usable). ([01:26](https://youtu.be/e3R9bi_coug?t=86))
- **Indicators and settings**
  - [E] Bollinger Bands: 20-period moving average middle line, bands 2 standard deviations away. ([05:37](https://youtu.be/e3R9bi_coug?t=337), [06:18](https://youtu.be/e3R9bi_coug?t=378))
- **Setup**
  - [E] Get ready only when price leaves a band for the first time (by wick, body or breakout). ([08:24](https://youtu.be/e3R9bi_coug?t=504), [09:04](https://youtu.be/e3R9bi_coug?t=544))
  - [E] Mark the first swing low (high) that forms outside the lower (upper) band. ([09:04](https://youtu.be/e3R9bi_coug?t=544), [10:25](https://youtu.be/e3R9bi_coug?t=625), [11:05](https://youtu.be/e3R9bi_coug?t=665))
  - [E] Price must come back to that swing level and fake out: a wick through it with the close back inside (weak fakeout), or an immediate fakeout: one candle closes through the level and the next candle closes back. ([01:26](https://youtu.be/e3R9bi_coug?t=86), [04:14](https://youtu.be/e3R9bi_coug?t=254), [04:56](https://youtu.be/e3R9bi_coug?t=296))
- **Entry and confirmation**
  - [E] Entry when price breaks the neckline (the swing high between the two lows of the W; mirror for M); a breakout is confirmed by the closes of two candles. ([11:05](https://youtu.be/e3R9bi_coug?t=665), [12:25](https://youtu.be/e3R9bi_coug?t=745), [13:06](https://youtu.be/e3R9bi_coug?t=786))
- **Stop-loss**
  - [E] Stop below the lower band or below the swing low (beyond the band for shorts). ([09:45](https://youtu.be/e3R9bi_coug?t=585), [13:46](https://youtu.be/e3R9bi_coug?t=826), [15:14](https://youtu.be/e3R9bi_coug?t=914))
- **Target**
  - [E] Target 1 at 1:1 at least: book 50-60% and move the stop to entry; target 2 where the previous move began. ([09:45](https://youtu.be/e3R9bi_coug?t=585), [13:46](https://youtu.be/e3R9bi_coug?t=826), [14:28](https://youtu.be/e3R9bi_coug?t=868))
- **Filters**
  - [E] The opposite band must not be tested between the first swing and the fakeout; if it is, watch the opposite setup instead. ([11:41](https://youtu.be/e3R9bi_coug?t=701), [12:25](https://youtu.be/e3R9bi_coug?t=745))
- **When not to trade**
  - [E] Skip the trade if price is already far from the ideal entry (about two candles away). ([13:06](https://youtu.be/e3R9bi_coug?t=786), [15:14](https://youtu.be/e3R9bi_coug?t=914))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] First exit: a bar whose low (high) is beyond the band while the 5 bars before stayed inside; the swing is a 2-bar fractal low (high) beyond the band within 20 bars; the fakeout must come within 30 bars of the swing.
- [A] Entry at the next open after the first 5-minute close beyond the neckline; skipped if that close is more than 0.5R past the neckline.
- [A] Stop at the lower of the fakeout low and the band at the fakeout bar, plus 0.02%; half at 1R (the engine books halves), then stop to entry; second target = the extreme of the 30 bars before the first exit, at least 1.5R; out at 23:55 UTC.

Why the status: Swing, fakeout window and second target need numbers (A)

### BI-05 Bitcoin 8-hour structure range: buy the discount quarter after a break of structure (smart money)

Video: "Bitcoin Institutional Strategy (Step By Step)" - ETM FX, uploaded 2024-05-08, 15 min - https://youtu.be/eVqCSx887G8 (transcript: YouTube auto-captions (en-orig))
Status: Duplicate of CP-25 - not added again. The same deep-retracement buy of a structure range already trades as CP-25 (OTE 0.705-0.79) and YT-06 (OTE 62%); this is the 8-hour version with a 0.75 level.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Bitcoin. ([00:01](https://youtu.be/eVqCSx887G8?t=1))
- **Timeframe**
  - [E] Operating timeframe 8 hours (6 hours possible); lower it to 1 hour or 30 minutes when high volume makes swings unclear. ([02:53](https://youtu.be/eVqCSx887G8?t=173), [09:55](https://youtu.be/eVqCSx887G8?t=595))
- **Indicators and settings**
  - [E] Fibonacci in quarters (0, 0.25, 0.5, 0.75, 1): the bottom quarter is discount (buy), the top quarter premium (sell). ([01:28](https://youtu.be/eVqCSx887G8?t=88), [02:09](https://youtu.be/eVqCSx887G8?t=129))
- **Setup**
  - [E] Range: when price breaks a swing high and comes back inside the previous range, the new high is the top and the swing low that started the move is the bottom. ([00:44](https://youtu.be/eVqCSx887G8?t=44), [01:28](https://youtu.be/eVqCSx887G8?t=88))
- **Entry and confirmation**
  - [E] Buy when price retraces into the discount quarter (the extreme level) of the current range in a bullish cycle; mirror for sells. ([02:09](https://youtu.be/eVqCSx887G8?t=129), [05:39](https://youtu.be/eVqCSx887G8?t=339))
- **Stop-loss**
  - [E] Stop a little below the swing low (the origin of the extreme level). ([02:09](https://youtu.be/eVqCSx887G8?t=129), [05:39](https://youtu.be/eVqCSx887G8?t=339))
- **Target**
  - [E] First target back to the previous range (then breakeven at 1:1), second target the liquidity beyond. ([05:39](https://youtu.be/eVqCSx887G8?t=339), [06:20](https://youtu.be/eVqCSx887G8?t=380))
- **Trade management**
  - [E] Move the stop to breakeven conservatively; early breakeven can stop a good trade. ([07:46](https://youtu.be/eVqCSx887G8?t=466))

Why the status: Swing and break-of-structure definitions by eye; an 8-hour swing method, not intraday

### BI-06 Two-candle turn through EMA 6 on 1-hour bitcoin, 1:3

Video: "Crypto 5-Star Intraday Strategy | 90% Accuracy Trading Setup" - Dr. Mukul Agrawal : Stock Market Coach, uploaded 2025-07-11, 12 min - https://youtu.be/XIlGVsPpIRw (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Bitcoin, ether, Solana, XRP on CoinDCX. ([00:07](https://youtu.be/XIlGVsPpIRw?t=7), [08:28](https://youtu.be/XIlGVsPpIRw?t=508))
- **Timeframe**
  - [E] 1-hour candles. ([01:33](https://youtu.be/XIlGVsPpIRw?t=93), [11:18](https://youtu.be/XIlGVsPpIRw?t=678))
- **Indicators and settings**
  - [E] EMA with length 6 (changed from the default 9). ([02:17](https://youtu.be/XIlGVsPpIRw?t=137))
- **Setup**
  - [E] Sell setup: a green candle at the top, then a red candle that does not break the green candle's high. ([03:00](https://youtu.be/XIlGVsPpIRw?t=180), [03:40](https://youtu.be/XIlGVsPpIRw?t=220))
  - [E] Buy setup: a red candle, then a green candle that does not break the red candle's low. ([04:20](https://youtu.be/XIlGVsPpIRw?t=260), [05:02](https://youtu.be/XIlGVsPpIRw?t=302))
- **Entry and confirmation**
  - [E] Sell when price breaks below the red candle's low and comes under EMA 6. ([03:40](https://youtu.be/XIlGVsPpIRw?t=220), [11:18](https://youtu.be/XIlGVsPpIRw?t=678))
  - [E] Buy when price breaks above the green candle's high and is above EMA 6. ([11:18](https://youtu.be/XIlGVsPpIRw?t=678))
- **Stop-loss**
  - [E] Stop above the green candle's high for sells (below the red candle's low for buys). ([03:40](https://youtu.be/XIlGVsPpIRw?t=220))
- **Target**
  - [E] Target 3 to 4 times the stop distance (1:3); 2-3x mentioned for buys in the summary. ([03:40](https://youtu.be/XIlGVsPpIRw?t=220), [08:28](https://youtu.be/XIlGVsPpIRw?t=508), [11:18](https://youtu.be/XIlGVsPpIRw?t=678))
- **When not to trade**
  - [E] No entry if the break does not take price through EMA 6 (a spike that stays on the wrong side is not a trade). ([07:03](https://youtu.be/XIlGVsPpIRw?t=423))
  - [E] After a stop is hit in a sideways patch, stop trading until price breaks out of the channel, then take fresh entries. ([09:09](https://youtu.be/XIlGVsPpIRw?t=549), [09:51](https://youtu.be/XIlGVsPpIRw?t=591))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Entry: a stop order at the red candle's low (green candle's high for buys) placed after the pair closes at the lower of that low and EMA 6 of the pair's bar (the higher of the high and EMA 6 for buys), so a fill is always through both; valid for the next 3 hourly bars.
- [A] Target 3R; stop 0.02% beyond the pair's far candle; after a stop, no new entries for the rest of that UTC day (the sideways rule needs trade outcomes, which a signal cannot see); exit at 23:55 UTC.

Why the status: Order life and the sideways rule need numbers (A)

### BI-07 Three-candle zone retest with a rejection candle (5-minute bitcoin)

Video: "🤯One BTC Setup I 💰 BTC 5-Minute Trading Strategy | Simple & Powerful 🎯" - The Trading Pinnacle, uploaded 2026-08-16, 7 min - https://youtu.be/2_6VTstvm_w (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Bitcoin (crypto scalping). ([00:52](https://youtu.be/2_6VTstvm_w?t=52))
- **Timeframe**
  - [E] 5-minute chart. ([00:52](https://youtu.be/2_6VTstvm_w?t=52))
- **Setup**
  - [E] Identify the trend; in an uptrend find three back-to-back green candles with no red candle between them (three red in a downtrend); size, wicks and bodies do not matter. ([00:52](https://youtu.be/2_6VTstvm_w?t=52), [01:32](https://youtu.be/2_6VTstvm_w?t=92))
  - [E] Mark a zone (box) from the first to the third candle. ([01:32](https://youtu.be/2_6VTstvm_w?t=92), [02:56](https://youtu.be/2_6VTstvm_w?t=176))
- **Entry and confirmation**
  - [E] When price comes back into the zone and makes a rejection candle that closes in the trend's direction, enter on the next candle. ([01:32](https://youtu.be/2_6VTstvm_w?t=92), [02:13](https://youtu.be/2_6VTstvm_w?t=133), [05:01](https://youtu.be/2_6VTstvm_w?t=301))
- **Stop-loss**
  - [E] The stop is very small (5-minute timeframe); its exact place is not stated. ([02:13](https://youtu.be/2_6VTstvm_w?t=133))
- **Target**
  - [E] No fixed target: 1:5 to 1:10 claimed, 'hold for bigger'. ([00:52](https://youtu.be/2_6VTstvm_w?t=52), [02:56](https://youtu.be/2_6VTstvm_w?t=176), [04:21](https://youtu.be/2_6VTstvm_w?t=261))
- **When not to trade**
  - [E] If price breaks through the zone instead, the setup fails; look for the opposite setup. ([05:41](https://youtu.be/2_6VTstvm_w?t=341), [06:24](https://youtu.be/2_6VTstvm_w?t=384))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Trend: close above EMA 50 for longs (below for shorts) at the third candle; the zone is the low-high span of the three candles; it stays valid for 48 bars (4 hours) or until a close beyond its far side.
- [A] Rejection candle coded as: the low trades into the zone (long) and the candle closes green above the zone midpoint; entry at the next open.
- [A] Stop 0.02% beyond the zone's far side; target 3R (below the video's claimed 1:5); exit at 23:55 UTC; one position at a time.

Why the status: Stop place and target are not given (A); trend has no rule (A)

### BI-08 5-minute multi-touch level for direction, 1-minute structure breakout (scalp)

Video: "The Only 1-Minute Scalping Strategy" - MambaFx, uploaded 2025-11-13, 10 min - https://youtu.be/h-Z7CEqBO3s (transcript: YouTube auto-captions (en-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Shown on index CFDs (US30); presented as working on any market. ([04:10](https://youtu.be/h-Z7CEqBO3s?t=250))
- **Timeframe**
  - [E] Direction from the 5-minute chart; every entry on the 1-minute chart. ([00:43](https://youtu.be/h-Z7CEqBO3s?t=43))
- **Session**
  - [E] About 30 minutes of trading a day. ([09:07](https://youtu.be/h-Z7CEqBO3s?t=547))
- **Setup**
  - [E] 5-minute direction: a strong support touched several times (four touches in the example) with a push up means buys; a resistance rejected with big wicks means sells. ([00:43](https://youtu.be/h-Z7CEqBO3s?t=43), [05:33](https://youtu.be/h-Z7CEqBO3s?t=333))
  - [E] 1-minute structure must agree: higher high, higher low, then a new higher high (mirror for sells). ([01:23](https://youtu.be/h-Z7CEqBO3s?t=83), [02:05](https://youtu.be/h-Z7CEqBO3s?t=125))
- **Entry and confirmation**
  - [E] Enter on a breakout on 1 minute: a resistance break for buys, a support or trend-line break for sells; more confirmations (level + trend line + 5-minute) are better. ([01:23](https://youtu.be/h-Z7CEqBO3s?t=83), [02:45](https://youtu.be/h-Z7CEqBO3s?t=165), [06:16](https://youtu.be/h-Z7CEqBO3s?t=376))
- **Stop-loss**
  - [E] A nice tight stop (place not given). ([02:45](https://youtu.be/h-Z7CEqBO3s?t=165), [06:59](https://youtu.be/h-Z7CEqBO3s?t=419))
- **Target**
  - [E] 1:3 to 1:5, managed at the next support/resistance zones; move to breakeven at the first zone. ([03:30](https://youtu.be/h-Z7CEqBO3s?t=210), [06:59](https://youtu.be/h-Z7CEqBO3s?t=419))
- **Trade management**
  - [E] A second position may be added on the next break after a retest. ([08:23](https://youtu.be/h-Z7CEqBO3s?t=503))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] 5-minute level: a 2-bar fractal low (high) touched again within 0.05% at least twice more in the last 6 hours, with the last 5-minute close above (below) it; the 1-minute break is a close above the latest 2-bar fractal high (below the low) after a higher low (lower high).
- [A] The break must happen within 0.5% of the 5-minute level; stop 0.02% beyond the 1-minute higher low (lower high) that preceded the break; target 3R; at most 3 trades a day; exit at 23:55 UTC.

Why the status: Levels and structure are read by eye; stop place not given (A)

### BI-09 SMA 100 side + higher-timeframe Heikin Ashi trend + MACD cross, 2R (5-minute bitcoin)

Video: "BEST 5 Minute Crypto Scalping Strategy (Simple)" - MoneyZG, uploaded 2023-10-19, 19 min - https://youtu.be/zpFQmtNd1pI (transcript: YouTube auto-captions (en-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Bitcoin futures (also ether); 5-minute chart (1 or 15 minutes possible). ([00:01](https://youtu.be/zpFQmtNd1pI?t=1), [02:51](https://youtu.be/zpFQmtNd1pI?t=171))
- **Indicators and settings**
  - [E] Simple moving average of 100 periods: no longs below it. ([02:51](https://youtu.be/zpFQmtNd1pI?t=171), [03:34](https://youtu.be/zpFQmtNd1pI?t=214))
  - [E] Candle Plot MTF indicator set to Heikin Ashi, showing the higher-timeframe trend; purple (down) candles mean no longs. ([03:34](https://youtu.be/zpFQmtNd1pI?t=214), [04:21](https://youtu.be/zpFQmtNd1pI?t=261))
  - [E] MACD (custom multi-timeframe MACD): the signal is a bullish crossover (momentum turning green). ([05:05](https://youtu.be/zpFQmtNd1pI?t=305), [05:45](https://youtu.be/zpFQmtNd1pI?t=345))
- **Entry and confirmation**
  - [E] Long when price is above the SMA 100, the higher-timeframe candles point up and the MACD crosses bullish; enter on the next candle. ([07:06](https://youtu.be/zpFQmtNd1pI?t=426), [07:48](https://youtu.be/zpFQmtNd1pI?t=468))
- **Stop-loss**
  - [E] Stop at the previous candle's low or a nearby support (9-18 basis points in the example; 15-20 bp gives room). ([07:48](https://youtu.be/zpFQmtNd1pI?t=468), [08:31](https://youtu.be/zpFQmtNd1pI?t=511), [15:40](https://youtu.be/zpFQmtNd1pI?t=940))
- **Target**
  - [E] Take profit at least 2:1 (2-2.5:1). ([09:12](https://youtu.be/zpFQmtNd1pI?t=552), [16:22](https://youtu.be/zpFQmtNd1pI?t=982))
- **Position sizing and risk**
  - [E] Risk 1-3% of the balance a trade (2% in the example), sized from the stop distance. ([10:40](https://youtu.be/zpFQmtNd1pI?t=640))
- **When not to trade**
  - [E] No trade against the filters, and avoid news spikes and very fast markets. ([05:45](https://youtu.be/zpFQmtNd1pI?t=345), [17:47](https://youtu.be/zpFQmtNd1pI?t=1067))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Higher-timeframe Heikin Ashi = Heikin Ashi built from 15-minute bars (the last completed one); up = HA close above HA open. MACD = (12, 26, 9) on 5-minute closes; cross = MACD line crossing its signal line.
- [A] Stop = the lower of the signal candle's low and the previous candle's low, at least 0.15% below entry; target 2R; shorts mirror the rules (the video shows longs); exit 23:55 UTC.

Why the status: The MTF candle timeframe and MACD settings are not stated (A); shorts not shown (A)

### BI-10 5 EMA untouched alert candle, next body crossing at least 30% (15-minute bitcoin)

Video: "Best Crypto Trading Strategy | 20-50$ Profit daily" - The Market Place, uploaded 2024-08-22, 13 min - https://youtu.be/PFnIohLAPOs (transcript: YouTube auto-captions (hi-orig))
Status: Duplicate of DR-03 - not added again. DR-03 (Devansh Rai) already trades the 5 EMA untouched candle on 15-minute bitcoin with a close beyond it and 1:2; YT-01 is the same alert candle on Indian indices; the 30%-of-body crossing is a small variation.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Bitcoin and ether on Delta Exchange. ([00:03](https://youtu.be/PFnIohLAPOs?t=3), [00:46](https://youtu.be/PFnIohLAPOs?t=46))
- **Timeframe**
  - [E] 15 minutes only (5 or 10 minutes gives big stop losses in crypto). ([00:46](https://youtu.be/PFnIohLAPOs?t=46), [01:27](https://youtu.be/PFnIohLAPOs?t=87))
- **Indicators and settings**
  - [E] EMA with length 5 (smoothing length left at 9). ([01:27](https://youtu.be/PFnIohLAPOs?t=87))
- **Setup**
  - [E] Alert candle: a candle that does not touch EMA 5 (below it: plan buys; above it: plan sells); the candle before it must not touch the EMA either. ([02:54](https://youtu.be/PFnIohLAPOs?t=174), [03:38](https://youtu.be/PFnIohLAPOs?t=218))
- **Entry and confirmation**
  - [E] The very next candle's body must cross the EMA by at least 30% of its body (50% or more is best); a wick touch is not enough. ([03:38](https://youtu.be/PFnIohLAPOs?t=218), [05:01](https://youtu.be/PFnIohLAPOs?t=301), [05:42](https://youtu.be/PFnIohLAPOs?t=342))
- **Stop-loss**
  - [E] Stop at the alert candle (the candle that did not touch the EMA). ([06:27](https://youtu.be/PFnIohLAPOs?t=387))
- **Target**
  - [E] 1:1 comes easily; take 1:2, up to 1:3-1:4. ([07:09](https://youtu.be/PFnIohLAPOs?t=429), [08:36](https://youtu.be/PFnIohLAPOs?t=516), [10:01](https://youtu.be/PFnIohLAPOs?t=601))

Why the status: Entry price within the crossing candle and target choice need numbers (A)

### BI-11 EMA 200 + RSI above 50 + bullish engulfing, long only, 1:2

Video: "Delta Exchange Best Strategy|| Delta Exchange india futures trading || @deltaexchange" - Delta Exchange, uploaded 2024-07-30, 9 min - https://youtu.be/0Qvy_S_giCI (transcript: YouTube auto-captions (hi-orig))
Status: Duplicate of TL-04 - not added again. TL-04 (TradingLab) already trades EMA 200 + RSI 50 + engulfing with a 2R target; this video is its long-only version with the stop at the engulfing low.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Ether and bitcoin (Indian markets and forex also possible). ([03:29](https://youtu.be/0Qvy_S_giCI?t=209))
- **Timeframe**
  - [E] Any timeframe; 5 minutes shown. ([01:26](https://youtu.be/0Qvy_S_giCI?t=86), [03:29](https://youtu.be/0Qvy_S_giCI?t=209))
- **Indicators and settings**
  - [E] EMA 200. ([00:45](https://youtu.be/0Qvy_S_giCI?t=45))
  - [E] RSI Divergence indicator (by Mohan): middle line 50; trade only when its RSI is above 50. ([01:26](https://youtu.be/0Qvy_S_giCI?t=86), [02:08](https://youtu.be/0Qvy_S_giCI?t=128))
  - [E] Engulfing-candle indicator: a candle whose body fully covers the previous candle's body. ([02:08](https://youtu.be/0Qvy_S_giCI?t=128), [02:49](https://youtu.be/0Qvy_S_giCI?t=169))
- **Entry and confirmation**
  - [E] Long only: price above EMA 200, RSI above 50 and a bullish engulfing candle; enter long. ([01:26](https://youtu.be/0Qvy_S_giCI?t=86), [04:11](https://youtu.be/0Qvy_S_giCI?t=251))
- **Stop-loss**
  - [E] Stop at the engulfing candle's low; exit if price goes below EMA 200. ([04:53](https://youtu.be/0Qvy_S_giCI?t=293), [06:55](https://youtu.be/0Qvy_S_giCI?t=415))
- **Target**
  - [E] Target at least 1:2. ([03:29](https://youtu.be/0Qvy_S_giCI?t=209), [04:53](https://youtu.be/0Qvy_S_giCI?t=293))
- **Filters**
  - [E] The closer the entry is to EMA 200, the smaller the stop and the better the setup. ([03:29](https://youtu.be/0Qvy_S_giCI?t=209), [05:33](https://youtu.be/0Qvy_S_giCI?t=333))

Why the status: RSI length unstated (default 14 assumed); entry at the next open (A)

### BI-12 EMA 21 break and retest: opposite candle within three bars, enter on its high/low (15-minute bitcoin)

Video: "15 Minute Trading Strategy for Beginners 🔥 | Stocks , Bitcoin & Forex" - HOLD with Priyank Live, uploaded 2026-05-17, 42 min - https://youtu.be/RW-bR1YKrNk (transcript: YouTube auto-captions (hi-orig))
Status: Duplicate of PV-02 - not added again. PV-02 (HOLD with Priyank, 20-channel study) already trades this exact rule set (EMA 21 close-through, opposite candle within 2-3 bars, break of its high, 1.5R) on Nifty and NSE stocks; this video adds bitcoin 15-minute and a 3R second target.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Crypto futures, options or spot; bitcoin chart. ([00:01](https://youtu.be/RW-bR1YKrNk?t=1))
- **Timeframe**
  - [E] 15 minutes for beginners (5 minutes for experienced traders, 1h/4h for swings); a single-timeframe strategy. ([00:42](https://youtu.be/RW-bR1YKrNk?t=42), [16:32](https://youtu.be/RW-bR1YKrNk?t=992))
- **Indicators and settings**
  - [E] EMA 21 (the average count of trading days in a month); 20 or 22 also fine. ([06:26](https://youtu.be/RW-bR1YKrNk?t=386), [07:06](https://youtu.be/RW-bR1YKrNk?t=426))
- **Setup**
  - [E] A candle closes across EMA 21 (up = long side, down = short side). ([13:45](https://youtu.be/RW-bR1YKrNk?t=825), [14:26](https://youtu.be/RW-bR1YKrNk?t=866))
  - [E] Within the next three candles an opposite-colour candle must form (a bearish candle after an upside break); if all three are the breakout colour, there is no setup. ([14:26](https://youtu.be/RW-bR1YKrNk?t=866), [15:10](https://youtu.be/RW-bR1YKrNk?t=910))
- **Entry and confirmation**
  - [E] Entry: a buy-stop at the opposite candle's high (sell-stop at its low); it triggers intrabar, no close needed. ([15:50](https://youtu.be/RW-bR1YKrNk?t=950), [17:14](https://youtu.be/RW-bR1YKrNk?t=1034))
- **Stop-loss**
  - [E] Stop just below the lowest low formed before the trigger (a point or two below for spread). ([15:50](https://youtu.be/RW-bR1YKrNk?t=950), [20:46](https://youtu.be/RW-bR1YKrNk?t=1246))
- **Target**
  - [E] First target 1.5R: book 40-60% and move the stop to entry. ([16:32](https://youtu.be/RW-bR1YKrNk?t=992), [22:07](https://youtu.be/RW-bR1YKrNk?t=1327))
  - [E] Second target 3R (his choice; 4R or a previous high also fine), or trail: hold until a candle closes back across EMA 21. ([21:26](https://youtu.be/RW-bR1YKrNk?t=1286), [27:05](https://youtu.be/RW-bR1YKrNk?t=1625))
- **Trade management**
  - [E] In a choppy market book the whole (or 80%) position at 1.5R. ([30:33](https://youtu.be/RW-bR1YKrNk?t=1833))
- **When not to trade**
  - [E] Before entry no candle may close back across EMA 21 (wicks are fine); a close back cancels the setup. ([17:57](https://youtu.be/RW-bR1YKrNk?t=1077), [18:37](https://youtu.be/RW-bR1YKrNk?t=1117))

Why the status: Order life after the third candle and the split need numbers (A)

## MCX commodity intraday

### CI-01 Crude oil 1-hour MACD side, fresh 15-minute MACD crossovers, exit on the opposite cross

Video: "Crude Oil Intraday Trading Strategy | High-Probability Setup" - Commodities by Dhan, uploaded 2026-03-20, 11 min - https://youtu.be/ZniDTRbVMsw (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] MCX crude oil futures (the near-month contract on Dhan charts). ([01:28](https://youtu.be/ZniDTRbVMsw?t=88))
- **Timeframe**
  - [E] Parent timeframe 1 hour; child timeframe one third or one quarter of it: 15 minutes (20 minutes possible). ([01:28](https://youtu.be/ZniDTRbVMsw?t=88), [04:12](https://youtu.be/ZniDTRbVMsw?t=252))
- **Indicators and settings**
  - [E] MACD with default settings (12, 26, 9) on both timeframes. ([01:28](https://youtu.be/ZniDTRbVMsw?t=88), [02:50](https://youtu.be/ZniDTRbVMsw?t=170))
- **Setup**
  - [E] Side: the 1-hour MACD buy signal (MACD line above the signal line) allows only buys; a 1-hour sell signal allows only sells. ([03:30](https://youtu.be/ZniDTRbVMsw?t=210))
- **Entry and confirmation**
  - [E] Inside the 1-hour phase, enter on each fresh 15-minute MACD crossover in the same direction, at that 15-minute candle's close; never join an old 15-minute signal. ([04:12](https://youtu.be/ZniDTRbVMsw?t=252), [06:23](https://youtu.be/ZniDTRbVMsw?t=383), [07:50](https://youtu.be/ZniDTRbVMsw?t=470))
- **Target**
  - [E] Book part from about 30 points (every 15-20 points with mini lots) and the rest by about 50 points. ([07:50](https://youtu.be/ZniDTRbVMsw?t=470), [08:31](https://youtu.be/ZniDTRbVMsw?t=511), [09:12](https://youtu.be/ZniDTRbVMsw?t=552))
- **Exit**
  - [E] Exit on the opposite 15-minute MACD crossover. ([04:57](https://youtu.be/ZniDTRbVMsw?t=297), [07:04](https://youtu.be/ZniDTRbVMsw?t=424))
- **Trade management**
  - [E] Trades may be carried overnight (bought 23:30, result by 12:30 next day). ([04:57](https://youtu.be/ZniDTRbVMsw?t=297))
- **Position sizing and risk**
  - [E] Start with the mini contract; quantity in lots. ([08:31](https://youtu.be/ZniDTRbVMsw?t=511), [09:55](https://youtu.be/ZniDTRbVMsw?t=595))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Coded: target 0.9% of price (50 points at about Rs 5,500 a barrel) or the opposite 15-minute cross, whichever comes first; a protective stop at the 15-minute swing low (high) of the last 6 bars minus 0.1%; positions held across sessions until an exit.
- [A] Coded on MCX hours 09:00-23:30 IST; no new entry after 23:00.

Why the status: No stop is stated (A: swing stop); targets given as a range of points (A: 0.9%)

### CI-02 Crude oil 66 moving-average slope + Stochastic 75/35 re-cross, 1:2

Video: "Crude Oil Intraday Strategy | By Siddharth Bhanushali" - SIDDHARTH BHANUSHALI , uploaded 2022-08-12, 34 min - https://youtu.be/5MehM14d0vQ (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] MCX crude oil (trades 09:00 to 23:00-23:30, so more intraday time). ([00:05](https://youtu.be/5MehM14d0vQ?t=5), [00:50](https://youtu.be/5MehM14d0vQ?t=50))
- **Timeframe**
  - [E] 15 minutes shown; any timeframe from 1 minute to daily works (5 minutes, 75 minutes, 5 hours shown). ([07:15](https://youtu.be/5MehM14d0vQ?t=435), [24:28](https://youtu.be/5MehM14d0vQ?t=1468))
- **Indicators and settings**
  - [E] Moving average 66 (simple). ([02:59](https://youtu.be/5MehM14d0vQ?t=179))
  - [E] Stochastic: length 14, %K smoothing 2, %D hidden; levels 75 (upper) and 35 (lower). ([08:36](https://youtu.be/5MehM14d0vQ?t=516), [09:17](https://youtu.be/5MehM14d0vQ?t=557), [10:38](https://youtu.be/5MehM14d0vQ?t=638))
- **Setup**
  - [E] A falling 66 average allows only shorts; a rising one only buys; where price sits versus the average does not matter. ([05:05](https://youtu.be/5MehM14d0vQ?t=305), [07:15](https://youtu.be/5MehM14d0vQ?t=435), [07:56](https://youtu.be/5MehM14d0vQ?t=476))
- **Entry and confirmation**
  - [E] Short: the Stochastic goes above 75, then the candle that brings it back below 75 is the trigger; sell below that candle's low. ([11:19](https://youtu.be/5MehM14d0vQ?t=679), [22:24](https://youtu.be/5MehM14d0vQ?t=1344), [22:24](https://youtu.be/5MehM14d0vQ?t=1344))
  - [E] Buy: with a rising average the Stochastic drops below 35; the candle that takes it back above 35 is the trigger; buy above its high. ([23:46](https://youtu.be/5MehM14d0vQ?t=1426))
- **Stop-loss**
  - [E] Stop above the higher high of the trigger candle and the candle before it (below the lower low for buys). ([14:04](https://youtu.be/5MehM14d0vQ?t=844), [22:24](https://youtu.be/5MehM14d0vQ?t=1344), [23:46](https://youtu.be/5MehM14d0vQ?t=1426))
- **Target**
  - [E] Target 1:2. ([12:41](https://youtu.be/5MehM14d0vQ?t=761), [14:44](https://youtu.be/5MehM14d0vQ?t=884))
- **Trade management**
  - [E] After a stop, keep taking new triggers while the average still slopes the same way. ([17:28](https://youtu.be/5MehM14d0vQ?t=1048), [18:54](https://youtu.be/5MehM14d0vQ?t=1134))
- **Filters**
  - [E] Choose the timeframe that shows a clear trend (daily, 5 hours, 75 minutes, 15, 5 minutes) - timeframe switching. ([28:39](https://youtu.be/5MehM14d0vQ?t=1719), [31:36](https://youtu.be/5MehM14d0vQ?t=1896))
- **When not to trade**
  - [E] Skip sideways phases (flat average, choppy price) and setups where the Stochastic jumps from below 35 to about 70 in one big candle. ([19:38](https://youtu.be/5MehM14d0vQ?t=1178), [27:12](https://youtu.be/5MehM14d0vQ?t=1632), [27:55](https://youtu.be/5MehM14d0vQ?t=1675))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Coded on 15 minutes: the average falls when SMA66 now is below SMA66 five bars ago by more than 0.05% of price (rises when above by more); otherwise flat (no trade).
- [A] The stop-entry order is valid for the 3 bars after the trigger; MCX hours 09:00-23:30 IST, no entry after 23:00, exit at 23:25.

Why the status: Slope and sideways need numbers (A); timeframe switching is discretionary (coded on 15 minutes)

### CI-03 Crude oil 17:30-18:00 IST 30-minute candle: 50% side and break after 18:00 on 3 minutes, 1:2

Video: "Crude Oil Trading Strategy | 5:30 Formula & MCX Research Analysis" - Trade With Dr Devendra, uploaded 2023-08-19, 18 min - https://youtu.be/Y8NILq4BITA (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] MCX crude oil futures (or its options via the same levels). ([02:44](https://youtu.be/Y8NILq4BITA?t=164), [03:25](https://youtu.be/Y8NILq4BITA?t=205))
- **Timeframe**
  - [E] Execute on a 3-minute chart (1 or 5 minutes also fine). ([09:51](https://youtu.be/Y8NILq4BITA?t=591))
- **Session**
  - [E] Evening only: wait for the 17:30-18:00 IST 30-minute candle; trade after 18:00 (crude often reverses or breaks out around 18:00 when inventories come). ([05:38](https://youtu.be/Y8NILq4BITA?t=338), [07:38](https://youtu.be/Y8NILq4BITA?t=458))
- **Indicators and settings**
  - [E] 20-period moving average; holding above it means positive sentiment. ([10:37](https://youtu.be/Y8NILq4BITA?t=637))
- **Setup**
  - [E] On the 30-minute chart mark that candle's high, low and its 50% level. ([07:38](https://youtu.be/Y8NILq4BITA?t=458), [09:05](https://youtu.be/Y8NILq4BITA?t=545))
  - [E] Its colour sets the interest: green = upside, red = downside. ([08:23](https://youtu.be/Y8NILq4BITA?t=503))
- **Entry and confirmation**
  - [E] After 18:00: when a candle breaks the candle's low (short) or a positive bar closes above (long) on the right side of the 50% level, enter. ([10:37](https://youtu.be/Y8NILq4BITA?t=637), [13:22](https://youtu.be/Y8NILq4BITA?t=802), [14:04](https://youtu.be/Y8NILq4BITA?t=844))
- **Stop-loss**
  - [E] Stop at the previous candle (12-15 points in the examples). ([10:37](https://youtu.be/Y8NILq4BITA?t=637), [14:04](https://youtu.be/Y8NILq4BITA?t=844))
- **Target**
  - [E] Target at least 1:2 (1:3 and 1:4 reached in the examples). ([11:22](https://youtu.be/Y8NILq4BITA?t=682), [14:04](https://youtu.be/Y8NILq4BITA?t=844))
- **Trade management**
  - [E] After a stop, the move the other way is the momentum trade: take it with the new risk and at least 1:2. ([11:22](https://youtu.be/Y8NILq4BITA?t=682), [12:02](https://youtu.be/Y8NILq4BITA?t=722))
- **Filters**
  - [E] Price trading above the 50% level is positive (no shorts once it crosses above after 18:00); below it is negative. ([09:05](https://youtu.be/Y8NILq4BITA?t=545), [12:02](https://youtu.be/Y8NILq4BITA?t=722))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Coded: long when a 3-minute candle closes above the 30-minute candle's high with the close above its 50% level and above SMA 20; short mirror below its low; entry at the next open; colour is not used as a filter (his own examples trade both sides).
- [A] Stop beyond the previous 3-minute candle's extreme; target 2R; at most 2 trades a day; entries 18:00-23:00 IST, exit 23:25 IST.

Why the status: 'Break' and the colour preference need rules (A)

### CI-04 Crude oil Donchian-200 extreme on 20 minutes, 5-minute EMA 9 reversal, 40 points then trail

Video: "Crude Oil After 3:30 PM: Intraday Pullback Trading Strategy" - Commodities by Dhan, uploaded 2026-01-13, 11 min - https://youtu.be/7kHXWtf8GVk (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] MCX crude oil and crude oil mini (10 barrels; about Rs 15,000 margin). ([02:58](https://youtu.be/7kHXWtf8GVk?t=178), [03:38](https://youtu.be/7kHXWtf8GVk?t=218))
- **Timeframe**
  - [E] Extremes on the 20-minute chart (intraday or BTST); 1-3 hours for longer holds. ([03:38](https://youtu.be/7kHXWtf8GVk?t=218), [04:19](https://youtu.be/7kHXWtf8GVk?t=259))
  - [E] Execute on the 5-minute chart with moving averages only. ([05:43](https://youtu.be/7kHXWtf8GVk?t=343), [06:24](https://youtu.be/7kHXWtf8GVk?t=384))
- **Indicators and settings**
  - [E] Donchian channel: length 200, offset 3, middle line hidden. ([05:01](https://youtu.be/7kHXWtf8GVk?t=301))
- **Setup**
  - [E] Crude, gold, silver, copper and USDINR are range ('trading') products: catch reversals and book small profits; never try to ride a big trend. ([01:28](https://youtu.be/7kHXWtf8GVk?t=88), [02:13](https://youtu.be/7kHXWtf8GVk?t=133))
  - [E] Mark the area where 20-minute candles form outside the channel (beyond the upper or lower band - a touch is not enough); a reversal is expected from there. ([05:01](https://youtu.be/7kHXWtf8GVk?t=301), [05:43](https://youtu.be/7kHXWtf8GVk?t=343))
- **Entry and confirmation**
  - [E] Short after an upper extreme when EMA 9 is below EMA 30 and below the slow average (heard as '300'); long mirror after a lower extreme. ([06:24](https://youtu.be/7kHXWtf8GVk?t=384))
- **Target**
  - [E] Book the first profit at 40 points without fail and trail the rest (intraday aim 60-70 points). ([07:51](https://youtu.be/7kHXWtf8GVk?t=471), [08:34](https://youtu.be/7kHXWtf8GVk?t=514))
- **Exit**
  - [E] Exit the short when EMA 9 goes back above EMA 100 (mirror for longs); positions may be carried to the next day. ([06:24](https://youtu.be/7kHXWtf8GVk?t=384), [07:08](https://youtu.be/7kHXWtf8GVk?t=428))
- **Trade management**
  - [E] About 2-3 trades a day on this timeframe; one usually pays, the others lose a little or scratch. ([09:14](https://youtu.be/7kHXWtf8GVk?t=554), [10:01](https://youtu.be/7kHXWtf8GVk?t=601))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Slow average read as EMA 100 (the exit uses 100; '300' is taken as a caption error); an extreme counts for 6 hours after a 20-minute close beyond the band.
- [A] Coded: half at 0.7% of price (40 points at about Rs 5,500), the rest exits on EMA 9 crossing EMA 100; protective stop at the 5-minute swing extreme of the last 12 bars plus 0.1%; MCX hours, exit 23:25 IST.

Why the status: The slow average length is ambiguous ('300' vs 100); no stop is stated (A)

### CI-05 Crude oil 15-minute two-candle rejection after 12:00 IST (sweep of the prior candle, break of the signal candle)

Video: "Crude Oil Intraday Strategy 15 Min Chart पर Daily Setup | 100+ Time Tested Trading Strategy" - Candle Pe Command , uploaded 2026-03-06, 13 min - https://youtu.be/2ZTBqEduoe0 (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] MCX crude oil (March future shown); backtested only on crude, other scripts untested. ([02:15](https://youtu.be/2ZTBqEduoe0?t=135), [03:38](https://youtu.be/2ZTBqEduoe0?t=218))
- **Timeframe**
  - [E] 15-minute chart. ([02:15](https://youtu.be/2ZTBqEduoe0?t=135), [05:45](https://youtu.be/2ZTBqEduoe0?t=345))
- **Session**
  - [E] Skip the first 13 fifteen-minute candles: trade only after 12:00 IST; earlier signals trap you. ([05:03](https://youtu.be/2ZTBqEduoe0?t=303), [05:45](https://youtu.be/2ZTBqEduoe0?t=345))
- **Setup**
  - [E] Sell setup: after a rise, a green candle, then a red candle whose high takes out the green candle's high and which closes red (rejection). ([05:45](https://youtu.be/2ZTBqEduoe0?t=345), [06:26](https://youtu.be/2ZTBqEduoe0?t=386))
  - [E] Buy setup: after a fall, a red candle, then a green candle that first breaks the red candle's low and closes green. ([07:50](https://youtu.be/2ZTBqEduoe0?t=470), [09:59](https://youtu.be/2ZTBqEduoe0?t=599))
- **Entry and confirmation**
  - [E] Sell when the red candle's low breaks. ([06:26](https://youtu.be/2ZTBqEduoe0?t=386))
  - [E] Buy when the green candle's high breaks; stop at its low. ([08:32](https://youtu.be/2ZTBqEduoe0?t=512), [09:59](https://youtu.be/2ZTBqEduoe0?t=599))
- **Stop-loss**
  - [E] Stop 2 points above the red candle's high. ([06:26](https://youtu.be/2ZTBqEduoe0?t=386))
- **Target**
  - [E] Exit at 1.5 times the risk, or a standard 50 points (moves of 100-230 points happen). ([07:07](https://youtu.be/2ZTBqEduoe0?t=427), [08:32](https://youtu.be/2ZTBqEduoe0?t=512))
- **Trade management**
  - [E] One or two signals a day; filters to remove fake signals exist but are not given. ([00:47](https://youtu.be/2ZTBqEduoe0?t=47), [11:22](https://youtu.be/2ZTBqEduoe0?t=682))
- **Position sizing and risk**
  - [E] Mega lot Rs 100 a point (about Rs 28,000 margin), mini lot Rs 10 a point (about Rs 21,000). ([03:38](https://youtu.be/2ZTBqEduoe0?t=218), [04:18](https://youtu.be/2ZTBqEduoe0?t=258))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] 'After a rise' coded as: the green candle's high is the highest high of the last 8 candles (the red candle's low the lowest of 8 for buys).
- [A] The stop-entry is valid for the 3 bars after the signal candle; stop 0.04% (2 points) beyond its extreme; target 1.5R; at most 2 trades a day; entries 12:00-23:00 IST, exit 23:25.

Why the status: 'After a rise' and the order life need numbers (A); the extra filters are not given

### CI-06 Crude oil RSI 60/40 cross on the SMA 89 side, 15 minutes, 18:00-22:00 IST, 1:2

Video: "Best Commodity Trading Strategy | Best MCX Strategy | Chart Commando" - Chart Commando, uploaded 2024-01-09, 21 min - https://youtu.be/AlMUdyYku8k (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Analyse on the US Oil (WTI) chart, which is continuous; place the trade in MCX crude futures. ([01:25](https://youtu.be/AlMUdyYku8k?t=85), [02:06](https://youtu.be/AlMUdyYku8k?t=126), [10:28](https://youtu.be/AlMUdyYku8k?t=628))
- **Timeframe**
  - [E] 15-minute chart. ([18:52](https://youtu.be/AlMUdyYku8k?t=1132))
- **Session**
  - [E] Trade between 18:00 and 22:00 IST (most setups come then); no entries after that (market to 23:55). ([18:52](https://youtu.be/AlMUdyYku8k?t=1132))
- **Indicators and settings**
  - [E] Simple moving average 89 (not exponential). ([04:50](https://youtu.be/AlMUdyYku8k?t=290), [05:31](https://youtu.be/AlMUdyYku8k?t=331))
  - [E] RSI (from the RSI Divergence indicator) with the levels moved from 70/30 to 60/40. ([06:56](https://youtu.be/AlMUdyYku8k?t=416))
- **Setup**
  - [E] Long trigger candle: the candle on which RSI crosses above 60 while price is above SMA 89. ([06:56](https://youtu.be/AlMUdyYku8k?t=416), [07:38](https://youtu.be/AlMUdyYku8k?t=458))
  - [E] Short trigger: the candle on which RSI crosses below 40 while price is below SMA 89; sell below its low; a retest gives another entry. ([13:57](https://youtu.be/AlMUdyYku8k?t=837), [14:40](https://youtu.be/AlMUdyYku8k?t=880))
- **Entry and confirmation**
  - [E] Buy above the trigger candle's high (a follow-up candle breaking it); if price pulls back toward SMA 89, trail the buy order down to the newer candles' highs and enter when one breaks. ([07:38](https://youtu.be/AlMUdyYku8k?t=458), [08:18](https://youtu.be/AlMUdyYku8k?t=498), [09:44](https://youtu.be/AlMUdyYku8k?t=584))
- **Stop-loss**
  - [E] Stop at the trigger candle's low (for shorts its high or the swing high). ([10:28](https://youtu.be/AlMUdyYku8k?t=628), [13:57](https://youtu.be/AlMUdyYku8k?t=837))
- **Target**
  - [E] Target 1:2 minimum; take 50% there and trail the rest along SMA 89, or book all at 1:2 while learning. ([10:28](https://youtu.be/AlMUdyYku8k?t=628), [11:11](https://youtu.be/AlMUdyYku8k?t=671), [13:15](https://youtu.be/AlMUdyYku8k?t=795))
- **Position sizing and risk**
  - [E] Futures only for this strategy. ([19:33](https://youtu.be/AlMUdyYku8k?t=1173))
- **When not to trade**
  - [E] Be very careful on Wednesdays (high volatility). ([19:33](https://youtu.be/AlMUdyYku8k?t=1173))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Coded on one crude series (no separate WTI analysis chart): the buy-stop starts at the trigger high and is lowered to each later candle's high while price stays above SMA 89 and RSI above 50, for up to 8 bars; fill when a candle trades through it.
- [A] Stop 0.02% beyond the trigger candle's extreme; target 2R; one position at a time; no entries on Wednesdays; entries 18:00-22:00 IST, exit 23:25.

Why the status: How long to keep trailing the entry order is not stated (A); WTI-for-analysis is folded into one series (A)

### CI-07 Natural gas MFI(140) 40/60 zone + Supertrend side + EMA 9/26 cross (1 hour)

Video: "🔥 Advanced Natural Gas Trading Strategy | Natural Gas Trading | Dhan" - Dhan ⚡, uploaded 2025-10-23, 9 min - https://youtu.be/wx-DyDEz2Xg (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] MCX natural gas or natural gas mini (Rs 1,250 vs Rs 250 per rupee; mini needs about Rs 10,000). ([02:14](https://youtu.be/wx-DyDEz2Xg?t=134))
- **Timeframe**
  - [E] 1-hour chart; often runs a few days (swing), sometimes done the same day. ([02:56](https://youtu.be/wx-DyDEz2Xg?t=176))
- **Indicators and settings**
  - [E] Money Flow Index with length 140 (not the default); horizontal lines at 40 and 60. ([03:37](https://youtu.be/wx-DyDEz2Xg?t=217))
  - [E] Supertrend and an EMA 9 / EMA 26 crossover as the two confirmations. ([04:21](https://youtu.be/wx-DyDEz2Xg?t=261), [05:04](https://youtu.be/wx-DyDEz2Xg?t=304))
- **Entry and confirmation**
  - [E] Buy near MFI 40 when price goes above Supertrend and EMA 9 crosses above EMA 26 together. ([04:21](https://youtu.be/wx-DyDEz2Xg?t=261), [05:04](https://youtu.be/wx-DyDEz2Xg?t=304))
  - [E] Sell near MFI 60 (overbought) when price falls below Supertrend and the EMAs cross bearish. ([06:28](https://youtu.be/wx-DyDEz2Xg?t=388))
- **Target**
  - [E] Exit at 0.6-0.8% intraday; if carried to the next day take about 1-1.25%. ([05:44](https://youtu.be/wx-DyDEz2Xg?t=344))
- **Exit**
  - [E] Trailing stop: exit when price closes below Supertrend or the EMAs cross the other way. ([05:44](https://youtu.be/wx-DyDEz2Xg?t=344))
- **Filters**
  - [E] The Thursday EIA inventory data (20:00, 21:00 in winter) sets the next week's trend; MFI often stretches after it and reversals follow within a day. ([00:47](https://youtu.be/wx-DyDEz2Xg?t=47), [07:09](https://youtu.be/wx-DyDEz2Xg?t=429))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Supertrend (10, 3) (settings not given); 'near 40' = MFI(140) at or below 42 at some point in the last 10 hourly bars (at or above 58 for sells).
- [A] Coded: target 0.8% from entry; exit on the trailing condition otherwise; protective stop at the Supertrend line at entry; one position at a time; MCX hours, positions may be held across sessions up to 3 days.

Why the status: Supertrend settings and 'near 40/60' need numbers (A)

### CI-08 Crude oil 7% stretch from the 200 average + slow Stochastic RSI turn (15 minutes)

Video: "15-Minute Crude Oil Trading Strategy | Catch Explosive Moves After Pullbacks" - Commodities by Dhan, uploaded 2026-08-18, 14 min - https://youtu.be/fcU8iz__qfE (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] MCX crude oil (gold and silver need other thresholds). ([02:10](https://youtu.be/fcU8iz__qfE?t=130))
- **Timeframe**
  - [E] 15-minute chart. ([02:10](https://youtu.be/fcU8iz__qfE?t=130))
- **Indicators and settings**
  - [E] Distance from Moving Average: 200-period average, shown as a percentage difference. ([06:23](https://youtu.be/fcU8iz__qfE?t=383), [07:07](https://youtu.be/fcU8iz__qfE?t=427))
  - [E] Stochastic RSI with ten times the usual parameters: 140, 140, 30, 30. ([09:14](https://youtu.be/fcU8iz__qfE?t=554))
- **Setup**
  - [E] A stretch is about 7% (5-9%) above or below the 200 average; lines at +7% and -7%. ([07:47](https://youtu.be/fcU8iz__qfE?t=467), [08:31](https://youtu.be/fcU8iz__qfE?t=511))
- **Entry and confirmation**
  - [E] Sell when stretched above +7% and the Stochastic RSI gives a sell signal; buy when stretched below -7% and it gives a buy signal. ([09:14](https://youtu.be/fcU8iz__qfE?t=554), [10:39](https://youtu.be/fcU8iz__qfE?t=639))
- **Stop-loss**
  - [E] Stop: exit when EMA 5 crosses below EMA 15 (above for shorts); re-enter if it crosses back. ([11:21](https://youtu.be/fcU8iz__qfE?t=681))
- **Target**
  - [E] On 15 minutes aim for Rs 50-100 a barrel (a monetary target), or hold until the opposite Stochastic RSI signal. ([09:55](https://youtu.be/fcU8iz__qfE?t=595), [11:21](https://youtu.be/fcU8iz__qfE?t=681), [12:02](https://youtu.be/fcU8iz__qfE?t=722))
- **Position sizing and risk**
  - [E] Trade 10 small lots instead of one big lot to book partial profits. ([12:02](https://youtu.be/fcU8iz__qfE?t=722))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Coded: a K line crossing below (above) the D line of Stochastic RSI (RSI 140, stochastic 140, smoothing 30/30), while the distance is beyond 6.5% or was within the last 20 bars; entry at the next open.
- [A] Target 1.5% of price (about 80 points), else exit on the EMA 5/15 cross against the trade or the opposite Stochastic RSI cross; a 2% safety stop from the fill (the video names no price stop); one position at a time; MCX hours; held across sessions.

Why the status: The stretch threshold is given as a range (A: 6.5%); signal definition of Stochastic RSI not spelled out (A)

### CI-09 Crude oil 17:45 IST 15-minute candle: three lines (high, low, 50%), 5-minute close beyond

Video: "5-45 KA FORMULA | COMMODITY TRADING SETUP | CRUDE OIL TRADING #commoditytrading" - Trade with Sanchit, uploaded 2023-09-08, 21 min - https://youtu.be/K_qNy37g1eA (transcript: YouTube auto-captions (hi-orig))
Status: Duplicate of CI-03 - not added again. Same evening inventory-candle method as CI-03 (Dr Devendra's 17:30 30-minute candle with its 50% level, break on 3 minutes): here the 17:45 15-minute candle and 5-minute closes; recorded as a second source of CI-03.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] MCX crude oil (also natural gas, silver, gold). ([02:04](https://youtu.be/K_qNy37g1eA?t=124), [04:05](https://youtu.be/K_qNy37g1eA?t=245))
- **Session**
  - [E] Evening only: the inventory data around 17:30 gives a one-sided move; trade after 17:45, two trades a day. ([01:22](https://youtu.be/K_qNy37g1eA?t=82), [04:45](https://youtu.be/K_qNy37g1eA?t=285), [13:55](https://youtu.be/K_qNy37g1eA?t=835))
- **Setup**
  - [E] On 15 minutes take the 17:45 candle and mark its 50% level, its high and its low: three lines. ([05:27](https://youtu.be/K_qNy37g1eA?t=327), [06:10](https://youtu.be/K_qNy37g1eA?t=370), [06:51](https://youtu.be/K_qNy37g1eA?t=411))
- **Entry and confirmation**
  - [E] On 5 minutes (1 minute also fine), after 18:00, a candle closing beyond the upper line is a buy, beyond the lower line a sell; an early entry is possible beyond the 50% zone. ([07:31](https://youtu.be/K_qNy37g1eA?t=451), [08:54](https://youtu.be/K_qNy37g1eA?t=534))
- **Stop-loss**
  - [E] Stop at the low of the candle that closed beyond the line (high for sells). ([07:31](https://youtu.be/K_qNy37g1eA?t=451))
- **Target**
  - [E] Profit at least 1:3; 1:4 in the example; one stop and one 5x winner a day is the claim. ([04:45](https://youtu.be/K_qNy37g1eA?t=285), [09:39](https://youtu.be/K_qNy37g1eA?t=579), [11:07](https://youtu.be/K_qNy37g1eA?t=667))

Why the status: Stop side and target choice need numbers (A)

### CI-10 Silver Micro 18:30 IST 30-minute candle breakout with a 50-point buffer, stop and reverse, 1:2

Video: "30-Minute Silver Micro Trading Strategy After 6 PM | Simple Breakout Setup for Busy Traders" - Commodities by Dhan, uploaded 2026-10-10, 6 min - https://youtu.be/zsFn_iUtPQI (transcript: YouTube auto-captions (hi-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] MCX Silver Micro (Rs 1 per point, so 100 points against you costs Rs 100). ([00:49](https://youtu.be/zsFn_iUtPQI?t=49))
- **Timeframe**
  - [E] 30-minute chart, no indicators or trend lines. ([01:29](https://youtu.be/zsFn_iUtPQI?t=89))
- **Session**
  - [E] Mark the 18:30 IST candle at 19:00, when global markets move commodities most. ([01:29](https://youtu.be/zsFn_iUtPQI?t=89), [02:11](https://youtu.be/zsFn_iUtPQI?t=131))
- **Setup**
  - [E] Add a 50-point buffer: high + 50 and low - 50. ([02:11](https://youtu.be/zsFn_iUtPQI?t=131), [03:33](https://youtu.be/zsFn_iUtPQI?t=213))
- **Entry and confirmation**
  - [E] Buy when price breaks above high + 50; sell when it breaks below low - 50. ([02:11](https://youtu.be/zsFn_iUtPQI?t=131))
- **Stop-loss**
  - [E] Stop at the other side; when it is hit, exit and reverse with a double order. ([04:16](https://youtu.be/zsFn_iUtPQI?t=256))
- **Target**
  - [E] Target 1:2; trail after 1:1. ([02:11](https://youtu.be/zsFn_iUtPQI?t=131))
- **Exit**
  - [E] Close everything by 23:15 IST. ([02:11](https://youtu.be/zsFn_iUtPQI?t=131))
- **Position sizing and risk**
  - [E] Start with single micro lots (low capital); several lots possible. ([00:49](https://youtu.be/zsFn_iUtPQI?t=49))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Stop orders at high + 50 and low - 50 points (scaled to 0.04% of price for a continuous silver series), re-placed at every 5-minute close from 19:00 to 23:00 IST; the first fill opens the trade; stop at the opposite trigger; after a stop the other side's order can fill (at the next open if price is already through it); one long and one short at most a day; target 2R.

Why the status: Trailing after 1:1 is not described (A: fixed 2R); one reversal assumed (A)

### CI-11 Daily inside-candle (mother/baby) levels traded intraday (crude oil)

Video: "Best Crude Oil Intraday Trading strategy || Jackpot Crude Oil, Natural Gas Strategy" - MCX Winning Trade, uploaded 2022-03-27, 14 min - https://youtu.be/rA5N0eznRaI (transcript: YouTube auto-captions (hi-orig))
Status: Blocked (no paper account): the entry confirmation is not given and the auto-captions are too garbled to recover exact rules.

Creator's rules ([E] stated, [I] inferred from the examples):
- **Timeframe**
  - [E] Start on the daily timeframe. ([00:43](https://youtu.be/rA5N0eznRaI?t=43))
- **Setup**
  - [E] Find an inside-candle formation: the next candle's whole range (high to low) inside the previous 'mother' candle; mark the mother candle's high and low. ([01:31](https://youtu.be/rA5N0eznRaI?t=91), [02:27](https://youtu.be/rA5N0eznRaI?t=147), [04:34](https://youtu.be/rA5N0eznRaI?t=274))
- **Entry and confirmation**
  - [E] At a level wait for an entry confirmation (not described). ([08:44](https://youtu.be/rA5N0eznRaI?t=524))
- **Stop-loss**
  - [E] Stop beyond the level (as far as the captions show). ([10:46](https://youtu.be/rA5N0eznRaI?t=646))
- **Target**
  - [E] Targets toward the next level / resistance (moves of 125-500 points shown). ([09:24](https://youtu.be/rA5N0eznRaI?t=564), [10:46](https://youtu.be/rA5N0eznRaI?t=646))
- **Filters**
  - [E] Trade only near those levels; nothing in between. ([02:27](https://youtu.be/rA5N0eznRaI?t=147), [03:13](https://youtu.be/rA5N0eznRaI?t=193))

Why the status: The entry confirmation is not given and the auto-captions are too garbled to recover exact rules

### CI-12 Crude oil 'bald' green candle (no lower wick) after a red series, 15-minute scalp

Video: "30 Points Scalping method in Crude Oil (Commodity Trading Series)" - Pivot Call, uploaded 2024-08-09, 17 min - https://youtu.be/nvcYcx9ljzY (transcript: YouTube auto-captions (en-orig))
Status: Coded as v1 (codeable once the [A] rules below fill the gaps).

Creator's rules ([E] stated, [I] inferred from the examples):
- **Market and instruments**
  - [E] Crude oil (MCX; the chart shown is WTI crude). ([00:10](https://youtu.be/nvcYcx9ljzY?t=10))
- **Timeframe**
  - [E] 15-minute candles only (not 5 minutes). ([07:27](https://youtu.be/nvcYcx9ljzY?t=447), [10:15](https://youtu.be/nvcYcx9ljzY?t=615))
- **Setup**
  - [E] Entry candle: a green body with zero lower wick (an upper wick is fine); not too big or small, about 20-30 points of range. ([02:18](https://youtu.be/nvcYcx9ljzY?t=138), [03:02](https://youtu.be/nvcYcx9ljzY?t=182), [03:47](https://youtu.be/nvcYcx9ljzY?t=227))
  - [E] It must be the first such candle after a series of red candles (3 or more, no green just before) or a series of pin bars/dojis. ([04:29](https://youtu.be/nvcYcx9ljzY?t=269), [05:14](https://youtu.be/nvcYcx9ljzY?t=314), [05:58](https://youtu.be/nvcYcx9ljzY?t=358))
- **Entry and confirmation**
  - [E] Take the entry on that bald candle. ([05:58](https://youtu.be/nvcYcx9ljzY?t=358), [06:40](https://youtu.be/nvcYcx9ljzY?t=400))
- **Stop-loss**
  - [E] Stop below the bald green candle's low, with some room. ([07:27](https://youtu.be/nvcYcx9ljzY?t=447), [10:15](https://youtu.be/nvcYcx9ljzY?t=615))
- **Target**
  - [E] Scalp 20-30 points: profit on the next candle, or the third candle if momentum is strong. ([06:40](https://youtu.be/nvcYcx9ljzY?t=400))
- **Trade management**
  - [E] If price comes back to the bald candle's low and makes a bullish pin bar, add; stop below the pin bar. ([06:40](https://youtu.be/nvcYcx9ljzY?t=400), [07:27](https://youtu.be/nvcYcx9ljzY?t=447))
- **Filters**
  - [E] Overall trend must be a strong uptrend: the 20 MA sloping up and higher lows. ([01:37](https://youtu.be/nvcYcx9ljzY?t=97), [02:18](https://youtu.be/nvcYcx9ljzY?t=138))
  - [E] Higher probability near the 20 MA, 50 MA, CPR, the day's low or a swing low. ([01:37](https://youtu.be/nvcYcx9ljzY?t=97), [05:14](https://youtu.be/nvcYcx9ljzY?t=314))

Research assumptions used to code it ([A] - ours, not the creator's):
- [A] Coded long only (the video teaches the uptrend case): uptrend = SMA 20 now above SMA 20 four bars ago and the bar's low above the low of 8 bars ago; zero lower wick = open within 0.02% of the low; range 0.3%-0.55% of price (20-30 points at about Rs 5,500).
- [A] Entry at the next open; stop 0.1% below the bald low; target 0.45% (25 points) or exit at the close of the third bar after entry; the add-on is not coded; MCX hours, exit 23:25 IST.

Why the status: 'Strong uptrend' and the exit candle need numbers (A); shorts are not taught

