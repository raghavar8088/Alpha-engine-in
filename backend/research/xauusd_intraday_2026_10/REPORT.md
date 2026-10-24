# Intraday XAUUSD strategies: can one make 2% a trade?

One-minute bars (HistData = Dukascopy bid, New York time with DST), mid prices, 11 published intraday families, 100 configurations. In-sample 2010-01-04 -> 2021-09-30; out-of-sample 2021-10-01 -> 2026-10-16. Locked code `6afbfebbaaa71054`, lock `df8df29dab201b56`.

2% of the account a trade at up to 20x leverage needs 0.10% a trade on the position after costs. Pass: out of sample, >= 50 trades, average >= 0.10%, profit factor > 1.

| Strategy | Verdict | IS trades | IS avg | OOS trades | OOS avg | OOS PF | OOS harsh | Random days | Leverage for 2% | 20x account OOS |
|---|---|---|---|---|---|---|---|---|---|---|
| Opening-range breakout, first bar (Zarattini & Aziz) (`anchor=comex, or_len=5, target=10R, exit=end`) | FAIL in-sample (best −0.023%) | 3018 | −0.031% | 1253 | −0.025% | 0.79 | −0.043% | −0.028% | never | −100% |
| Crabel opening-range breakout with the stretch (`anchor=comex, k=1.0, stop=opposite`) | FAIL in-sample (best −0.026%) | 2962 | −0.032% | 1168 | −0.005% | 0.98 | −0.022% | −0.029% | never | −100% |
| Williams volatility breakout, day-trade form (`k=0.5, direction=long_short, stop=none`) | FAIL in-sample (best +0.040%) | 1280 | −0.017% | 896 | +0.017% | 1.06 | −0.000% | −0.026% | 115x | −100% (zero on 2026-02-06) |
| London breakout of the Asian range (`tp_r=2.5, range_filter=True, breakeven=True`) | FAIL in-sample (best −0.005%) | 1949 | −0.014% | 992 | +0.035% | 1.14 | +0.017% | −0.029% | 58x | −45% |
| Intraday momentum, first half-hour (Gao, Han, Li & Zhou) (`window=comex, predictor=first`) | FAIL in-sample (best −0.040%) | 2982 | −0.042% | 1183 | −0.027% | 0.59 | −0.045% | −0.028% | never | −100% |
| Noise-area intraday momentum (Zarattini, Aziz & Barbon) (`anchor=comex, check=30, mult=1.0`) | FAIL in-sample (best −0.035%) | 4068 | −0.041% | 1590 | −0.031% | 0.81 | −0.048% | −0.028% | never | −100% |
| Asia/London session drift (`exit=ny0800`) | FAIL in-sample (best −0.021%) | 1816 | −0.037% | 1138 | +0.054% | 1.23 | +0.036% | +0.049% | 37x | −100% (zero on 2026-01-30) |
| London fix leakage (Caminschi & Heaney) (`fix=pm, window=2`) | FAIL in-sample (best −0.049%) | 3007 | −0.049% | 1248 | −0.027% | 0.58 | −0.045% | −0.028% | never | −100% |
| US payrolls-day breakout (`mode=straddle, exit=end, tp=3R`) | PASS as tested; fails with realistic fills | 135 | +0.123% | 55 | +0.249% | 2.61 | +0.231% | −0.026% | 8x | +889% |
| Floor-trader pivots (fade or breakout) (`mode=fade, window=london_ny`) | FAIL in-sample (best −0.037%) | 1828 | −0.037% | 772 | −0.060% | 0.76 | −0.078% | −0.028% | never | −100% (zero on 2026-01-30) |
| Bollinger reversion on intraday bars (`tf=15, k=2.0, direction=long_short`) | FAIL in-sample (best −0.035%) | 10911 | −0.043% | 4581 | −0.032% | 0.79 | −0.050% | −0.028% | never | −100% |

## The payroll straddle under stress

| Variant | In-sample avg | Out-of-sample avg |
|---|---|---|
| As tested (stops filled at their level) | +0.123% | +0.249% |
| Extra slippage +$1 a side | −0.022% | +0.166% |
| Extra slippage +$2 a side | −0.168% | +0.084% |
| Extra slippage +$3 a side | −0.314% | +0.001% |
| Extra slippage +$5 a side | −0.605% | −0.164% |
| Entry at the close of the trigger minute | −0.001% | +0.052% |
| Entry at the next minute's open | +0.001% | +0.051% |
| Placebo: non-payroll weekdays | −0.046% | −0.029% |

Accounts (total return, max drawdown): as_tested_10x: IS +282% / −35%, OOS +250% / −19%; as_tested_20x: IS +689% / −60%, OOS +889% / −35%; entry_at_trigger_close_10x: IS −31% / −58%, OOS +16% / −35%; entry_at_trigger_close_20x: IS −76% / −87%, OOS +6% / −61%

Backtests on past prices; not a forecast. Full report: report/xauusd-intraday-study.html.
