# Pre-registered protocol: option selling on MCX Crude Oil Mini and Natural Gas Mini

Written 2026-10-22, before any strategy's performance was computed. The only things looked at
so far are data AVAILABILITY (which contracts exist, how many lots trade). This file's
SHA-256 is recorded in the report; nothing below is changed after the search runs. Any
deviation is listed in the report as an amendment, with its reason.

## Question
Which option-SELLING strategies on CRUDEOILM (10 bbl) and NATGASMINI (250 mmBtu) options
make money after real costs on real MCX prices, and keep making it on data the selection
never saw? Up to five are reported. Fewer are reported if fewer pass. None is padded in.

## Data
MCX's official daily bhavcopy (mcxindia.com, commodity-wise endpoint), downloaded 2026-10-22:
OPTFUT and FUTCOM for CRUDEOIL, CRUDEOILM, NATURALGAS and NATGASMINI, every contract over its
listed life. Fields: open, high, low, close, volume, open interest, strike, option type.

## Periods (fixed by data availability, not by results)
| | Discovery (selection) | Validation (untouched until selection is frozen) |
|---|---|---|
| Crude | CRUDEOIL option expiries Jan 2020 - May 2024 | CRUDEOILM's own option prices, expiries Jun 2024 - Oct 2026 |
| Natural gas | NATURALGAS option expiries Mar 2022 - Apr 2024 | NATGASMINI's own option prices, expiries Jun 2024 - Oct 2026 |

Discovery uses the parent contract's per-unit premiums (the minis did not exist yet). The
mini and the parent are the same underlying, so the premium per barrel / mmBtu is the same.
This is checked on the overlap, and P&L is in mini lots. The parents' prices over the
validation period are a secondary cross-check only. Expiries after Oct 2026 are excluded
because they had not finished on the download date.

## Execution model (identical in both periods)
- Decide and fill at the day's close, using only contracts that **traded that day** (volume
  > 0). A leg's strike is the traded strike nearest its target level. If none lies within
  two listed strike steps, that cycle is skipped.
- Slippage per leg per transaction is max(1 tick, 1% of premium). Stress runs use 2x and 3x.
- A leg that did not trade on an exit day is closed at the exchange close with 3x slippage,
  and the event is counted.
- Fees use Angel One's MCX option card (`mcx_option_fees`): Rs20 per order, MCX 0.0418%,
  CTT 0.05% sell side, stamp 0.003% buy side, SEBI Rs10/cr, GST 18%.
- Size is one lot per leg. Every position is closed by the expiry-day close, never left to
  devolve into futures.
- Capital per trade = margin + premium paid. Margin per SHORT leg = 1.20 x measured futures
  margin rate x notional (crude 0.311, natural gas 0.167, measured on Angel 2026-10-09),
  with no netting (Angel's calculator gave 0% on a straddle and 1.8% on a vertical).

## Strategy space (complete list; distances in multiples of the ATM straddle price)
| Structure | Parameters |
|---|---|
| Short strangle | k = 0.5, 0.75, 1.0, 1.25, 1.5, 2.0 |
| Short straddle | k = 0 |
| Iron condor | k = 0.5, 0.75, 1.0, 1.25, 1.5; wing w = 0.5, 1.0 beyond each short |
| Iron butterfly | k = 0; w = 0.5, 1.0 |
| Bull put credit spread | k = 0, 0.5, 0.75, 1.0, 1.25; w = 0.5, 1.0 |
| Bear call credit spread | k = 0, 0.5, 0.75, 1.0, 1.25; w = 0.5, 1.0 |
| Naked short put / short call | k = 0.5, 0.75, 1.0, 1.25, 1.5, 2.0 each |

Each structure is crossed with every value below.
- **Entry:** 20, 15, 10, 7 or 5 trading days before expiry.
- **Profit take:** none, 50% of credit, or 75%.
- **Stop:** none, loss = 1x credit, or loss = 2x credit (checked at the close).
- **Time exit:** expiry-day close, or 1 trading day before.
- **Filter:** none, or ATM implied vol > 20-day realised vol at entry.

That is 51 structures x 180 = 9,180 variants per instrument. One position per strategy per
monthly cycle.

## Discovery selection (fixed)
1. **Eligible** if all of these hold in discovery:
   - trades >= 70% of the cycles;
   - net P&L > 0;
   - profit factor >= 1.3;
   - t-stat of mean trade P&L >= 1.5;
   - the 2x-slippage run is still net positive;
   - worst single trade loss <= 30% of that trade's capital.
2. **Plateau:** at least 2/3 of the variant's grid neighbours must have profit factor >= 1.1.
   Neighbours are the adjacent k, the adjacent entry day and the other filter setting, with
   all else equal. This guards against a lucky point.
3. **Ranking:** eligible plateau variants are ranked by the 5th percentile of a 5,000-draw
   bootstrap of mean trade return on capital.
4. **Candidates:** the top 6 per instrument go forward. No two may share both structure and
   entry day.

## Validation (fixed; run once, after candidates are frozen)
A candidate PASSES if all of these hold on the mini's own prices:
- net P&L > 0;
- profit factor >= 1.15;
- worst trade no worse than 1.5x its discovery worst trade (as return on capital);
- still net positive at 2x slippage.

The final list is the passers ranked by validation mean return on capital divided by its
standard deviation. There are at most 5, and at most 3 per instrument. The Deflated Sharpe
Ratio is reported for each, given the 9,180 trials per instrument.

## Reported for every finalist
- full rules;
- per-trade log;
- year-by-year P&L;
- the slippage stress (1x/2x/3x);
- entry shifted +/-2 days and k shifted by one grid step;
- results with the single best month removed;
- worst trade, worst drawdown and capital needed.

The descriptive study is reported separately: ATM implied vol vs realised vol per cycle,
i.e. whether there is a premium to sell at all.
