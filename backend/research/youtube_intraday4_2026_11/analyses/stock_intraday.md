# Indian stock intraday: 13 videos

Each strategy is written from the video's own words (timestamps link to the moment). The [A] lines are
ours: the creator did not say them. Duplicates of the library and blocked strategies are listed with the reason.

## SI-01 9:25 F&O top-mover body-range breakout on 3 minutes (no-gap stocks, index-aligned), ATM option buy

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

Missing or ambiguous in the video:
- "range from bodies" ([10:51](https://youtu.be/XhFNkKnr9hk?t=651)): Which candles count to 9:25. Coded as: 3-minute bodies 9:15-9:24.
- Open question: How is the trail split between the 1% target and EMA 9?

Claims (quoted as said; not verified):
- 4-5 trades a week [other, not stated] ([15:59](https://youtu.be/XhFNkKnr9hk?t=959))

Example trades shown:
- 2025-10-09 TCS long: top gainer, 9:25 body range, 3-minute close above at 9:36; entry 2170 (2120 CE at 75), stop below the range, target 1% -> target - option 75 to 100 ([09:24](https://youtu.be/XhFNkKnr9hk?t=564))
- 2025-09-30 Coforge long: top gainer, range breakout; entry 1780 CE, stop below the range, target 1% -> target - strong move ([23:50](https://youtu.be/XhFNkKnr9hk?t=1430))

Promotions: Upsurge course discount (00:02-00:47)

## SI-02 Fixed watchlist: 9:15-9:30 range break on the VWAP side, pullback engulfing entry, stop beyond VWAP

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

Missing or ambiguous in the video:
- "close to VWAP" ([06:19](https://youtu.be/9hWKM8bAWl4?t=379)): Distance not given. Coded as: within 0.2% of VWAP.
- Open question: What is the target or exit?

Example trades shown:
- date not shown Titan short: range broken down, below VWAP, bearish engulfing on the pullback; entry engulfing close, stop above VWAP, target - -> stop - stop hit ([04:16](https://youtu.be/9hWKM8bAWl4?t=256))
- date not shown Maruti short: trend down below VWAP, bearish engulfing; entry engulfing close, stop above VWAP, target - -> target - ran in the direction ([04:56](https://youtu.be/9hWKM8bAWl4?t=296))

Promotions: Dhan app download (00:45-01:26)

## SI-03 NIFTY second-and-third 15-minute candle range (9:30-10:00), first break in the running candle

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

Missing or ambiguous in the video:
- Open question: What is the target and the stop-and-reverse rule?

Claims (quoted as said; not verified):
- 400-500 points of momentum in 3 days (70, 114, 112, 147 points) [points, examples] ([09:09](https://youtu.be/Pv1K3OwPIuc?t=549))

Promotions: Paid course and workshop links; private community (00:01-00:46)

## SI-04 NIFTY first 15-minute candle colour picks the side; top three movers, break of their second 15-minute candle, 1:2

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

Missing or ambiguous in the video:
- "top three" ([03:27](https://youtu.be/HeZUP-j1tN8?t=207)): Which ranking. Coded as: largest % move from the previous close at 9:30.
- Open question: What does the 52-week high/low list add?

Example trades shown:
- 2025-12-08 IndiGo short: NIFTY first candle red, IndiGo top decliner, second-candle low broken; entry below the low, stop candle high, target 1:2 -> target - strong fall ([04:09](https://youtu.be/HeZUP-j1tN8?t=249))

## SI-05 Futures OI-gainer selection + long build-up check + EMA 20/50/200 stack (5 minutes)

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

Missing or ambiguous in the video:
- Open question: What exact candle triggers the entry once the EMAs are stacked?

Example trades shown:
- date not shown Paytm long: OI gainer, long build-up, EMA 20 > 50 > 200; entry 5-minute chart, stop -, target - -> target - moved up ([04:26](https://youtu.be/1EPFJY4Mhws?t=266))

Promotions: Dhan Options Trader web insights (00:49-01:33)

## SI-06 SMMA 11/21 crossover on the side of the higher-timeframe 21 average (5-minute stocks / 3-minute index)

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

Missing or ambiguous in the video:
- "expected result" ([23:38](https://youtu.be/-KUnWt8PqAY?t=1418)): No number. Coded as: 2R for the first half.
- Open question: What exactly is the first target?

Example trades shown:
- 2025-08-21 NIFTY short: bearish SMMA cross below the 15-minute MA, bullish crosses ignored; entry confirmation candle, stop about 30-35 points, target half at target -> target - trend day down ([11:08](https://youtu.be/-KUnWt8PqAY?t=668))

Promotions: Upsurge course for Pawan Sharma's intraday options (00:03-00:47)

## SI-07 Lowest-volume opposite candle after a three-candle move (Kushal Varshney)

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

Missing or ambiguous in the video:
- Open question: What is the stock-selection rule and the target?

Claims (quoted as said; not verified):
- the world's smallest stop-loss and the biggest target [other, not stated] ([00:07](https://youtu.be/rOBS_fgFIZE?t=7))

Promotions: Sunday webinars and an in-person mentorship in Noida (09:17-11:27)

## SI-08 Previous afternoon (14:00-15:30) range around VWAP: break, pullback, engulfing entry, 1:2 (fixed list)

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

Missing or ambiguous in the video:
- "flat VWAP" ([03:35](https://youtu.be/kAF642I922g?t=215)): No slope test. Coded as: VWAP moving less than 0.3% across the range window.
- Open question: Is the previous day's afternoon range required, or is any range fine?

Example trades shown:
- date not shown Titan short: range breakdown, pullback, bearish engulfing; entry 3697, stop 3708, target 1:2 = 3681 -> target - 1:2 reached ([05:02](https://youtu.be/kAF642I922g?t=302))

Promotions: Dhan app download (00:05-00:46)

## SI-09 First 15-minute candle breakout on 5 minutes, stop at the far side, 1:2, nothing after 10:00, no Tuesdays

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

Missing or ambiguous in the video:
- Open question: Is the break a 5-minute close or a touch?

Claims (quoted as said; not verified):
- 1:4 to 1:5 on a trend day [r_multiple, example] ([08:22](https://youtu.be/g0xJhdy4asQ?t=502))

Promotions: Free demat account links (01:33-02:14)

## SI-10 Breadth-chosen sector, previous-day high/low break with two same-colour 5-minute candles, half at 1:2, rest to 15:15

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

Missing or ambiguous in the video:
- "weakest sector" ([07:49](https://youtu.be/ibO1Sp1bess?t=469)): Needs sector membership. Coded as: dropped in the desk version.
- Open question: Which sector list and stock watchlist are used exactly?

Example trades shown:
- date not shown Saregama (media) short: media weakest, master candle below previous-day low, red confirmation; entry below the confirmation candle, stop its high, target half 1:2, rest 15:15 -> target - - ([10:39](https://youtu.be/ibO1Sp1bess?t=639))

Promotions: Channel and broker mentions (00:09-00:54)

## SI-11 9:30 open-equals-low gainer (open-equals-high loser): first 15-minute candle breakout, stop at the open

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

Missing or ambiguous in the video:
- "open equals low" ([02:51](https://youtu.be/nlXGU_7xxjA?t=171)): Exact equality on tick data. Coded as: low within 0.02% of the open.
- Open question: Does the order expire if the high is not broken by a set time?

Example trades shown:
- 2025-08-19 Persistent long: gainer with open = low, 15-minute high 5448 broken; entry 5448, stop 5335.80, target 1:1 or 14:00 -> target - 5515 in three candles, 5548 by 11:00 ([04:15](https://youtu.be/nlXGU_7xxjA?t=255))

Promotions: Upsurge course links for Rajesh Jain's setups (21:22-22:19)

## SI-12 Leading sector's top mover: 9:20 five-minute candle on the VWAP side, break of it, 1:1.5 then 1:2

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

Missing or ambiguous in the video:
- "maximum 6%" ([03:29](https://youtu.be/aW9LEPh43Go?t=209)): Said as '6%', shown as 0.6% on the tool. Coded as: 0.6%.
- Open question: Is the 0.6% cap applied to all stocks?

Example trades shown:
- 2026-06-04 TCS short: IT weakest, 9:20 red candle below VWAP, low broken; entry below the low, stop candle high (max 0.6%), target 1:1.5 then 1:2 -> target - fell all day ([03:29](https://youtu.be/aW9LEPh43Go?t=209))

Promotions: 'Brahmastra' indicator and Lemonn broker referral (06:17-07:43)

## SI-13 First-hour (9:15-10:15) range breakout, touch entry, opposite-side stop, out at 15:15, one trade a day

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

Missing or ambiguous in the video:
- Open question: None for the core rule.

Claims (quoted as said; not verified):
- 48.12% win rate, profit factor 1.22, max drawdown 11.52% [win_rate, Bank Nifty 5-minute, about 2009-2023] ([17:48](https://youtu.be/wch7m96yZ2M?t=1068))
- day high and low set in the first hour on 64% (NIFTY) and 70% (Bank Nifty) of 3,066/3,090 days [other, about 2010-2022] ([04:57](https://youtu.be/wch7m96yZ2M?t=297))

Promotions: Paid ORB AFL course and his book (00:46-01:27)

