# NIFTY 50 ATM same-week option opening-range breakout (October 2026): research code

The owner's follow-up to `../niftybees_orb_2026_10`: the same opening-range breakout, traded with NIFTY 50 options instead of the NIFTYBEES ETF. The rules:

- the opening range is read on the NIFTY 50 index (the options' underlying), 09:15–09:29;
- buy the at-the-money call on a break above it, or the at-the-money put on a break below it;
- the contract is the nearest weekly expiry on or after the trade day, expiry day included;
- the stop and the target (1:2, and 1:3 to 1:6) are levels on the index;
- one lot of today's 65 units;
- out by 15:15.

**Results:** [REPORT.md](REPORT.md), also the private page https://claude.ai/artifact/BHjpnCQZUN4B8fikjnMfMC.

- **Buying loses at every ratio.** At 1:2 it lost −₹2,71,175 on one lot, −2.2% a month on ₹2 lakh, t −2.2. Before costs it was already −₹1,56,115, which is time decay.
- **The mirror** (the owner's "do the opposite": sell the same option at the same moments) made **+₹40,798 at 1:2**. That is +0.33% a month on ₹2 lakh with about ₹1.24 lakh of margin a lot, t +0.33, not significant. Across the ratios it ran from −₹25,343 to +₹40,798.
- **That profit comes from expiry-day trades**, where the model still flatters a seller. Without expiry days it was −₹8,866; selling next week's expiry lost −₹1,31,564.

## Why the premiums are modelled, and how they are checked

No source this app can reach keeps intraday prices of EXPIRED NIFTY options. Angel One and Dhan serve candles only for live contracts, and the app's own recorder (`app/services/option_chain_recorder.py`) started on 2026-10-05. So each trade's entry and exit premium comes from the model the BANKNIFTY study built and validated (`../banknifty_2026_10`), redone for NIFTY weeklies:

- **Volatility.** It comes from the previous session's REAL NSE closing prices of that very contract (bhavcopy). Nothing from the trade day's own option prices is used.
- **Moves during the day.** India VIX moves are passed through with a calibrated exponent, under a sticky-strike or moving smile.
- **Time.** A variance clock of trading minutes plus 0.2 of a session a night.

It is checked three ways:

1. on the day-over-day change of real closing premiums, calibrated on 2021-10 → 2023-12 and checked on 2024-01 → 2026-10 (`nopt_calibrate.py`);
2. against real intraday quotes the recorder kept for 14 sessions, 5–23 Oct 2026 (`nopt_intraday_check.py`);
3. by re-pricing the strategy's own October 2026 trades at those real quotes (`nopt_run.py`, `real_price_check`).

## Run order

Run each from the repository root with `python -I backend/research/nifty_options_orb_2026_10/<script>`.

| Script | What it does |
|---|---|
| `nopt_fetch_bhav.py` | NSE F&O bhavcopies 2021-10 → 2026-10-23 from nsearchives (works from a home connection). Keeps NIFTY options within 8% of the money, expiries ≤ 45 days, and futures. Writes `data/bhav/`. |
| `nopt_data.py` | NIFTY 50 and India VIX 1-minute history from the index-intraday store plus the server's daily files. Writes `data/minutes.npz`. |
| `nopt_surface.py` | The per-session smile of every expiry from real closes: parity forward, quadratic smile. Writes `data/surface.json.gz`, `closes.json.gz` and `listing.json.gz`. |
| `nopt_clock.py` | The share of a day's variance left at each minute, from NIFTY's 2021-23 minutes. The final model's clock runs on it; `NOPT_CLOCK=flat` reruns the first model. |
| `nopt_calibrate.py` | Chooses the VIX pass-through and the smile rule on 2021-23, then reports 2024-26 (`results/calibration.json`). |
| `nopt_intraday_check.py` | Compares the model with recorded real quotes (`data/optchain/`, copied from the server's `/data/intraday/optchain`). |
| `nopt_run.py` | The backtest at 1:2 … 1:6, BUYING and the mirror SELLING (with margin), the monthly figures, the comparison runs and the real-price check. Writes `results/summary.json` (`summary_flat.json` with `NOPT_CLOCK=flat`) and `trades_{buy,sell}_rr_1_*.csv`. |
| `nopt_verify.py` | Pricing, clock, calendar, fills, charges, contract rules and the invariants of every trade file. |
| `nopt_report.py` | Writes `REPORT.md` and the HTML page from the results. |

`data/` is not in git (`data/.gitignore`): NSE files, Angel's licensed candles and the recorded quotes.
