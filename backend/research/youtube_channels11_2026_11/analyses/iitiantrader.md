# IITian Trader (Saurabh, @iitiantrader): video analyses

Tags as in neerajjoshi.md: E = stated or shown; I = inferred; A = research assumption. Times HH:MM:SS.

## Crypto videos built on liquidation data: not reproducible

Most of his crypto strategies read third-party derivatives data: CoinGlass liquidation heatmaps and "max pain"
levels (the price where most long or short stops sit, with the dollar amount: e.g. 34 million long stops 300 points
below, 30 million short stops 2,000 points above; trade toward the nearer pool, 0jzwrqtzeiU 00:00:30-00:04:30),
12/24-hour long vs short liquidation totals, the long/short ratio and a market-wide average RSI (1w2WL4VGsEE
00:08:00-00:11:30). The desk records only Delta's own trades and candles, and no historical record of those
liquidation maps is available to it, so these cannot be tested or paper traded faithfully: 0jzwrqtzeiU (distance /
max pain), zhCyKBzUopk (max pain part 2), 1w2WL4VGsEE (liquidity concept), and any of the videos below that turn out
to depend on the same data are marked as such.

d--zlXbSWUA (gold scalping, beginner to pro, 9 Sep 2026, 23 min): the session's volume profile (value-area high/low,
point of control; below the POC sellers dominate and price tends to visit the value-area low; outside the value area =
overbought/oversold), 1-hour momentum areas, and a sell shown with a $17 stop and a 1:1 first target, trailing the stop
to 50% of the open profit. The entry trigger is his reading of the chart: not defined well enough to test (Brad Goh's
English video of the same title is analysed separately).

## Indian-market videos

E7o6WmS4TPM (scalping master class ep. 11, 9 Apr 2023, 38 min) and GUKg_sTMwGk (scalping master setup, 3 Aug 2023,
22 min): BankNifty futures on 3 minutes, at most three scalps a day, rectangles at support/resistance from volume and
pivot points, trailing stops, avoid 09:15-09:30, after a gap wait 5 minutes and for a retest. Discretionary levels:
not implemented. Xa0m_ytnDW4 ("3 candles secrets", 23 Jul 2023): candle-psychology patterns (after a breakout candle
wait for the stop-hunting candle; a "zig-zag" morning set-up with targets equal to a candle's length) described with
"big" and "small" candles only: not defined well enough. -ogElzwPKeo (strategy for new traders, 3.7M views): paper
trade 2-4 months, one trade a day, risk-reward first: advice, no strategy. 9Nvljrq0dQc (gap up/down options, ep. 7):
a BankNifty gap of 250+ points from the previous close is "significant"; read the previous 3 days of FII positions;
then the trader's judgment: not implemented.

## IT-01 BankNifty first 5-minute candle theory (TDQW8QUZ6LY, ep. 6, 4 Mar 2023, 14 min: "4 time slots")

Read the first slot in full (digest).

- Slots (E 00:01:30-00:02:00): pre-open 09:00-09:08, settle 09:08-09:15, the open 09:15; 09:15-09:20 is the volatile
  first 5-minute candle (BankNifty moves 100+ points in it).
- First candle theory (E 00:02:30-00:04:30): if the first 5-minute candle is green with its body at the top and its
  wick below (a very small upper wick is fine), buy calls at the open of the second candle with the first candle's low
  as the stop; a red candle with the body at the bottom and its wick above is the mirror (puts, stop at its high). On
  a losing day the loss is small; on a winning day hold the profit until 15:15. Only for traders who can take the
  risk of entering on the second candle's open.
- After 10:30 (E 00:05:30-00:06:00): trade support/resistance from the morning's structure: discretionary, not part of
  IT-01.
- A: BANKNIFTY; "body at the top" = green with the upper wick at most 20% of the candle's range and the body at least
  40% of it; enter at 09:20; stop at the first candle's low (high); exit at 15:15; one trade a day.

## IT-02 The "room" strategy: EMA 45 trend, EMA 9/11 entry, a second lot one room away (KaGCRCXVOVc, 11 May 2024,
21 min; Nze7_u29y9k, 7 Dec 2024; QfLoyBl5YNs, 22 Oct 2025)

Market: crypto first (bitcoin), also NIFTY/BANKNIFTY; 15-minute candles (E 00:03:00-00:04:30). Read the rule parts in
full.

- Trend (E 00:06:00-00:08:00): EMA 45 is the "big brother", the trend decider; EMA 9 and EMA 11 are the "little
  brothers": their cross (or price near it) is the entry point. When the little brothers run against the big brother
  they come back to his direction: trade only in EMA 45's direction (E 00:12:00).
- Sizing (E 00:08:00-00:10:00): put in only part of the planned money first (10%, then 25%: 35% of the fund in all).
- The room (E 00:12:00-00:16:00): BTC 15-minute candles span 300-400 points, so the second lot goes 300 points away
  against the first (NIFTY about 30 points, BANKNIFTY 80-90). Example: sell 0.5 lot at 60,750, then a limit to sell
  1 lot 300 points higher; that is the maximum size.
- Exit (E 00:16:00): once both are in, the average sits near the second entry; put the stop 200-300 points beyond the
  average; if price comes back, take the target. A losing first lot is not averaged forever: two entries only (E
  00:02:00).
- A: BTCUSD 15-minute; trend up = close above EMA 45 and EMA 45 rising over 4 candles; entry = EMA 9 crossing above
  EMA 11 (back in the trend's direction) while the trend holds; lot 1 (one third of the size) at the next open; lot 2
  (two thirds) on a limit one room against it, room = ATR 14 of the 15-minute candles (his 300 points was about one
  candle's range); stop 0.8 room beyond the average once both are in (1.8 rooms from lot 1 if only lot 1 fills);
  target one room in favour of the average (of lot 1 alone if lot 2 never fills); time stop 48 candles; one position
  at a time. Simulated as a two-lot trade with a weighted result.

The other crypto videos (QfLoyBl5YNs, 6rc19A3AgnY, aVUFnXN_D2s, k805sEB58YU, 615D-5qOtag) are trade journals,
liquidity/heat-map reading and money management; zO_VOqEwqxk (base strategy + Fibonacci), fN8E6oLjuY0 (hidden
accumulation zones), 4z-S6Cp8mDc and PlqCP0d5DsM (trap / fake-breakout trading) are discretionary; qz345WaXKPs and
RnpUmpjEsN0 (D+T: FII/pro positions plus time zones) need NSE participant-wise open interest, which the desk does not
load. None is implemented.

Desk markets: IT-01 BANKNIFTY; IT-02 BTCUSD.
