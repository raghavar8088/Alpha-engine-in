# Premium Intraday Strategies: research register

*22 Nov 2026. Sources with links, dates, markets, samples and cost treatment; every hypothesis with its mechanism, when it should fail, what would invalidate it, how it differs from the existing catalogs, and whether it was implemented, deferred or rejected. 'International' evidence still needs validation on Indian equities.*

## Hypotheses

| ID | Family | Status | Evidence | Why / difference from existing |
|---|---|---|---|---|
| N01 | Sector-confirmed opening-range breakout | implemented | S01, S02, S09, S07, S20, S22 | Tournament ORB-in-play: 30-minute range, top-20 relative volume, no sector condition, ATR stop. Stock Momentum orb15: no sector condition, stop at the signal candle (tight), Rs 10k positions. N01 adds the sector confirmation, the 09:40 persistence check, a structural stop (range midpoint, 0.35-1.5%) and a walk-forward target. |
| N02 | Relative-strength leaders and laggards | implemented | S06, S04, S10, S21 | Stock Momentum 'relative': 09:30 out/underperformance then a break of the previous bar, candle stop. N02 requires persistence to 09:40, a break of the morning's extreme, a VWAP-based stop (0.4-1.5%), and an opposite-sector filter. |
| N03 | VWAP pullback on trend days | implemented | S03, S04, S05, S22 | Tournament VWAP Reclaim trades crosses of VWAP on any day; Stock Momentum 'vwap' trades breaks above VWAP. N03 trades only on a classified trend morning and enters on the PULLBACK to VWAP, not the break. |
| N04 | Failed-gap reversal (no news) | implemented | S07, S08, S11, S12, S13, S19 | Tournament Gap Fade enters at 09:45 if price sits between the open and the previous close, low volume. Stock Momentum gap_fade breaks against the gap. N04 requires the gap to FAIL (a red opening range and a close back below the open, then a break of the range low), no material news, room to the previous close >= 1R. |
| N05 | Volatility compression then expansion | implemented | S17 | Selected ORB picks the LARGEST expected movers; N05 picks the most COMPRESSED stocks. No existing rule conditions on NR7/inside days. |
| N06 | News-catalyst continuation | implemented | S07, S16, S18, S10, S21 | Tournament Gap and Go and Stock Momentum gap_go use price and volume only; N06 requires a MATERIAL NSE announcement disseminated before 09:15 (exchange timestamp). |
| D01 | ADR overnight transmission (INFY, WIPRO, HDFCBANK, ICICIBANK, DRREDDY) | deferred | S19 | the edge is gone by 10:15 and this desk enters only after the 09:45 plan on five-minute bars; it needs a 09:15 entry path and a fresh quote at the open. |
| D02 | Pre-open auction imbalance | deferred | S12 | the pre-open snapshot has been stored only since Oct 2026, too short to test; collect forward first. |
| D03 | Bulk/block deal follow-through | deferred | S15 | Indian evidence points to leakage BEFORE the event and temporary impact that reverses, so a next-day continuation rule has no support; the data exists (nse_events) for a later test. |
| D04 | Results-day expected move (size, not direction) | deferred | S21 | a selection input, already used by Selected ORB; not a separate directional strategy. |
| R01 | Market intraday momentum (first half hour -> last half hour) | rejected | S04, S05, S19 | the effect lives in the last half hour (15:00-15:30) and this desk must be flat by 15:10; our NSE-IND-008 test of it was negative (-7.9 bp net). |
| R02 | Same half-hour periodicity | rejected | S06, S19 | our NSE-IND-010 test: -11.2 bp net per trade (2.3 bp gross). |
| R03 | Sector residual reversal | rejected | S19 | our NSE-IND-009 test: -19.0 bp net; N04 keeps only the narrower no-news failed-gap case. |
| R04 | Opening-auction reversal (fade the open) | rejected | S12, S19 | 96% of the gross edge came from auction prints never revisited that day (not tradable); ~0 net from the first continuous trade. |
| R05 | Circuit-limit magnet | rejected |  | a locked stock cannot be exited (failed exits by design); most of the universe is F&O with no fixed bands. |
| R06 | 52-week-high breakout intraday | rejected | S19 | our NSE-IND-005 test: -19.2 bp net in the hold-out. |
| R07 | Expiry-cycle effects in the cash market | rejected | S19 | our NSE-IND-007 test failed validation. |

