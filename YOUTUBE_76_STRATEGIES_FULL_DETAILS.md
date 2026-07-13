# 76 YouTube NIFTY-50 Strategies — Full Implementation Detail

**Compiled:** 2026-07-12 · Companion to `YOUTUBE_CHANNELS_NIFTY_STRATEGY_CATALOG.md`
**Scope:** every named strategy found across the 12 content-bearing channels of the scan (P R Sundar = commentary-only; Pro Traders = duplicate of Pro Trader Aakash). Total = **76**.

> **Provenance (read this):** strategy *names* are confirmed from each channel's real video titles (yt-dlp catalog pull). The *mechanics* below are the standard, publicly-documented form of each named technique, aligned to how the channel frames it — deep per-video transcript extraction was only done for Trade For Sure and Stock Force. Exact channel-specific parameters (precise SL points, "90% accuracy" claims) are the creators' marketing claims and would need per-video transcript confirmation. Treat this as an **implementation spec**, not verified performance.

> **Code-spec convention:** each strategy is written to the lab's `OptionBuyStrategy.direction(ctx)` contract — return `+1` (buy ATM CE), `−1` (buy ATM PE), `0` (exit), `None` (hold). Category sets the engine's premium stop/target/DTE (`options_scalp` / `options_intraday` / `options_swing` / `options_breakout`). "SELLING" strategies fall outside the current buying engine and are flagged.

---

## A. Pro Trader Aakash (10) — option-buying scalper

**A1. Nifty Option-Buying Trap** · `options_intraday` · 15m
Price closes beyond an obvious intraday level (range high/low), trapping breakout traders, then closes back inside within 1–3 bars → fade the failed break. Entry: close back inside; SL: the trap extreme; target: ≥2× (opposite side of range). Codeable ✅ (analog of `trade_room_trap` / `tfs_trap_fade`).

**A2. Super Scalping (option buying)** · `options_scalp` · 5m
Momentum micro-scalp: enter on a strong full-body candle in trend direction after a 1-bar pause; exit on the first opposite-color candle. SL: signal-candle extreme; target: 1:1.5–1:2. Codeable ✅.

**A3. Pullback Scalping** · `options_scalp` · 5m
In an established intraday trend, buy the shallow pullback that resumes (pullback to a fast MA / prior swing, then continuation candle). SL: pullback low; target: prior swing extension. Codeable ✅ (analog of `trade_room_915_pullback`).

**A4. Stop-Loss-Hunting Avoidance** · rule-overlay · any
Not a standalone entry — place SL beyond the liquidity pool (below swing-low wicks / round numbers) rather than at the obvious level, so operators' stop-sweeps don't hit you. Implement as an SL-placement modifier on other setups. Codeable 🟡 (engine overlay).

**A5. 1:3 RR Option-Buying Plan** · rule-overlay · any
Only take trades where the structural target is ≥3× the risk to the invalidation level; skip otherwise. Implement as an entry gate (reject signals whose measured target/SL < 3). Codeable 🟡 (gate).

**A6. 3 Ways to Find Price Direction After Breakout** · `options_breakout` · 15m
Confirm breakout direction via (i) retest-hold, (ii) higher-high/higher-low follow-through, (iii) prior-range flip to support. Enter only when ≥2 of 3 confirm. SL: retest level; target: measured range height. Codeable ✅.

**A7. BankNifty Supply-Demand Strategy** · `options_intraday` · 15m
Mark supply/demand zones (last consolidation before a strong move); fade first touch with the higher-TF trend. SL: beyond zone; target: opposite zone. Codeable ✅ (analog of Stock Force zone system / `tfs_level_reversal`).

**A8. Intraday SmartMoney Flow** · `options_intraday` · 15m
Enter in the direction of displacement candles that leave an imbalance (FVG), on the retrace into that imbalance. SL: FVG far edge; target: next liquidity pool. Codeable ✅ (SMC/FVG family).

**A9. Option Buying in Sideways Market** · `options_scalp` · 5m
Range-scalp: buy CE at range support, PE at range resistance, exit at mid/opposite. Only when range width ≥ premium round-trip cost. SL: outside range; target: opposite band. Codeable ✅.

**A10. Fully Automated Option-Buying** · infra · —
His algo build (Tradefinder-driven signals). Not a distinct edge — an execution wrapper. Codeable 🔴 (tooling, not a strategy).

---

## B. Stock Burner — Dinesh Kirola (9) — SMC + scalping

