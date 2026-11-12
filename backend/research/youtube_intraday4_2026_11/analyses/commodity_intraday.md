# MCX commodity intraday: 12 videos

Each strategy is written from the video's own words (timestamps link to the moment). The [A] lines are
ours: the creator did not say them. Duplicates of the library and blocked strategies are listed with the reason.

## CI-01 Crude oil 1-hour MACD side, fresh 15-minute MACD crossovers, exit on the opposite cross

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

Missing or ambiguous in the video:
- "fresh signal" ([06:23](https://youtu.be/ZniDTRbVMsw?t=383)): Only crossovers after the 1-hour phase began count. Coded as: crossovers on 15-minute bars after the last 1-hour MACD cross.
- Open question: Is there any stop besides the opposite crossover?

Claims (quoted as said; not verified):
- losses 7-12 points, profits 40-50 points [r_multiple, Dec 2025 examples] ([08:31](https://youtu.be/ZniDTRbVMsw?t=511))

Example trades shown:
- 2025-12-12 MCX Crude long: 1-hour buy phase, 15-minute buy cross; entry 15-minute close, stop -, target opposite cross -> stop - about 13 points lost ([07:04](https://youtu.be/ZniDTRbVMsw?t=424))
- 2025-12-15 MCX Crude short: 1-hour sell phase, fresh 15-minute sell cross; entry 15-minute close, stop -, target opposite cross -> target - about 54 points down move ([07:50](https://youtu.be/ZniDTRbVMsw?t=470))

Promotions: Dhan app and its scalper tool (09:55-10:30)

## CI-02 Crude oil 66 moving-average slope + Stochastic 75/35 re-cross, 1:2

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

Missing or ambiguous in the video:
- "falling / rising" ([05:05](https://youtu.be/5MehM14d0vQ?t=305)): Slope read by eye. Coded as: SMA66 change over 5 bars beyond 0.05% of price.
- "sideways" ([27:12](https://youtu.be/5MehM14d0vQ?t=1632)): 'Visual concept'. Coded as: flat average by the same test.
- Open question: How is a falling average measured?

Example trades shown:
- date not shown MCX Crude short: falling MA66, Stochastic back below 75; entry trigger low 8600, stop about 400 points above, target 1:2, 7800 -> target - 5-hour chart ([14:04](https://youtu.be/5MehM14d0vQ?t=844))
- date not shown MCX Crude short: re-entry below a doji after a stop; entry 7800, stop about 150 points, target 7500 -> target - made money on the second try ([17:28](https://youtu.be/5MehM14d0vQ?t=1048))

Promotions: Risk-management videos and a paid program (31:36-33:52)

## CI-03 Crude oil 17:30-18:00 IST 30-minute candle: 50% side and break after 18:00 on 3 minutes, 1:2

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

Missing or ambiguous in the video:
- "break" ([10:37](https://youtu.be/Y8NILq4BITA?t=637)): Whether a wick or a close counts. Coded as: a 3-minute close beyond the 30-minute candle's high/low.
- "previous candle" ([10:37](https://youtu.be/Y8NILq4BITA?t=637)): Which side of which candle. Coded as: the extreme of the candle before the entry candle.
- Open question: Is the long trigger a close above the candle's high or any positive bar above the 50% level?

Claims (quoted as said; not verified):
- 90% accuracy [win_rate, not stated] ([07:38](https://youtu.be/Y8NILq4BITA?t=458))

Example trades shown:
- date not shown MCX Crude short: break below after 18:00; entry -, stop previous candle, 15 points, target 1:2 -> stop - then reversed long ([10:37](https://youtu.be/Y8NILq4BITA?t=637))
- date not shown MCX Crude long: momentum after the stop, close above; entry -, stop 30 points, target 1:2 -> target - 1:3 reached (90 points) ([11:22](https://youtu.be/Y8NILq4BITA?t=682))
- 2023-08-17 MCX Crude long: above the 50% level after 18:00, positive bar close; entry -, stop 12 points, target 1:2 -> target - 1:3-1:4 ([13:22](https://youtu.be/Y8NILq4BITA?t=802))

Promotions: Telegram community via broker sign-up links (06:18-06:58)

## CI-04 Crude oil Donchian-200 extreme on 20 minutes, 5-minute EMA 9 reversal, 40 points then trail

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

Missing or ambiguous in the video:
- "outside the channel" ([05:43](https://youtu.be/7kHXWtf8GVk?t=343)): How far and for how long counts. Coded as: a 20-minute close beyond the offset band.
- "300" ([06:24](https://youtu.be/7kHXWtf8GVk?t=384)): Heard as 300; the exit uses 100. Coded as: EMA 100.
- Open question: Is the slow average 100 or 300?
- Open question: Where is the protective stop?

Claims (quoted as said; not verified):
- losses 8-15 points, profits 40-60 points [r_multiple, Nov-Dec 2025 examples] ([07:51](https://youtu.be/7kHXWtf8GVk?t=471))

Example trades shown:
- date not shown MCX Crude short: above the Donchian band on 20 minutes, 5-minute EMA 9 below its averages; entry -, stop -, target 40 points -> target - 44 points in 4 hours, 60 by the close ([06:24](https://youtu.be/7kHXWtf8GVk?t=384))
- 2025-11-12 MCX Crude long: below the lower band, buy signal; entry -, stop -, target 40 points -> closed_early - 31 points, exited at cost on the reversal ([07:51](https://youtu.be/7kHXWtf8GVk?t=471))

Promotions: Dhan Super Order and scalper tools (10:01-10:46)

## CI-05 Crude oil 15-minute two-candle rejection after 12:00 IST (sweep of the prior candle, break of the signal candle)

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

Missing or ambiguous in the video:
- "after a rise / top" ([05:45](https://youtu.be/2ZTBqEduoe0?t=345)): Not measured. Coded as: the green candle's high is the 8-bar high.
- Open question: What are the filters that remove fake signals?

Claims (quoted as said; not verified):
- one candle gave Rs 13,000; another Rs 23,600 (mega lot) [money, single trades] ([00:05](https://youtu.be/2ZTBqEduoe0?t=5))
- the signal forms every day [other, not stated] ([00:05](https://youtu.be/2ZTBqEduoe0?t=5))

Example trades shown:
- date not shown MCX Crude short: red candle swept the green high after 12:00; entry red low break, stop red high + 2, target 1.5R or 50 points -> target - - ([05:45](https://youtu.be/2ZTBqEduoe0?t=345))
- date not shown MCX Crude long: green candle swept the red low, closed green; entry green high break, stop green low, target 50 points -> target - 230 points move ([09:59](https://youtu.be/2ZTBqEduoe0?t=599))

Promotions: Filters promised in a later video (12:05-12:30)

## CI-06 Crude oil RSI 60/40 cross on the SMA 89 side, 15 minutes, 18:00-22:00 IST, 1:2

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

Missing or ambiguous in the video:
- "trail the order" ([09:02](https://youtu.be/AlMUdyYku8k?t=542)): No rule for how far or how long. Coded as: lower it to each new candle's high for up to 8 bars.
- Open question: How long does the trailed entry order stay live?

Claims (quoted as said; not verified):
- consistent profit, excellent accuracy, can change your life [other, not stated] ([01:25](https://youtu.be/AlMUdyYku8k?t=85))

Example trades shown:
- date not shown US Oil / MCX Crude long: RSI crossed 60 above SMA 89, order trailed on the pullback; entry 70.97, stop trigger low, target 1:2 -> target - went beyond 1:3 ([09:44](https://youtu.be/AlMUdyYku8k?t=584))
- date not shown US Oil / MCX Crude short: RSI crossed 40 below SMA 89; entry trigger low, stop trigger high or swing high, target 1:2 -> target - more than 1:5 ([15:21](https://youtu.be/AlMUdyYku8k?t=921))

Promotions: Broker sign-up links for a VIP group and two free courses (12:33-13:15)

## CI-07 Natural gas MFI(140) 40/60 zone + Supertrend side + EMA 9/26 cross (1 hour)

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

Missing or ambiguous in the video:
- "near 40" ([04:21](https://youtu.be/wx-DyDEz2Xg?t=261)): Distance to 40 not given. Coded as: MFI at or below 42 within 10 bars.
- Open question: What Supertrend settings are used?

Claims (quoted as said; not verified):
- moves of 1.5-6.5% after signals [other, Aug 2025 examples] ([05:04](https://youtu.be/wx-DyDEz2Xg?t=304))

Example trades shown:
- date not shown MCX Natural Gas long: MFI near 40, above Supertrend, EMA 9/26 bullish; entry -, stop Supertrend, target 0.6-0.8% -> target - 2% in a day ([05:04](https://youtu.be/wx-DyDEz2Xg?t=304))
- date not shown MCX Natural Gas short: MFI overbought, below Supertrend, bearish cross; entry -, stop Supertrend, target 1% -> target - 2.5% in 19 hours ([06:28](https://youtu.be/wx-DyDEz2Xg?t=388))

Promotions: Dhan ScanX inventory updates and weekly reels (07:54-08:30)

## CI-08 Crude oil 7% stretch from the 200 average + slow Stochastic RSI turn (15 minutes)

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

Missing or ambiguous in the video:
- "about 7%" ([08:31](https://youtu.be/fcU8iz__qfE?t=511)): Given as 5-9%. Coded as: 6.5%.
- "sell signal" ([09:14](https://youtu.be/fcU8iz__qfE?t=554)): Which crossover is meant. Coded as: K crossing D.
- Open question: Is the stretch measured at the signal bar or any recent bar?

Claims (quoted as said; not verified):
- 4.5% fall in 11 hours; 8.5-9% in 3 days; losses only 50-60 points vs profits of thousands of rupees [other, examples] ([09:55](https://youtu.be/fcU8iz__qfE?t=595))

Example trades shown:
- date not shown MCX Crude short: stretched above +7%, Stochastic RSI sell; entry -, stop EMA 5/15 cross, target Stochastic RSI buy -> target - 4.5% in 11 hours ([09:14](https://youtu.be/fcU8iz__qfE?t=554))
- date not shown MCX Crude long: stretched below -7%, Stochastic RSI buy; entry -, stop EMA 5/15 cross, target 50-100 points -> target - 4.5% in 7 hours ([10:39](https://youtu.be/fcU8iz__qfE?t=639))

Promotions: Free MTF leverage Excel sheet via a Google form (04:18-05:01)

## CI-09 Crude oil 17:45 IST 15-minute candle: three lines (high, low, 50%), 5-minute close beyond

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

Missing or ambiguous in the video:
- Open question: Is the early entry above the 50% level a separate rule with its own stop?

Claims (quoted as said; not verified):
- 80% accuracy [win_rate, not stated] ([04:05](https://youtu.be/K_qNy37g1eA?t=245))
- Rs 7,200 profit against Rs 800 risk in one shot [money, single trade] ([00:02](https://youtu.be/K_qNy37g1eA?t=2))

Example trades shown:
- date not shown MCX Crude long: close above the upper line after 18:00; entry -, stop breakout candle low, target 1:4 -> target - 48 points, Rs 4,800 vs Rs 1,300 risk ([09:39](https://youtu.be/K_qNy37g1eA?t=579))

Promotions: Live trading sessions (01:22-02:04); Paid mentorship (Rs 399 code), Telegram (11:51-12:33)

## CI-10 Silver Micro 18:30 IST 30-minute candle breakout with a 50-point buffer, stop and reverse, 1:2

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

Missing or ambiguous in the video:
- "double order" ([04:16](https://youtu.be/zsFn_iUtPQI?t=256)): Size of the reversal not clear. Coded as: one reversal at normal size.
- Open question: Is the stop exactly the opposite trigger or the candle's other side?

Claims (quoted as said; not verified):
- 6-7 of 10 trades profitable; a month's trades covered in a day; up to 1:10 [win_rate, Aug-Sep 2025] ([05:38](https://youtu.be/zsFn_iUtPQI?t=338))

Example trades shown:
- 2025-08-31 MCX Silver Micro short: 18:30 candle, upside break failed, downside break; entry low - 50, stop high + 50, target 1:2 -> target - big down move until 23:00 ([03:33](https://youtu.be/zsFn_iUtPQI?t=213))
- 2025-08-24 MCX Silver Micro short: 18:30 candle break; entry 255900, stop -, target 1:2 -> target - 3,000 points vs 1,500 lost ([04:57](https://youtu.be/zsFn_iUtPQI?t=297))

## CI-11 Daily inside-candle (mother/baby) levels traded intraday (crude oil)

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

Missing or ambiguous in the video:
- Open question: What confirms an entry at the mother-candle level?
- Open question: Is it a breakout or a rejection trade at the level?

Promotions: Subscribe requests (01:31-02:27)

## CI-12 Crude oil 'bald' green candle (no lower wick) after a red series, 15-minute scalp

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

Missing or ambiguous in the video:
- "strong uptrend" ([02:18](https://youtu.be/nvcYcx9ljzY?t=138)): Read by eye. Coded as: SMA 20 rising over 4 bars and higher lows.
- "some room" ([10:15](https://youtu.be/nvcYcx9ljzY?t=615)): Distance not given. Coded as: 0.1% below the low.
- Open question: Is the entry at the bald candle's close or the next open?

Claims (quoted as said; not verified):
- one of the highest win rates [win_rate, not stated] ([00:10](https://youtu.be/nvcYcx9ljzY?t=10))

Example trades shown:
- 2024-06-12 WTI crude long: bald green candles in an uptrend; entry candle close, stop below the low, target next candle -> target - strong moves after ([11:01](https://youtu.be/nvcYcx9ljzY?t=661))
- 2024-06-27 WTI crude long: bald green candle, retest of its low rejected; entry candle close, stop below the low, target 20-30 points -> target - - ([12:28](https://youtu.be/nvcYcx9ljzY?t=748))

Promotions: Paid crude oil course with 10 strategies (00:10-01:05)

