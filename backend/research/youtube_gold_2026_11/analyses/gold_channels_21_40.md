# Gold channels 21-40 (2026-11-22)

20 channels, 59 videos picked, 58 read from their captions. 16 strategies coded (version v1, Rs 10 lakh each on Delta XAUTUSD from 2026-11-22T22:00:00Z), 17 methods not coded (10 need data the desk lacks or paid tools, 3 repeat another, 4 teach no testable rule). None was backtested.

## AF-03 Gold inside-day break, continuation to the mother day's extreme
Axia Futures - https://youtu.be/Zw-0ImGVUY0 (GOLD Inside Day Break | Axia Futures)

After an inside day (its range inside the day before), the first 15-minute close beyond the inside day's high or low takes the break, with the stop beyond that candle and the mother day's high or low as the target ('we target the big high').

- [E] Setup: An inside day: the previous gold day's high and low inside the day before's range. "so we have an inside day you had an open" (Zw-0ImGVUY0 01:00)
- [E] Setup: The idea is to trade the break out of the inside day's range. "last week that was an inside day and then a breakout from the inside day" (5QvzsnwAPek 00:04)
- [A] Entry: Long at the open after the first 15-minute close above the inside day's high (short: below its low); one trade a day, entries until 16:00 New York.
- [E] Target: Target the big high outside the inside day: the mother day's high (low for shorts). "we target the big high that we had" (Zw-0ImGVUY0 01:18)
- [A] Target: If the mother day's extreme is less than 1R away, 2R instead.
- [A] Stop: Beyond the breakout candle's far end (one tick).
- [A] Exit: Flat at 16:55 New York (the gold session's end).

Code check: look-ahead ok, fills ok; 14 signals, 14 simulated fills on research data.

## AF-04 COMEX-hours break of a repeatedly tested prior-day high (low), target last week's high (low)
Axia Futures - https://youtu.be/4nbC_2SoDpM (AXIA Junior Funded Trader Trades Gold Breakout Of Daily Highs [LIVE TRADING])

In the US cash session a prior-day high that has been tested again and again is 'vulnerable'; the first 5-minute close through it is bought, targeting last week's high, with the stop under the last half hour.

- [E] Setup: The break of yesterday's high is the trigger. "there's a break of yesterday's high which is a possibility" (2QKPzxKgbnQ 06:40)
- [E] Setup: The level has been tested many times, which makes it vulnerable. "it's been tested so many times the market keeps coming back to it" (2QKPzxKgbnQ 06:46)
- [E] Session: Taken inside the US cash session, when 'all the flows are there'. "inside the um inside sort of the u.s cash session" (2QKPzxKgbnQ 08:50)
- [A] Setup: A test is a 5-minute high within 0.03% of the level that closes back below; at least two tests, 30 minutes apart, earlier in the day; the cash session is 08:20-13:30 New York.
- [A] Entry: Long at the next open after the first 5-minute close above the prior day's high (short: below the low).
- [E] Target: Last week's high is the next objective once yesterday's high breaks. "the break of yesterday's high and then 35 and a half is last week's high" (2QKPzxKgbnQ 08:19)
- [A] Target: If last week's high is less than 1.5R away, 2R.
- [A] Stop: Below the lowest low of the 30 minutes before the break (above the highest for shorts).

Code check: look-ahead ok, fills ok; 39 signals, 39 simulated fills on research data.

## BO-01 Anchored VWAP from the last 4-hour swing, retested against the trend and rejected
BikoTrading | Futures Trading - https://youtu.be/ZQlxKZk0YIY (Gold: Time to Buy or Another Drop? My VWAP Trading Plan)

Follow the trend: in a 4-hour downtrend, the VWAP anchored at the last swing high is where to sell a retest; the target is the swing low. Mirror in an uptrend.

- [E] Trend: Trade with the trend until a clear reversal. "your major priority would be still to follow the trend" (ZQlxKZk0YIY 01:39)
- [A] Trend: A downtrend: the last two confirmed 4-hour swing highs and lows (2-bar fractals) both lower; an uptrend: both higher.
- [E] Level: The VWAP anchored at the swing high. "it would be unkept Vwap from this swing high" (ZQlxKZk0YIY 01:52)
- [E] Level: He builds the anchored VWAP from the swing high in a downward structure. "I will build anchored view up from swing high" (cRlHoGcCgEA 40:48)
- [E] Entry: Sell its retest, ideally after a local consolidation. "retest of that view up plus some local consolidation could be one of the best place for a short" (ZQlxKZk0YIY 01:58)
- [A] Entry: A 15-minute candle that trades up to the anchored VWAP from below and closes back below it (his absorption confirmation needs order flow the desk lacks); one per anchor, at most two a day, 02:00-16:00 New York.
- [E] Target: The swing low. "with a target to take this swing low" (ZQlxKZk0YIY 03:38)
- [A] Target: The last confirmed 4-hour swing low, if at least 1.5R away; else 2R.
- [A] Stop: A quarter of the 15-minute ATR(14) beyond the rejection candle.

Code check: look-ahead ok, fills ok; 36 signals, 36 simulated fills on research data.

## BO-02 False breakout of a daily key level: entry at the level, stop 2 pips beyond the tail, 4R
BikoTrading | Futures Trading - https://youtu.be/mETNGRc9cgU (False Breakout — Best Trading Strategy for all markets: Forex, Crypto, Stocks, GOLD, OIL.)

Key levels come from the daily chart. When price breaks one and comes back, enter at the level with the stop two pips beyond the tail and a target four times the risk.

- [E] Levels: Key levels from the daily (and weekly) chart. "it's important to use kilos on daily and weekly chart" (mETNGRc9cgU 23:51)
- [A] Levels: The previous gold day's high and low and the last confirmed daily swing high and low (2-day fractals).
- [E] Levels: In his gold plan, a long needs price to take Friday's low first. "price take Friday low and there would be some absorption" (ZQlxKZk0YIY 05:11)
- [E] Entry: After the break, enter as price comes back through the level, stop below the tail. "when price break you level opposite you can set by stop stop loss below tail" (mETNGRc9cgU 26:47)
- [E] Entry: Enter at most 5 pips from the level, otherwise wait with a limit order there. "I recommend to open entry maximum 5 pips from key level" (mETNGRc9cgU 37:35)
- [A] Entry: A 15-minute close back inside within an hour of the first trade beyond the level: at the next open if the close is within $0.50 of the level, else a limit at the level for an hour.
- [E] Stop: Two pips beyond the tail. "always you set stop-loss to pips above tails" (mETNGRc9cgU 37:16)
- [A] Stop: Two pips on gold read as $0.20.
- [E] Target: Take profit at four times the stop. "take profit in 4 times bigger" (mETNGRc9cgU 33:57)

Code check: look-ahead ok, fills ok; 109 signals, 71 simulated fills on research data.

## TO-01 Daily 9-period MA side, 1-hour Bollinger Band touch at the previous swing, 1:5
Trading Orbit - https://youtu.be/B_rkzkbbYlQ (XAUUSD Gold Trading on Delta Exchange 🔥  Bollinger Band 1H Strategy + LIVE Trade 15 RR)

Presented for gold on Delta Exchange: the daily 9-period moving average decides the side; on the 1-hour chart sell where the upper Bollinger Band meets the previous swing high (buy the lower band at support), with a small stop beyond the level and at least five times the risk as the target.

- [E] Side: On the daily chart look at the 9-period moving average. "delee taaim phrem men naain peeriyad mooving evarej dekhanaa hai" (B_rkzkbbYlQ 04:00)
- [E] Side: Above it only longs, below it only shorts. "agar ye mooving evarej ke oopar hai to ham long jaate hain" (B_rkzkbbYlQ 04:15)
- [E] Entry chart: Then switch to the 1-hour chart and apply the Bollinger Band. "van ovar taaim phrem men shipht karo end bulinjaa baind ko inpleement karo" (B_rkzkbbYlQ 04:21)
- [E] Entry: Sell when the upper band is touched near the previous swing high. "sel hamako tab karanaa hai ye jo apar laain hai apar laain ko jab tach karegaa" (B_rkzkbbYlQ 04:57)
- [A] Entry: Default bands (20, 2) on the completed candle's close (side from the last completed day's close against its 9-day SMA); the last confirmed 1-hour swing (2-bar fractal) within half an ATR(14) of the band; a limit at the band for the next hour; one trade a day.
- [E] Stop: The stop goes 10-20 points beyond the resistance. "stop los besikalee rejistens ke oopar rakhanaa hotaa hai 10 20 point" (B_rkzkbbYlQ 08:49)
- [A] Stop: $15 beyond the swing or the band, whichever is farther.
- [E] Target: Risk-reward at least 1:5. "risk end rivord 1:5 minimam honaa chaahie" (B_rkzkbbYlQ 02:15)
- [E] Discipline: Do not take many trades an hour; wait hours for one. "1 ghante men paanch tred le liyaa aap" (B_rkzkbbYlQ 01:02)
- [A] Exit: Flat at 16:55 New York.

