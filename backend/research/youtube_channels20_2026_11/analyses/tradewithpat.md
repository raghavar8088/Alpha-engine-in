# Trade with Pat (@TradewithPat, UC04-HvUvHG4hpMnQx07ObYQ)

English; forex, gold and US index futures scalping and day trading; most videos show TradingView backtests and
"tested N times" claims (taken as claims only). Tags: **[E]** stated, **[I]** inferred from the chart demonstration,
**[A]** research assumption needed to code it.

## TP-01 Gold range trading: support + impulsive FVG + discount below 50% + EMA 200: kbacCLdZs7w
"Ultimate GOLD Trading Strategy for 2026 (3 Simple Concepts)" (2025-12-16, 13:43), https://youtu.be/kbacCLdZs7w

- Market: XAUUSD; works on H1 and M5 [E 07:00-08:00]. Buys only while price is above the 200-period EMA (gold uptrend)
  [E 04:00, 05:31-06:00].
- Concept 1, range: mark support and resistance; trade inside the range, expect support to hold [E 00:00-01:30].
- Concept 2, fair value gap: an impulsive move off support leaves a bullish FVG (3-candle gap); enter when price
  comes back into it [E 05:31-08:00].
- Concept 3, discount: Fibonacci from the swing low to the swing high of the impulse; enter only below the 50% level
  [E 09:34-11:00].
- Exits: first partial (about 30%) at the top of the latest pullback / first level, then stop to break-even; the rest
  to the range resistance (exits there manually) [E 04:00-05:00, 11:00-12:30]. Stop level not stated (below support) [I].
- Code (H1 and M5 books) [A]: support = a level where at least two confirmed swing lows (fractal n=3) in the last 150
  bars sit within 0.25 ATR(14); impulse = a 3-bar bullish FVG whose middle bar's range >= 1.5 ATR, formed within 1 ATR
  of support; the swing high = the highest high from the FVG until the first tap; entry = limit at the FVG top only if
  that price is below the 50% level of (support low -> swing high); stop = below the FVG's first bar low and the
  support, 0.1 ATR buffer; TP1 = the swing high, 30% off, stop to entry; TP2 = the highest swing high of the last 150
  bars (range top), at least 2R; FVG valid for 48 bars; one position at a time; close at the 17:00 New York gold session
  end for the M5 book, H1 book holds overnight.
- Status: ready with documented assumptions (support and range are chosen by eye in the video).

## TP-02 Gold 5-minute: level, liquidity sweep, minor trend-line break on a big candle, EMA 200 side: QCJZc3iAKgk
"Ultimate GOLD Trading Strategy (1000+ Pips Per Week)" (2026-06-25, 10:32), https://youtu.be/QCJZc3iAKgk

- Market: XAUUSD, entries on 5 minutes [E 02:00]. Side from the 200-period EMA (below = sells, above = buys) [E 01:00-02:36].
- Concept 1: a support / resistance box where price exploded from; it becomes a level after a second push [E 00:40-03:00].
- Concept 2: wait for the liquidity sweep beyond the obvious level (stops taken) before entering [E 02:36-05:00].
- Concept 3: then a break of the minor trend line (swing high -> pullback, one or two touches) on a big candle (an
  "ATR candle"), enter on the break or on the pullback into the zone [E 05:00-07:25, 08:00-10:00].
- Stop: beyond the sweep wick [E 06:00]; target: the next obvious opposite level [E 03:00, 06:00].
- Relation: liquidity-sweep-then-structure-break family (the library has it on NIFTY: D9 and its 22 versions; on BTC:
  NJ-31 with a 5-minute engulfing). This one is on gold with an EMA 200 side and a trend-line-break entry, so the
  market and the entry differ - kept as a variant.
- Code [A]: XAUUSD 5-minute; side = close vs EMA 200; level = a cluster of at least two confirmed 5-minute swing
  highs (lows) within 0.25 ATR(14) in the last 150 bars; sweep = a bar trades beyond the level and closes back on
  the near side; minor trend line = the line through the last two confirmed swing lows (highs) of the push into the
  sweep (fractal n=2); break = a close through that line with a bar range >= 1.2 ATR within 12 bars of the sweep;
  entry next bar open; stop = sweep extreme + 0.1 ATR; target = the next opposite level, at least 2R (2R if none);
  exit 16:55 New York.
