# Trade For Sure — Complete Nifty 50 Option Trading Strategy Extraction

**Channel:** [Trade For Sure](https://www.youtube.com/@TradeForSure) (Rahul Singh)
**Source video provided:** [#day12 Option Trading Challenge Live](https://youtu.be/8jN4yBYLB4M)
**Extraction date:** 2026-07-12 · 60 videos catalogued · 18 challenge-episode transcripts analyzed (Hindi auto-captions, pulled via caption-URL + proxy — direct transcript API was IP-throttled)
**Channel profile:** Primarily a broker-app review channel (Kotak Neo, Dhan, Shoonya, Groww, Mstock demos) + a daily **"Option Trading Challenge"** series: one NIFTY option trade per day, 3 lots, filmed and posted as ~13-minute edited episodes across two seasons. Also crypto/gold lives. Not SEBI registered (stated in every description). Paid course ("Options 360") exists — **not used**; this extraction is from free public videos only.

> ⚠️ All rules below are the creator's claims/behavior from his videos, not verified performance. The system is **pure price action off pre-marked levels** — across 18 transcripts: trend line ×96, support ×95, resistance ×74, breakout ×80, retest ×61, candle ×113, trap ×34, gap ×36 … and **zero** VWAP/Fibonacci/RSI/OI. The single indicator that appears (4 mentions) is the **daily 200 EMA — used as a level, not a signal**.

---

## 1. The Series Rules (stated verbatim as "rules," Day 1 of each season)

1. **One trade per day, every day**; max **2 trades/day** — and the 2nd only if the 1st hit its stop loss (never after a target), only if session time remains, and only with **double/triple confirmation** (trend line + zone + something else).
2. **Minimum 1:2 risk-reward, always.** "10-point SL → 20-point target; 25-point SL → 50-point target." Non-negotiable.
3. **Full SL or full target — nothing in between.** No early booking ("₹9,950 showing on a ₹10,000 target — I will not book"), no panic exits at cost-to-cost, no widening/moving the stop. All analysis happens BEFORE entry; after entry "it's in the market's hands."
4. **~3:00 PM hard square-off.** Around 3 PM, whatever the P&L, close at market ("we won't give losses from our own house" — near 3 PM he trails SL to cost-to-cost and gives it a few minutes if moving favorably).
5. **No revenge trading.** A ₹5,000 loss carries zero obligation to be recovered today.
6. **No random trades.** "Draw the level, wait at the level with patience. If the market never comes — no trade today, and that is a good day too."

**Execution details:** buys ~0.8–0.85-delta **ITM strikes**; converts index points → premium points via delta; keeps a 2–4-point premium buffer on targets ("index at your favor doesn't guarantee the premium follows"); pre-sets the strike before open after missing two sniper entries to strike-switching.

## 2. The Setups (what actually triggers a trade)

### a) Level Reversal — the core system (every episode)
Pre-market: mark support/resistance zones from recent swing highs/lows, the prior day's extremes, and daily-timeframe reaction areas. A zone is a **range**, not a line (e.g. 24,435–24,450). When price enters the zone → reversal trade (PE at resistance, CE at support). Zone-entry tactic: if the market **struggles** toward the zone, enter at the lower/middle edge; if it **runs straight** in, wait for the upper edge. SL just beyond the zone; target ≥2× SL.

### b) "Index Sniper" — his named opening setup (Day 1, 2, 9)
When the market **opens into (or gaps beyond) a pre-marked zone at the prior day's extreme**, take the reversal **immediately at the open** — strike pre-set, no waiting. "Target often comes in the first 2–3 candles." Missing the first minute usually means missing the trade — he refuses to chase 15–20 premium points higher.

### c) Trap trading — failed CLOSED range break (Day 9, 12)
A candle **closes** beyond a well-watched range ("everyone sees the breakdown close and sells") but the move fails within a few bars and closes back inside → the trapped side's unwind fuels the reversal — enter with it. Distinct from a wick-poke trap: the close is what pulls traders in.

### d) Gap-origin support/resistance (Day 2)
After a **big** gap-up (small gaps carry no memory), the daily-chart area the gap launched from acts as **support when price later comes back to fill the gap** — "it tries to take support once at that area." Mirror for gap-downs. Traded as a first-revisit fade.

### e) Daily 200-EMA level (Day 1 of new season)
The one indicator: daily 200 EMA marked **in advance** as a reversal level ("I gave this level on Friday"). Rally into it from below → sell side; dip onto it from above → buy side.

## 3. Psychology & meta-rules (constant refrains)

- Neutrality after entry: red MTM, green MTM, cost-to-cost — "I am neutral; I already did my job before the trade."
- Patience is the edge: "between my two levels other people took 3–4–5 trades and sat with red MTM; I took zero."
- Yesterday's result never changes today's target ("after Friday's SL I kept today's target modest — just easily achievable").
- Rules > outcome: "The market will be here, I will be here; if I don't follow my rules my capital won't be here."

## 4. TradingAI implementation (built 2026-07-12)

Five mechanical strategies in `TradingAI/strategy-service/strategy_service/strategies/options_buying/trade_for_sure.py` (#183–187, registered, auto-swept). Engine's premium stop/target (1:2) + EOD square-off mirror rules 2–4; the strategy layer resets flat each session (his 3-PM rule) — this reset was load-bearing: without it three strategies deadlocked after their first trade.

Real 9.3-year NIFTY backtest (synthetic BS premiums, 1 lot):

| # | strategy_id | Setup | TF | Trades | Win | PF | Exp/trade | Qualifies?* |
|---|---|---|---|---|---|---|---|---|
| 183 | `tfs_level_reversal` | §2a core system | 15m | 3,061 | **42.9%** | 1.17 | **₹154** | ✅ (beats ₹150 floor too) |
| 184 | `tfs_index_sniper` | §2b opening sniper | 5m | 550 | 30.2% | 1.005 | ₹4 | ❌ breakeven |
| 185 | `tfs_trap_fade` | §2c closed-break trap | 15m | 1,300 | **42.4%** | 1.13 | ₹116 | ✅ |
| 186 | `tfs_gap_origin` | §2d gap-origin fade | 15m | 478 | **40.8%** | 1.08 | ₹81 | ✅ |
| 187 | `tfs_200dma_reject` | §2e 200-DMA fade | 1d | 24 | 25.0% | 0.68 | −₹2,799 | ❌ fails — NIFTY trends through its 200-DMA |

*Gate: win ≥40% AND ≥10 trades AND expectancy ≥0. First YouTube-channel extraction where strategies clear it — his level-fading style produces the ~43% win / 1:2 payoff profile his rules target. What does NOT survive mechanization: his discretionary level selection (which zone matters today), the 2-trades/day cap, ITM-vs-ATM strike choice, and premium-vs-index divergence reads.