Code check: look-ahead ok, fills ok; 924 signals, 57 simulated fills on research data.

## PF-01 Claudia's 30-minute engulfing zone with a 5-minute two-highs confirmation
PropFirmTrader - https://youtu.be/fw9HYrSBVo0 (STEAL This INSANE 5-Minute Gold Trading Strategy ($325,000 Payouts))

A 30-minute engulfing candle sets the direction and its open-to-close body is the zone; drop to 5 minutes, wait for the pull back into it and a series of highs broken (lows for sells); stop below the pull back, target the previous higher-timeframe high.

- [E] Style: An intraday gold trader in and out in a few hours. "I'm an intraday trader, so I like getting in and out in a few hours" (fw9HYrSBVo0 00:04)
- [E] Setup: 30-minute bullish or bearish engulfing candles give the direction. "I decided to start using 30 minute bullish engulfing candles" (fw9HYrSBVo0 33:52)
- [E] Zone: Mark the engulfing candle's open and close; look for a trade inside. "I'll mark the engulfing candle open and the uh the candle close" (fw9HYrSBVo0 34:29)
- [E] Invalidation: If price comes below the candle's open there is no trade. "If it doesn't show that and it comes below the open, then there's no trade" (fw9HYrSBVo0 35:10)
- [E] Entry: She waits for a series of highs to break (lows for sells) on 5 minutes before entering. "I need a series of highs failing before I get in" (fw9HYrSBVo0 38:12)
- [I] Entry: For sells, two highs holding and two lows failing; buys are the mirror. "waiting for that series of two highs holding, two lows failing" (fw9HYrSBVo0 1:03:31)
- [A] Entry: After a 5-minute low touches the zone, two 5-minute closes above the high of the three bars before them, each at a new high; enter at the next open; the zone is watched for 8 hours.
- [E] Stop: Below the low. "With my stop loss below this low" (fw9HYrSBVo0 36:38)
- [E] Target: The previous higher-timeframe high. "I can target a previous higher time frame high on that one" (fw9HYrSBVo0 36:34)
- [A] Target: The highest high of the 12 thirty-minute bars before the engulfing candle if at least 1R away, else 2R.
- [E] Risk: At most 1% risk a trade. "I tend to risk 1% maximum per trade" (fw9HYrSBVo0 40:47)
- [E] Daily stop: Her daily lock leaves room for about three losses. "that gives me room for around three consecutive losses in a day" (fw9HYrSBVo0 44:20)

