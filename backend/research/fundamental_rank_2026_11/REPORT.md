# Fundamental Rank: validation results (15 Nov 2026)

The rules are in [PLAN.md](PLAN.md), written before any result. Panels come from `study.py`; statistics come
from `report.py`.

## Finding

**No part of the module's fundamental scoring predicted the next 12 months' return consistently** from
Oct 2021 to Oct 2026, either alone or combined.

- Quality, growth and strength flip sign with the market:
  - They hurt in the 2021-22 rally; IC −0.12 to −0.20, the worst figures.
  - They helped in the falling 2024-26 market, at about +0.07 to +0.16.
- Valuation was the only component to pass the development rule. It then failed the hold-out.

The NSE Stock Ratings Rank column therefore ranks **fundamental strength, not future returns**. It is built
from the stock rating's five business parts at the rating's own weights; nothing is fitted to returns. It is
labelled that way in the app.

## Self-check: the reconstruction reproduces the live table

Each page was rebuilt at its own fetch date and compared with the live row.

| Component | Stocks | Correlation | Median abs. difference |
|---|---|---|---|
| Quality | 2,532 | 0.963 | 0.20 |
| Growth | 2,449 | 0.952 | 0.30 |
| Valuation | 2,088 | 0.849 | 0.60 (the live P/E is TTM; the rebuild uses the last year) |
| Strength | 2,236 | 0.941 | 0.00 |
| Fundamentals score | 2,532 | 0.949 | 0.30 |

## Development years: Spearman IC against the next 12 months

Rule: a component passes with a mean IC of 0.02 or more, and a positive IC in at least 3 of the 4 years.

| Component | Oct 2021 | Oct 2022 | Oct 2023 | Oct 2024 | Mean (t) | Positive | Passes |
|---|---|---|---|---|---|---|---|
| Quality | −0.181 | +0.020 | −0.046 | +0.138 | −0.017 (−0.26) | 2/4 | no |
| Growth | −0.198 | −0.022 | −0.071 | +0.090 | −0.050 (−0.84) | 1/4 | no |
| Valuation | −0.008 | +0.110 | +0.078 | +0.027 | +0.052 (1.98) | 3/4 | **yes** |
| Strength | −0.124 | +0.025 | −0.089 | +0.067 | −0.030 (−0.67) | 2/4 | no |

The plan's "at least 2 components" clause could not be met with a single passing component. The composite is
therefore that component alone, which involves no weights. This reading is written into `report.py`.

## Hold-out: 1 Oct 2025 to 1 Oct 2026, opened once

| | IC | Weakest fifth (median) | Strongest fifth (median) | Weakest fifth (mean) | Strongest fifth (mean) |
|---|---|---|---|---|---|
| Valuation | −0.004 | −14.2% | −11.8% | +1.8% | −2.1% |

The rule needs IC > 0, so the component **fails**.

Robustness (reported, not used to select):

- within-sector IC 0.004;
- breaks dropped: −0.016;
- the largest 1,000 by market cap: +0.010;
- 6-month horizon: −0.002.

## Reported signals: never used to select

| Signal | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| Fundamentals score (7 pillars) | −0.195 | +0.018 | −0.058 | +0.137 | +0.146 |
| P&L record | −0.190 | −0.003 | −0.097 | +0.099 | +0.166 |
| Cash conversion | −0.047 | +0.099 | +0.015 | +0.115 | +0.111 |
| P/E vs sector | −0.012 | +0.100 | +0.073 | +0.019 | +0.005 |
| Quarterly results | — | — | — | +0.179 | +0.113 |
| Ownership | — | — | — | +0.073 | +0.040 |

Cash conversion is the steadiest: positive in 4 of 5 years. Quarterly results and ownership have only two
years of data. **These five years are now spent.** A composite of the steadiest signals chosen from this table
would be fitted to it, not validated. It could only be judged on a forward record from today.

## The Rank column as shipped

It ranks on the rating's five business parts, momentum left out. A stock needs quality and at least 4 of the
5 parts.

| Ranked on 1 Oct | Strongest fifth (median 12m) | Weakest fifth | Rank IC | Stocks |
|---|---|---|---|---|
| 2021 | −13.7% | +15.0% | −0.192 | 912 |
| 2022 | +23.1% | +21.8% | −0.006 | 1,118 |
| 2023 | +30.2% | +36.7% | −0.030 | 1,216 |
| 2024 | −16.8% | −25.0% | +0.140 | 1,372 |
| 2025 | −9.1% | −21.5% | +0.161 | 1,971 |

It is defensive. The strongest fifth fell less in the two falling years, and lagged in the 2021 and 2023 rallies.
Quarterly results enter only from 2024, because no earlier quarters are cached. Before 2024 a stock needs the
other four parts, which is why fewer stocks are ranked.

## Caveats

- **Survivorship.** Today's listed universe only. Companies delisted since are missing, which mostly flatters
  the weakest names.
- **Returns are price-only.** Dividends are not included, which slightly understates cheap, high-yield stocks.
- **Restatements.** screener.in shows restated past figures, not the figures as first reported.
- **Market cap at past dates** assumes no share-count change other than bonuses, splits and consolidations.
- **Five yearly cross-sections are few.** A t-stat over 4 or 5 points is weak evidence either way.