## Implemented hypotheses in full

### N01 Sector-confirmed opening-range breakout
- **Mechanism.** Sector-wide information (news, flows, index rebalancing) diffuses through a sector over hours (S09); a stock that leads a BROADLY strong sector and breaks its opening range is more likely to be carrying that information than an isolated breakout (S07, S08).
- **Should fail when.** the sector's headline move comes from one heavyweight while most members fall (narrow); the market rotates after the open; range days.
- **Invalidated if.** out of sample, the sector-confirmed rule earns no more per trade than the same breakout without the sector condition, or loses after costs.
- **Evidence.** International (S01, S02, S09: needs Indian validation); our tests: plain ORB loses on NSE (S20, S22).
- **Different from the existing catalogs.** Tournament ORB-in-play: 30-minute range, top-20 relative volume, no sector condition, ATR stop. Stock Momentum orb15: no sector condition, stop at the signal candle (tight), Rs 10k positions. N01 adds the sector confirmation, the 09:40 persistence check, a structural stop (range midpoint, 0.35-1.5%) and a walk-forward target.
- **Data.** ok

### N02 Relative-strength leaders and laggards
- **Mechanism.** Stocks outperforming both their sector and NIFTY in the first half hour, and still doing so at 09:40, are absorbing persistent order flow (institutional orders worked through the day: S06); intraday continuation is stronger on high-volume days (S04).
- **Should fail when.** the leadership is a single block trade or an auction artefact; mean reversion dominates in quiet markets.
- **Invalidated if.** out of sample the 09:40-confirmed leaders earn <= 0 after costs, or no more than the 09:30 list alone.
- **Evidence.** International; S10 and S21 warn intraday components are weak.
- **Different from the existing catalogs.** Stock Momentum 'relative': 09:30 out/underperformance then a break of the previous bar, candle stop. N02 requires persistence to 09:40, a break of the morning's extreme, a VWAP-based stop (0.4-1.5%), and an opposite-sector filter.
- **Data.** ok

### N03 VWAP pullback on trend days
- **Mechanism.** On broad trend days institutions benchmark execution to VWAP, so pullbacks to VWAP in leaders meet VWAP-anchored demand (S03, practitioner); intraday momentum is stronger on high-volatility days (S04, S05).
- **Should fail when.** the morning trend reverses (no trend day); VWAP is crossed decisively.
- **Invalidated if.** out of sample, pullback entries on classified trend days lose after costs, or the trend-day condition does not improve on all days.
- **Evidence.** International (S03 disputed by replications); S22: trend days pay on NIFTY 50, range days lose.
- **Different from the existing catalogs.** Tournament VWAP Reclaim trades crosses of VWAP on any day; Stock Momentum 'vwap' trades breaks above VWAP. N03 trades only on a classified trend morning and enters on the PULLBACK to VWAP, not the break.
- **Data.** ok

### N04 Failed-gap reversal (no news)
- **Mechanism.** Gaps without public information are liquidity or sentiment shocks that reverse (S07, S08, S11); the NSE opening auction overshoots (S12); low-volume large moves reverse in India (S13). Entry waits for continuous-trading confirmation because the naive fade's edge is mostly auction prints (S19).
- **Should fail when.** the gap is informed (news, results, sector-wide); high volume; trend days in the gap's direction.
- **Invalidated if.** out of sample, confirmed failed gaps without news do not earn a positive net R, or the no-news filter does not improve them.
- **Evidence.** S12, S13 are Indian; S19 (our test) found the plain fade ~0 net from the first continuous trade.
- **Different from the existing catalogs.** Tournament Gap Fade enters at 09:45 if price sits between the open and the previous close, low volume. Stock Momentum gap_fade breaks against the gap. N04 requires the gap to FAIL (a red opening range and a close back below the open, then a break of the range low), no material news, room to the previous close >= 1R.
- **Data.** ok

### N05 Volatility compression then expansion
- **Mechanism.** Ranges mean-revert: unusually narrow days (NR7, inside days) and a narrow opening range tend to be followed by range expansion, and the break of the range shows its direction (S17).
- **Should fail when.** compression continues all day; the break is false (no follow-through).
- **Invalidated if.** out of sample, compressed-range breaks lose after costs (the stops are small, so costs weigh more).
- **Evidence.** Practitioner only (no independent test); our crypto session lab's NR4 finalist failed its hold-out.
- **Different from the existing catalogs.** Selected ORB picks the LARGEST expected movers; N05 picks the most COMPRESSED stocks. No existing rule conditions on NR7/inside days.
- **Data.** ok

