# Method: how the strategies were found and tested

## Data: real MCX prices, not a model
- MCX's own daily **bhavcopy**, pulled from mcxindia.com on 2026-10-22. It covers every option
  contract on CRUDEOIL, CRUDEOILM, NATURALGAS and NATGASMINI across its whole listed life,
  plus the futures each option month is written on: 463 contracts, about 2 million option rows.
- Each row is one strike, one type, one day: open, high, low, close, lots traded and open
  interest.
- Mini options only began in mid-2024: CRUDEOILM's first option expiry was 14 Jun 2024 and
  NATGASMINI's was 24 May 2024. Their parents are the same underlying with the same expiry
  dates (32 of 32 for both), so the parents' longer history was used to SEARCH. The minis'
  own prices were used to JUDGE.

## Checks on the data before any strategy was run
- **Tick sizes** were read from the price grid itself.
- **Put-call parity** against the mapped future: the median gap was 0.05-0.08%. This
  confirms each option month is matched to the right futures contract.
- **Mini vs parent premiums:** the minis' closes are typically within ~2% of the parent's
  for the same strike and day.
- **Liquidity on every entry day:** Crude Oil Mini has about 33-39 traded strikes within
  ±10% of the future; Natural Gas Mini about 20-22.

## Pre-registration
`PROTOCOL.md` (sha256 `93306f5c…79c2cb`) fixed everything before any result was computed:
- the strategy grid;
- the cost and fill model;
- the discovery and validation periods;
- every selection rule.

`DEVIATIONS.md` lists the one slip.

## The fill model, in plain words
- **When trades happen:** you act at the day's closing price, and only on strikes that
  actually traded that day.
- **Slippage:** every order pays 1% of the premium, minimum one tick. Results are re-run
  at 2% and 3%.
- **A stale strike** (not traded on exit day) pays 3x slippage.
- **Costs:** Angel One's MCX option charge card on every order: ₹20 brokerage, MCX 0.0418%,
  CTT 0.05% on sells, stamp 0.003% on buys, SEBI fee, 18% GST.
- **Capital** is the margin Angel actually asks for: about 37% of a lot's value per short
  crude option and 20% per short natural-gas option. There is no hedge discount, because
  Angel's calculator gave 0% on a straddle and 1.8% on a vertical.
- **Expiry:** every position is closed by the expiry-day close, never left to turn into
  futures.

## What a daily backtest cannot see
- **Intraday spikes.** A stop is checked at the close, so a move that reverses inside the
  day is not caught. A real intraday stop would sometimes fill worse.
- **The exact close.** The close is the last trade of a session that runs to 23:30/23:55
  IST. You would need to be trading near then, or accept a slightly different price.
- **Short mini history.** Validation covers about 28 monthly cycles per instrument. That
  is enough to reject strategies that do not work, but not enough to promise future
  returns.
