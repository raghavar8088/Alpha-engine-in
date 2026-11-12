# Bitcoin intraday: 12 videos

Each strategy is written from the video's own words (timestamps link to the moment). The [A] lines are
ours: the creator did not say them. Duplicates of the library and blocked strategies are listed with the reason.

## BI-01 Bitcoin 05:30-09:30 IST four-hour opening range, 15-minute breakout, 2 ATR stop from the range line

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

Missing or ambiguous in the video:
- "strong close" ([06:21](https://youtu.be/3XW9lCrMnmg?t=381)): Given as 40-50% of the body. Coded as: 40% of the body beyond the line (the stated minimum).
- "follow-up candle" ([12:36](https://youtu.be/3XW9lCrMnmg?t=756)): Not defined beyond 'a candle after the breakout'. Coded as: any later 15-minute candle that closes beyond the line with 40% of its body.
- "trail" ([08:23](https://youtu.be/3XW9lCrMnmg?t=503)): Methods listed, not specified. Coded as: not coded: fixed 1:2 for the second half.
- Open question: What is the exit time if neither target nor stop is hit?
- Open question: Is more than one trade a day allowed (both sides of the range)?

Claims (quoted as said; not verified):
- back tested for multiple years, very successful [other, multiple years] ([01:24](https://youtu.be/3XW9lCrMnmg?t=84))

Example trades shown:
- 2025-10-13 BTC short: 4-hour range broken down; follow-up candle low broken with 0.03% buffer; entry 113980, stop range line + 2 ATR (ATR about 290: 580 points), target 1:1, then 1:2 -> target - 1:1, 1:2 and 1:3 all reached per the presenter ([09:48](https://youtu.be/3XW9lCrMnmg?t=588))
- 2025-10-15 BTC short: 4-hour range broken down at 111765, prominent close; entry 111280, stop 2 x ATR 372 above 111765, target 1:1 -> unknown - live trade, result left to viewers ([16:52](https://youtu.be/3XW9lCrMnmg?t=1012))

Promotions: Like, share and subscribe for CoinDCX (19:39-20:23)

## BI-02 Fresh zone inside a zone: 4-hour supply/demand refined to the two outermost untouched 15-minute zones, reversal-candle entry

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

Missing or ambiguous in the video:
- "hard fall / strong candles" ([09:16](https://youtu.be/2Ff07pvp4jE?t=556)): No size given for the move away from the base. Coded as: two candles moving at least 1.5 ATR(14).
- "touched" ([14:07](https://youtu.be/2Ff07pvp4jE?t=847)): Whether a wick into the zone counts. Coded as: any later bar's high/low entering the zone marks it tested.
- "pattern" ([25:21](https://youtu.be/2Ff07pvp4jE?t=1521)): Six patterns named, shapes not defined. Coded as: standard definitions: engulf = body covers the previous body; hammer = lower wick at least 2x body.
- Open question: How strong must the move away from a base be?
- Open question: Is the entry at the pattern's close or at a break of its extreme?

Example trades shown:
- 2026-10-12 XAU/USDT short: 4-hour supply zone, 15-minute zone no. 2 rejected with a bearish engulfing; entry inside zone 2, stop zone high, target 1:1 half, rest to cost -> target - move reached about 1:7 per the presenter ([21:54](https://youtu.be/2Ff07pvp4jE?t=1314))

Promotions: Asks for likes and subscriptions; promotes CoinDCX as a registered platform (07:48-08:32)

## BI-03 EMA 9/20 crossover at a twice-touched support or resistance, 5-minute bitcoin

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

Missing or ambiguous in the video:
- "support/resistance" ([06:33](https://youtu.be/WOWeE7XuWOM?t=393)): Levels drawn by eye. Coded as: swing levels touched twice within 0.15%.
- "swing" ([08:43](https://youtu.be/WOWeE7XuWOM?t=523)): Which swing is not fixed. Coded as: the latest confirmed swing beyond the entry.
- Open question: How old may a level be, and how close must the cross be to it?

Claims (quoted as said; not verified):
- earned in 2-3 months of crypto what took 2 years in Indian markets [money, not stated] ([01:33](https://youtu.be/WOWeE7XuWOM?t=93))
- a universal setup that works in every market and trend [other, not stated] ([10:53](https://youtu.be/WOWeE7XuWOM?t=653))

Promotions: Free Telegram channels and a VIP group (08:43-09:30); Broker sign-up for a free course and VIP group access (partner codes in the description) (12:18-12:58)

## BI-04 Bollinger W/M fakeout: first swing outside the band, fakeout of it, neckline break (5-minute bitcoin)

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

Missing or ambiguous in the video:
- "first time" ([08:24](https://youtu.be/e3R9bi_coug?t=504)): How long price must stay inside before an exit counts as first. Coded as: 5 bars inside the band before the exit.
- "far from entry" ([15:14](https://youtu.be/e3R9bi_coug?t=914)): Two candles away is not a distance. Coded as: 0.5R beyond the neckline.
- "where the move began" ([13:46](https://youtu.be/e3R9bi_coug?t=826)): Start of the move is read by eye. Coded as: extreme of the 30 bars before the first band exit.
- Open question: Does the neckline break need one close or two?
- Open question: How far beyond the band does the stop go?

Example trades shown:
- date not shown BTC/USD long: first exit below the lower band, swing low outside, immediate fakeout, neckline break; entry neckline break, stop below the band, target 1:1 then the move start -> target - 1:1 reached (1.12 at recording) ([10:25](https://youtu.be/e3R9bi_coug?t=625))

Promotions: Introduces himself as a SEBI-registered research analyst; exchange referral links in the description (00:02-00:43)

## BI-05 Bitcoin 8-hour structure range: buy the discount quarter after a break of structure (smart money)

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

Missing or ambiguous in the video:
- "extreme level" ([04:57](https://youtu.be/eVqCSx887G8?t=297)): Extreme demand chosen by eye. Coded as: the 0.75-1.0 retracement of the current range.
- Open question: How is a break of structure confirmed (close or wick)?

Example trades shown:
- date not shown BTC long: break of structure, back inside the range, discount entry; entry discount quarter, stop below the swing low, target previous range, then liquidity -> target - both targets hit ([05:39](https://youtu.be/eVqCSx887G8?t=339))

Promotions: Like/subscribe; website for more lessons (02:53-03:35)

## BI-06 Two-candle turn through EMA 6 on 1-hour bitcoin, 1:3

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

Missing or ambiguous in the video:
- "channel breakout" ([09:51](https://youtu.be/XIlGVsPpIRw?t=591)): The channel is not defined. Coded as: no new entries for the rest of the UTC day after a stop.
- "top" ([03:00](https://youtu.be/XIlGVsPpIRw?t=180)): 'Green candle at the top' is not measured. Coded as: no extra condition.
- Open question: How long does the entry order stay valid after the pair?

Claims (quoted as said; not verified):
- real-time tested sniper system, no fake breakouts [other, not stated] ([00:47](https://youtu.be/XIlGVsPpIRw?t=47))
- three wins of 3R for every loss [r_multiple, not stated] ([09:09](https://youtu.be/XIlGVsPpIRw?t=549))

Example trades shown:
- date not shown BTC long: red then green not breaking the low, above EMA 6; entry green high break, stop red low, target 3R -> target - profit per the presenter ([05:42](https://youtu.be/XIlGVsPpIRw?t=342))

Promotions: CoinDCX account via his link: 5-day class and premium Telegram (09:51-10:33)

## BI-07 Three-candle zone retest with a rejection candle (5-minute bitcoin)

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

Missing or ambiguous in the video:
- "rejection candle" ([01:32](https://youtu.be/2_6VTstvm_w?t=92)): Shape not defined. Coded as: trades into the zone and closes in the trend direction above the zone's midpoint.
- "trend" ([00:52](https://youtu.be/2_6VTstvm_w?t=52)): Read by eye. Coded as: close vs EMA 50.
- "small stop" ([02:13](https://youtu.be/2_6VTstvm_w?t=133)): No place given. Coded as: beyond the zone's far side.
- Open question: Where exactly is the stop?
- Open question: What is the target, given 1:5 to 1:10 is only a claim?

Claims (quoted as said; not verified):
- 110% guarantee you will need no other strategy [guarantee, not stated] ([00:06](https://youtu.be/2_6VTstvm_w?t=6))
- minimum 1:5 to 1:10 in one trade [r_multiple, backtested 2-3 months] ([00:52](https://youtu.be/2_6VTstvm_w?t=52))
- a no-loss strategy: the stop will not be hit [other, not stated] ([02:56](https://youtu.be/2_6VTstvm_w?t=176))

Example trades shown:
- date not shown BTC short: three red candles boxed, price back in the box, rejection; entry next candle, stop not stated, target not stated -> target - about 1:6 ([02:56](https://youtu.be/2_6VTstvm_w?t=176))
- date not shown BTC long: three green candles boxed, retest, rejection; entry next candle, stop not stated, target not stated -> target - about 1:10 ([04:21](https://youtu.be/2_6VTstvm_w?t=261))

Promotions: Telegram link for live trades (06:24-06:50)

## BI-08 5-minute multi-touch level for direction, 1-minute structure breakout (scalp)

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

Missing or ambiguous in the video:
- "several touches" ([00:43](https://youtu.be/h-Z7CEqBO3s?t=43)): No count or tolerance. Coded as: 3+ touches within 0.05% in 6 hours.
- "tight stop" ([02:45](https://youtu.be/h-Z7CEqBO3s?t=165)): No place given. Coded as: beyond the last 1-minute higher low.
- Open question: Where exactly is the stop?
- Open question: Which 1-minute level counts as the breakout level?

Claims (quoted as said; not verified):
- up $44,000 on a live US30 trade; made nearly $50,000 today with this strategy [money, that day] ([04:10](https://youtu.be/h-Z7CEqBO3s?t=250))
- three confirmations take the chance from 50% to 75-80% [win_rate, not stated] ([06:59](https://youtu.be/h-Z7CEqBO3s?t=419))

Promotions: Prop firm (Clarity Traders) discount codes (00:01-00:43); Paid live-trading membership at $39.99 a month (04:50-05:33)

## BI-09 SMA 100 side + higher-timeframe Heikin Ashi trend + MACD cross, 2R (5-minute bitcoin)

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

Missing or ambiguous in the video:
- "higher timeframe" ([03:34](https://youtu.be/zpFQmtNd1pI?t=214)): The Candle Plot MTF timeframe is not given. Coded as: 15-minute Heikin Ashi.
- "previous move" ([08:31](https://youtu.be/zpFQmtNd1pI?t=511)): Stop place left to the trader. Coded as: the lower of the two last lows, at least 0.15%.
- Open question: Near DT-01 (MACD cross in an EMA 100 trend on 1 hour): kept as the 5-minute version with the Heikin Ashi filter.
- Open question: Which timeframe do the Heikin Ashi candles use?

Example trades shown:
- date not shown BTC long: above SMA 100, HA up, MACD cross; entry 26774, stop 26727, target 26880 -> unknown - about 18 bp risk, 40 bp target ([09:12](https://youtu.be/zpFQmtNd1pI?t=552))

Promotions: Apex Pro exchange and TradingView sign-up links (02:07-02:51)

## BI-10 5 EMA untouched alert candle, next body crossing at least 30% (15-minute bitcoin)

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

Missing or ambiguous in the video:
- Open question: Is the entry at the crossing candle's close or during it?

Claims (quoted as said; not verified):
- 80-90% success, 70-80% [win_rate, not stated] ([01:27](https://youtu.be/PFnIohLAPOs?t=87))
- account grown from 5,000 to about 20,800 [money, not stated] ([00:46](https://youtu.be/PFnIohLAPOs?t=46))

Promotions: Delta Exchange discount link and Telegram in the description (00:03-00:10)

## BI-11 EMA 200 + RSI above 50 + bullish engulfing, long only, 1:2

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

Missing or ambiguous in the video:
- Open question: What RSI length does the divergence indicator use?

Claims (quoted as said; not verified):
- 7 to 8 of 10 trades profitable at 1:2 [win_rate, not stated] ([04:53](https://youtu.be/0Qvy_S_giCI?t=293))

Example trades shown:
- 2024-07-29 BTC long: above EMA 200, RSI above 50, bullish engulfing; entry engulfing close, stop engulfing low, target 1:2 -> target - 500-600 points ([07:37](https://youtu.be/0Qvy_S_giCI?t=457))

Promotions: Like, share, subscribe (00:04-00:45)

## BI-12 EMA 21 break and retest: opposite candle within three bars, enter on its high/low (15-minute bitcoin)

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

Missing or ambiguous in the video:
- Open question: Does the buy-stop stay live after the third candle?

Claims (quoted as said; not verified):
- traded since 2018 and still working [other, 2018-2026] ([31:17](https://youtu.be/RW-bR1YKrNk?t=1877))

Example trades shown:
- date not shown BTC long: close above EMA 21, then a bearish candle; entry its high, stop lowest low before trigger, target 1.5R, 3R -> target - 1.65R reached live ([20:03](https://youtu.be/RW-bR1YKrNk?t=1203))