- Status: ready with documented assumptions.

## TP-03 Asian range -> London push -> New York reversal, entered on the 9:30-9:45 New York ORB + FVG + engulfing: Bdgev1or-7M
"My BEST 5 Minute Scalping Strategy (330 Backtests)" (2026-03-03, 10:44), https://youtu.be/Bdgev1or-7M

- Timeframe 5 minutes; examples on EURUSD; trades only in the New York session [E 00:41-01:08, 04:15].
- Step 1, direction (AMD): a tight Asian range (accumulation), an aggressive London push that sweeps the Asian high or
  low (manipulation), then expect the New York session to reverse the other way (distribution) [E 01:08-04:00]. Asian
  range too wide, or no aggressive London push -> no trade that day [E 02:00].
- Step 2, three entry models, all with a bullish (bearish) engulfing confirmation [E 04:09-10:00]: (1) a support /
  resistance level that held after the London sweep; (2) a demand / supply zone (the candle before an impulse with a
  FVG); (3) favourite: the New York opening range 9:30-9:45 (first three 5-minute candles), a candle close beyond it in
  the reversal direction, then a pullback into the FVG / demand and an engulfing candle; stop below the FVG; target
  about 1:2 or the next supply / resistance [E 08:07-10:00].
- Their backtest (stated): 330 trades, models at 72%, 77%, 86% winners [E 00:00] (not verified).
- Code (model 3 only - the one with fixed times) [A]: Asian range 00:00-06:00 UTC; tight = its width below the median of
  its previous 20 sessions; London push = between 07:00 and 12:00 UTC price trades beyond one side of the Asian range by
  at least 30% of its width and closes the window on that side; New York side = opposite to the push; NY ORB = the three
  5-minute bars from 09:30 New York time; break = a 5-minute close beyond the ORB on the NY side; entry = the first
  engulfing candle in that direction whose low (high) touches the break's FVG or the ORB edge, within 90 minutes of the
  break; stop beyond the FVG's far edge (or the engulfing candle), 0.1 ATR buffer; target 2R; exit by 16:00 New York.
- Markets: XAUUSD (Pat's main market) and BTC [A: the video's examples are EURUSD].
- Status: ready with documented assumptions.

### TP-03 second source (same strategy, merged): E3McKlAp3qk
"The ONLY Day Trading Strategy I'll use ALL 2026 (Backtested 1000 Times)" (2026-02-17, 12:18), https://youtu.be/E3McKlAp3qk
- Same displacement ORB: the first 15-minute candle of the NYSE open (9:30-9:45 New York), then on 5 minutes an
  impulsive candle close out of it (wicks do not count) with 3-4 big candles, a broken recent high and a FVG / demand
  zone (the last opposite candle before the push) [E 01:00-03:00, 04:00-05:00].
- Entry when price returns to the demand / FVG and prints an engulfing candle (or the zone simply holds); stop below the
  demand (or the FVG midline); target 1.5-2R or about 2% [E 02:00-05:00, 10:00-11:00].
- Session analysis: Asian range, London push, New York reversal; when London sweeps both sides of the Asian range,
  expect continuation instead [E 05:49-09:30]. Claimed backtest: 1,000 trades, 79.45% winners [E 00:41].
- Merged into TP-03 (adds the both-sides-swept continuation rule and the 3-big-candle displacement test) - counted as a
  duplicate video of the same strategy.

## TP-04 New York 15-minute ORB: 5-minute close out of it, limit entry at range top / midline / bottom by impulse strength: deymRD3kSD0
"My Open Range Break Out Trading Strategy is UNSTOPPABLE (15 Minute ORB)" (2025-10-23, 12:42), https://youtu.be/deymRD3kSD0

- Range: the 9:30 New York 15-minute candle (NYSE open), high and low with wicks [E 00:48-01:00]. "Works for forex,
  futures, indices, crypto, everything" [E description].
