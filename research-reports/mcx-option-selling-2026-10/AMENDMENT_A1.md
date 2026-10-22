# Amendment A1: walk-forward stage (written 2026-10-22, after validation, before running it)

## Why there is a second stage
The pre-registered protocol (`PROTOCOL.md`) ran as written.

- 12 candidates went into validation and 2 passed, both on crude.
- One passer is robust (A: short put). The other is fragile (B: short strangle).
- Every natural-gas candidate failed. Short calls chosen in the 2022-24 natural-gas collapse
  lost heavily in the 2024-26 rallies.

One train/test split cannot say much more. A walk-forward evaluation can: it tests the
SELECTION PROCESS many times, out of sample each time.

## What I knew when writing this
- The 12 candidates' validation results.
- The discovery landscape: naked short options were mostly profitable; bought-wing
  structures mostly were not.
- The literature (Trolle & Schwartz 2010): selling energy variance pays on average, but
  natural-gas variance is call-like (it spikes in rallies) and crude's is put-like (it spikes
  in crashes).

The new trend-aware family below was motivated by that literature AND by seeing the
natural-gas short calls fail in rallies. The natural-gas walk-forward years 2024-2026
therefore cannot be called blind for that family. The report must say so.

## Additions to the grid
- **Trend-aware side ("trend").** At entry, compare the futures close with its own n-day
  simple moving average, n = 10 or 20.
  - Above the average: sell the PUT side.
  - Below it: sell the CALL side.

  It comes in two forms:
  - naked: k = 0.5, 0.75, 1.0, 1.25, 1.5;
  - credit spread: the same k with wing w = 0.5 or 1.0.

  That is 30 structures, each crossed with the same entry, exit, profit-take, stop and filter
  values as PROTOCOL.md.
- **One stricter filter:** "ivrv110", meaning ATM IV > 1.10 x the 20-day realised vol.

Everything else (fills, slippage, fees, margin, the eligibility rules, plateau and ranking) is
exactly PROTOCOL.md.

## Data for the walk-forward
Parent-contract prices throughout, for one consistent and longer series:
- crude: CRUDEOIL expiries Jan 2020 - Oct 2026;
- natural gas: NATURALGAS expiries Mar 2022 - Oct 2026.

P&L is in mini lots. The minis' own prices for Jun 2024 - Oct 2026 are reported alongside as a
check. The minis' closes run 2-4% richer than the parent's, so they are the less conservative
series.

## Walk-forward procedure
For each test year Y:
- crude: Y = 2022 ... 2026;
- natural gas: Y = 2024 ... 2026;
- the training data is every cycle expiring before 1 Jan Y;
- a year is tested only if its training data has at least 20 cycles.

In each year:
1. Apply PROTOCOL.md's eligibility, plateau and ranking rules to the training cycles only.
2. Take the top 3 variants with distinct (structure, entry).
3. Trade each, one lot, in every cycle that expires in year Y.

The yearly results are stitched together into the procedure's out-of-sample record.

## Final picks (fixed now)
The procedure is run once more on all data through Oct 2026 to give its current top 3 per
instrument. They are recommended only if the stitched out-of-sample record for that
instrument has net P&L > 0 and profit factor >= 1.15 at 1% slippage, and is still net > 0 at
2%. The final report combines these with PROTOCOL.md's validated finalists, at most 5 in
total, each labelled with its evidence level.
