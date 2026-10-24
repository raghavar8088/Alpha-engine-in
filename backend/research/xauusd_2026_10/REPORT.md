# XAUUSD strategies targeting 2% a trade

**Data:** Dukascopy XAUUSD bid/ask hourly, mid prices, New York-close sessions · **In-sample** 2010-01 → 2021-09 · **Out-of-sample** 2021-10 → 2026-10-23 · **Locked** 2026-10-24T07:55:51+00:00 (code `2e704d054e71ff37`, lock `0b73dd53bc113bec`) · **Configurations tested** 238

**1 of 23** strategy families pass the brief's test (out-of-sample average ≥ 2% a trade after base costs, ≥ 8 trades, profit factor > 1). Gold itself returned +105% over the out-of-sample period after financing.

| # | Strategy | Verdict | IS trades | IS avg | OOS trades | OOS avg | OOS PF | OOS avg (harsh) | OOS return Oct 2021–Dec 2023 | OOS return Jan 2024– | Drift alone | Timing p (Holm) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Time-series momentum (Moskowitz, Ooi & Pedersen; Bartsch et al.) (`lookback=6, direction=long_short`) | **PASS** (small sample): +4.14% a trade over 12 out-of-sample trades | 27 | +2.83% | 12 | +4.14% | 2.30 | +3.48% | −30.8% | +84.2% | +5.64% | 1.000 |
| 2 | Faber monthly SMA timing (`months=8, direction=long`) | **FAIL**: only 3 out-of-sample trades | 14 | +3.68% | 3 | +38.39% | 1656.08 | +36.45% | +2.6% | +109.7% | +32.38% | 1.000 |
| 3 | Winter effect (Potrykus & Augustynowicz 2024) (`mode=dec_feb`) | **FAIL**: only 5 out-of-sample trades | 12 | +3.42% | 5 | +8.17% | 37.56 | +7.78% | +9.9% | +32.3% | +3.73% | 0.823 |
| 4 | Gold monthly moving-average rules (Bartsch, Baur, Dichtl & Drobetz) (`pair=(2, 9)`) | **FAIL**: only 3 out-of-sample trades | 12 | +4.80% | 3 | +26.52% | 17.62 | +24.58% | −4.3% | +83.6% | +32.17% | 1.000 |
| 5 | Moving-average crossover (Brock, Lakonishok & LeBaron; golden cross) (`pair=(1, 200), band=0.01, direction=long`) | **FAIL**: only 6 out-of-sample trades | 17 | +2.76% | 6 | +15.99% | 9.74 | +14.98% | −3.3% | +92.1% | +16.60% | 1.000 |
| 6 | Bollinger Band squeeze breakout (`tol=0.1, window=20, exit=mid, direction=long`) | **FAIL**: out-of-sample average +1.17% < 2% | 17 | +2.35% | 11 | +1.17% | 2.41 | +1.05% | +2.3% | +10.3% | +0.91% | 1.000 |
| 7 | Ichimoku cloud trend (`timeframe=daily, exit=kijun, direction=long`) | **FAIL**: no in-sample configuration reached 2% a trade (best +1.99% with ≥12 trades) | 145 | +0.20% | 96 | +0.52% | 1.93 | +0.46% | −2.1% | +60.9% | – | – |
| 8 | Weinstein stage analysis (30-week MA) (`weeks=30, rising=True, direction=long`) | **FAIL**: no in-sample configuration reached 2% a trade (best +1.99% with ≥12 trades) | 21 | +1.99% | 8 | +12.73% | 9.61 | +12.06% | −9.0% | +109.4% | – | – |
| 9 | Turtle breakout (System 1 / System 2) (`entry_exit=(55, 20), stop_n=2.0, direction=long_short, filter_s1=False`) | **FAIL**: no in-sample configuration reached 2% a trade (best +1.41% with ≥12 trades) | 60 | +0.19% | 20 | +2.67% | 3.04 | +2.44% | −1.1% | +57.8% | – | – |
| 10 | Keltner / ATR channel breakout (`n=20, k=2.0, direction=long_short`) | **FAIL**: no in-sample configuration reached 2% a trade (best +1.39% with ≥12 trades) | 71 | −0.20% | 27 | +0.48% | 1.40 | +0.36% | +6.9% | +3.6% | – | – |
| 11 | Breakout with LeBeau chandelier exit (`entry_n=50, k=3.0, direction=long_short`) | **FAIL**: no in-sample configuration reached 2% a trade (best +1.29% with ≥12 trades) | 70 | +0.40% | 32 | +1.07% | 1.79 | +0.96% | +10.3% | +21.3% | – | – |
| 12 | Clenow core trend model (`breakout=50, atr_mult=3.0, direction=long_short`) | **FAIL**: no in-sample configuration reached 2% a trade (best +0.99% with ≥12 trades) | 47 | +0.42% | 23 | +1.80% | 2.34 | +1.67% | +3.5% | +39.0% | – | – |
| 13 | Bollinger Band reversion (`k=2.0, trend=none, direction=long`) | **FAIL**: no in-sample configuration reached 2% a trade (best +0.98% with ≥12 trades) | 56 | +0.27% | 19 | +0.11% | 1.12 | +0.02% | −1.2% | +3.5% | – | – |
| 14 | Connors RSI(2) pullback (`threshold=10, exit_ma=5, direction=long`) | **FAIL**: no in-sample configuration reached 2% a trade (best +0.88% with ≥12 trades) | 72 | +0.27% | 33 | +0.33% | 1.52 | +0.28% | −3.0% | +13.6% | – | – |
| 15 | Wilder DMI / ADX trend (`adx_min=25, direction=long_short`) | **FAIL**: no in-sample configuration reached 2% a trade (best +0.82% with ≥12 trades) | 84 | −0.12% | 40 | +0.12% | 1.09 | −0.01% | −10.2% | +13.1% | – | – |
| 16 | Volatility-shock continuation (`k=2.5, hold=10, stop=none`) | **FAIL**: no in-sample configuration reached 2% a trade (best +0.59% with ≥12 trades) | 80 | +0.19% | 33 | −0.18% | 0.89 | −0.25% | +6.2% | −13.8% | – | – |
| 17 | MACD(12,26,9) trend (`timeframe=daily, zero_filter=False, direction=long`) | **FAIL**: no in-sample configuration reached 2% a trade (best +0.55% with ≥12 trades) | 114 | +0.33% | 58 | +0.59% | 1.59 | +0.50% | +3.7% | +30.0% | – | – |
| 18 | Connors Double 7s (`n=7, direction=long`) | **FAIL**: no in-sample configuration reached 2% a trade (best +0.35% with ≥12 trades) | 94 | +0.33% | 48 | +0.53% | 1.65 | +0.47% | −9.1% | +38.8% | – | – |
| 19 | Crabel NR7 / ID-NR4 breakout (`pattern=NR7, hold=1, direction=long_short`) | **FAIL**: no in-sample configuration reached 2% a trade (best +0.24% with ≥12 trades) | 434 | +0.03% | 195 | +0.04% | 1.12 | +0.02% | +3.3% | +3.9% | – | – |
| 20 | Larry Williams volatility breakout (`k=0.75, exit=bailout, direction=long_short`) | **FAIL**: no in-sample configuration reached 2% a trade (best +0.15% with ≥12 trades) | 1136 | +0.01% | 511 | −0.02% | 0.96 | −0.04% | −17.3% | +6.2% | – | – |
| 21 | London breakout of the Asian range (`tp_r=2.5, range_filter=True`) | **FAIL**: no in-sample configuration reached 2% a trade (best −0.02% with ≥12 trades) | 1975 | −0.02% | 995 | +0.03% | 1.12 | +0.01% | −3.0% | +38.9% | – | – |
| 22 | Overnight (Asia/London) session drift (`exit_hour=8`) | **FAIL**: no in-sample configuration reached 2% a trade (best −0.02% with ≥12 trades) | 3035 | −0.04% | 1307 | +0.03% | 1.11 | +0.01% | −15.4% | +60.6% | – | – |
| 23 | Autumn effect (Baur 2013) (`mode=sep_and_nov`) | **FAIL**: no in-sample configuration reached 2% a trade (best −2.48% with ≥12 trades) | 23 | −2.48% | 10 | +1.26% | 1.64 | +1.11% | +0.6% | +10.8% | – | – |

