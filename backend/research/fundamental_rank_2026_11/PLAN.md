# Fundamental Rank: validation plan

Written 15 Nov 2026, before any result was computed. The rules below decide what the NSE Stock Ratings
tab's Rank column is built from. They are not changed after the results are seen.

## Question

Does the module's own fundamental scoring rank NSE stocks by how they did over the next 12 months? The
scoring may only use what was known at the time. If parts of it do, the Rank column is built from those
parts only, with weights that were not fitted to returns.

## Data

- **screener.in pages, as the app caches them.** 2,647 companies, fetched 27 Sep to 15 Nov 2026.
  - Yearly P&L, balance sheet, cash flow and ratios: from FY2015.
  - Quarters: from Sep 2023.
  - Shareholding: from Dec 2023.
- **NSE daily closes, 1 Oct 2021 to 9 Nov 2026.**
  - Adjusted for bonuses, splits and consolidations from NSE's corporate-actions feed. This uses the
    ratings module's own `parse_action`.
  - Symbols are mapped to today's names with NSE's symbol-change list.

## Point in time

- **As-of dates.**
  - Development: 1 Oct 2021, 2022, 2023 and 2024.
  - Hold-out: 1 Oct 2025. It is opened once, after the components are chosen.
- **When a column counts as known.** A column is used only if enough days have passed since its period
  ended. Each lag is the SEBI filing deadline plus 7 days' grace:
  - yearly columns: 67 days (60-day deadline for audited annual results);
  - half-year balance sheets: 52 days;
  - quarters: 52 days, or 67 for the March quarter;
  - shareholding: 28 days.
- **Rebuilt, not read.** TTM columns are dropped. So are screener's ready-made growth and ROE ranges;
  they are recomputed from the kept years. Today's ratios are replaced by their as-of values:
  - P/E = market cap at the as-of date / the latest kept year's net profit;
  - ROCE = that year's ROCE %;
  - ROE = net profit / average net worth.
- **Market cap at the as-of date** = today's market cap × (adjusted close then / adjusted close on the
  fetch date). Share-count changes other than bonuses, splits and consolidations are not modelled.
- **Scoring.** Every as-of panel is scored by the module's own code: `fundamental_rating.rate`,
  `pnl_strength`, `results_strength`, and `nse_ratings_logic.static_row` / `rating_components`.
  - The sector P/E percentile is recomputed across that date's stocks, sectors with 8 or more peers
    only (MIN_SECTOR_PEERS).
- **Self-check.** The same reconstruction run at each page's fetch date must reproduce the live table's
  components. Agreement is reported. Valuation is expected to differ a little, because the live P/E
  is trailing-twelve-month.

## Outcome

- The 12-month price return, adjusted, without dividends. It runs from the last close on or before the
  as-of date to the first close on or after it + 365 days. Both closes must fall within 5 sessions of
  those dates.
- **Breaks stay in the main test.** A break is a window with an unexplained one-day move over 40% (the
  module's BREAK), or a rights issue or demerger. Breaks are dropped in a robustness test.

## Universe

Today's NSE mainboard list (EQ/BE/BZ). This means survivorship: companies delisted since are missing.
On each date, a stock must have:

- closes at both ends of the window;
- at least 3 yearly columns kept;
- the module's own data rule: at least 4 pillars, and at least 60% of the applicable pillar weight.

## Signals

- **Candidates.** The four fundamental components the table shows that can be rebuilt for every year:
  quality, growth, valuation and strength. Quarterly results and ownership have data only from late
  2023, so they are reported but never used to select.
- **Reported, not selected on:**
  - the seven raw pillars;
  - the module's fundamentals score;
  - the fundamental part of today's stock rating (no momentum).

## Decision rules (fixed now)

1. **A component passes** if both hold:
   - its development mean Spearman IC against 12-month returns is at least 0.02;
   - it is positive in at least 3 of the 4 development years.
2. **Fundamental Rank** is the rank of the equal-weighted mean of the passing components' cross-sectional
   percentiles. No weights are fitted to returns.
   - A stock needs all but one of the passing components, and at least 2.
   - A lender has no strength component; it is ranked on the others.
3. **Hold-out** (1 Oct 2025 to 1 Oct 2026), opened once. The composite passes if both hold:
   - its IC is above 0;
   - its top quintile's median return beats its bottom quintile's.
4. **If no component passes,** no Fundamental Rank is called validated, and that is the finding reported.

## Robustness

These are reported, not used to select:

- medians as well as means;
- within-sector IC;
- the largest 1,000 by market cap;
- breaks dropped;
- a 6-month horizon.
