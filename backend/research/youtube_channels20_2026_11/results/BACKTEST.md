# The 20-channel study: backtests (net of costs)

Run by zc_backtest.py through the paper desk's own code (yc_run.run, the 11-channel fill engine): next-bar fills at
the bid / ask with slippage and fees; Indian pools with the desk's 4-position rule. R = result / risk at entry, net.
% = the sum at the desk's risk a trade (1%; 0.25% in the NSE pools), no compounding. Windows: Nifty / Bank Nifty
500 sessions, gold 520 sessions, bitcoin 730 days, ether Aug-Oct 2026, NSE 5-minute pool 520 sessions (268 stocks),
NSE daily stocks from 2019, Nifty daily from 2016. These windows include the years the videos were made in: a
positive result is in-sample, not evidence of an edge.

| Strategy | Market | Trades | Win % | Net R / trade | Gross R | Cost R | Total R | % at desk risk | PF | Max DD R | t | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DH-01 | NIFTY | 72 | 33 | -0.547 | 0.009 | 0.556 | -39.4 | -39.4 | 0.47 | 40.2 | -3.15 | Not supported (loses after costs) |
| DH-02 | NSE5 | 376 | 34 | -0.197 | 0.038 | 0.234 | -74.0 | -18.5 | 0.74 | 96.6 | -2.67 | Not supported (loses after costs) |
| DH-03 | NIFTY | 176 | 35 | -0.897 | -0.111 | 0.786 | -157.9 | -157.9 | 0.15 | 157.9 | -10.80 | Not supported (loses after costs) |
| DH-04 | NIFTY | 183 | 31 | -0.520 | -0.029 | 0.491 | -95.2 | -95.2 | 0.49 | 98.6 | -4.88 | Not supported (loses after costs) |
| DH-05 | NSE5 | 2804 | 52 | -0.041 | 0.060 | 0.101 | -114.4 | -28.6 | 0.89 | 137.6 | -2.60 | Not supported (loses after costs) |
| DH-06 | NSE5 | 2932 | 64 | -0.081 | -0.022 | 0.059 | -237.5 | -59.4 | 0.74 | 243.9 | -6.85 | Not supported (loses after costs) |
| DH-07 | NIFTY | 396 | 34 | -0.223 | 0.185 | 0.408 | -88.2 | -88.2 | 0.66 | 114.8 | -3.05 | Not supported (loses after costs) |
| DH-08 | NIFTY | 830 | 22 | -0.868 | 0.060 | 0.928 | -720.1 | -720.1 | 0.18 | 721.2 | -22.27 | Not supported (loses after costs) |
| AX-01 | NIFTY | 477 | 38 | -0.205 | 0.105 | 0.310 | -97.9 | -97.9 | 0.73 | 107.7 | -3.28 | Not supported (loses after costs) |
| AX-01 | BANKNIFTY | 476 | 35 | -0.277 | -0.009 | 0.268 | -132.0 | -132.0 | 0.64 | 144.5 | -4.57 | Not supported (loses after costs) |
| AX-02 | NIFTY | 408 | 36 | -0.213 | 0.069 | 0.282 | -86.8 | -86.8 | 0.66 | 91.6 | -3.61 | Not supported (loses after costs) |
| AX-03 | NIFTY | 496 | 71 | -0.155 | 0.007 | 0.163 | -77.0 | -77.0 | 0.51 | 78.2 | -5.55 | Not supported (loses after costs) |
| AX-04 | NIFTY | 240 | 52 | -0.214 | 0.063 | 0.278 | -51.5 | -51.5 | 0.65 | 58.6 | -3.24 | Not supported (loses after costs) |
| AX-05 | NIFTY | 327 | 42 | -0.144 | 0.058 | 0.202 | -47.2 | -47.2 | 0.76 | 60.0 | -2.25 | Not supported (loses after costs) |
| AX-06 | BTCUSD | 116 | 34 | -0.196 | -0.055 | 0.141 | -22.7 | -22.7 | 0.62 | 25.3 | -2.12 | Not supported (loses after costs) |
| AB-01 | NSE5 | 983 | 34 | -0.286 | -0.001 | 0.286 | -281.3 | -70.3 | 0.62 | 296.7 | -6.17 | Not supported (loses after costs) |
| AB-02 | NSE15 | 2056 | 48 | -0.246 | 0.020 | 0.266 | -506.5 | -126.6 | 0.61 | 515.5 | -10.91 | Not supported (loses after costs) |
| AB-03 | NSE15 | 3734 | 40 | -0.099 | 0.066 | 0.165 | -370.3 | -92.6 | 0.81 | 386.7 | -5.31 | Not supported (loses after costs) |
| AB-04 | NSE5 | 1221 | 35 | -0.118 | -0.030 | 0.088 | -144.7 | -36.2 | 0.84 | 157.3 | -2.85 | Not supported (loses after costs) |
| AB-06 | NIFTY | 525 | 45 | -0.514 | 0.053 | 0.567 | -270.0 | -270.0 | 0.35 | 270.5 | -10.69 | Not supported (loses after costs) |
| TS-01 | NIFTY | 263 | 38 | -0.157 | 0.091 | 0.248 | -41.3 | -41.3 | 0.76 | 43.1 | -2.03 | Not supported (loses after costs) |
| TS-01 | BANKNIFTY | 259 | 32 | -0.285 | -0.071 | 0.214 | -73.9 | -73.9 | 0.60 | 76.1 | -3.82 | Not supported (loses after costs) |
| TS-02 | NIFTY | 301 | 45 | -0.174 | 0.166 | 0.340 | -52.5 | -52.5 | 0.73 | 53.7 | -2.50 | Not supported (loses after costs) |
| TS-02 | BANKNIFTY | 299 | 38 | -0.298 | -0.014 | 0.284 | -89.2 | -89.2 | 0.56 | 90.6 | -4.44 | Not supported (loses after costs) |
| TS-03 | NSE15 | 2635 | 32 | -0.055 | 0.038 | 0.093 | -144.4 | -36.1 | 0.79 | 162.5 | -4.50 | Not supported (loses after costs) |
| TS-04 | XAUUSD | 580 | 31 | -0.104 | 0.029 | 0.133 | -60.3 | -60.3 | 0.85 | 74.2 | -1.85 | Not supported (loses after costs) |
| TS-05 | BTCUSD | 3182 | 25 | -1.378 | 0.059 | 1.437 | -4386.3 | -4386.3 | 0.07 | 4387.2 | -58.47 | Not supported (loses after costs) |
| PV-02 | NIFTY | 618 | 40 | -0.460 | 0.040 | 0.500 | -284.0 | -284.0 | 0.47 | 286.3 | -9.17 | Not supported (loses after costs) |
| PV-02 | NSE5 | 20094 | 32 | -0.544 | -0.101 | 0.443 | -10928.9 | -2732.2 | 0.41 | 10931.8 | -63.59 | Not supported (loses after costs) |
| PV-03 | NIFTY | 234 | 40 | -0.254 | -0.063 | 0.191 | -59.4 | -59.4 | 0.51 | 63.6 | -4.62 | Not supported (loses after costs) |
| PV-04 | BTCUSD | 386 | 40 | -0.157 | 0.020 | 0.177 | -60.6 | -60.6 | 0.67 | 67.2 | -3.32 | Not supported (loses after costs) |
| UP-01 | NIFTY | 456 | 55 | -0.343 | -0.021 | 0.323 | -156.5 | -156.5 | 0.31 | 158.3 | -9.19 | Not supported (loses after costs) |
| UP-01 | BANKNIFTY | 447 | 66 | -0.256 | -0.017 | 0.239 | -114.4 | -114.4 | 0.31 | 115.1 | -8.21 | Not supported (loses after costs) |
| UP-02 | NSE5 | 1313 | 25 | -0.041 | 0.043 | 0.084 | -53.6 | -13.4 | 0.84 | 70.6 | -2.04 | Not supported (loses after costs) |
| UP-03 | NSE15 | 5542 | 34 | -0.163 | 0.023 | 0.186 | -902.1 | -225.5 | 0.69 | 921.2 | -9.61 | Not supported (loses after costs) |
| UP-04 | NIFTY | 497 | 30 | -0.253 | -0.026 | 0.226 | -125.5 | -125.5 | 0.52 | 127.5 | -6.14 | Not supported (loses after costs) |
| UP-05 | NIFTY | 2 | 0 | -1.359 | -0.955 | 0.404 | -2.7 | -2.7 | 0.00 | 2.7 | - | Too few trades to judge |
| UP-06 | NIFTY | 1409 | 30 | -1.134 | -0.222 | 0.912 | -1597.3 | -1597.3 | 0.15 | 1598.0 | -22.47 | Not supported (loses after costs) |
| VT-01 | NIFTY | 522 | 36 | -0.302 | 0.029 | 0.331 | -157.6 | -157.6 | 0.56 | 165.4 | -5.97 | Not supported (loses after costs) |
| VT-01 | BANKNIFTY | 543 | 36 | -0.228 | 0.061 | 0.289 | -123.8 | -123.8 | 0.64 | 127.2 | -4.61 | Not supported (loses after costs) |
| VT-02 | NSED | 213 | 44 | 0.517 | 0.529 | 0.012 | 110.2 | 110.2 | 2.47 | 10.9 | 3.63 | Positive after costs (t >= 2), in-sample only |
| VT-03 | NSED | 2076 | 31 | 0.083 | 0.143 | 0.060 | 172.9 | 172.9 | 1.13 | 104.7 | 1.63 | Positive after costs, not significant |
| TB-01 | NIFTY | 465 | 41 | -0.070 | 0.146 | 0.215 | -32.4 | -32.4 | 0.88 | 50.6 | -1.16 | Not supported (loses after costs) |
| TB-02 | NIFTY | 735 | 36 | -0.139 | 0.066 | 0.205 | -102.4 | -102.4 | 0.79 | 128.7 | -2.63 | Not supported (loses after costs) |
| TB-04 | NIFTY_D | 48 | 50 | 0.751 | 0.765 | 0.014 | 36.1 | 36.1 | 3.16 | 3.8 | 2.50 | Positive after costs (t >= 2), in-sample only |
| DE-01 | BTCUSD | 5 | 0 | -3.137 | 0.061 | 3.197 | -15.7 | -15.7 | 0.00 | 15.7 | -4.03 | Too few trades to judge |
| DE-02 | BTCUSD | 6163 | 26 | -0.989 | 0.009 | 0.998 | -6095.8 | -6095.8 | 0.27 | 6095.8 | -52.45 | Not supported (loses after costs) |
| DE-03 | BTCUSD | 34 | 18 | -0.576 | 0.271 | 0.848 | -19.6 | -19.6 | 0.44 | 20.8 | -1.77 | Not supported (loses after costs) |
| DE-04 | XAUUSD | 57 | 44 | 0.959 | 0.977 | 0.018 | 54.7 | 54.7 | 2.62 | 19.6 | 2.02 | Positive after costs (t >= 2), in-sample only |
| DE-07 | BTCUSD | 521 | 43 | -0.530 | 0.011 | 0.541 | -276.1 | -276.1 | 0.32 | 276.5 | -11.64 | Not supported (loses after costs) |
| TP-01 | XAUUSD | 143 | 44 | -0.014 | 0.143 | 0.157 | -2.0 | -2.0 | 0.97 | 14.1 | -0.14 | Not supported (loses after costs) |
| TP-01H | XAUUSD | 12 | 67 | 0.598 | 0.640 | 0.042 | 7.2 | 7.2 | 2.78 | 2.0 | 1.66 | Too few trades to judge |
| TP-02 | XAUUSD | 1260 | 31 | -0.183 | -0.012 | 0.171 | -230.7 | -230.7 | 0.73 | 238.7 | -5.11 | Not supported (loses after costs) |
| TP-03 | XAUUSD | 29 | 21 | -0.409 | -0.234 | 0.175 | -11.9 | -11.9 | 0.48 | 11.9 | -1.88 | Too few trades to judge |
| TP-03 | BTCUSD | 47 | 32 | -0.647 | 0.068 | 0.716 | -30.4 | -30.4 | 0.40 | 33.5 | -3.07 | Not supported (loses after costs) |
| TP-04 | XAUUSD | 207 | 20 | -0.434 | -0.103 | 0.331 | -89.9 | -89.9 | 0.49 | 89.9 | -4.28 | Not supported (loses after costs) |
| TP-04 | BTCUSD | 306 | 21 | -2.000 | 0.290 | 2.291 | -612.1 | -612.1 | 0.18 | 612.1 | -7.44 | Not supported (loses after costs) |
| TP-05 | XAUUSD | 265 | 25 | -0.295 | -0.120 | 0.176 | -78.2 | -78.2 | 0.61 | 78.2 | -3.80 | Not supported (loses after costs) |
| TP-05 | BTCUSD | 446 | 31 | -0.623 | 0.072 | 0.694 | -277.7 | -277.7 | 0.42 | 279.5 | -8.85 | Not supported (loses after costs) |
| DT-01 | BTCUSD | 281 | 39 | -0.107 | -0.003 | 0.104 | -30.2 | -30.2 | 0.84 | 37.9 | -1.47 | Not supported (loses after costs) |
| DT-01 | XAUUSD | 223 | 45 | 0.118 | 0.148 | 0.030 | 26.3 | 26.3 | 1.21 | 13.0 | 1.39 | Positive after costs, not significant |
| DT-02 | BTCUSD | 1170 | 50 | -0.180 | 0.046 | 0.225 | -210.3 | -210.3 | 0.70 | 211.8 | -6.04 | Not supported (loses after costs) |
| DT-02 | XAUUSD | 680 | 51 | 0.015 | 0.063 | 0.048 | 10.2 | 10.2 | 1.03 | 20.8 | 0.38 | Positive after costs, not significant |
| DT-03 | BTCUSD | 515 | 39 | -0.238 | 0.067 | 0.305 | -122.5 | -122.5 | 0.66 | 125.1 | -4.58 | Not supported (loses after costs) |
| DT-03 | XAUUSD | 347 | 40 | -0.023 | 0.066 | 0.089 | -8.0 | -8.0 | 0.96 | 25.9 | -0.37 | Not supported (loses after costs) |
| DT-04 | BTCUSD | 24 | 29 | 0.578 | 0.728 | 0.151 | 13.9 | 13.9 | 1.36 | 13.7 | 0.48 | Too few trades to judge |
| DT-05 | BTCUSD | 1540 | 38 | -0.259 | 0.002 | 0.260 | -398.2 | -398.2 | 0.61 | 398.2 | -9.17 | Not supported (loses after costs) |
| DT-06 | BTCUSD | 1378 | 31 | -0.556 | 0.016 | 0.572 | -766.3 | -766.3 | 0.44 | 768.6 | -14.59 | Not supported (loses after costs) |
| DT-06 | XAUUSD | 1051 | 32 | -0.184 | -0.034 | 0.150 | -193.4 | -193.4 | 0.73 | 206.3 | -4.78 | Not supported (loses after costs) |
| DT-07 | BTCUSD | 12 | 17 | -1.207 | -0.321 | 0.887 | -14.5 | -14.5 | 0.19 | 14.5 | -2.76 | Too few trades to judge |
| DT-07 | XAUUSD | 13 | 8 | -0.794 | -0.604 | 0.189 | -10.3 | -10.3 | 0.16 | 10.3 | -3.44 | Too few trades to judge |
| DT-08 | BTCUSD | 2875 | 26 | -1.100 | 0.064 | 1.165 | -3163.1 | -3163.1 | 0.24 | 3164.8 | -37.87 | Not supported (loses after costs) |
| DT-08 | XAUUSD | 1757 | 26 | -0.302 | 0.053 | 0.355 | -530.8 | -530.8 | 0.62 | 534.7 | -9.61 | Not supported (loses after costs) |
| TL-01 | BTCUSD | 152 | 38 | -0.296 | -0.001 | 0.296 | -45.0 | -45.0 | 0.63 | 46.3 | -2.85 | Not supported (loses after costs) |
| TL-01 | XAUUSD | 102 | 37 | -0.081 | 0.017 | 0.098 | -8.2 | -8.2 | 0.87 | 16.9 | -0.67 | Not supported (loses after costs) |
| TL-02 | BTCUSD | 979 | 32 | -0.338 | -0.062 | 0.276 | -331.0 | -331.0 | 0.57 | 338.1 | -8.06 | Not supported (loses after costs) |
| TL-02 | XAUUSD | 725 | 33 | -0.134 | -0.054 | 0.079 | -96.9 | -96.9 | 0.79 | 104.5 | -2.90 | Not supported (loses after costs) |
| TL-03 | BTCUSD | 1313 | 29 | -0.218 | -0.003 | 0.216 | -286.7 | -286.7 | 0.65 | 303.6 | -5.20 | Not supported (loses after costs) |
| TL-04 | BTCUSD | 2134 | 32 | -0.307 | 0.003 | 0.310 | -654.5 | -654.5 | 0.59 | 660.2 | -11.14 | Not supported (loses after costs) |
| TL-04 | XAUUSD | 1304 | 38 | -0.035 | 0.059 | 0.094 | -46.1 | -46.1 | 0.94 | 64.9 | -1.04 | Not supported (loses after costs) |
| JR-01 | BTCUSD | 504 | 32 | -0.640 | 0.079 | 0.719 | -322.5 | -322.5 | 0.42 | 322.6 | -8.86 | Not supported (loses after costs) |
| JR-01 | XAUUSD | 341 | 32 | -0.154 | -0.013 | 0.141 | -52.6 | -52.6 | 0.77 | 58.1 | -2.24 | Not supported (loses after costs) |
| JR-02 | BTCUSD | 636 | 36 | -0.574 | 0.077 | 0.651 | -364.8 | -364.8 | 0.34 | 367.4 | -11.43 | Not supported (loses after costs) |
| JR-03 | BTCUSD | 680 | 27 | -0.856 | -0.021 | 0.835 | -582.3 | -582.3 | 0.32 | 582.3 | -14.21 | Not supported (loses after costs) |
| JR-03 | XAUUSD | 499 | 30 | -0.131 | 0.072 | 0.204 | -65.5 | -65.5 | 0.82 | 79.0 | -2.14 | Not supported (loses after costs) |
| JR-04 | BTCUSD | 488 | 27 | -0.729 | -0.046 | 0.683 | -355.8 | -355.8 | 0.36 | 356.1 | -11.24 | Not supported (loses after costs) |
| JR-04 | XAUUSD | 343 | 32 | -0.127 | 0.029 | 0.156 | -43.7 | -43.7 | 0.82 | 50.3 | -1.77 | Not supported (loses after costs) |
| JR-05 | BTCUSD | 411 | 18 | -1.269 | -0.007 | 1.262 | -521.5 | -521.5 | 0.24 | 521.5 | -14.67 | Not supported (loses after costs) |
| JR-05 | XAUUSD | 197 | 20 | -0.298 | 0.003 | 0.301 | -58.6 | -58.6 | 0.65 | 60.5 | -2.67 | Not supported (loses after costs) |
| DR-01 | BTCUSD | 2285 | 27 | -1.075 | 0.064 | 1.138 | -2455.4 | -2455.4 | 0.27 | 2457.4 | -25.88 | Not supported (loses after costs) |
| DR-01 | XAUUSD | 1467 | 27 | -0.261 | 0.038 | 0.299 | -383.3 | -383.3 | 0.67 | 389.7 | -7.29 | Not supported (loses after costs) |
| DR-02 | XAUUSD | 2798 | 27 | -0.258 | 0.022 | 0.280 | -721.8 | -721.8 | 0.67 | 728.9 | -10.29 | Not supported (loses after costs) |
| DR-02 | BTCUSD | 4132 | 27 | -0.968 | 0.047 | 1.015 | -3999.7 | -3999.7 | 0.28 | 3999.7 | -40.12 | Not supported (loses after costs) |
| DR-03 | BTCUSD | 2719 | 31 | -0.441 | 0.014 | 0.455 | -1198.2 | -1198.2 | 0.54 | 1199.8 | -15.90 | Not supported (loses after costs) |
| DR-04 | ETHUSD | 18 | 33 | -0.926 | 0.508 | 1.434 | -16.7 | -16.7 | 0.34 | 20.5 | -1.95 | Too few trades to judge |
| RU-01 | BTCUSD | 175 | 36 | -0.204 | -0.072 | 0.132 | -35.7 | -35.7 | 0.71 | 37.1 | -2.25 | Not supported (loses after costs) |
| RU-01 | XAUUSD | 115 | 46 | 0.142 | 0.176 | 0.034 | 16.3 | 16.3 | 1.26 | 8.6 | 1.20 | Positive after costs, not significant |
| RU-02 | BTCUSD | 1210 | 37 | -0.224 | -0.020 | 0.204 | -271.2 | -271.2 | 0.61 | 276.0 | -7.77 | Not supported (loses after costs) |
| RU-02 | XAUUSD | 795 | 42 | -0.056 | 0.011 | 0.067 | -44.7 | -44.7 | 0.88 | 54.4 | -1.60 | Not supported (loses after costs) |
| RU-03 | BTCUSD | 417 | 41 | -0.081 | 0.048 | 0.129 | -34.0 | -34.0 | 0.83 | 39.5 | -1.71 | Not supported (loses after costs) |
| RU-03 | XAUUSD | 316 | 48 | 0.044 | 0.093 | 0.049 | 13.8 | 13.8 | 1.11 | 12.2 | 0.81 | Positive after costs, not significant |
| RU-04 | BTCUSD | 1178 | 38 | -0.158 | 0.022 | 0.179 | -185.7 | -185.7 | 0.71 | 190.0 | -5.31 | Not supported (loses after costs) |
| RU-04 | XAUUSD | 832 | 45 | 0.039 | 0.097 | 0.058 | 32.6 | 32.6 | 1.09 | 18.3 | 1.10 | Positive after costs, not significant |
| PT-01 | XAUUSD | 3998 | 24 | -0.350 | -0.012 | 0.338 | -1398.3 | -1398.3 | 0.57 | 1403.0 | -17.29 | Not supported (loses after costs) |
| PT-02 | XAUUSD | 233 | 26 | -0.315 | 0.002 | 0.318 | -73.4 | -73.4 | 0.60 | 78.8 | -3.74 | Not supported (loses after costs) |
| PT-03 | XAUUSD | 86 | 13 | -0.475 | -0.258 | 0.217 | -40.9 | -40.9 | 0.47 | 45.3 | -2.86 | Not supported (loses after costs) |
| PT-03 | BTCUSD | 107 | 21 | -0.729 | 0.105 | 0.834 | -78.0 | -78.0 | 0.47 | 78.2 | -3.25 | Not supported (loses after costs) |
| PT-04 | BTCUSD | 270 | 33 | -0.197 | 0.024 | 0.221 | -53.2 | -53.2 | 0.75 | 66.4 | -2.28 | Not supported (loses after costs) |
| PT-04 | XAUUSD | 260 | 28 | -0.192 | -0.064 | 0.128 | -49.8 | -49.8 | 0.74 | 59.6 | -2.25 | Not supported (loses after costs) |
| TF-01 | XAUUSD | 1374 | 21 | -0.209 | 0.019 | 0.227 | -286.9 | -286.9 | 0.74 | 292.2 | -4.65 | Not supported (loses after costs) |
| TF-01 | BTCUSD | 2123 | 25 | -0.618 | 0.163 | 0.781 | -1311.6 | -1311.6 | 0.49 | 1315.5 | -15.27 | Not supported (loses after costs) |
| TD-01 | XAUUSD | 117 | 35 | -0.134 | 0.052 | 0.186 | -15.7 | -15.7 | 0.79 | 23.1 | -1.23 | Not supported (loses after costs) |
| TD-01 | BTCUSD | 165 | 30 | -0.715 | -0.063 | 0.651 | -117.9 | -117.9 | 0.29 | 118.6 | -7.65 | Not supported (loses after costs) |
| TD-02 | XAUUSD | 1988 | 21 | -0.251 | 0.025 | 0.276 | -499.3 | -499.3 | 0.66 | 502.7 | -5.66 | Not supported (loses after costs) |
| TD-02 | BTCUSD | 998 | 23 | -0.369 | 0.226 | 0.595 | -368.1 | -368.1 | 0.63 | 432.2 | -3.53 | Not supported (loses after costs) |
| TD-03 | BTCUSD | 1092 | 36 | -0.196 | 0.029 | 0.225 | -214.1 | -214.1 | 0.69 | 224.5 | -5.50 | Not supported (loses after costs) |
| TD-03 | XAUUSD | 728 | 36 | -0.108 | -0.032 | 0.076 | -78.5 | -78.5 | 0.80 | 82.4 | -2.57 | Not supported (loses after costs) |
| TD-04 | BTCUSD | 929 | 28 | -0.124 | -0.033 | 0.092 | -115.6 | -115.6 | 0.58 | 115.7 | -5.77 | Not supported (loses after costs) |
| TD-04 | XAUUSD | 620 | 38 | -0.014 | 0.012 | 0.026 | -8.9 | -8.9 | 0.94 | 19.3 | -0.58 | Not supported (loses after costs) |
| TD-05 | XAUUSD | 64 | 38 | -0.137 | -0.075 | 0.062 | -8.7 | -8.7 | 0.74 | 12.3 | -1.07 | Not supported (loses after costs) |
| TD-05 | BTCUSD | 100 | 33 | -0.298 | -0.053 | 0.245 | -29.8 | -29.8 | 0.55 | 29.8 | -2.62 | Not supported (loses after costs) |
| FZ-01 | XAUUSD | 523 | 22 | -0.182 | -0.025 | 0.156 | -95.0 | -95.0 | 0.71 | 105.7 | -3.42 | Not supported (loses after costs) |
| FZ-02 | XAUUSD | 179 | 18 | -0.177 | 0.007 | 0.184 | -31.7 | -31.7 | 0.69 | 43.8 | -1.95 | Not supported (loses after costs) |
| MH-01 | XAUUSD | 451 | 38 | 0.087 | 0.181 | 0.094 | 39.3 | 39.3 | 1.14 | 20.2 | 1.32 | Positive after costs, not significant |
| MH-02 | XAUUSD | 2128 | 25 | -0.233 | 0.024 | 0.257 | -495.9 | -495.9 | 0.70 | 497.9 | -6.42 | Not supported (loses after costs) |
| MH-02 | BTCUSD | 2909 | 24 | -0.820 | 0.032 | 0.853 | -2386.7 | -2386.7 | 0.36 | 2386.7 | -25.31 | Not supported (loses after costs) |
| MH-03 | XAUUSD | 7 | 0 | -1.040 | -0.855 | 0.185 | -7.3 | -7.3 | 0.00 | 7.3 | -134.02 | Too few trades to judge |
| MH-03 | BTCUSD | 6 | 17 | -0.664 | -0.138 | 0.526 | -4.0 | -4.0 | 0.45 | 5.5 | -0.85 | Too few trades to judge |

Books: 128; positive after costs: 12.