**B1. 9-20 Strategy** · `options_scalp` · 5m
Buy when 9-EMA crosses 20-EMA with candle closing beyond both; ITM/ATM option. SL: signal-candle low; target 1:2. Exit on reverse cross. Codeable ✅ (EMA family — NEW variant, 20 vs 15).

**B2. 9 EMA Scalping** · `options_scalp` · 5m
Trend-scalp along the 9-EMA: buy when price pulls to and bounces off the 9-EMA in an up-move. SL: below 9-EMA; target: prior high. Codeable ✅.

**B3. CRT (Candle Range Theory)** · `options_intraday` · 15m/1h
A "range candle" (large candle) sets high/low; the next candle sweeps one side and closes back inside → trade toward the opposite side (liquidity manipulation model). SL: sweep extreme; target: opposite CRT boundary. Codeable ✅ (NEW).

**B4. Liquidity Sweep Entries** · `options_intraday` · 15m
Price sweeps a prior swing high/low (grabs liquidity) then reverses; enter on the reversal confirmation. SL: beyond sweep; target: opposite pool. Codeable ✅ (SMC family — NEW).

**B5. AMD (Accumulation-Manipulation-Distribution)** · `options_intraday` · 15m
Session model: accumulation range (Asia/first hour) → manipulation (false break) → distribution (real move). Enter at the manipulation-fail, ride distribution. SL: manipulation extreme; target: range projection. Codeable ✅ (NEW).

**B6. Volume Profile Strategy** · `options_intraday` · 15m
Fade/deflect at HVN (high-volume node) as S/R; trade breakouts through LVN (low-volume node). Entry at node reaction. Codeable 🟡 (needs volume — index spot has none; usable on futures/stock).

**B7. Order Blocks / FVG** · `options_intraday` · 15m
Buy the last down-candle before a strong up-move (bullish order block) on retest; or fill of a fair-value-gap imbalance. SL: OB far edge; target: next structure. Codeable ✅ (SMC family — NEW).

**B8. Sideways / Consolidation Strategy** · `options_scalp` · 5m
Same as A9: range-fade in a defined consolidation box until a decisive break. Codeable ✅.

**B9. Simple Option-Buying Setup (beginner)** · `options_scalp` · 5m
Single-confirmation trend entry (break of first-15-min range with trend). SL: opposite side of ORB; target 1:2. Codeable ✅ (ORB analog).

---

## C. Monika Rajput Official (8) — intraday option-buying scalper

**C1. 9 EMA Scalping** · `options_scalp` · 5m — as B2. Codeable ✅.
**C2. 1-Minute Scalping** · `options_scalp` · 1m/5m — micro-scalp on 1-min momentum; needs 1m bars (not backfilled). Codeable 🟡 (data gap).
**C3. FII-Data Strategy** · `options_intraday` · 1d — bias from daily FII/DII cash + index-futures long/short and options data; trade with net institutional flow. Codeable 🟡 (needs external FII/DII feed).
**C4. Big Bar Scalping** · `options_scalp` · 5m — enter on an outsized momentum candle (range ≫ recent ATR) in trend direction; exit on exhaustion. SL: bar mid; target 1:2. Codeable ✅ (NEW).
**C5. Volatility / Event Trading** · `options_intraday` · 5m — trade big directional expansion on event days (budget, election, expiry); size down, wide SL. Codeable 🟡 (event-calendar gated).
**C6. BTST (FinNifty)** · `options_swing` · 1d — buy near close on a strong-close day, exit next morning on gap/continuation. SL: day low; target: gap+. Codeable ✅ (NEW, overnight).
**C7. 12 PM Scalping** · `options_scalp` · 5m — midday-range-break scalp after the lunch lull. Time-filtered ORB. Codeable ✅ (time filter).
**C8. Sideways Scalping** · `options_scalp` · 5m — as A9. Codeable ✅.

---

## D. Booming Bulls — Anish Singh Thakur (8) — SMC

**D1. "Ultimate Nifty & Stock" Strategy** · `options_intraday` · 15m — trend + S/R confluence entry with candle confirmation. Codeable ✅.
**D2. Liquidity Concept** · `options_intraday` · 15m — as B4 (sweep-and-reverse). Codeable ✅.
**D3. Order Block + FVG** · `options_intraday` · 15m — as B7. Codeable ✅.
**D4. Volume Profile / POC** · `options_intraday` · 15m — fade/accept at Point of Control. Codeable 🟡 (volume).
**D5. FRVP (Fixed-Range Volume Profile)** · `options_intraday` · 15m — POC/value-area of a chosen swing range as S/R. Codeable 🟡 (volume).
**D6. Daily Bias** · bias-overlay · 1d — set CE-only or PE-only for the day from daily structure (higher-high/lower-low, prior-day close). Implement as a directional gate on intraday setups. Codeable ✅ (NEW overlay).
**D7. Simple Entry Setup** · `options_scalp` · 5m — beginner ORB/trend entry. Codeable ✅.
**D8. AI / Algo Options** · infra — execution tooling. Codeable 🔴.