- Direction: the first 5-minute candle close above (below) the range [E 01:00].
- Entry by impulse strength: very impulsive break -> buy at the range top; medium -> the range midline; weak -> the range
  bottom; better still a demand zone (the candle before 3+ big candles with FVGs) near that level [E 02:18-04:00, 06:00-07:00].
  Wait for a candle to close inside the demand and react before entering [E 04:00, 07:00].
- Stop: below the range bottom and below the demand [E 03:00-04:00]. Target: recent price (the high of the impulse) /
  next level; R:R about 2-2.7 [E 03:00-04:00]. A trailing-stop indicator on counter-trend runs [E 10:00-12:00] (not coded).
- Rules: no massive opening range; avoid entering on huge candles; earlier is better - nothing after 12:00 Eastern
  [E 04:42-05:00]. Confluence: with the EMA 200 trend, entry below the 50% Fibonacci of the swing [E 05:00-07:30].
- Code [A]: XAUUSD and BTC 5-minute; skip days whose opening range is wider than 1.5x its 20-session median; strength =
  (furthest extension beyond the range edge during the break bar and the next 2 bars) / range width: >= 1.0 strong
  (limit at the range edge), 0.5-1.0 medium (limit at the midline), < 0.5 weak (limit at the far edge + 10% of width);
  stop = 0.1 ATR beyond the far edge; target = the impulse extreme, at least 1.5R; orders live until 12:00 New York;
  exit 16:00 New York.
- Relation: same opening range as TP-03 but no session filter and a different, level-based entry and stop - kept as a
  separate variant.
- Status: ready with documented assumptions.

## TP-05 "9:30 AM candle" displacement ORB without the session filter: DmRFA0cZ0C8
"My 3 Step "9:30AM Candle" Scalping Strategy (5 Minute Chart)" (2026-01-27, 10:45), https://youtu.be/DmRFA0cZ0C8

- Used on forex, futures, gold and crypto [E description, 00:00]. Range: the first 15-minute candle at 9:30 New York
  [E 00:51-01:00]. Direction: a 5-minute break and close beyond it [E 01:00].
- Basic version (enter on the break close, stop beyond the break candle's wick, ~1:1) = 48% win in his test; with his
  rules 81% (claims) [E 00:31, 02:00]. Problems to avoid: fake / weak breakouts, trading every breakout, trading into a
  higher-timeframe level [E 02:26-04:00].
- Entry models: (1) displacement = several big-bodied, small-wick candles creating a demand zone; wait for price to
  return to it and a bullish engulfing, enter at that candle's close; (2) the same with a fair value gap instead of the
  demand zone [E 04:14-09:00]. Stop below the demand / below the FVG midline; target about 2% or the last level where
  price pushed down hard (1:2-1:3); stop to break-even and 20-30% off at a minor resistance [E 06:00-10:00].
- Code: the TP-03 displacement-ORB engine without the Asian/London direction filter (both sides allowed, first valid
  setup of the day) [A]; target 2R [A: "about 2%" is a price target on futures; 2R keeps it scale-free]; one trade a day.
- Relation: a filter variant of TP-03 (kept separate because the direction filter is removed).
- Status: ready with documented assumptions.

### TP-04 second source (same strategy, merged): OkwrhkWfFC0
"If I Could Only Trade ONE 5 Minute Scalping Strategy, It'd Be This" (2026-10-18, 14:20), https://youtu.be/OkwrhkWfFC0
- Same 9:30-9:45 New York range and 5-minute break-and-close direction [E 02:54-04:42]; the entry is a limit at a
  "common-sense level": a flip zone (old support/resistance that broke and now holds from the other side) or a demand
  zone of 3 big candles; stop below the range; target the recent high; half off and break-even at 1R [E 04:42-09:00].
  Shown on gold, mostly sells with the higher-timeframe downtrend [E 10:06-12:00].
- Merged into TP-04 (adds the flip-zone level; TP-04's code keeps the range-level entry) - counted as a duplicate video.

## Trade with Pat summary
Coded: TP-01 to TP-05 (TP-02 is a gold variant of the liquidity-sweep family). Videos merged as second
sources: E3McKlAp3qk (TP-03), OkwrhkWfFC0 (TP-04).