Code check: look-ahead ok, fills ok; 330 signals, 238 simulated fills on research data.

## MA-02 Daily Heikin Ashi direction, 1-hour no-wick Heikin Ashi entry, out on the colour change (swing)
The Moving Average - https://youtu.be/MKJz4yURCEs (How to Trade Gold - Ride Massive Trends Using this Method)

A swing method for gold: the daily chart gives the direction, 1-hour Heikin Ashi candles with no wick against the move and a strong body give the entry beyond daily resistance, and the trade is held until a Heikin Ashi candle of the opposite colour closes.

- [E] Direction: The daily chart gives the direction. "you need a daily time frame chart for direction" (MKJz4yURCEs 01:00)
- [A] Direction: The last completed day's Heikin Ashi candle: green for longs, red for shorts.
- [E] Entry chart: Entries on the 1-hour chart with Heikin Ashi candles. "looking at your 1 hour chart for entries using hikenashi candles" (MKJz4yURCEs 01:08)
- [E] Entry: A 1-hour Heikin Ashi candle closing with no bottom wick and a strong body. "the 1-hour hike and aashy candles closes with no bottom wick strong body size" (MKJz4yURCEs 05:16)
- [E] Entry: The breakout must be above daily resistance. "the breakouts must be above the daily resistance" (MKJz4yURCEs 05:14)
- [A] Entry: Strong body: larger than the average of the previous 10 Heikin Ashi bodies; daily resistance: the previous gold day's high (support: its low).
- [E] Entry: Enter once the candle closes. "you can enter in a trade once that candle closes" (MKJz4yURCEs 04:30)
- [E] Exit: Exit only when an opposite-colour Heikin Ashi candle closes. "exit only when an opposite color hyenashi candle closes" (MKJz4yURCEs 05:54)
- [A] Stop: No stop in the video: a far guard stop 2% away, and the position sized as if the stop were 1% away (a position about the size of the account).
- [I] Holding: Positions may be held for days (it is a swing method).