---

## E. Neeraj Joshi (8) — full ICT / Smart-Money curriculum

**E1. ICT Manipulation Model** · `options_intraday` · 15m — judas-swing false move at session open, then reverse into the real trend. SL: manipulation high/low; target: opposing liquidity. Codeable ✅ (NEW).
**E2. Order Block + POI** · `options_intraday` · 15m — as B7, with point-of-interest refinement. Codeable ✅.
**E3. FVG / CISD Strategy** · `options_intraday` · 15m — Change-in-State-of-Delivery: enter when price flips an FVG and closes through the last opposing candle. Codeable ✅ (NEW).
**E4. Liquidity Sweep + Fibonacci** · `options_intraday` · 15m — sweep then enter on 62–79% OTE fib retrace. Codeable ✅ (NEW).
**E5. Premium & Discount Zones** · overlay · 15m — only buy in "discount" (below 50% of dealing range), sell in "premium." Entry-location gate. Codeable ✅ (overlay).
**E6. Daily Bias** · overlay · 1d — as D6. Codeable ✅.
**E7. SMT (Smart Money Technique/Divergence)** · `options_intraday` · 15m — divergence between correlated indices (NIFTY vs BANKNIFTY: one makes new high, other fails) → reversal. Codeable ✅ (NEW, needs 2 symbols).
**E8. Supply & Demand + SMC** · `options_intraday` · 15m — as A7. Codeable ✅.

---

## F. Stock Learners (7) — scalping + operator psychology

**F1. Scalping (small capital)** · `options_scalp` · 5m — tight trend micro-scalp. Codeable ✅.
**F2. Top & Bottom Capture** · `options_intraday` · 15m — reversal at exhaustion (climax candle + failure). SL: extreme; target: mean. Codeable ✅.
**F3. Event-Level Trading** · `options_intraday` · 15m — trade reaction at a major pre-marked level on event days. Codeable ✅.
**F4. Trap Trading** · `options_intraday` · 15m — as A1. Codeable ✅.
**F5. Reversal-Finding** · `options_intraday` · 15m — divergence/structure-break reversal. Codeable ✅.
**F6. Breakout (operator style)** · `options_breakout` · 15m — breakout with retest, framed as "operator-driven." Codeable ✅.
**F7. SMC RR Setup** · `options_intraday` · 15m — OB/FVG entry with fixed ≥1:3 RR. Codeable ✅.

---

## G. Pushkar Raj Thakur (6) — option SELLING (⚠ outside buying engine)

**G1. Sensex Hero-Zero "Brahmastra"** · SELLING/lottery · expiry 0DTE — expiry-day far-OTM cheap option played for a violent move (mostly a buy-lottery; can also be the sold side). Codeable 🟡 (0DTE, separate handling).
**G2. Triple Calendar Spread** · SELLING · multi-expiry — three calendars at different strikes for a wide profit tent. Codeable 🔴 (multi-leg selling; needs selling engine).
**G3. Reverse Calendar Spread** · SELLING · multi-expiry — short near-dated / long far-dated for vol events. Codeable 🔴.
**G4. Directional Option Selling** · SELLING · intraday — sell OTM against the trend's opposite side. Codeable 🔴.
**G5. Daily Premium Selling** · SELLING · intraday — sell straddle/strangle, manage with SL. Codeable 🔴.
**G6. CE/PE Buy Checklist** · overlay — pre-trade confirmation checklist (trend, level, momentum) before buying a call vs put. Codeable ✅ (gate/overlay).

---

## H. Wizard Trader — Harshit Patel (6) — SMC + named-number

