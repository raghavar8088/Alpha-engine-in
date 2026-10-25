# Top 20 NIFTY option-buying strategies of the last month (October 2026)

The owner asked for the top 20 option-buying strategies, backtested over the last month. Report: [REPORT.md](REPORT.md); page: https://claude.ai/artifact/PiubMP4cCcNEnMRRuA3rC5.

- `obt_run.py [workers]` replays the app's whole option-buying library (strategy-service `options_buying`, 167 strategy x timeframe pairs) with the live Pre-Live desk's rules. It covers 24 Sep – 23 Oct 2026, then 13 months for the persistence check, and writes `results/summary.json`. Prices on 5–23 Oct are the app's real recorded quotes (bought at the ask, sold at the bid). Other days use the validated premium model of `../nifty_options_orb_2026_10`, which must be built first.
- `obt_report.py` writes `REPORT.md` and `report/option-buying-top20.html`. It keeps twenty DISTINCT strategies: names whose trades repeat a higher-ranked one exactly are dropped.

**Result.** The top 20 together made +Rs3.92 lakh last month, one lot each, with at most Rs1.56 lakh of premium out at once. That was a month in which 84 of 167 strategies were up. Over the 12 months before, a month's top 20 lost money the following month 11 times out of 12 (-Rs14.2 lakh in all). That is better than an average 20 (-Rs18.1 lakh) or the bottom 20 (-Rs26.7 lakh), but still a loss.

`data/` (trade files) is not in git.