Code check: look-ahead ok, fills ok; 184 signals, 64 simulated fills on research data.

## MA-03 XAUUSD 5-minute scalp: smoothed MAs 21/50/200 and the three-line strike
The Moving Average - https://youtu.be/oDOCBTYgCQM (XAUUSD Scalping Strategy)

With the smoothed 21, 50 and 200 MAs fanned out in one direction and RSI on that side, three candles against the trend followed by a candle engulfing at least half of them is the entry; the stop is twice the engulfing candle and the exit an RSI divergence, within six candles.

- [E] Chart: The 5-minute chart. "the five minute is nice and quick" (oDOCBTYgCQM 02:36)
- [E] Trend: Smoothed moving averages 21, 50 and 200. "they are the 21 the 50 and the 200" (oDOCBTYgCQM 03:46)
- [E] Trend: Long above the 200 smoothed MA, short below it. "going long when it is above the 200 period smoothed moving average" (oDOCBTYgCQM 03:11)
- [E] Trend: The averages fanned out at a slope, never tangled and flat. "i want you to visually see these three moving averages fanned out at a nice slope" (oDOCBTYgCQM 03:38)
- [E] Trend: RSI above 50 for longs, below for shorts. "see if the price is below or above the 50 level on the rsi" (oDOCBTYgCQM 03:52)
- [A] Trend: Fanned: 21 > 50 > 200 (longs) and the 50 moved at least 0.05% over the last 12 bars; RSI(14).
- [E] Entry: Three candles against the trend, then an engulfing candle covering at least half of their move. "engulfing at least fifty percent of this move" (oDOCBTYgCQM 04:32)
- [E] Stop: Twice the engulfing candle's size. "usually i double the size of this engulfing candle for my stop loss" (oDOCBTYgCQM 05:10)
- [E] Exit: Exit on an RSI divergence. "when exiting a trade you are looking for an rsi divergence" (oDOCBTYgCQM 05:21)
- [E] Exit: At most six 5-minute candles in a trade. "a maximum of six five minute candles" (oDOCBTYgCQM 02:47)
- [A] Exit: Divergence: a close beyond the highest (lowest) close of the previous 10 bars with a lower (higher) RSI than at that close.

Code check: look-ahead ok, fills ok; 173 signals, 151 simulated fills on research data.

## MA-04 RSI leaves 70 / 30 and closes back inside: trade back toward the middle
The Moving Average - https://youtu.be/RJH-2TD1fZk (RSI Divergence (GOLD) Trading Strategy)

Shown on gold's 15-minute chart with the default RSI: wait for RSI to leave the 70/30 range and come back inside, then trade the turn with the stop beyond the swing.

