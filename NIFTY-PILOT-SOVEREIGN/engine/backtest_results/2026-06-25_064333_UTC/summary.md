# Backtest Summary

- **Period (IST):** 2023-10-01 → 2024-01-01
- **Data source:** Synthetic
- **Capital:** ₹10000000
- **Instruments:** [NIFTY50 BANKNIFTY]
- **Total trades:** 331
- **Kill events:** 2

## Walk-forward promotion (live rules: Sharpe ≥ 0.60, WinRate ≥ 0.48, two 30-trade windows)

### S1_ORB_Nifty_Breakout
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S2_VWAP_Reversion_BankNifty
Total trades: 41

- Window 1 (trades 1–30): Sharpe 0.92  WinRate 83%  MaxDD -12.4%  PF 6.57x → **PASS**
- Window 2 (trades 31–60): _not evaluated_ (INSUFFICIENT_DATA)
**Promotion: ✗ INSUFFICIENT_DATA** — Window 1 PASSED but only 41 trades total; need 60 for the confirmation window

---

### S3_IV_Crush_Theta_Decay
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S4_PCR_Extreme_Reversal
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S5_Max_Pain_Magnet
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S6_OI_Buildup_Directional
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S7_Gap_Fill_Opening
Total trades: 1

- Window 1 (trades 1–30): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → **INSUFFICIENT_DATA**
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 1 trades in backtest; need 30 for window 1

---

### S8_EMA_Ribbon_Trend_Rider
Total trades: 82

- Window 1 (trades 1–30): Sharpe 42.36  WinRate 100%  MaxDD 0.0%  PF ∞ → **PASS**
- Window 2 (trades 31–60): Sharpe 0.42  WinRate 90%  MaxDD -3.8%  PF 10.82x → **FAIL**
**Promotion: ✗ REJECTED** — Window 1 passed but Window 2 failed: Sharpe 0.42 < 0.60 (fast-demotion: flip to conservative)

---

### S9_Event_Volatility_Fade
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S10_Tick_Scalp_Bid_Ask_Compression
Total trades: 12

- Window 1 (trades 1–30): Sharpe -0.03  WinRate 42%  MaxDD 0.0%  PF 0.00x → **INSUFFICIENT_DATA**
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 12 trades in backtest; need 30 for window 1

---

### S11_Pullback_Scalp_VWAP_Micro
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S12_Volume_Spike_Scalp_Order_Flow
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S13_EMA_Ribbon_Scalp_Fast
Total trades: 10

- Window 1 (trades 1–30): Sharpe 1.63  WinRate 90%  MaxDD 0.0%  PF 0.00x → **INSUFFICIENT_DATA**
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 10 trades in backtest; need 30 for window 1

---

### S14_Breakout_Scalp_Support_Resistance
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S15_RSI_Divergence_Scalp
Total trades: 1

- Window 1 (trades 1–30): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → **INSUFFICIENT_DATA**
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 1 trades in backtest; need 30 for window 1

---

### S16_ATR_Breakout_Scalp_Volatility
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S17_Opening_Range_Breakout_Intraday
Total trades: 1

- Window 1 (trades 1–30): Sharpe 0.00  WinRate 100%  MaxDD 0.0%  PF 0.00x → **INSUFFICIENT_DATA**
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 1 trades in backtest; need 30 for window 1

---

### S18_VWAP_Mean_Reversion_Options_Straddle
Total trades: 174

- Window 1 (trades 1–30): Sharpe 78.27  WinRate 100%  MaxDD 0.0%  PF ∞ → **PASS**
- Window 2 (trades 31–60): Sharpe 101.72  WinRate 100%  MaxDD 0.0%  PF ∞ → **PASS**
**Promotion: ✓ PROMOTED** — Both windows passed (Sharpe ≥ 0.60, WinRate ≥ 0.48): eligible for live paper trading

---

### S19_ADX_Trend_Filter_Breakouts
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S20_Fibonacci_Retracement_Intraday
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S21_Bollinger_Band_Squeeze_Breakout_Intraday
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S22_News_Event_Vol_Fade_Options_Sell
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S23_Weekly_Options_Theta_Decay_Strangle
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S24_Momentum_Breakout_Swing
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S25_Mean_Reversion_RSI_Oversold_Swing
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S26_Sector_Rotation_Nifty_Rebalance
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S27_Gap_Up_Down_Fade_Options
Total trades: 9

- Window 1 (trades 1–30): Sharpe -9.67  WinRate 0%  MaxDD 0.0%  PF 0.00x → **INSUFFICIENT_DATA**
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 9 trades in backtest; need 30 for window 1

---

### S28_Earnings_Straddle_IV_Play
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

### S29_Index_Futures_Positional_Trend
Total trades: 0

- Window 1 (trades 1–30): _not evaluated_ (INSUFFICIENT_DATA)
- Window 2 (trades 31–60): Sharpe 0.00  WinRate 0%  MaxDD 0.0%  PF 0.00x → ****
**Promotion: ✗ INSUFFICIENT_DATA** — only 0 trades in backtest; need 30 for window 1

---

