# Eleven YouTube channels: 103 strategies as exact rules, paper trading

Channels: Neeraj Joshi (47 strategies), Brad Goh / The Trading Geek (10), Pushkar Raj Thakur (13), Theta Gainers (9),
Stock Burner (8), Tanisha Garg (6), Sagar Sinha (6), IITian Trader (2), The Trade Room (1), saya crypto (1). Conor
Kenny's videos (mindset and discretionary price action) gave no rule that could be tested.

Nothing here is a backtest result. Every strategy was written from its videos as exact rules, coded, and checked for
look-ahead; it then paper trades its own Rs 10 lakh account on the Premium Strategies desk (`premium-paper-service`,
source `youtube_channels11`), flat from `settings.YC_START_T`. Paper trading is each strategy's first test.

## Files

| File | What it is |
|---|---|
| `catalogue/selection/<channel>.tsv` | the videos chosen per channel (strategy videos first), with the reason |
| `analyses/<channel>.md` | per strategy: the video's rules with times (E = stated, I = inferred) and the testable form (A = research assumption) |
| `specs/RULES.md` | the cards' rules, generated from the analyses by `make_rules.py` (`python -I make_rules.py`) |
| `yc_strategies.py` | the registry: per strategy its code, markets, bars, forced exit, daily limits and how its book runs |
| `yc_nj_india.py`, `yc_nj_crypto.py` | Neeraj Joshi NJ-01 .. NJ-26, NJ-46 (India) and NJ-27 .. NJ-45, NJ-47 (bitcoin) |
| `yc_channels.py` | Tanisha Garg, IITian Trader, The Trade Room, Sagar Sinha, saya crypto, Brad Goh |
| `yc_more.py` | Pushkar Raj Thakur, Stock Burner, Theta Gainers |
| `yc_common.py`, `yc_ind.py` | shared candle tests, swings, fair value gaps, CISD lines, sweeps, local clocks; indicators |
| `yc_engine.py` | the YouTube study's fill engine plus per-trade exits (trails, partials, close-based stops, own time exits, percentage stops) and the multi-leg books (IT-02's two lots, PR-12/13's ladder) |
| `yc_run.py` | one book on one market, exactly as the desk runs it, and the pool contexts |
| `yc_markets.py`, `yc_checks.py` | research data in the desk's layouts; the checks (`python -I yc_checks.py 6`) |
| `results/checks.json` | the last check run |

## Checks (results/checks.json)

`yc_checks.py` cuts every market at 6 random minutes and runs every book again on the shorter data: the signals known
at the cut must equal the full run's field by field, and every trade closed before the cut must be identical. All 103
pass (30,575 signals and 29,335 trades on recent research data). It also checks that each fill lies inside its bar's
price range plus the spread and slippage charged: no optimistic fill in any book. `premium-paper-service/test_yc.py`
runs every book through the desk's own runner, documents and ledger.

The check found one look-ahead in the inherited book logic (yt_engine.run_book takes signals in the order they were
placed, so an order resting for several bars that filled late could block a newer order that filled first, depending
on data after that fill). `yc_engine.run_book_x` takes positions in the order orders fill: an order is placed only
while flat, the first to fill takes the position and the others still resting are cancelled. With market orders it is
identical to run_book (verified on 10 books).

## Decisions worth knowing

- Markets: Indian index rules on NIFTY / BANKNIFTY minutes (the futures stand in through Angel One's futures costs);
  VWAP and volume rules on the NSE stock pool (the index has no volume); crypto on Delta's BTCUSD (the desk has no
  ether account; NJ-33 reads Delta ETHUSD as its second coin); gold on Delta XAUTUSD; forex and the Nasdaq from the
  desk's feeds. PR-12's ladder books Delta's XAUTUSD at its own 0.001 contract size (book market `XAUTUSD`), because
  its 10% legs are a fraction of an ounce.
- Bitcoin trades 24 hours: rules without a time exit hold across days (the whole period is replayed every cycle);
  NJ-35 (out 23:30 IST), NJ-36 (out 16:00 New York) and TH-06 (out 05:25 IST) keep their own exits.
- Where a video gives no stop (TH-03, TH-04, TH-07) the book carries a far catastrophe stop (15%) and is sized on a
  stated risk unit (two Renko boxes; the distance to EMA 200).
- NJ-25 (buy at the close, sell at the next open) ranks its basket on the previous session's close: ranking on the
  same close that fills the order would peek at it.
- TG-06 and SS-05 (overnight NIFTY trades) decide at 15:28 / 15:15 on the minute data and exit at the next session's
  close / 09:20.
- The ladder's and the room trade's resting targets fill at the open when a bar gaps through them.