- [E] Chart: Gold on the 15-minute chart. "This is gold US dollar on the 15-minute time frame" (RJH-2TD1fZk 02:54)
- [E] RSI: Default settings. "These are default settings" (RJH-2TD1fZk 03:07)
- [E] Entry: Wait for RSI to leave the 70/30 zone and come back inside. "I wait for the RSI to leave the 7030 zone Then I wait for it to come back inside that zone" (RJH-2TD1fZk 02:31)
- [A] Entry: RSI(14): sell at the next open after the first close back below 70, buy after the first close back above 30.
- [E] Stop: Beyond the previous swing. "Put your stop loss below the previous swing" (RJH-2TD1fZk 06:12)
- [A] Stop: The extreme price reached while RSI was beyond 70 (30), one tick past it.
- [A] Target: No target in the video (he drops the position tool): 2R. At most three trades a day; flat at 16:55 New York.

Code check: look-ahead ok, fills ok; 303 signals, 229 simulated fills on research data.

## TU-01 Previous day's high (low) swept after 8:30 New York, 5-minute fair value gap entry, 2R
TTrades - https://youtu.be/0R61Y6Pn74Q (CPI Gold Trade Review | ICT Market Maker Sell Model [MMXM])

His CPI gold trade: after 8:30 New York price sweeps the previous day's high and closes back lower on the hour; on 5 minutes he sells a fair value gap in the premium of the move, stop on the intermediate high, and takes 2R.

