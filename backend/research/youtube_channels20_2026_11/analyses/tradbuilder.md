# TradBuilder (@TradBuilder, UCIaCP4uF4NpYXnx1Nq7JK-Q)

Hindi with English subtitles; NIFTY option strategies with spreadsheet backtests shown on screen (claims, not
verified). Tags: **[E]** stated, **[I]** inferred, **[A]** research assumption.

## TB-01 NIFTY 15-minute two-colour pair: the next candle(s) close below the pair's low -> short, stop at the pair's high, 1:3: 5g3nGHlhpv0
"Intraday Strategy with Backtest || 1:3 Risk To Reward" (2026-08-11, 13:28), https://youtu.be/5g3nGHlhpv0
- NIFTY, 15 minutes [E 00:00-01:00]. Find two consecutive candles of different colours (red + green or green + red);
  mark the high and low of the pair [E 01:00-02:00].
- If one of the next two candles closes below the pair's low -> short at that close; stop = the pair's high (on the
  live price, not a close); target 1:3; otherwise out at the day's end [E 02:00-05:00, 05:00-07:00].
- Short only - his long-side backtest was not attractive [E 02:00]. His sheet: Dec 2024 - Apr 2026, 399 short trades,
  average +6.18 NIFTY points a trade [E 10:00-11:30] (claims).
- Code [A]: NIFTY 15-minute; the pair can form any time from 09:15; first qualifying break of the day only; entry at
  the next bar open; stop = pair high (intrabar); target 3R; exit 15:15 (the desk's NIFTY exit; his 15:29).
- Status: ready (explicit; one trade a day assumed).

## TB-02 NIFTY 5-minute range of the 2nd and 3rd candles: close beyond -> trade, stop at the far edge, reverse once, hold to the close: tOaifCp0K-A
"Easiest Intraday Strategy || 1:4 Risk to Reward" (2026-07-09, 10:24), https://youtu.be/tOaifCp0K-A
- 5 minutes; skip the first (09:15) candle; range = high and low of the 09:20 and 09:25 candles [E 01:00-03:00].
- A 5-minute close above the range -> long (he sells a put); close below -> short; stop = the range's other edge; no
  fixed target - hold to 15:29 [E 03:00-04:00, 05:00]. If stopped and price closes beyond the other edge, take the
  opposite trade (two trades a day at most) [E 05:00-06:00]. "1:4" in the title is his average win/loss (claim).
- Code [A]: NIFTY 5-minute index proxy; entry next bar open after the close; stop on the live price at the other edge;
  reverse once on a close beyond the other edge; exit 15:15.
- Relation: AX-03 uses the 2nd/3rd 15-minute candles with a 25-point target - different - kept.
- Status: ready.

## TB-03 NIFTY weekly call sold at 09:25 (premium nearest Rs 30), 8-point stop, re-entry at cost, out 15:25: H6snDCl6iR0 - **blocked**
"7+ Years Backtested Data || Nifty Intraday Algo Strategy" (2026-02-10, 10:45), https://youtu.be/H6snDCl6iR0
- AlgoTest set-up: sell the weekly NIFTY call whose premium is closest to Rs 30 at 09:25; stop at Rs 38 (8 points);
  re-enter at cost after a stop; exit 15:25; best on expiry day (0 DTE) [E 00:00-05:00]. His sheet: 2019-2026, 66%
  winners, max drawdown 6.11% (claims) [E 05:00].
- Premium-based option selling - needs NIFTY option premiums by strike (history and live) that the desk does not have. Not coded.

## TB-04 NIFTY daily EMA 9 / EMA 20 cross, long only, exit on the opposite cross: -bWn7r2t2PQ
"9 & 20 EMA Strategy || 16 Years Backtest || Honest Review" (2026-10-24, 15:52), https://youtu.be/-bWn7r2t2PQ
- NIFTY daily; long when EMA 9 crosses above EMA 20, entry at that day's close; hold until EMA 9 crosses back below,
  exit at that close; long only [E 01:00-05:00]. His 16-year sheet: 86 trades, ~11-12% a year before costs - "no better
  than buying NIFTY" (his own verdict); waiting for a pullback after the cross is an untested idea [E 05:00-12:00].
- Code: NIFTY daily (desk NIFTY_D) [E]; entry at the next open [I: the desk cannot fill at the signal close]; R unit
  = 3% of entry for reporting [A]; no stop beyond the cross exit.
- Status: ready.

## TB-05 SENSEX weekly call bought at 14:30 (premium >= Rs 100), 10% stop trailed 1:1, out 15:25: gXhm3UI0aT8 - **blocked**
"Option Buying Strategy || 4 Years Backtest || Less Screentime" (2026-09-24, 11:06), https://youtu.be/gXhm3UI0aT8
- Premium-based (strike chosen by premium, stop and trail in premium %); his sheet: 38% winners, drawdowns up to 175%
  of the margin on 0 DTE [E]. Needs SENSEX option premiums - blocked.

## TB-06 NIFTY 1-minute ADX(14) above 50 before 10:00 -> buy the ATM straddle, Rs 30k target / Rs 20k stop on 10 lots: v0IUgWuqn-g - **blocked**
"Intraday ADX Strategy || Option Buying Setup || 3 Years Backtest" (2026-10-27, 11:42), https://youtu.be/v0IUgWuqn-g
- ADX 14 / DI 14; when ADX crosses above 50 between 09:15 and 10:00 buy the ATM call and put (long straddle); exits on
  the combined P&L target / stop or 15:25; no trade on expiry day [E 00:00-07:00].
- A straddle priced in premiums - blocked for the same reason.

## TB-07 Intraday rolling short straddle from 10:00 with leg-wise re-entries and a combined Rs 15k target / stop: U0df-RTI5tg - **blocked**
"Intraday Rolling Straddle Strategy || 6 Years Backtested Data" (2026-10-20, 11:38), https://youtu.be/U0df-RTI5tg
- Sell the ATM call and put at 10:00; when a leg's stop hits, wait 15 minutes and sell a fresh ATM straddle; combined
  target and stop; out 15:25 [E 00:00-06:00]. Option selling on premiums - blocked.

## TradBuilder summary
Coded: TB-01, TB-02, TB-04. Blocked (option premiums needed): TB-03, TB-05, TB-06, TB-07.
