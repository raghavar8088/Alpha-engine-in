# Champion traders' intraday rules: do they work?

Rules registered first (PREREGISTRATION.md); one setting per rule and market chosen in-sample and locked (code `9d807cc9aad5ffd1`); out of sample run once. Average net return a trade out of sample, base costs (trades):

| Rule | Gold | S&P 500 | Nasdaq 100 | DAX |
|---|---|---|---|---|
| Crabel breakout, every day | +0.004% (1161) | +0.000% (1086) | +0.063% (1083) | +0.053% (717) |
| Crabel breakout after a narrow day | −0.063% (81) | +0.013% (53) | −0.022% (42) | +0.020% (38) |
| Williams volatility breakout | −0.039% (324) | +0.050% (425) | +0.078% (432) | +0.001% (549) |
| Williams Oops! gap reversal | −0.065% (60) | −0.017% (109) | +0.083% (107) | −0.051% (125) |
| Unger first-hours breakout | −0.019% (472) | +0.030% (500) | +0.043% (875) | +0.005% (637) |
| Unger false-breakout reversal | −0.029% (543) | −0.012% (612) | −0.011% (664) | −0.034% (401) |
| Unger time-of-day bias | −0.025% (1161) | −0.008% (1086) | −0.009% (1083) | −0.003% (728) |

No single rule passes. Unger's portfolio (14 rules that were profitable in-sample, equal shares): +0.25% a month out of sample at 1× (t 2.76; +0.19% at double costs), verdict WORKING. Gold: no rule better than break-even (best +0.004% a trade). Backtests; not a forecast.