- [E] Time: Interest starts after 8:30 New York (the news release). "this is where my interest lies post 8:30" (0R61Y6Pn74Q 01:10)
- [E] Setup: The previous day's high is taken, then price closes lower. "we take our previous day's highs now we manipulate up and then we close lower" (0R61Y6Pn74Q 02:08)
- [A] Setup: An hourly candle starting 08:00-10:00 New York trades above the previous day's high and closes back inside the previous day's range (mirror for the low).
- [E] Entry: Wait for price to come back into the premium of the range. "I want to see price reach back up into a premium of the range" (0R61Y6Pn74Q 02:47)
- [E] Entry: Enter on the fair value gap. "look to take my entry on the fair value Gap" (0R61Y6Pn74Q 04:54)
- [A] Entry: A bearish 5-minute fair value gap (a candle's high below the low two candles before) whose top is above half of the range from the sweep high to the low made since; a limit at its lower edge for 30 minutes; before noon.
- [E] Stop: On the intermediate-term high. "My Stop on this intermediate term high" (0R61Y6Pn74Q 04:54)
- [A] Stop: The highest high since the low made after the sweep, one tick above.
- [E] Target: 2R. "I personally just went for 2 R here" (0R61Y6Pn74Q 05:09)

Code check: look-ahead ok, fills ok; 12 signals, 6 simulated fills on research data.

## TU-02 Fractal model scalp: hourly candle-2 closure, 5-minute change in the state of delivery, 2R
TTrades - https://youtu.be/eywpZT3z6GQ (TTrades Scalping Model - Simple Day Trading Strategy)

An hourly candle that sweeps the previous hour's high and closes back inside its range sets a bearish bias for the next hours; on 5 minutes a close through the run of up-close candles that made the high is the entry, stop on the high, 2R (mirror for longs).

- [E] Bias chart: For scalping the higher-timeframe candle is the hourly. "for scalping we're using much lower time frames. So, we're going to focus on the hourly chart" (eywpZT3z6GQ 00:29)
- [E] Bias: Candle 2 closure: price sweeps the previous candle's high and closes back inside its range. "price has swept out its previous candle high and then closed back inside the range" (CqMIh-Vvhbg 00:51)
- [E] Entry: A close through the series of up-close candles that made the high (change in the state of delivery). "we have closed through the series of up closed candles that have made this high" (CqMIh-Vvhbg 01:19)
- [A] Entry: In the next two hourly candles, a 5-minute close below the open of the first up-close candle of the run that made the highest high since the hour closed; next open; at most two a day.
- [E] Stop: Stop on the high, 2R. "my stop on the high and looking for 2 R" (CqMIh-Vvhbg 02:14)
- [E] Target: 2R in the scalping examples too. "Put my stop on the low and then be looking for 2 R" (eywpZT3z6GQ 04:34)
- [E] Time: He filters setups to the New York morning. "only interested in price in the New York session between 8 to 11:30" (CqMIh-Vvhbg 07:42)
- [A] Time: Entries 08:00-11:30 New York and in London's 02:00-05:00.

Code check: look-ahead ok, fills ok; 318 signals, 191 simulated fills on research data.

## CA-01 New York open: overnight volume profile against the developing session profile
Cammy Capital - https://youtu.be/J7XAKuYK5O4 (Use THIS Volume Profile Strategy on Market Open (Step by Step))

Build the overnight profile from 18:00 to 09:30 New York and the session's own from 09:30; at 10:00, if value has moved down and the overnight point of control is now the session's premium, sell at it with the stop behind it and target the session value area low (mirror for longs).

- [E] Overnight profile: The overnight profile starts at 6 pm. "start the profile from 6 pm" (J7XAKuYK5O4 00:51)
- [E] Value area: The value area holds 70% of the volume. "70% of the trading volume occurred is in the value area" (wH3ypUlgQXw 06:16)
- [E] Time: Let the session develop for half an hour; look for the setup from 10:00. "allow price to develop for at least half an hour. So 10:00 a.m. is when you can start to look for a trade setup" (J7XAKuYK5O4 02:26)
- [E] Entry: Short at the overnight fair value when it sits at the session's value high. "we can take that short position on the overnight fair value and right on the current sessions value high" (J7XAKuYK5O4 03:56)
- [A] Entry: At 10:00: the session point of control below the overnight one and the overnight one in the top quarter of the session value area or above it; a limit at the overnight point of control until 11:30 (mirror for longs). Profiles from Delta's own XAUTUSD volume in 50-cent bins.
- [E] Stop: Behind the high-volume node. "Set your stop loss somewhere behind that high volume node" (J7XAKuYK5O4 04:15)
- [A] Stop: Half the session value area's width beyond the entry, at least $1.50.
- [E] Target: The value area low of the developing session profile. "I personally would only be targeting the value area low of the current session's developing profile" (J7XAKuYK5O4 04:42)
- [A] Target: Skipped when the target is less than 1R away.

Code check: look-ahead ok, fills ok; 100 signals, 24 simulated fills on research data.

## CA-02 Yesterday's premium is today's discount: previous value area high meets today's value area low
Cammy Capital - https://youtu.be/-_1Pf652IJk (Finding an A+ Volume Profile Trade Setup Every Day)

Draw the previous regular session's profile (9:30-16:00). When the session holds above yesterday's fair value and its own value area low rises to yesterday's value area high, buy that overlap; stop near yesterday's point of control; target the session value area high (mirror for shorts).

- [E] Previous profile: The most recent regular session, 9:30 to 4 pm. "Thursday 9:30 through to 400 p.m." (-_1Pf652IJk 01:22)
- [E] Entry: Yesterday's premium price is today's discount price: buy there. "what was yesterday's premium price is today's discount price" (-_1Pf652IJk 05:28)
- [A] Entry: The session (overnight from 18:00, regular from 09:30) opened at or above yesterday's point of control; its developing value area low within a quarter of yesterday's value-area width of yesterday's value area high; a limit at that high for 30 minutes; one a day.
- [E] Stop: Near yesterday's fair value. "I would have my stop loss personally right down here just near fair value again" (-_1Pf652IJk 05:34)
- [E] Target: No higher than the session's value area high. "I personally wouldn't set my take-profit target any higher than the current session's value area high" (-_1Pf652IJk 05:56)
- [A] Target: Skipped when that target is less than 1R away.

Code check: look-ahead ok, fills ok; 70 signals, 17 simulated fills on research data.

## HF-01 Sweep, break, retest in the 1-hour trend (London and New York kill zones)
HANNAH FOREX - https://youtu.be/zt9TmyI5-z0 (I Made 13% in ONE WEEK Trading Metals (The Mindset Shift That Changed Everything))

Her SBR model on metals: price sweeps liquidity below a low, breaks the internal high, and the retest into a discount array is bought toward the next liquidity, with the stop under the sweep (mirror for shorts).

- [E] Model: Sweep, break and retest. "it's all about the sweep, the break, and retest" (zt9TmyI5-z0 00:27)
- [E] Trend: The 1-hour trend agrees. "if I just go on the 1 hour real quick, you guys can see that we've pretty much been bullish this whole time" (zt9TmyI5-z0 02:00)
- [A] Trend: Bullish: the last two confirmed 1-hour swing highs and lows both higher (bearish: both lower).
- [E] Entry: Then a retest into a premium or discount array. "I would look for a retest in some sort of premium discount array" (zt9TmyI5-z0 00:47)
- [A] Entry: A 5-minute low below the last confirmed 5-minute swing low, then within an hour a close above the last swing high, then a limit at half of the leg from the sweep low to the high, for an hour.
- [E] Time: Kill zone timing: sweep, then a clear break. "kill zone timing, sweep, followed by a clear break" (6cUsfbpU1G4 04:38)
- [A] Time: The sweep inside 02:00-05:00 or 07:00-10:00 New York.
- [E] Stop: Under the lows that should hold. "with my stop-loss placement, the theory here is if we are going to the upside, these lows should hold" (zt9TmyI5-z0 02:56)
- [A] Target: The last confirmed 1-hour swing high (the draw on liquidity) if at least 1.5R away, else 2R.

Code check: look-ahead ok, fills ok; 115 signals, 58 simulated fills on research data.

## RU-10 Donchian Channel with the 200 moving average, 1.5R
TRADING RUSH - https://youtu.be/icYe2SS3-4M (TESTING Best Trend Following Strategy Ever 100 TIMES - Donchian Channels)

His tested Donchian version: only longs above the 200-period moving average; buy when the upper band makes a new high after the lower band made a new low, stop just below the lower band, 1.5 times the risk (mirror for shorts).

- [E] Trend: The 200-period moving average filters the signals. "I have used the 200 period moving average" (icYe2SS3-4M 02:27)
- [E] Entry: Buy when the upper band makes a new high after the lower band made a lower low. "the long entry signal is when, the upper band makes a new higher high, after lower band" (icYe2SS3-4M 02:47)
- [E] Stop: Just below the lower band. "set your stoploss just below the lower band" (icYe2SS3-4M 02:55)
- [E] Target: 1.5 times the risk. "I was using a 1.5 to 1 reward risk ratio" (icYe2SS3-4M 06:45)
- [E] Chart: Tested on 30-minute charts. "on the 30 minutes timeframe" (icYe2SS3-4M 04:41)
- [E] Skip: Skip a trade whose stop is far from the entry. "you can simply skip that trade" (icYe2SS3-4M 05:38)
- [A] Settings: Donchian length 20 (TradingView's default), the 200 EMA, 'far' = more than 3 ATR(14); flat at 16:55 New York.

Code check: look-ahead ok, fills ok; 30 signals, 27 simulated fills on research data.

## TQ-05 Triple Supertrend with the Stochastic RSI and the 200 EMA, 1.5R
Trade Pro - https://youtu.be/HpNZ2VpZzSE (HIGHEST PROFIT Triple Supertrend Trading Strategy Proven 100 Trade Results)

Longs only above the 200 EMA when the Stochastic RSI crosses up out of oversold with at least two of three Supertrends below price; the stop goes at the second Supertrend line, the target 1.5 times the risk (mirror for shorts).

- [E] Settings: Stochastic RSI default 3, 3, 14, 14. "settings are default 3 3" (HpNZ2VpZzSE 01:22)
- [E] Settings: Supertrends 12/3, 11/2 and 10/1. "the settings are 12 and three" (HpNZ2VpZzSE 01:50)
- [E] Trend: Shorts only under the 200 EMA (longs only over it). "you can only take short positions when price is under the 200 ema" (HpNZ2VpZzSE 02:30)
- [E] Entry: Long when the Stochastic RSI goes below 20 and crosses up. "you can only take a long when stochastic rsi goes oversold below the 20 line and then crosses up" (HpNZ2VpZzSE 02:56)
- [E] Confirmation: At least two Supertrend lines on the trade's side. "having at least two of their lines above the price" (HpNZ2VpZzSE 03:11)
- [E] Stop: At the second Supertrend line, never the closest. "you're never going to have it placed at the closest super trend line" (HpNZ2VpZzSE 06:31)
- [E] Target: 1.5 times the risk. "targeting 1.5 times the risk" (HpNZ2VpZzSE 03:41)
- [E] Chart: Tested on the 1-hour chart. "euro against the us dollar one hour time frame" (HpNZ2VpZzSE 08:12)
- [A] Entry: A late second Supertrend still counts while the Stochastic RSI has not passed 50; flat at 16:55 New York.

Code check: look-ahead ok, fills ok; 91 signals, 68 simulated fills on research data.

## Not coded

- AF-05 Failed extension below the morning low, a 30-minute close back above, target the weekly profile (Axia Futures): duplicate - the same mechanics as BO-02 (a key low traded through, then a close back above, bought)
- AF-06 Front-runners of a large resting order trapped; buy the continuation (Axia Futures): blocked - read from the depth of market (resting order sizes on the ladder); the desk has 1-minute candles only
- BO-03 Gold scalps from delta absorption and big trades (BikoTrading | Futures Trading): blocked - needs every trade's aggressor side and size (delta, big trades); the desk records no trade feed for gold
- AT-02 Gold with order flow and the GEX (options gamma) profile (ATAS): duplicate - presented by BikoTrading's Yuriy: the price part is BO-01's anchored VWAP; the GEX profile and big trades need data the desk lacks
- FR-01 Demand zone at the strong low after a break of structure, with rough pullbacks (Fractal Flow - Pro Trading Strategies): concept - teaches the idea and says these concepts are not mechanical; no entry, stop or target rule
- PF-02 Price trap: 1-minute refined zones in a consolidation, alerts, sweep to sweep (PropFirmTrader): concept - discretionary refinement of a range trade with alerts; its sweep back inside repeats BO-02
- CA-03 15-30-second scalps from high-volume nodes with the DOM and cumulative delta, 2-4 ticks (Cammy Capital): blocked - needs sub-minute bars, the order book and cumulative delta
- RU-11 Reward-to-risk comparison on the Schaff Trend Cycle strategy (1.5R chosen) (TRADING RUSH): concept - a test of target sizes on a strategy defined in another video; its finding (1.5R) is RU-10's target
- VA-01 Footprint reading: strong bids at new highs, stacked imbalances, exhaustion (Orderflows (Michael Valtos)): blocked - needs bid and ask volume at every price (footprint); the desk has 1-minute candles only
- JG-01 Order flow in thin markets; reversals and breakouts read from the tape (Jigsaw Trading): blocked - needs the order book and the time and sales tape
- OF-03 Breakouts confirmed on footprint charts (Optimus Futures): blocked - the confirmation needs footprint data; the micro-gold guide the list mentions is not on the channel's YouTube uploads
- NT-03 DiNapoli MACD predictor, stop grabber and highlight bars on gold (NinjaTrader): blocked - built on paid proprietary indicators whose formulas are not shown
- NT-04 Small traders' COT net position at extremes as a contrarian gold signal (NinjaTrader): blocked - needs the weekly CFTC Commitment of Traders report, and its signals last weeks (not intraday)
- NT-05 Order flow for precious metals (NinjaTrader): blocked - needs delta and the footprint
- MA-05 Aurora gold signals and automation (The Moving Average): blocked - a paid closed system; its rules are not shown
- UK-03 Hold a catalyst move while gold stays beyond the 1-minute 10-period MA (UKspreadbetting): concept - an exit idea with no entry rule
- UK-04 15-minute fake-out below the range, stop under the low (UKspreadbetting): duplicate - the false breakout of BO-02