## Time-series momentum (Moskowitz, Ooi & Pedersen; Bartsch et al.)

- **Rules:** At each month end, the sign of the past k-month return over the T-bill decides the next month: long if positive; short (MOP) or cash (Bartsch et al.) if negative.
- **Stop-loss / take-profit:** No stop or target; the position is re-decided at every month end.
- **Locked parameters:** `lookback=6, direction=long_short`
- **Source:** Moskowitz, Ooi & Pedersen (2012). Time series momentum. Journal of Financial Economics 104(2), 228-250; gold lookbacks from Bartsch et al. (2018). (https://papers.ssrn.com/abstract=2089463)
- **Sizing:** published MOP scale each position to 40% annual volatility; Bartsch et al. 100% gold or cash; tested at 1× notional.
- **Deviations:** volatility scaling not applied (1x notional for every strategy)

| Metric | In-sample | Out-of-sample |
|---|---|---|
| Trades | 27 | 12 |
| Average net return a trade | +2.83% | +4.14% |
| Median trade | −0.53% | −2.48% |
| Win rate | 40.7% | 33.3% |
| Average win | +12.36% | +21.99% |
| Average loss | −3.73% | −4.79% |
| Profit factor | 2.28 | 2.30 |
| Longest losing streak (trades) | 4 | 6 |
| Total return | +73.1% | +28.4% |
| CAGR | +4.78% | +5.07% |
| Maximum drawdown | −26.1% | −38.7% |
| Sharpe ratio (daily, ×√252) | 0.38 | 0.35 |

Harsh-cost OOS average +3.48%; random entries average +5.64% (timing p 0.628, Holm 1.000); bootstrap 95% interval −4.65% to +19.65%; neighbours passing 4/8.

## Two more out-of-sample checks (added after the locked run)

**2005–2009** (never read by any stage; gold +139% after financing):

| Strategy | Trades | Avg / trade | PF | Random entries | Timing p |
|---|---|---|---|---|---|
| Faber monthly SMA timing (`months=8, direction=long`) | 7 | +9.35% | 6.38 | +11.02% | 0.618 |
| Gold monthly moving-average rules (Bartsch, Baur, Dichtl & Drobetz) (`pair=(2, 9)`) | 5 | +12.92% | 10.11 | +15.49% | 0.638 |
| Time-series momentum (Moskowitz, Ooi & Pedersen; Bartsch et al.) (`lookback=6, direction=long_short`) | 11 | +2.55% | 1.79 | +4.05% | 0.657 |
| Moving-average crossover (Brock, Lakonishok & LeBaron; golden cross) (`pair=(1, 200), band=0.01, direction=long`) | 9 | +6.44% | 3.36 | +8.55% | 0.721 |
| Bollinger Band squeeze breakout (`tol=0.1, window=20, exit=mid, direction=long`) | 9 | −1.06% | 0.13 | +0.81% | 0.881 |
| Winter effect (Potrykus & Augustynowicz 2024) (`mode=dec_feb`) | 6 | +7.53% | 6.47 | +3.72% | 0.138 |

**Walk-forward 2014 → latest** (parameters re-chosen each year from earlier years only; pass ≥ 20 trades, ≥ 2%, PF > 1):

| Family | Trades | Avg / trade | PF | Random entries | Timing p (Holm) | Pass |
|---|---|---|---|---|---|---|
| Faber monthly SMA timing | 12 | +8.78% | 4.63 | +4.42% | 1.000 |  |
| Gold monthly moving-average rules (Bartsch, Baur, Dichtl & Drobetz) | 3 | +24.22% | 8.52 | +12.64% | 1.000 |  |
| Time-series momentum (Moskowitz, Ooi & Pedersen; Bartsch et al.) | 30 | +2.88% | 1.99 | +1.24% | 1.000 | PASS |
| Moving-average crossover (Brock, Lakonishok & LeBaron; golden cross) | 57 | +0.77% | 1.40 | +0.92% | 1.000 |  |
| Turtle breakout (System 1 / System 2) | 2 | +0.23% | 1.08 | +1.07% | 1.000 |  |
| MACD(12,26,9) trend | 5 | −2.85% | 0.30 | −0.52% | 1.000 |  |
| Weinstein stage analysis (30-week MA) | 29 | −1.26% | 0.40 | +0.32% | 1.000 |  |
| Ichimoku cloud trend | 13 | +3.75% | 1.86 | +3.08% | 1.000 |  |
| Bollinger Band squeeze breakout | 14 | +0.15% | 1.12 | +0.41% | 1.000 |  |
| Keltner / ATR channel breakout | 6 | −0.45% | 0.74 | +0.51% | 1.000 |  |
| Winter effect (Potrykus & Augustynowicz 2024) | 7 | +2.07% | 2.23 | +1.72% | 1.000 |  |

## Failed

- **Faber monthly SMA timing**: only 3 out-of-sample trades.
- **Winter effect (Potrykus & Augustynowicz 2024)**: only 5 out-of-sample trades.
- **Gold monthly moving-average rules (Bartsch, Baur, Dichtl & Drobetz)**: only 3 out-of-sample trades.
- **Moving-average crossover (Brock, Lakonishok & LeBaron; golden cross)**: only 6 out-of-sample trades.
- **Bollinger Band squeeze breakout**: out-of-sample average +1.17% < 2%.
- **Ichimoku cloud trend**: no in-sample configuration reached 2% a trade (best +1.99% with ≥12 trades).
- **Weinstein stage analysis (30-week MA)**: no in-sample configuration reached 2% a trade (best +1.99% with ≥12 trades).
- **Turtle breakout (System 1 / System 2)**: no in-sample configuration reached 2% a trade (best +1.41% with ≥12 trades).
- **Keltner / ATR channel breakout**: no in-sample configuration reached 2% a trade (best +1.39% with ≥12 trades).
- **Breakout with LeBeau chandelier exit**: no in-sample configuration reached 2% a trade (best +1.29% with ≥12 trades).
- **Clenow core trend model**: no in-sample configuration reached 2% a trade (best +0.99% with ≥12 trades).
- **Bollinger Band reversion**: no in-sample configuration reached 2% a trade (best +0.98% with ≥12 trades).
- **Connors RSI(2) pullback**: no in-sample configuration reached 2% a trade (best +0.88% with ≥12 trades).
- **Wilder DMI / ADX trend**: no in-sample configuration reached 2% a trade (best +0.82% with ≥12 trades).
- **Volatility-shock continuation**: no in-sample configuration reached 2% a trade (best +0.59% with ≥12 trades).
- **MACD(12,26,9) trend**: no in-sample configuration reached 2% a trade (best +0.55% with ≥12 trades).
- **Connors Double 7s**: no in-sample configuration reached 2% a trade (best +0.35% with ≥12 trades).
- **Crabel NR7 / ID-NR4 breakout**: no in-sample configuration reached 2% a trade (best +0.24% with ≥12 trades).
- **Larry Williams volatility breakout**: no in-sample configuration reached 2% a trade (best +0.15% with ≥12 trades).
- **London breakout of the Asian range**: no in-sample configuration reached 2% a trade (best −0.02% with ≥12 trades).
- **Overnight (Asia/London) session drift**: no in-sample configuration reached 2% a trade (best −0.02% with ≥12 trades).
- **Autumn effect (Baur 2013)**: no in-sample configuration reached 2% a trade (best −2.48% with ≥12 trades).

Code, data checks and full results: this folder (`results/`). Backtests on past prices; not a forecast.