### N06 News-catalyst continuation
- **Mechanism.** Firm-specific information released outside market hours is absorbed gradually (S07, S16, S18); a gap in the news' direction that holds through the opening range on heavy volume continues.
- **Should fail when.** the news is fully priced at the open (overnight drift, S10); intraday reversal of overnight gains on NSE (S21).
- **Invalidated if.** out of sample, catalyst gaps that hold do not continue after costs.
- **Evidence.** S16 is Indian (underreaction, daily); S21 (ours) finds intraday returns negative on average.
- **Different from the existing catalogs.** Tournament Gap and Go and Stock Momentum gap_go use price and volume only; N06 requires a MATERIAL NSE announcement disseminated before 09:15 (exchange timestamp).
- **Data.** announcements Nov 2025 onward only: tested on that period, the rest prospectively

## Sources

| ID | Title | Authors | Date | Market / sample | Costs | Type | Region | Read |
|---|---|---|---|---|---|---|---|---|
| S01 | [A Profitable Day Trading Strategy For The U.S. Equity Market (Stocks in Play, 5-minute ORB)](https://ideas.repec.org/p/chf/rpseri/rp2498.html) | C. Zarattini, A. Barbon, A. Aziz (Swiss Finance Institute RP 24-98) | 2024 | US equities; 2016-2023 | commissions included per summaries; slippage not confirmed | published (working paper) | International | abstract and secondary write-ups |
| S02 | [Can Day Trading Really Be Profitable? Evidence of Sustainable Long-term Profits from ORB](https://papers.ssrn.com/abstract=4416622) | C. Zarattini, A. Aziz | 2023 | QQQ (US); 2016 - Feb 2023 | commission $0.0005/share, no slippage | published (working paper) | International | abstract and secondary write-ups |
| S03 | [Volume Weighted Average Price (VWAP): The Holy Grail for Day Trading Systems](https://ssrn.com/abstract=4631351) | C. Zarattini, A. Aziz | 13 Nov 2023 | QQQ, TQQQ (US); Jan 2018 - Sep 2023 | unclear; public replications came in far lower | published (working paper) | International | secondary sources only |
| S04 | [Market intraday momentum](https://www3.nd.edu/~zda/intramom.pdf) | L. Gao, Y. Han, S. Li, G. Zhou | 2018 (J. Financial Economics 129(2)) | S&P 500 ETF (US); 1993-2013 | gross | published | International | paper/summary |
| S05 | [Hedging demand and market intraday momentum](https://pure.eur.nl/en/publications/hedging-demand-and-market-intraday-momentum/) | G. Baltussen, Z. Da, S. Lammers, M. Martens | 2021 (J. Financial Economics 142(1)) | 60+ futures (equity, bond, commodity, FX); 1974-2020 | gross | published | International | abstract |
| S06 | [Intraday patterns in the cross-section of stock returns](https://arxiv.org/pdf/1005.3535.pdf) | S. Heston, R. Korajczyk, R. Sadka | 2010 (J. Finance 65(4)) | NYSE stocks; 2001-2005 (TAQ) | not a cost-inclusive strategy test | published | International | abstract |
| S07 | [Stock returns after major price shocks: the impact of information](https://ideas.repec.org/a/eee/jfinec/v106y2012i3p635-659.html) | P. Savor | 2012 (J. Financial Economics 106(3)) | US stocks; analyst-report events | not a trading test | published | International | abstract |
| S08 | [Stock price reaction to news and no-news: drift and reversal after headlines](https://econpapers.repec.org/RePEc:eee:jfinec:v:70:y:2003:i:2:p:223-260) | W. Chan | 2003 (J. Financial Economics 70(2)) | US stocks (monthly); headline data | risk-adjusted, gross | published | International | abstract |
| S09 | [Industry information diffusion and the lead-lag effect in stock returns](https://ideas.repec.org/a/oup/rfinst/v20y2007i4p1113-1138.html) | K. Hou | 2007 (Review of Financial Studies 20(4)) | US stocks (daily/weekly); long history | gross | published | International | abstract |
| S10 | [A tug of war: overnight versus intraday expected returns](https://eprints.lse.ac.uk/87481/) | D. Lou, C. Polk, S. Skouras | 2019 (J. Financial Economics 134(1)) | US stocks; multi-decade | gross | published | International | abstract |
| S11 | [Intraday price reversals in the US stock index futures market: a 15-year study](https://ideas.repec.org/a/eee/jbfina/v29y2005i5p1311-1327.html) | J. Grant, A. Wolf, S. Yu | 2005 (J. Banking & Finance 29(5)) | S&P 500 futures; Nov 1987 - Sep 2002 | bid-ask estimate: significance drops sharply | published | International | abstract |
| S12 | [Impact of the introduction of call auction on price discovery: evidence from India](https://econpapers.repec.org/RePEc:eee:finana:v:39:y:2015:i:c:p:167-178) | S. Agarwalla, J. Jacob, A. Pandey (IIM Ahmedabad) | 2015 (Int. Review of Financial Analysis 39) | NSE (top 50); around the 2010 pre-open call auction | not a trading study | published | India | abstract (via the earlier independent study) |
| S13 | [Predictable patterns following large price changes and volume: evidence from the Indian stock market](https://ideas.repec.org/a/eme/rbfpps/rbf-06-2018-0058.html) | S. Parthasarathy | 2019 (Review of Behavioral Finance 11(4)) | Indian stocks (daily); not stated in abstract | not stated | published | India | abstract |
| S14 | [Analysis of intraday trading by individuals in the equity cash segment](https://www.sebi.gov.in/media-and-notifications/press-releases/jul-2024/sebi-study-finds-that-7-out-of-10-individual-intraday-traders-in-equity-cash-segment-make-losses_84948.html) | SEBI | 24 Jul 2024 | NSE/BSE cash intraday, individuals at the top 10 brokers; FY19, FY22, FY23 | included | regulator | India | press release |
| S15 | [Bulk deals on NSE: front-running and price leakage](https://studentlive.iimcal.ac.in/sites/all/files/pdfs/wp_863.pdf) | IIM Calcutta (WP 863); Managerial Finance (2022) | 2010-2019 samples | NSE bulk deals; 2010-2019 | not a trading test | published (working paper) | India | abstract |
| S16 | [An analysis of corporate insider trading and earnings announcements in India](https://nsearchives.nseindia.com/research/content/NSE-IGIDR-WP4-14-15.pdf) | NSE-IGIDR WP | 2014-15 | Indian listed firms; not read in full | not a trading test | published (working paper) | India | search summary |
| S17 | [Day Trading with Short Term Price Patterns and Opening Range Breakout (NR7, ORB)](https://store.traders.com/-v07-c04-orb-pdf.html) | T. Crabel | 1990 (Traders Press) | US futures; 1980s | not stated | practitioner | International | secondary descriptions |
| S18 | [News as sources of jumps in stock returns (21 million articles, 9,000 firms)](https://ideas.repec.org/a/eee/jfinec/v145y2022i2p1-17.html) | Y. Jeon, T. McCurdy, X. Zhao | 2022 (J. Financial Economics 145(2)) | US stocks; decades | not a trading test | published | International | abstract |
| S19 | [NSE-IND-001..010 independent intraday study (opening-auction reversal, ADR transmission, sector residual reversal, same-slot periodicity, market intraday momentum)](https://claude.ai/artifact/XnU2PkhUaoz3Y5tN4fSbCi) | this project (D:/NSE-Intraday-Research) | 5-6 Nov 2026 | NSE cash; 2013-2026 (hold-out 2023-Nov 2026) | included | our test | India | full |
| S20 | [Intraday Stocks: audit of the 54 tournament strategies](INTRADAY_STOCKS_54_STRATEGY_AUDIT.md) | this project | 4 Nov 2026 | NSE top 200; 4 Nov 2024 - 3 Nov 2026 | included (measured slippage) | our test | India | full |
| S21 | [Stock selection research S0-S7 (where vs which way)](INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md) | this project | 2 Oct 2026 | NSE top 200; Sep 2024 - Oct 2026 | 10 bp hurdle | our test | India | full |
| S22 | [NIFTY 50 first-15-minute momentum study](research-reports/nifty50-strategies-2026-10/REPORT.md) | this project | 25 Oct 2026 | NIFTY 50 constituents; Oct 2021 - Oct 2026 | included | our test | India | full |
