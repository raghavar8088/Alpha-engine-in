# Phase 0 data report: 5-minute bars for NIFTY 50 stocks, Oct 2021 – Oct 2026

## What was pulled
- **Source:** Angel One's candle endpoint, through the app's own client and shared pacer (`n50_fetch.py`).
  - It ran on the server on Sat 24 Oct 2026, with markets closed, in a separate 300 MB container.
  - Database access was read-only; nothing was written to it.
- **Coverage:**

  | | Count | Notes |
  |---|---|---|
  | Stocks | **60** | every NIFTY 50 member of the period with an Angel token |
  | Indices | **19** | NIFTY, India VIX and 17 sector indices |
- **Size:** 1,490 requests and 7,319,462 candles, with no failed request.
- **Missing:**
  - **HDFC Ltd** was delisted in 2023, so Angel has no history.
  - **LTIM** is not in the app's instrument master.

  Both are disclosed in `membership.json`.
- **Housekeeping:** the copy on the server was deleted after transfer, because its disk is 94% full.

## What the checks found (`n50_checks.py`)
| Check | Result |
|---|---|
| Trading days | 1,255 NIFTY sessions, 1 Oct 2021 – 23 Oct 2026; every stock present on every one (JIOFIN from its Aug 2023 listing) |
| Candles per session | 75 (09:15–15:25) on ~95% of stock-days |
| Duplicates, off-grid stamps, impossible prices | none (indices: a handful of bad prints) |
| Zero-volume candles | 0.03–0.04% per stock |
| Alignment | every stock's 5-minute returns correlate 0.20–0.64 with NIFTY's, so timestamps line up |
| **Closing auction** | from **3 Aug 2026** every stock has 72–73 candles: the 15:15–15:25 candles stop, because NSE's closing auction replaced continuous trading at the end of the day. The plan's 15:10 square-off is before it in every period |
| Special sessions | Muhurat trading (5) and two Saturday disaster-recovery drills (2 Mar and 18 May 2024): dropped |

## Corporate actions
Angel's prices are adjusted for most splits and bonuses: the 2024–25 bonuses, the NESTLEIND and BAJFINANCE
splits, and the Tata Motors demerger all show no jump in price or volume. **Three are not adjusted.** Each was
proven by turnover (price × volume), which is continuous only after the fix:

| Stock | What was wrong | Fix |
|---|---|---|
| TATASTEEL | 26–27 Jul 2022 carry the pre-split price (+911%, then −90%); volume before the split is in pre-split shares | price ÷ 10 and volume × 10 on 26–27 Jul; volume × 10 before 26 Jul |
| NESTLEIND | before 31 Dec 2021, price and volume are both pre-split (−90% on 31 Dec) | price ÷ 10, volume × 10 |
| BAJAJFINSV | before 13 Sep 2022, volume is in pre-split shares (turnover read 10× low) | volume × 10 |

After the fixes, the largest overnight gap in any stock is 15%, and every such gap is real news:
- BSE (Apr 2024);
- BEL on the Jun 2024 election-result day;
- the 7 Apr 2025 global sell-off;
- IndusInd's Mar 2025 accounting shock.

The remaining turnover surges are also real:
- Adani–Hindenburg (Jan 2023);
- IndiGo's crisis (late 2025);
- new listings.

## The clean panel
- **`n50_clean.pkl`:** 7,223,775 candles, 1,248 sessions, 59 stocks and 19 indices (sha256 `ada44df0…`).
- **Corrections:** recorded in `adjust_log.json`.
- **Not committed:** the raw files and the panel stay out of the repository, because the repo is public and
  this is licensed market data.
