# NIFTY intraday option buying: 11 videos

Each strategy is written from the video's own words (timestamps link to the moment). The [A] lines are
ours: the creator did not say them. Duplicates of the library and blocked strategies are listed with the reason.

## OB-01 NIFTY 9:30 premium-180 breakout: ITM call or put that first breaks Rs 180, stop 20, target 40

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

Missing or ambiguous in the video:
- "sustaining above 180" ([05:10](https://youtu.be/uvut8SRcFGY?t=310)): 'Sustain' is not measured. Coded as: a stop order at the trigger (the first touch fills).
- Open question: Does 'sustains above 180' need a close, and over which candle?

Claims (quoted as said; not verified):
- 70-75% success month on month (a friend's results) [win_rate, monthly] ([00:49](https://youtu.be/uvut8SRcFGY?t=49))

Example trades shown:
- 2025-08-12 NIFTY 24500 CE / 24750 PE unclear: 9:26 strikes near 180 (175 and 166); entry 180, stop 160, target 220 -> unknown - live example ([14:58](https://youtu.be/uvut8SRcFGY?t=898))

Promotions: Telegram group for strike calls (14:14-14:58)

## OB-02 NIFTY 9:20 Rs 62.5 option, buy on a 50% premium rise, hold overnight (BTST), 50% stop, +75 target

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

Missing or ambiguous in the video:
- Open question: How are the 50% trigger and stop filled in a fast market (slippage beyond the 0.5% assumed)?

Claims (quoted as said; not verified):
- yearly returns 890%, 1800%, 200-600%, 400%, 800-900%, 1600% on Rs 3,000; 120% in 2026 so far [return_pct, 2019-2026] ([12:41](https://youtu.be/9IADhg-bMSg?t=761))
- Rs 3,94,000 total net profit; max drawdown Rs 72,000 [money, 2019-2026] ([16:52](https://youtu.be/9IADhg-bMSg?t=1012))
- hit ratio 46% [win_rate, 2019-2026] ([16:52](https://youtu.be/9IADhg-bMSg?t=1012))
- overnight +39,000 points vs intraday -19,000 points in NIFTY since 2016 [other, 2016-2026] ([03:36](https://youtu.be/9IADhg-bMSg?t=216))

## OB-03 Williams %R (280) overbought on 60, 20 and 5 minutes: ATM call on the fresh 5-minute signal, +10-12% premium

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

Missing or ambiguous in the video:
- "fresh" ([04:12](https://youtu.be/J63EL3Xb02g?t=252)): How far back the previous non-overbought reading must be. Coded as: the 5-minute %R crosses above -20 after being below -50 within the last 12 bars.
- Open question: Where is the stop loss?

Example trades shown:
- 2025-06-17 Bank Nifty 57400 CE long: 60m and 20m overbought, fresh 5m overbought; entry ATM call, stop -, target 10-12% -> target - 60 points in an hour, 150 in a day ([04:12](https://youtu.be/J63EL3Xb02g?t=252))
- 2025-06-23 Infosys 140 PE short: overbought put chart, oversold underlying; entry 140 PE, stop -, target 10-12% -> target - 15% in 1.5 hours ([08:28](https://youtu.be/J63EL3Xb02g?t=508))

Promotions: Dhan Options Trader web (OI, futures build-up, IV) (09:59-11:16)

## OB-04 NIFTY 14:55 five-minute candle breakout with a 5-point buffer, out at 15:15

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

Missing or ambiguous in the video:
- Open question: Does the entry order stay valid until 15:10?

Claims (quoted as said; not verified):
- 1% move in one candle on 29 May [other, 2025-05-29] ([12:43](https://youtu.be/Hn6N3JpOcuA?t=763))

Example trades shown:
- 2025-06-09 NIFTY short: 14:55 candle low broken next candle; entry below the low, stop candle high + 2, target 15:15 close -> target - profit ([02:50](https://youtu.be/Hn6N3JpOcuA?t=170))
- 2025-06-07 NIFTY short: low broken; entry below the low, stop candle high, target 15:15 close -> closed_early - small loss at 15:15 ([07:50](https://youtu.be/Hn6N3JpOcuA?t=470))
- date not shown NIFTY long: high broken by a wick, then reversal; entry above 23453, stop low, target 15:15 -> stop - trap day: buffer advice ([10:38](https://youtu.be/Hn6N3JpOcuA?t=638))

Promotions: Demat and CoinDCX referral links (00:06-00:46)

## OB-05 9:15 open-price cross after 30 seconds, ATM option, out by 9:30 (Rajesh Jain)

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

Missing or ambiguous in the video:
- Open question: What is the stop level?

Claims (quoted as said; not verified):
- Rs 2,000-8,000 a day by 9:30, every day [money, daily] ([02:54](https://youtu.be/Whb5Nr1iukY?t=174))

Example trades shown:
- date not shown Power India short: first loser, made a high then broke below the open 35435; entry ATM put, stop -, target 9:30 exit -> target - red all 15 minutes ([05:42](https://youtu.be/Whb5Nr1iukY?t=342))

## OB-06 ADX turning up + price breakout + big candle (15 minutes), ATM option, 20% premium stop

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

Missing or ambiguous in the video:
- "price breakout" ([07:19](https://youtu.be/Wu_uvG4cwc8?t=439)): No level is defined. Coded as: close beyond the 8-bar high/low.
- "big candle" ([07:19](https://youtu.be/Wu_uvG4cwc8?t=439)): No size given. Coded as: body 1.5x the 20-bar average body.
- Open question: What is the pre-set target?

Example trades shown:
- 2023-09-18 Bank Nifty short: ADX turning up, breakdown at 15:00, big red candle; entry ATM put about Rs 100, stop 20% of premium, target pre-set -> target - 600-700 points down next day, put multiplied ([06:38](https://youtu.be/Wu_uvG4cwc8?t=398))
- 2023-09-01 Bank Nifty long: ADX turned up, breakout above 44150, big green candle; entry call at 150, stop 30 (20%), target 300 -> target - premium doubled on a 300-point rally ([10:03](https://youtu.be/Wu_uvG4cwc8?t=603))

## OB-07 NIFTY ATM straddle-chart day filter: buy options only after the straddle sell stops out, then a 5-minute band breakout on spot

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

Missing or ambiguous in the video:
- Open question: How is the straddle stop-out confirmed before switching to buying?

Claims (quoted as said; not verified):
- Rs 3,59,000 on about Rs 2.2 lakh, max drawdown 2.6% (his forward-tested selling algorithm) [money, forward test] ([11:24](https://youtu.be/GCZOslINAHs?t=684))

Example trades shown:
- 2026-09-22 NIFTY 23400 PE short: straddle sell stopped, spot band break down at 12:50; entry 147, stop 137, target 1:2+ -> target - ran to 198 ([14:48](https://youtu.be/GCZOslINAHs?t=888))

Promotions: Paid indicator and algorithm subscriptions; CoinSwitch demat link (10:42-11:24)

## OB-08 Supertrend (10, 1) + (10, 3) both bullish with a fresh flip and a strong candle, 10-point stop, 20-point target (5-minute NIFTY)

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

Missing or ambiguous in the video:
- "proper candle" ([04:20](https://youtu.be/nVG4mXMcsAA?t=260)): No size rule. Coded as: body at least 60% of the candle range.
- Open question: Does 'just flipped' mean on the signal bar itself or the bar before?

Claims (quoted as said; not verified):
- about 9,000 trades [trade_count, 2015-2025] ([00:49](https://youtu.be/nVG4mXMcsAA?t=49))
- 62% accuracy, average win 20, average loss 10 [win_rate, 2015-2025] ([00:49](https://youtu.be/nVG4mXMcsAA?t=49))
- +79,000 futures points [points, 2015-2025] ([01:33](https://youtu.be/nVG4mXMcsAA?t=93))

Example trades shown:
- date not shown NIFTY long: both green, the faster one just turned green, proper green candle; entry candle close, stop 10 points, target 20 points -> target - 40 points in the next candle ([04:20](https://youtu.be/nVG4mXMcsAA?t=260))

Promotions: Free Telegram alert group via a Dhan account (09:57-10:37)

## OB-09 2-minute EMA 10/20 trend pullback after a stop hunt, star or engulfing entry, done by noon (VIX filter)

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

Missing or ambiguous in the video:
- "big candle" ([04:27](https://youtu.be/pvmvkiS1cx4?t=267)): No size. Coded as: range 2x the 20-bar average.
- "stop hunt" ([07:21](https://youtu.be/pvmvkiS1cx4?t=441)): Depth not given. Coded as: trades through the big candle's 50% level and touches EMA 20.
- Open question: What is the target?

Promotions: Dhan app; free MTF calculator (00:04-00:49)

## OB-10 VWAP side + EMA 5/13 cross + RSI 50, break of the signal candle, EMA 5 trail (5 minutes)

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

Missing or ambiguous in the video:
- "crossover" ([08:36](https://youtu.be/BPF2RjINDeI?t=516)): How recent the cross must be. Coded as: within the last 6 bars.
- Open question: Is half booked at a fixed R before the EMA 5 trail?

Claims (quoted as said; not verified):
- 1:4 and 1:8 trades shown (33-point stop, 290-point target) [r_multiple, examples] ([14:20](https://youtu.be/BPF2RjINDeI?t=860))

Example trades shown:
- date not shown Bank Nifty long: green above VWAP, 5/13 bull cross, RSI above 50; entry above the candle, stop its low, target EMA 5 trail -> target - 400 points vs 100 stop ([09:21](https://youtu.be/BPF2RjINDeI?t=561))
- date not shown Bank Nifty short: 9:30 red below VWAP, RSI under 50, bearish cross; entry below the candle, stop its high, target EMA 5 trail -> target - 290 points vs 33 ([11:34](https://youtu.be/BPF2RjINDeI?t=694))

## OB-11 NIFTY expiry-day 'gamma blast': sub-Rs 10 option on the more-negative-theta side, 14:00-15:00

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

Missing or ambiguous in the video:
- Open question: How is theta compared when the two strikes differ?

Claims (quoted as said; not verified):
- a Rs 3 Sensex premium went to Rs 140 (more than 50x) [other, recent expiry] ([02:53](https://youtu.be/jUNSZnP9MVI?t=173))
- zero-to-hero accuracy about 50% [win_rate, not stated] ([11:20](https://youtu.be/jUNSZnP9MVI?t=680))

Promotions: Paid Upsurge course with the Lorentz setup (10:37-11:20)