**H1. "833" Strategy** · `options_scalp` · 5m — named setup (8:33-ish entry / 3-part rule per his framing); exact rules need transcript. Codeable 🟡 (confirm params).
**H2. "8:30" Strategy** · `options_scalp` · 5m — early-session (first candles after 9:15, or an 8:30-labeled setup) breakout, claimed 80% accuracy. Time-filtered ORB variant. Codeable 🟡 (confirm params).
**H3. Support & Resistance Masterclass** · `options_intraday` · 15m — advanced S/R fade/break, claimed 90%. As A7/F-level. Codeable ✅.
**H4. Inducement Zone + Correlation** · `options_intraday` · 15m — enter after inducement (minor liquidity grab) confirmed by a correlated instrument. Codeable ✅ (NEW, needs 2 symbols).
**H5. BTST Trade (80%)** · `options_swing` · 1d — as C6. Codeable ✅.
**H6. SMC (FVG / Liquidity / OB)** · `options_intraday` · 15m — as B7/B4. Codeable ✅.

---

## I. The Madras Trader (5) — breakout + swing (showcase-style)

**I1. Breakout Trading** · `options_breakout` · 15m/1d — trade clean breakouts of chart patterns/levels with volume. Codeable ✅.
**I2. Breakout-Failure Handling** · `options_intraday` · 15m — fade a failed breakout (as A1) / exit rules for false breaks. Codeable ✅.
**I3. NIFTY Price-Action Backtesting** · method — not a live setup; a backtest walkthrough. Codeable 🔴 (method, not signal).
**I4. Option-Buying on Breakouts** · `options_breakout` · 15m — buy CE/PE on directional pattern break. Codeable ✅.
**I5. Swing Trading (Nifty-200 stocks)** · `options_swing`/equity · 1d — multi-day breakout swing on stocks. Codeable 🟡 (equity, not index option).

---

## J. IITian Trader — Saurabh Maurya (5) — mostly crypto/analysis

**J1. Fake Breakout / Breakdown** · `options_intraday` · 15m — as A1/I2. Codeable ✅.
**J2. Breakout by Heatmap/Indicators** · `options_breakout` · 15m — breakout confirmed by a heatmap/indicator cluster. Codeable 🟡 (tool-dependent).
**J3. Max Pain Strategy** · `options_intraday` · 1d — bias toward the max-pain strike into expiry. Codeable ✅ (NEW, needs OI chain).
**J4. Buildup Strategy** · `options_intraday` · 15m — trade long/short buildup from OI+price change quadrants. Codeable 🟡 (needs OI).
**J5. Market-Structure Reading** · overlay — HH/HL vs LH/LL structure bias. Codeable ✅ (overlay).

---

## K. Devansh Rai (3) — EMA family

**K1. 200 EMA Strategy** · `options_scalp`/`options_intraday` · 5m/15m — trend by price vs 200-EMA; buy pullbacks to a rising 200-EMA, sell into a falling one. SL: EMA break; target 1:2. Codeable ✅ (NEW; note `tfs_200dma_reject` uses daily-200 as a fade — this is intraday-200 as trend).
**K2. 9-20 EMA Strategy** · `options_scalp` · 5m — as B1. Codeable ✅.
**K3. 5 EMA Strategy** · `options_scalp` · 5m — Subhashish-style: after a candle closes fully above/below the 5-EMA at a swing, enter on that candle's break; SL its extreme. Codeable ✅ (NEW).

---

## L. Umar Punjabi (1)

**L1. 1-Minute Sniper Scalping** · `options_scalp` · 1m — precise 1-min momentum entry ("sniper") on Nifty option buying. Codeable 🟡 (needs 1m bars).

---

## P R Sundar (0)
Recent catalog is entirely daily Pre/Post-Market Reports — no rule-based strategy video in-window. Known off-catalog as a short-strangle/option-**selling** practitioner (outside buying engine).

---

## Rollup — codeability of the 76

| Bucket | Count | Notes |
|---|---|---|
| ✅ Codeable now (buying engine) | ~44 | many overlap already-coded families |
| 🟡 Codeable with a dependency | ~19 | 1m bars · FII/DII feed · OI chain · 2nd symbol · volume · event calendar |
| 🔴 Not a codeable buying strategy | ~13 | selling multi-leg (Pushkar ×5), infra/tooling, method-only |

**Genuinely NEW codeable buying families (dedup):** 9-20 EMA · 200-EMA-trend · 5 EMA · CRT · AMD · Liquidity Sweep · Order Block/FVG · ICT Manipulation Model · CISD · SMT/correlation divergence · Daily-Bias overlay · Premium/Discount overlay · Big-Bar scalp · BTST overnight · Max-Pain bias · 833/8:30. Everything else duplicates strategies already in the lab (trap, breakout, supply-demand, pullback, sideways, ORB, 9-EMA).

**Needs a new engine path:** option **selling** (calendars, strangles, directional selling) — Pushkar Raj Thakur & P R Sundar.
