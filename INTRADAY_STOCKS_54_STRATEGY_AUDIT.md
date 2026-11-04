# Intraday Stocks — audit of the 54 tournament strategies

*4 November 2026. Audit only: no strategy rule, parameter, filter, stop or target was changed. The improvement ideas are in Part 2, kept apart, and none of them has been applied.*

**What was audited.** The 54 strategies that the Intraday Stocks tournament runs. They live in [backend/app/services/intraday_v2_strategies.py](backend/app/services/intraday_v2_strategies.py) at commit `c64c7b7`, and that file is byte-identical to the one running on the server (md5 `010bc509…`).

**How.**
- Each rule was read line by line, along with the parts of the live engine and the backtest that feed it and trade it.
- Six automatic checks were run on the code.
- The production backtest was replayed over two years with the costs measured from Angel's order book.
- That replay was compared with the tournament's own 20 live sessions.

---

## The short version

1. **The code does what it says, and nothing reads the future.** Every rule was evaluated at 24,768 bar closes (40 random stocks × 20 random days): 386,712 rule decisions, 14,438 of them signals. Each was run with the next five sessions present and with the history cut at the close, and the decision and every price were identical each time. The live engine's shorter windows gave the same signals too, and no rule hit a hidden error. RSI, MACD, Bollinger bands and CCI match their textbook formulas exactly.
2. **Defects found** (all recorded, none fixed):
   - **ADX is not the standard ADX(14).** It smooths about twice as fast as Wilder's version, so it reads higher and crosses 25 at different times than the ADX on Kite or TradingView. On 40 stocks it reads below 20 on 7–11% of bars, where the standard ADX does so on 27–28%. It crosses 25 about 1.7 times as often, and only 4–5% of its crossings fall within one bar of a standard one. This affects 9 strategies: ADX Trend Start ×3, and the "no trend" filters of Z-Score ×3 and Stochastic ×3. ATR and Supertrend smooth the same way; there the difference is smaller.
   - **Donchian's "fresh breakout" check can never fail.** The previous close is compared with a channel that already includes the previous bar's high. So 25–42% of Donchian signals come on the second or later bar of a breakout that had already happened.
   - **VWAP Reclaim compares the previous bar's close with the current VWAP**, not with the VWAP at that time. Because of this, 1–6% of its signals repeat on consecutive bars without the price ever dipping back below VWAP. The 45-minute version can never trade the day's first bar. The 1-hour version's first check of the day compares yesterday's close with today's VWAP.
   - **The tournament ranks every signal by one number, `priority`, but the families fill it with different units**: relative volume, z-score, RSI depth, gap %. When two strategies already hold a stock, the units decide who gets the next slot, not the signal's quality.
   - **The description has drifted from the code.** The module still says trend rules trade only with NIFTY's direction (that filter was switched off on 2 Oct). Donchian's trade note still says "NIFTY up on the day". "First dip" in EMA Pullback is not enforced.
3. **None of the 54 makes money after realistic costs.** The test covered 495 sessions (4 Nov 2024 – 3 Nov 2026), the top 200 stocks as they stood each day, and Angel's charges plus measured slippage.
   - Every signal simulated as a trade: **1,122,659 trades, +0.8 bp before costs, −9.65 bp after**.
   - 37 of the 52 rules the backtest can replay have some edge before costs. Only two (VWAP Reclaim 45 min and 1 hour) clear the bar a 52-rule search needs (t ≥ 3.3).
   - The best edge before costs is +3.6 bp for a bar rule and +8.9 bp for Gap and Go. A round trip costs about **10.5 bp** (6.4 bp slippage + 4.0 bp charges).
   - Run alone with ₹50 lakh each, **all 52 lose**: from −₹2.6 lakh (Gap Fade, −5%) to −₹40.5 lakh (VWAP Reversion 15 min, −81%). Together in the tournament they lose ₹12.4 crore over two years.
   - The two pre-registered Selected ORB rules cannot be replayed (they need the expected-move model). Their forward paper record decides, as registered.
4. **The live paper record points the same way.** Over 20 sessions (8,033 trades), the 52 replayable strategies lost ₹37.9 lakh, at the old, lower slippage; 16 of the 54 were up. The backtest reproduces 56% of live trades exactly, and 95% of those close for the same reason. Live entries land a median 0.0 bp from the bar close the backtest assumes.
5. **The strategies are independent in code but not in the book.**
   - Each has its own ₹50 lakh and five slots, and evaluation order changes nothing (24,200 decisions re-run in reversed order, 0 differences).
   - Two shared limits couple them: the cap of two strategies per stock (which refused 260,081 signals over two years) and the shared priority sort.
   - Against trading alone, the coupling moved single strategies by between −₹8.0 lakh and +₹9.8 lakh over two years. It never turned a loser into a winner.
6. **Indian market fit is good on timing and costs, with four gaps for real money.**
   - **Timing is right:** the 09:15 open, entries 09:45–14:30, and square-off at 15:05 (closing-auction stocks) or 15:12 (others), inside Angel's 15:10 / 15:15.
   - **Costs are right:** MIS shorts in EQ series only, 45m and 1h bars anchored to 09:15, and the 2026 rate card. The Budget 2026-27 STT rise applies to F&O only.
   - **Gap 1, circuit limits:** 22% of the universe is non-F&O stocks with circuit limits (11% of trades), and the paper desk assumes a stop always fills.
   - **Gap 2, no ASM/GSM screen.**
   - **Gap 3, tick size:** stops and targets are not rounded to the tick.
   - **Gap 4, gap reference:** the gap rules use the last trade as "yesterday's close", not NSE's official close.

---

## How the audit was done

| Step | What | Tool |
|---|---|---|
| Code review | The 54 rules, the context builder (`build_ctx`), the indicator library (`nifty_scalp_strategies`), the live engine's entries, limits and exits (`intraday_v2_engine`, `intraday_fills`, `intraday_session`), the bar store and the backtest | reading |
| Look-ahead | Every rule at every bar close of 40 randomly chosen stocks × 20 random days (24,768 closes; 386,712 rule decisions): evaluated with five later sessions present (as the backtest holds the data) and with the history cut at that close. Any difference means a rule read the future. | `audit54_checks.py` |
| Live window | The same closes on the live engine's own window (420 × 15m bars; 220 × 45m / 1h bars, built as the bar store builds them) | `audit54_checks.py` |
| Hidden errors | `evaluate()` turns four kinds of exception into "no signal"; every rule was called directly and each exception counted | `audit54_checks.py` |
| Indicators | RSI, MACD, Bollinger, CCI against reference formulas; ATR, ADX, Supertrend against Wilder's definitions | `audit54_checks.py` |
| Bar structure | The 15:15 stub bar of every 45m / 1h session; how often the volume filter passes at each time of day | `audit54_checks.py` |
| Independence | Every close evaluated twice on fresh data, in catalog order and reversed, so each shared indicator cache is filled by a different rule first | `audit54_checks.py --order-only` |
| Replay | The production backtest built from the committed code. 4 Nov 2024 – 3 Nov 2026, 495 sessions. The point-in-time top-200 universe (267 names over the period; median 159 a day with stored bars). 15-minute bars. | `audit54.py` |
| Numbers | Four views per strategy (below), plus the live paper record and the backtest-vs-live fidelity per strategy | `audit54_analyze.py`, `audit54_tables.py` |

**The fill model** (the live engine's, on 15-minute bars):
- Entry at the signal bar's close plus slippage.
- Stop and target checked bar by bar. When one bar reaches both, it counts as the stop.
- A bar that opens beyond a level fills at its open.
- Targets are limit orders with no slippage; every other exit is a market order.
- Time stop after the strategy's bar count; square-off at 15:05 / 15:12.
- ORB stop-entries fill at the trigger. If the trigger bar also reached the stop, the trade counts as stopped (the pessimistic reading; the optimistic one is reported too).

**Costs per ₹10 lakh round trip.**
- **Angel's intraday rate card, 4.0 bp:** brokerage ₹20 per order; STT 0.025% on the sell leg; NSE transaction charge 0.00297% on both legs; SEBI fee and IPFT ₹10 per crore each; stamp duty 0.003% on the buy leg; GST 18% on brokerage and fees.
- **Slippage measured from Angel's live order book** at 3,355 tournament entries (H1 study), by the stock's daily traded value:

| Daily traded value | ≥ ₹1,000 cr | ₹300–1,000 cr | ₹150–300 cr | < ₹150 cr |
|---|---:|---:|---:|---:|
| Per side | 1.50 bp | 2.85 bp | 3.73 bp | 4.12 bp |

With a target exit paying no slippage, a round trip averages **10.5 bp**: 6.4 slippage + 4.0 charges.

**Four views per strategy.**
1. **Signals:** what the rule asks for.
2. **Every signal as a trade:** no slot, cash or per-stock limit. This measures the rule itself.
3. **Solo book:** the strategy alone with its live limits — ₹50 lakh, five ₹10 lakh slots, the cash check, and never two positions in one stock.
4. **Tournament book:** all strategies together under the live caps. The difference from the solo book is the interference.

**Reading the numbers.**
- **bp** = 0.01% of the traded value.
- **Edge before costs** is the price move captured, before slippage and charges.
- **t** says how sure we can be that an edge is not luck. Trades on the same day move together, so t is computed with day-clustered errors, which is lower and honest.
- With 52 rules tested, a t of about 3.3 is needed before one rule's edge is believable (Bonferroni, 5%).
- **Max drawdown** is the largest fall from a running peak of the book.
- **"Months up"** counts months with a profit.
- **The cash check matters when reading the books.** A strategy that has lost money can afford fewer of its five ₹10 lakh positions, so a losing book shrinks. Its rupee loss is therefore smaller than its per-trade loss suggests. The every-trade view is the clean measure of a rule.

---

# Part 1 — Findings that apply to every strategy

## 1.1 Timing and the NSE session — correct

| Rule | Value | Check |
|---|---|---|
| Bars | 15m from 09:15 (25 a day); 45m and 1h built from 15m and anchored to 09:15 (9 and 7 a day) | ✔ the old cross-session bars were fixed 2 Oct; the store returns closed bars only |
| Entries | bar closes from 09:45 to before 14:30 (Selected ORB 15: from 09:30) | ✔ the opening auction and the first half hour are information, not entries |
| Square-off | 15:05 in closing-auction (CAS) stocks, 15:12 in others | ✔ inside Angel's MIS square-off at 15:10 / 15:15 |
| Time stop | 8 × 15m = 2 h; 4 × 45m = 3 h; 3 × 1h = 3 h | ✔ measured from the fill, same in backtest and live |
| Shorts | MIS intraday shorts, EQ series only (BE / SME excluded), price ≥ ₹50 | ✔ |
| 45m / 1h evaluation | 45m: 10:00, 10:45, 11:30, 12:15, 13:00, 13:45; 1h: 10:15, 11:15, 12:15, 13:15, 14:15 | ✔ |

**One structural quirk: the stub bar.** Every 45m and 1h session ends with a 15-minute bar (15:15–15:30). That bar is never traded, because the desk is flat by 15:12, but it enters every indicator. It lasts a third (45m) or a quarter (1h) of a normal bar, yet its range is 69% (45m) and 58% (1h) of a full bar's, and its volume 95% and 69%: the closing session's activity squeezed into one bar. So one bar in nine (45m) or seven (1h) is a different object from the rest. It pulls ATR, the 20-bar volume average and the bands slightly toward the closing auction.

## 1.2 Indicators — exact, except the Wilder family

| Indicator | Used by | What the check found |
|---|---|---|
| RSI(14), RSI(2) | RSI Momentum, RSI(2) Extreme | Wilder's RSI; identical to the reference after warm-up |
| MACD(12, 26, 9) | MACD Trend Turn | identical to the reference |
| Bollinger 20 / 2 (population SD), z-score | Bollinger Snap-Back, Z-Score | identical |
| CCI(20) | CCI ±200 Return | identical (0.015 × mean absolute deviation) |
| Stochastic(14, 3) | Stochastic Range Turn | the *fast* stochastic: %K is not smoothed |
| Session VWAP | VWAP Reclaim, VWAP Reversion | typical price × volume from 09:15 — standard |
| ATR(14) | every stop and target (Keltner's band: ATR(10)) | EMA-smoothed (α = 2/15) instead of Wilder's (α = 1/14). 80% of readings lie within −13% … +12% of Wilder's ATR on 15m bars (−10% … +9% on 45m / 1h), so stops and targets sit about ±10% from a chart's ATR. |
| ADX(14), +DI, −DI | ADX Trend Start; the "range" filters of Z-Score (ADX < 25) and Stochastic (ADX < 20) | EMA-smoothed throughout, so it behaves like a 7-period ADX. Median 33–34 against 25–26 for standard ADX(14). Below 20 on 7–11% of bars against 27–28%. Crosses 25 1.6–1.8× as often, and only 4.4–4.8% of its crossings land within one bar of a standard crossing. Measured on 40 stocks, all three timeframes; confirmed against an independent pandas implementation on RELIANCE, HDFCBANK and TATASTEEL. |
| Supertrend(10, 3) | Supertrend Flip | the standard band logic on the EMA ATR: 76–80% of its flips land within one bar of a standard (Wilder-ATR) Supertrend's |

**The volume filter is blind to the time of day.** Donchian and Prior-Day High/Low need a bar's volume to be at least 1.2 × the average of the previous 20 bars. NSE volume is U-shaped, so the filter mostly selects the time of day, not unusual volume:
- **15-minute bars:** it passes half of the 09:30 bars (the first that can trade) and a third of the 09:45 bars, but only 10–14% between 11:00 and 13:00.
- **45m and 1h bars:** it passes 60–62% of the day's first bar against 14–24% of later bars.

## 1.3 Look-ahead, hidden errors and live-versus-backtest

**Look-ahead: none.** At 24,768 closes the rules were run with the next five sessions present and with the history cut at the close. All 386,712 decisions (14,438 signals) were identical, prices included. The code agrees:
- every indicator is trailing;
- `build_ctx` reads strategy bars up to the closed bar, and 15-minute bars up to the last closed one;
- the daily ATR and yesterday's high and low come from earlier sessions;
- the opening range waits for both the 09:15 and 09:30 bars to close;
- relative volume compares today's first k bars with the same k bars of the 14 sessions before;
- the bar store hands out closed bars only.

**Hidden errors: none.** `evaluate()` turns an IndexError, ValueError, ZeroDivisionError or TypeError into "no signal", which could hide a broken rule. Every rule was called directly at all 24,768 closes, and none of those errors occurred.

**Live window: identical.** The live engine gives the rules the last 420 fifteen-minute bars and 220 bars of 45m / 1h; the backtest gives them the whole history. On the same closes both produced exactly the same 14,438 signals, because the recursive indicators (EMA 50, RSI, ADX, Supertrend) have long settled within those windows.

**How the live engine differs from the backtest** (measured on 20 live sessions with `fidelity.py`):
- **Entry price.** Live fills at the last price about 20 seconds after the bar closes. Across 7,754 live bar-rule entries, the fill (before slippage) was a median **0.0 bp** and a mean **+0.4 bp** worse than the bar close; 80% fell within −8.3 to +9.3 bp. The backtest's "close + slippage" is fair.
- **Exits.**
  - The backtest reproduces 56% of live trades, and 95% of those exit for the same reason.
  - On those 4,524 shared trades the backtest books −₹23.4 lakh and live −₹15.1 lakh. The backtest is the stricter of the two, mainly because it charges the measured slippage (live used the old 1–4 bp until 5 Nov) and because of the ORB trigger bars (below).
  - The rest is path dependence. Live exits on minute bars free a slot at a different moment, and the next signal goes elsewhere.
- **ORB stop-entries are where the two disagree.**
  - The backtest counts a 15-minute trigger bar that also touched the stop as stopped.
  - Live, the exit scan starts at the minute after the fill, so a stop touched inside the fill minute is caught only if the price is still beyond it at a 3-second check.
  - On the same 84 ORB-10% trades the backtest booked −₹2.39 lakh and live +₹0.73 lakh. The truth is in between, and both readings lose after costs (below).
- **Targets fill on touch, with no slippage, in both.** That is slightly optimistic: a real limit order usually needs the price to trade through it.

## 1.4 Costs — the wall every rule hits

Across all signals the rules capture **+0.8 bp before costs**. Slippage takes 5.5–6.9 bp a round trip and charges 4.0 bp. Those two lines decide every verdict below:

- Even the strongest bar rules capture +3 to +4 bp before costs. That is a third of the round trip.
- On 15-minute bars the median stop is 39–70 bp. Costs are therefore 15–27% of the risk on every trade before the trade starts, and 8–27% of the target.
- For ORB-in-play 10% the stop is 26 bp, so costs are 41% of the risk.

The October audit reached the same verdict with the older cost model. Measured costs (Phase 1) made the gap wider, not narrower.

## 1.5 Independence and interference

**In the code, the strategies are independent.**
- Each rule is a pure function of the bars it is handed.
- Indicator arrays are cached on each bar series and shared between rules that ask for the same thing (EMA 50, ADX 14, SMA 20, SD 20). The shared values are computed identically, so sharing is safe.
- The per-day ATR cache is shared too and depends only on prior sessions.
- Measured: every close of 10 stocks × 5 days was evaluated twice on fresh data, once in catalog order and once reversed, so each shared cache was filled by a different rule first. 24,200 decisions, 0 differences.

**In the book, they are coupled in three ways:**

1. **Two strategies per stock.** A third strategy cannot enter a stock two others hold (the pre-registered Selected ORB rules are exempt). Over two years this refused **260,081** signals.
   - Against trading alone, single strategies ended between −₹8.0 lakh (Gap and Go) and +₹9.8 lakh (OR Close Break 1h).
   - In total the 52 lost ₹12.68 crore alone and ₹12.36 crore together.
   - No loser became a winner.
2. **One priority sort for all.** At each close, every candidate from every strategy is sorted by `priority`, and the first two to reach a stock take it. Each family fills that field with different units:

| Family | What `priority` holds | Median | 90th percentile |
|---|---|---:|---:|
| Donchian 20 Breakout | relative volume | 1.24 | 3.52 |
| EMA Trend Pullback | relative volume | 0.69 | 1.61 |
| MACD Trend Turn | relative volume | 0.79 | 2.1 |
| Keltner Breakout | relative volume | 0.98 | 2.64 |
| Supertrend Flip | relative volume | 0.85 | 2.29 |
| ADX Trend Start | relative volume | 0.75 | 1.91 |
| RSI Momentum 60/40 | relative volume | 0.78 | 1.98 |
| VWAP Reclaim | relative volume | 1.4 | 3.04 |
| Prior-Day High/Low Break | relative volume | 1.09 | 2.97 |
| Opening-Range Close Break | relative volume | 1.68 | 3.65 |
| VWAP Reversion | stretch from VWAP, ATRs | 1.63 | 2.78 |
| RSI(2) Extreme | 5 − RSI(2) / RSI(2) − 95 | 2.06 | 4.06 |
| Bollinger Snap-Back | relative volume | 0.82 | 1.48 |
| Z-Score Fade in Range | z-score (absolute) | 2.78 | 3.39 |
| Stochastic Range Turn | relative volume | 0.61 | 1.21 |
| CCI ±200 Return | relative volume | 0.87 | 1.53 |
| ORB Stocks-in-Play (stop 10% ATR) | relative volume | 2.32 | 5.81 |
| ORB Stocks-in-Play (stop 25% ATR) | relative volume | 2.32 | 5.81 |
| Gap and Go | relative volume | 3.49 | 11.24 |
| Gap Fade | gap, % | 2.1 | 3.79 |

   A Z-Score signal (priority ≈ 2.8) therefore beats an EMA Pullback signal (≈ 0.7) on the same stock because of its units, not its merit.
3. **The daily loss breaker** (3% of ₹27 crore = ₹81 lakh) is shared. One strategy cannot trip it alone at ₹50 lakh of capital, so in practice it does not couple them.

## 1.6 Indian-market gaps (they matter for real money, not for the paper record)

| Gap | Evidence | Effect |
|---|---|---|
| Non-F&O stocks have circuit limits | 45 of today's 200 universe names have no CAS flag; 11.2% of all simulated trades are in them | A stock locked at its upper or lower circuit cannot be exited. The paper desk fills the stop anyway. |
| No ASM / GSM screen | the universe rule is "top 200 by traded value, EQ series, price ≥ ₹50" | Angel restricts MIS (or asks full margin) in some surveillance stages; real orders would be rejected |
| Tick size | stops and targets are stored to ₹0.01 of any value | real orders need the ₹0.05 (or ₹0.01 below ₹250) grid |
| Gap reference | gap rules use the last 15m close as "yesterday's close" | NSE's official close is the 15:00–15:30 VWAP (or the closing-auction price); the gap a trader sees differs by a few bp |

The F&O split (appendix) cuts both ways, and it is descriptive only:
- **Reversion rules lose far more in non-F&O stocks.** Z-Score 45m and 1h lose about −31 bp there against −10 to −15 bp in F&O names; RSI(2) loses −19 to −20 bp against −10 to −11 bp.
- **Trend rules lose less in non-F&O stocks.** Supertrend 1h is +0.7 bp a trade and MACD 1h −1.0 bp there, and Gap and Go is +8.5 bp on 135 trades. That fits stronger intraday follow-through in less-followed stocks.
- Neither split was pre-registered, so neither is evidence on its own.

---

# Part 1 — Strategy by strategy

**Common to the 48 bar strategies (16 families × 15 min / 45 min / 1 hour):**
- Evaluated at each close of their own bar.
- Entry at market. Stop and target in multiples of the timeframe's ATR(14) (an EMA-smoothed ATR, §1.2), or a price level for three reversion families.
- Time stop: 2 hours (15m) or 3 hours (45m, 1h). Flat by the square-off.
- ₹10 lakh a trade, at most five open, never two in one stock.
- Every rule needs 30 bars of history.
- `priority` is relative volume unless stated otherwise.

**How to read a card.**
- *Signals* describe the rule.
- *Every signal as a trade* is the rule's own record.
- *Solo book* is the strategy alone with ₹50 lakh.
- *Tournament* is the strategy as it actually runs today.
- *Live paper* covers 6 Oct – 3 Nov 2026. It used the old 1–4 bp slippage, so its costs are lower than the backtest's.

## Trend and breakout families (30 strategies)

### Donchian 20 Breakout — `iv2_donchian_15m / _45m / _1h`
**Rule.** BUY when the bar closes above the highest high of the previous 20 bars, the previous close was not above that high, and the bar's volume is at least 1.2 × the average of the previous 20 bars. SELL is the mirror at the 20-bar low. Stop 1.0 ATR, target 2.0 ATR (reward : risk 2.0).

**Code review.**
- **Defect.** The "previous close not above the channel" test compares the previous close with a channel that already includes the previous bar's own high. A close can never exceed its own bar's high, so the test is always true. The rule therefore fires on every close beyond the channel, not only the first: on 15m, 42% of signals come when the previous bar had already broken out.
- **Volume filter.** It compares the bar with the last 20 bars at any time of day. NSE volume is U-shaped, so the opening bars pass it 3–5× more often than midday bars (§1.2). That is why 35–56% of signals land in the first hour.
- **Wording.** The trade note says "NIFTY up on the day"; that filter is off.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 95.9 | 52.3 | 45.3 |
| Stop / target, median bp | 54 / 108 | 91 / 182 | 102 / 204 |
| Planned reward : risk | 2.0 | 2.0 | 2.0 |
| Signals in the first hour (to 10:15) | 35.0% | 51.1% | 55.7% |
| Same signal on the bar before | 21.6% | 17.5% | 16.5% |
| Previous bar had already broken out | 42.0% | 26.5% | 24.9% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 47,491 | 25,899 | 22,411 |
| Edge before costs, bp (t, clustered by day) | +0.76 (0.87) | +2.54 (1.71) | +3.64 (2.44) |
| Same edge with every day weighted equally, bp | -1.88 | +0.16 | +0.22 |
| Slippage + charges, bp | 6.4 + 4.0 | 6.6 + 4.0 | 6.7 + 4.0 |
| Net per trade, bp (t, clustered by day) | -9.63 (-10.85) | -8.07 (-5.41) | -7.04 (-4.7) |
| Win rate / direction right | 36.6% / 40.8% | 41.6% / 46.3% | 42.8% / 48.3% |
| Average win ÷ average loss | 1.28 | 1.14 | 1.11 |
| Exits: target / stop / time / close | 16 / 50 / 28 / 6 % | 8 / 32 / 42 / 17 % | 5 / 25 / 47 / 23 % |
| Median hold, minutes | 60 | 165 | 165 |
| Net bp: first 18 months / last 6 months | -9.2 / -10.5 | -6.9 / -10.5 | -5.9 / -9.4 |
| **Solo book (₹50 lakh):** trades | 4,242 | 3,507 | 3,183 |
| 2-year P&L, ₹ lakh (return) | -36.4 (-72.8%) | -16.1 (-32.3%) | -13.9 (-27.8%) |
| Win rate / profit factor | 37.3% / 0.781 | 43.6% / 0.903 | 44.9% / 0.905 |
| Max drawdown, ₹ lakh (% of capital) | 37.6 (75.2%) | 18.2 (36.3%) | 17.2 (34.5%) |
| Sharpe (annualised) | -4.25 | -1.51 | -1.29 |
| Months up / worst month ₹ lakh | 4/25 / -4.1 | 7/25 / -3.9 | 11/25 / -3.7 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -21.8 / -14.6 / -2.4 | -9.9 / -6.2 / -3.1 | -11.0 / -2.9 / +0.5 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -34.2 (+2.2) | -22.5 (-6.3) | -20.4 (-6.5) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.0 (309, 36.6%) | -1.8 (143, 42.0%) | +1.1 (138, 50.0%) |
| Live trades the backtest reproduces / same exit | 59% / 92% | 54% / 92% | 46% / 92% |
| Verdict | Weak | Weak | Small, unproven |

**Reading it.** The 1-hour version has the best edge before costs in the family (+3.6 bp, t 2.4), but with every day weighted equally it is +0.2 bp. The edge sits on a few strong-trend days. All three lose 7–10 bp a trade after costs, and the loss is just as large in the last six months.

### EMA Trend Pullback — `iv2_ema_pullback_*`
**Rule.** BUY when EMA9 > EMA21 > EMA50, the previous bar's low touched EMA21, and this bar closed green above EMA9. SELL is the mirror. Stop 1.0 ATR, target 1.8 ATR.

**Code review.** Correct as written.
- The description says "the first dip". Nothing enforces "first": any touch of EMA21 qualifies, so 21–23% of signals repeat on the next bar.
- The touching bar may be the previous session's last bar.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 169.5 | 60.1 | 48.7 |
| Stop / target, median bp | 44 / 78 | 76 / 137 | 86 / 156 |
| Planned reward : risk | 1.8 | 1.8 | 1.8 |
| Signals in the first hour (to 10:15) | 26.1% | 20.4% | 22.1% |
| Same signal on the bar before | 23.2% | 21.0% | 20.5% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 83,913 | 29,729 | 24,130 |
| Edge before costs, bp (t, clustered by day) | +0.14 (0.28) | +1.45 (1.47) | +1.39 (1.23) |
| Same edge with every day weighted equally, bp | +0.75 | +0.40 | -0.66 |
| Slippage + charges, bp | 6.3 + 4.0 | 6.6 + 4.0 | 6.7 + 4.0 |
| Net per trade, bp (t, clustered by day) | -10.21 (-20.18) | -9.21 (-9.29) | -9.38 (-8.3) |
| Win rate / direction right | 36.0% / 41.6% | 41.0% / 47.6% | 41.4% / 48.8% |
| Average win ÷ average loss | 1.16 | 1.06 | 1.02 |
| Exits: target / stop / time / close | 16 / 47 / 26 / 10 % | 7 / 28 / 37 / 27 % | 5 / 20 / 37 / 38 % |
| Median hold, minutes | 75 | 150 | 165 |
| Net bp: first 18 months / last 6 months | -9.5 / -11.6 | -8.9 / -9.9 | -8.8 / -10.5 |
| **Solo book (₹50 lakh):** trades | 4,479 | 2,945 | 2,455 |
| 2-year P&L, ₹ lakh (return) | -36.0 (-72.0%) | -22.6 (-45.3%) | -31.5 (-63.0%) |
| Win rate / profit factor | 38.0% / 0.738 | 41.6% / 0.8 | 40.2% / 0.668 |
| Max drawdown, ₹ lakh (% of capital) | 36.3 (72.6%) | 24.2 (48.5%) | 32.8 (65.6%) |
| Sharpe (annualised) | -5.55 | -3.28 | -4.59 |
| Months up / worst month ₹ lakh | 2/25 / -4.0 | 5/25 / -2.7 | 4/25 / -3.6 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -22.8 / -13.2 / -5.0 | -15.1 / -7.5 / -2.4 | -21.5 / -10.0 / -5.8 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -37.4 (-1.4) | -27.1 (-4.5) | -32.6 (-1.1) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.9 (294, 38.8%) | -0.3 (174, 50.0%) | -0.1 (157, 49.7%) |
| Live trades the backtest reproduces / same exit | 48% / 92% | 56% / 97% | 44% / 99% |
| Verdict | Weak | Weak | Weak |

**Reading it.** This family has almost no edge (t ≤ 1.5 on every timeframe). The 15-minute version fires 170 times a session and loses 10.2 bp a trade.

### MACD Trend Turn — `iv2_macd_trend_*`
**Rule.** BUY when the MACD(12, 26, 9) histogram turns from ≤ 0 to > 0 with the close above EMA50. SELL is the mirror. Stop 1.2 ATR, target 2.0 ATR.

**Code review.** Correct. MACD matches the reference formula exactly after warm-up.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 79.8 | 35.5 | 29.6 |
| Stop / target, median bp | 53 / 88 | 96 / 161 | 110 / 182 |
| Planned reward : risk | 1.67 | 1.67 | 1.67 |
| Signals in the first hour (to 10:15) | 25.8% | 36.1% | 36.4% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 39,519 | 17,577 | 14,660 |
| Edge before costs, bp (t, clustered by day) | +1.29 (2.09) | +1.06 (0.74) | +3.42 (2.11) |
| Same edge with every day weighted equally, bp | +1.55 | +1.67 | +3.93 |
| Slippage + charges, bp | 6.4 + 4.0 | 6.6 + 4.0 | 6.7 + 4.0 |
| Net per trade, bp (t, clustered by day) | -9.13 (-14.56) | -9.60 (-6.66) | -7.34 (-4.51) |
| Win rate / direction right | 39.0% / 45.4% | 41.8% / 47.8% | 42.8% / 49.9% |
| Average win ÷ average loss | 1.1 | 1.05 | 1.06 |
| Exits: target / stop / time / close | 15 / 39 / 34 / 12 % | 7 / 22 / 48 / 24 % | 4 / 15 / 45 / 36 % |
| Median hold, minutes | 90 | 180 | 165 |
| Net bp: first 18 months / last 6 months | -8.8 / -9.9 | -9.3 / -10.3 | -7.7 / -6.7 |
| **Solo book (₹50 lakh):** trades | 4,463 | 2,736 | 3,044 |
| 2-year P&L, ₹ lakh (return) | -32.7 (-65.4%) | -24.2 (-48.3%) | -14.9 (-29.8%) |
| Win rate / profit factor | 39.9% / 0.767 | 42.3% / 0.789 | 44.2% / 0.87 |
| Max drawdown, ₹ lakh (% of capital) | 33.2 (66.3%) | 25.3 (50.7%) | 15.6 (31.3%) |
| Sharpe (annualised) | -4.33 | -3.02 | -1.7 |
| Months up / worst month ₹ lakh | 4/25 / -3.4 | 5/25 / -4.9 | 9/25 / -5.1 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -18.2 / -14.5 / -6.1 | -16.7 / -7.5 / -2.9 | -12.5 / -2.4 / -2.3 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -32.1 (+0.6) | -27.1 (-2.9) | -21.4 (-6.5) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.7 (263, 42.2%) | -1.0 (147, 40.1%) | +1.6 (159, 51.6%) |
| Live trades the backtest reproduces / same exit | 55% / 94% | 53% / 91% | 60% / 99% |
| Verdict | Small, unproven | Weak | Small, unproven |

### Keltner Breakout — `iv2_keltner_*`
**Rule.** BUY when the close crosses above EMA20 + 2 × ATR(10). SELL when it crosses below EMA20 − 2 × ATR(10). Stop 1.0 ATR(14), target 2.0 ATR(14).

**Code review.** The crossing is tested correctly against each bar's own band. The band's ATR is EMA-smoothed (§1.2). The description says "in the market's direction"; no such filter exists any more.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 92.4 | 38.8 | 32.3 |
| Stop / target, median bp | 48 / 96 | 87 / 174 | 98 / 195 |
| Planned reward : risk | 2.0 | 2.0 | 2.0 |
| Signals in the first hour (to 10:15) | 18.7% | 37.8% | 40.5% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 45,727 | 19,184 | 16,010 |
| Edge before costs, bp (t, clustered by day) | +0.99 (1.34) | +2.86 (1.89) | +3.41 (2.2) |
| Same edge with every day weighted equally, bp | -0.16 | +0.34 | +0.05 |
| Slippage + charges, bp | 6.4 + 4.0 | 6.6 + 4.0 | 6.7 + 4.0 |
| Net per trade, bp (t, clustered by day) | -9.40 (-12.58) | -7.78 (-5.12) | -7.30 (-4.71) |
| Win rate / direction right | 36.9% / 41.9% | 42.0% / 47.4% | 42.4% / 49.0% |
| Average win ÷ average loss | 1.21 | 1.11 | 1.1 |
| Exits: target / stop / time / close | 15 / 48 / 26 / 11 % | 7 / 30 / 38 / 26 % | 4 / 22 / 38 / 36 % |
| Median hold, minutes | 60 | 150 | 165 |
| Net bp: first 18 months / last 6 months | -9.3 / -9.6 | -7.1 / -9.2 | -6.9 / -8.2 |
| **Solo book (₹50 lakh):** trades | 4,153 | 3,042 | 2,819 |
| 2-year P&L, ₹ lakh (return) | -37.6 (-75.2%) | -20.1 (-40.3%) | -25.9 (-51.7%) |
| Win rate / profit factor | 37.8% / 0.736 | 41.1% / 0.846 | 42.2% / 0.782 |
| Max drawdown, ₹ lakh (% of capital) | 38.4 (76.8%) | 24.2 (48.3%) | 26.3 (52.7%) |
| Sharpe (annualised) | -5.04 | -2.26 | -3.08 |
| Months up / worst month ₹ lakh | 4/25 / -3.8 | 10/25 / -4.4 | 5/25 / -3.6 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -24.8 / -12.8 / -6.7 | -12.7 / -7.4 / +2.3 | -15.2 / -10.7 / -1.1 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -38.1 (-0.5) | -21.5 (-1.3) | -23.9 (+2.0) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -0.8 (295, 44.4%) | +1.3 (160, 49.4%) | +1.4 (152, 52.0%) |
| Live trades the backtest reproduces / same exit | 39% / 92% | 55% / 99% | 45% / 97% |
| Verdict | Weak | Weak | Small, unproven |

### Supertrend Flip — `iv2_supertrend_*`
**Rule.** BUY when Supertrend(10, 3) flips up; SELL when it flips down. Stop 1.5 ATR, target 2.5 ATR.

**Code review.** The band logic is the standard one, but the ATR inside it is EMA-smoothed rather than Wilder's. 76–80% of its flips land within one bar of a standard Supertrend's; the rest are flips a chart would not show.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 46.0 | 27.7 | 23.0 |
| Stop / target, median bp | 70 / 118 | 129 / 215 | 146 / 244 |
| Planned reward : risk | 1.67 | 1.67 | 1.67 |
| Signals in the first hour (to 10:15) | 30.3% | 47.1% | 48.8% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 22,761 | 13,714 | 11,390 |
| Edge before costs, bp (t, clustered by day) | +0.94 (0.95) | +1.74 (1.01) | +3.85 (2.19) |
| Same edge with every day weighted equally, bp | +0.07 | +0.50 | +1.31 |
| Slippage + charges, bp | 6.6 + 4.0 | 6.7 + 4.0 | 6.8 + 4.0 |
| Net per trade, bp (t, clustered by day) | -9.67 (-9.71) | -9.01 (-5.2) | -6.94 (-3.94) |
| Win rate / direction right | 40.5% / 47.3% | 42.9% / 48.8% | 43.9% / 50.1% |
| Average win ÷ average loss | 1.05 | 1.04 | 1.05 |
| Exits: target / stop / time / close | 9 / 28 / 47 / 15 % | 3 / 14 / 60 / 23 % | 2 / 8 / 58 / 32 % |
| Median hold, minutes | 120 | 180 | 180 |
| Net bp: first 18 months / last 6 months | -8.9 / -11.3 | -8.0 / -11.1 | -7.3 / -6.2 |
| **Solo book (₹50 lakh):** trades | 3,715 | 2,938 | 2,811 |
| 2-year P&L, ₹ lakh (return) | -33.4 (-66.7%) | -17.2 (-34.4%) | -18.6 (-37.2%) |
| Win rate / profit factor | 40.6% / 0.74 | 45.3% / 0.861 | 43.4% / 0.834 |
| Max drawdown, ₹ lakh (% of capital) | 33.9 (67.8%) | 20.4 (40.7%) | 20.8 (41.7%) |
| Sharpe (annualised) | -4.63 | -1.92 | -2.23 |
| Months up / worst month ₹ lakh | 0/25 / -3.4 | 7/25 / -4.1 | 7/25 / -6.0 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -19.1 / -14.3 / -6.9 | -11.6 / -5.6 / -5.3 | -14.1 / -4.6 / -2.5 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -30.2 (+3.1) | -20.0 (-2.8) | -24.1 (-5.5) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | +0.1 (227, 46.7%) | +2.3 (138, 49.3%) | +1.3 (129, 55.8%) |
| Live trades the backtest reproduces / same exit | 57% / 96% | 65% / 100% | 66% / 99% |
| Verdict | Weak | Weak | Small, unproven |

### ADX Trend Start — `iv2_adx_dmi_*`
**Rule.** When ADX(14) crosses up through 25: BUY if +DI > −DI, SELL if −DI > +DI. Stop 1.2 ATR, target 2.4 ATR.

**Code review — definition defect.** This ADX smooths +DM, −DM, true range and DX with an EMA (α = 2/15), not Wilder's average (α = 1/14). It behaves like a 7-period ADX. Measured on 40 stocks over two years, it reads below 20 on 7–11% of bars (standard ADX(14): 27–28%). It crosses 25 about 1.7× as often (15m: 14,933 times against 8,450), and only 4.5% of its crossings land within one bar of a standard crossing. An independent pandas implementation on RELIANCE, HDFCBANK and TATASTEEL agrees: median 33–34 against 25–26. The rule is consistent between live and backtest, but it does not trade the "ADX(14) through 25" that its name describes. Any chart check on Kite or TradingView will disagree with it.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 59.6 | 26.4 | 22.2 |
| Stop / target, median bp | 51 / 102 | 92 / 185 | 105 / 210 |
| Planned reward : risk | 2.0 | 2.0 | 2.0 |
| Signals in the first hour (to 10:15) | 25.7% | 33.4% | 34.8% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 29,479 | 13,069 | 11,007 |
| Edge before costs, bp (t, clustered by day) | +1.81 (2.97) | +1.72 (1.3) | +0.55 (0.41) |
| Same edge with every day weighted equally, bp | +2.03 | +0.78 | -0.51 |
| Slippage + charges, bp | 6.5 + 4.0 | 6.7 + 4.0 | 6.8 + 4.0 |
| Net per trade, bp (t, clustered by day) | -8.76 (-14.26) | -9.04 (-6.8) | -10.26 (-7.6) |
| Win rate / direction right | 38.1% / 45.0% | 41.9% / 48.0% | 41.3% / 48.5% |
| Average win ÷ average loss | 1.14 | 1.05 | 1.02 |
| Exits: target / stop / time / close | 10 / 39 / 34 / 17 % | 4 / 23 / 53 / 20 % | 2 / 16 / 48 / 33 % |
| Median hold, minutes | 90 | 180 | 180 |
| Net bp: first 18 months / last 6 months | -7.9 / -10.6 | -8.3 / -10.5 | -10.1 / -10.6 |
| **Solo book (₹50 lakh):** trades | 4,181 | 2,909 | 2,438 |
| 2-year P&L, ₹ lakh (return) | -30.6 (-61.1%) | -20.7 (-41.4%) | -29.2 (-58.4%) |
| Win rate / profit factor | 39.2% / 0.761 | 42.1% / 0.809 | 40.0% / 0.679 |
| Max drawdown, ₹ lakh (% of capital) | 31.6 (63.2%) | 20.7 (41.4%) | 29.5 (59.0%) |
| Sharpe (annualised) | -4.64 | -2.82 | -4.47 |
| Months up / worst month ₹ lakh | 3/25 / -3.3 | 5/25 / -3.9 | 3/25 / -4.0 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -21.6 / -9.0 / -6.7 | -12.7 / -8.0 / -4.3 | -15.4 / -13.9 / -5.9 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -31.6 (-1.1) | -20.7 (-0.0) | -26.1 (+3.1) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -1.0 (254, 43.7%) | -0.1 (133, 49.6%) | -0.1 (137, 43.1%) |
| Live trades the backtest reproduces / same exit | 38% / 96% | 70% / 99% | 61% / 98% |
| Verdict | Small, unproven | Weak | Weak |

### RSI Momentum 60/40 — `iv2_rsi_momentum_*`
**Rule.** BUY when RSI(14) crosses up through 60 with the close above EMA50. SELL when RSI crosses down through 40 below EMA50. Stop 1.0 ATR, target 2.0 ATR.

**Code review.** Correct. RSI is Wilder's and matches the reference exactly.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 158.3 | 69.2 | 57.4 |
| Stop / target, median bp | 44 / 89 | 80 / 161 | 91 / 182 |
| Planned reward : risk | 2.0 | 2.0 | 2.0 |
| Signals in the first hour (to 10:15) | 19.8% | 41.0% | 44.1% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 78,369 | 34,274 | 28,398 |
| Edge before costs, bp (t, clustered by day) | +0.97 (2.02) | +2.48 (2.4) | +2.57 (2.42) |
| Same edge with every day weighted equally, bp | +1.32 | +2.46 | +1.41 |
| Slippage + charges, bp | 6.4 + 4.0 | 6.6 + 4.0 | 6.7 + 4.0 |
| Net per trade, bp (t, clustered by day) | -9.46 (-19.45) | -8.19 (-7.89) | -8.16 (-7.66) |
| Win rate / direction right | 36.2% / 41.7% | 41.4% / 47.3% | 41.9% / 48.6% |
| Average win ÷ average loss | 1.2 | 1.1 | 1.07 |
| Exits: target / stop / time / close | 14 / 47 / 28 / 11 % | 7 / 30 / 40 / 24 % | 4 / 22 / 40 / 33 % |
| Median hold, minutes | 75 | 165 | 165 |
| Net bp: first 18 months / last 6 months | -9.0 / -10.4 | -7.5 / -9.6 | -7.9 / -8.7 |
| **Solo book (₹50 lakh):** trades | 4,213 | 3,699 | 3,143 |
| 2-year P&L, ₹ lakh (return) | -36.8 (-73.6%) | -20.6 (-41.2%) | -24.9 (-49.8%) |
| Win rate / profit factor | 37.4% / 0.729 | 43.3% / 0.86 | 42.3% / 0.796 |
| Max drawdown, ₹ lakh (% of capital) | 38.0 (76.0%) | 21.9 (43.9%) | 25.2 (50.5%) |
| Sharpe (annualised) | -5.43 | -2.26 | -3.0 |
| Months up / worst month ₹ lakh | 3/25 / -5.0 | 5/25 / -3.7 | 2/25 / -2.9 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -26.0 / -10.8 / -5.0 | -9.3 / -11.2 / -5.6 | -14.6 / -10.3 / -5.0 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -35.1 (+1.8) | -21.3 (-0.7) | -25.3 (-0.4) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.5 (285, 36.5%) | -2.1 (152, 38.8%) | +0.2 (157, 44.6%) |
| Live trades the backtest reproduces / same exit | 44% / 91% | 45% / 96% | 43% / 98% |
| Verdict | Small, unproven | Small, unproven | Small, unproven |

### VWAP Reclaim — `iv2_vwap_trend_*`
**Rule.** Needs at least four of today's 15m bars and relative volume ≥ 1.0. BUY when the previous bar's close is below the session VWAP, this close is above it, and VWAP is higher than 30 minutes ago. SELL is the mirror. Stop 1.0 ATR, target 1.8 ATR.

**Code review — three defects.**
1. **Wrong VWAP for the previous close.** The previous close is compared with the VWAP as of now, not the VWAP when that bar closed. If VWAP rose above a close that had been above it, a "reclaim" fires although the price never fell below VWAP. 1.2% / 3.2% / 6.0% of signals (15m / 45m / 1h) repeat on consecutive bars this way.
2. **45 min can never trade the first bar.** At 10:00 only three 15m bars exist, so the four-bar minimum blocks it (0% of its signals before 10:15).
3. **1 hour, first check of the day.** At 10:15 the "previous close" is yesterday's last bar, so the first hourly signal is a gap-and-reclaim, not a reclaim (35% of its signals).

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 42.8 | 47.8 | 68.6 |
| Stop / target, median bp | 52 / 94 | 88 / 158 | 101 / 182 |
| Planned reward : risk | 1.8 | 1.8 | 1.8 |
| Signals in the first hour (to 10:15) | 11.1% | 0.0% | 34.7% |
| Same signal on the bar before | 1.2% | 3.2% | 6.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 21,199 | 23,637 | 33,940 |
| Edge before costs, bp (t, clustered by day) | +1.01 (1.82) | +3.13 (3.51) | +2.83 (3.75) |
| Same edge with every day weighted equally, bp | +2.92 | +4.56 | +3.82 |
| Slippage + charges, bp | 6.3 + 4.0 | 6.6 + 4.0 | 6.6 + 4.0 |
| Net per trade, bp (t, clustered by day) | -9.31 (-16.54) | -7.48 (-8.34) | -7.80 (-10.29) |
| Win rate / direction right | 38.2% / 43.9% | 42.5% / 48.6% | 42.9% / 49.1% |
| Average win ÷ average loss | 1.15 | 1.08 | 1.06 |
| Exits: target / stop / time / close | 15 / 42 / 33 / 10 % | 7 / 25 / 35 / 34 % | 5 / 21 / 40 / 34 % |
| Median hold, minutes | 75 | 150 | 165 |
| Net bp: first 18 months / last 6 months | -9.1 / -9.8 | -7.0 / -8.6 | -7.2 / -9.1 |
| **Solo book (₹50 lakh):** trades | 4,164 | 3,205 | 3,645 |
| 2-year P&L, ₹ lakh (return) | -31.8 (-63.7%) | -17.5 (-34.9%) | -16.6 (-33.1%) |
| Win rate / profit factor | 39.1% / 0.766 | 42.9% / 0.863 | 44.7% / 0.897 |
| Max drawdown, ₹ lakh (% of capital) | 32.9 (65.8%) | 19.4 (38.8%) | 17.4 (34.8%) |
| Sharpe (annualised) | -4.71 | -2.15 | -1.54 |
| Months up / worst month ₹ lakh | 4/25 / -4.0 | 9/25 / -2.3 | 8/25 / -3.2 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -17.1 / -14.7 / -6.7 | -11.0 / -6.4 / -2.8 | -11.1 / -5.5 / -2.8 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -33.0 (-1.2) | -13.5 (+3.9) | -22.4 (-5.8) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -1.8 (227, 37.0%) | +1.2 (117, 49.6%) | -0.9 (147, 42.9%) |
| Live trades the backtest reproduces / same exit | 52% / 92% | 58% / 94% | 37% / 98% |
| Verdict | Weak | Real, below costs | Real, below costs |

**Reading it.** This is the only family whose edge before costs is believable after 52 tests (45m: +3.1 bp, t 3.5; 1h: +2.8 bp, t 3.75). It is still a third of the cost of a trade, so it loses 7.5–7.8 bp after costs. The six rules the Phase 3 depth recorder follows include VWAP Reclaim 1h for this reason.

### Prior-Day High/Low Break — `iv2_pdh_pdl_*`
**Rule.** BUY on the first close of the day above yesterday's high (no earlier close today above it), with volume at least 1.2 × the 20-bar average. SELL is the mirror at yesterday's low. Stop 1.0 ATR, target 2.0 ATR.

**Code review.** Correct. A stock that opens above yesterday's high and closes there before 09:45 is skipped for the day, by design ("first close"). The same untimed volume filter as Donchian puts 78–80% of the 45m and 1h signals in the first hour.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 23.3 | 46.8 | 45.8 |
| Stop / target, median bp | 54 / 108 | 90 / 181 | 101 / 202 |
| Planned reward : risk | 2.0 | 2.0 | 2.0 |
| Signals in the first hour (to 10:15) | 50.0% | 77.8% | 79.9% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 11,527 | 23,178 | 22,653 |
| Edge before costs, bp (t, clustered by day) | -0.54 (-0.44) | +1.31 (0.8) | +1.92 (1.18) |
| Same edge with every day weighted equally, bp | -0.73 | +2.01 | +1.39 |
| Slippage + charges, bp | 6.4 + 4.0 | 6.6 + 4.0 | 6.7 + 4.0 |
| Net per trade, bp (t, clustered by day) | -10.96 (-8.71) | -9.29 (-5.68) | -8.77 (-5.4) |
| Win rate / direction right | 35.4% / 39.3% | 40.8% / 45.2% | 42.1% / 47.2% |
| Average win ÷ average loss | 1.29 | 1.15 | 1.1 |
| Exits: target / stop / time / close | 16 / 52 / 28 / 4 % | 8 / 34 / 51 / 6 % | 5 / 27 / 58 / 9 % |
| Median hold, minutes | 60 | 180 | 180 |
| Net bp: first 18 months / last 6 months | -10.6 / -11.6 | -7.7 / -12.6 | -7.0 / -12.4 |
| **Solo book (₹50 lakh):** trades | 2,908 | 2,991 | 2,537 |
| 2-year P&L, ₹ lakh (return) | -40.2 (-80.4%) | -14.9 (-29.8%) | -25.0 (-49.9%) |
| Win rate / profit factor | 33.6% / 0.639 | 42.9% / 0.894 | 41.4% / 0.793 |
| Max drawdown, ₹ lakh (% of capital) | 40.2 (80.4%) | 19.2 (38.5%) | 26.2 (52.3%) |
| Sharpe (annualised) | -6.15 | -1.45 | -2.71 |
| Months up / worst month ₹ lakh | 1/24 / -5.3 | 9/25 / -3.7 | 5/25 / -4.0 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -23.6 / -16.5 / -6.1 | -14.2 / -0.7 / +0.2 | -17.9 / -7.1 / -1.2 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -34.3 (+5.8) | -17.0 (-2.1) | -15.9 (+9.1) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.1 (209, 36.4%) | -1.2 (100, 45.0%) | +0.4 (100, 50.0%) |
| Live trades the backtest reproduces / same exit | 73% / 91% | 65% / 94% | 57% / 100% |
| Verdict | None | Weak | Weak |

### Opening-Range Close Break — `iv2_or_close_break_*`
**Rule.** The opening range is the 09:15–09:45 high and low. With relative volume ≥ 1.2, BUY on the first close of the day above the range high; SELL on the first close below the range low. Stop 1.0 ATR, target 2.0 ATR.

**Code review.** Correct. On 15m the first possible signal is the 10:00 close; the 09:45 close is a range bar and cannot break its own range.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 24.7 | 22.7 | 22.8 |
| Stop / target, median bp | 62 / 124 | 96 / 192 | 107 / 213 |
| Planned reward : risk | 2.0 | 2.0 | 2.0 |
| Signals in the first hour (to 10:15) | 43.0% | 31.0% | 40.0% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 12,237 | 11,220 | 11,284 |
| Edge before costs, bp (t, clustered by day) | +0.59 (0.58) | +1.39 (0.98) | +2.27 (1.7) |
| Same edge with every day weighted equally, bp | +1.12 | +3.19 | +1.26 |
| Slippage + charges, bp | 6.3 + 4.0 | 6.5 + 4.0 | 6.6 + 4.0 |
| Net per trade, bp (t, clustered by day) | -9.77 (-9.42) | -9.19 (-6.45) | -8.39 (-6.29) |
| Win rate / direction right | 38.4% / 42.6% | 42.5% / 47.3% | 43.2% / 48.4% |
| Average win ÷ average loss | 1.2 | 1.07 | 1.06 |
| Exits: target / stop / time / close | 13 / 45 / 38 / 4 % | 7 / 29 / 46 / 18 % | 4 / 23 / 46 / 27 % |
| Median hold, minutes | 90 | 165 | 165 |
| Net bp: first 18 months / last 6 months | -9.1 / -11.1 | -9.0 / -9.6 | -8.5 / -8.1 |
| **Solo book (₹50 lakh):** trades | 3,635 | 2,801 | 2,559 |
| 2-year P&L, ₹ lakh (return) | -30.4 (-60.9%) | -24.1 (-48.3%) | -20.4 (-40.8%) |
| Win rate / profit factor | 39.2% / 0.781 | 43.1% / 0.816 | 43.3% / 0.823 |
| Max drawdown, ₹ lakh (% of capital) | 32.1 (64.1%) | 27.2 (54.3%) | 24.3 (48.5%) |
| Sharpe (annualised) | -3.94 | -2.83 | -2.45 |
| Months up / worst month ₹ lakh | 5/25 / -4.2 | 7/25 / -2.6 | 6/25 / -3.6 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -15.4 / -15.1 / -6.4 | -13.4 / -10.8 / -5.1 | -16.1 / -4.4 / +1.2 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -29.6 (+0.8) | -15.0 (+9.1) | -10.6 (+9.8) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.0 (167, 38.3%) | -0.8 (86, 41.9%) | +1.0 (82, 50.0%) |
| Live trades the backtest reproduces / same exit | 41% / 96% | 52% / 100% | 43% / 97% |
| Verdict | Weak | Weak | Weak |

## Mean-reversion families (18 strategies — none trades a stock "in play", i.e. relative volume > 1.8)

### VWAP Reversion — `iv2_vwap_reversion_*`
**Rule.** BUY when the close is at least 1.5 ATR below the session VWAP and closed at least 30% off the bar's low; target = that VWAP, stop 1.0 ATR. SELL is the mirror. Priority = the stretch in ATRs.

**Code review.** Correct as written.
- The stretch is measured in the timeframe's own ATR, so the 45m and 1h versions almost never fire (2.0 and 0.7 signals a session against 191 for 15m).
- The 15m version fires on the next bar 42% of the time while a stock stays stretched. Once a position is closed, it re-enters the same stretched stock.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 191.1 | 2.0 | 0.7 |
| Stop / target, median bp | 41 / 83 | 78 / 133 | 93 / 153 |
| Planned reward : risk | 1.92 | 1.63 | 1.61 |
| Signals in the first hour (to 10:15) | 0.3% | 0.0% | 0.0% |
| Same signal on the bar before | 41.8% | 12.9% | 9.6% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 94,589 | 1,012 | 332 |
| Edge before costs, bp (t, clustered by day) | -2.70 (-3.81) | -2.14 (-0.64) | -4.08 (-0.94) |
| Same edge with every day weighted equally, bp | -1.35 | -2.46 | -6.92 |
| Slippage + charges, bp | 6.5 + 4.0 | 6.8 + 4.0 | 6.9 + 4.0 |
| Net per trade, bp (t, clustered by day) | -13.19 (-18.32) | -12.96 (-3.84) | -14.97 (-3.44) |
| Win rate / direction right | 33.1% / 39.6% | 39.2% / 47.3% | 35.2% / 47.6% |
| Average win ÷ average loss | 1.08 | 0.93 | 0.89 |
| Exits: target / stop / time / close | 12 / 48 / 15 / 24 % | 4 / 21 / 1 / 73 % | 2 / 9 / 0 / 89 % |
| Median hold, minutes | 60 | 75 | 45 |
| Net bp: first 18 months / last 6 months | -12.8 / -14.1 | -8.8 / -23.2 | -11.7 / -21.2 |
| **Solo book (₹50 lakh):** trades | 2,769 | 727 | 273 |
| 2-year P&L, ₹ lakh (return) | -40.5 (-80.9%) | -11.0 (-22.1%) | -4.8 (-9.5%) |
| Win rate / profit factor | 33.1% / 0.53 | 38.2% / 0.555 | 34.4% / 0.42 |
| Max drawdown, ₹ lakh (% of capital) | 40.6 (81.1%) | 11.2 (22.4%) | 4.8 (9.5%) |
| Sharpe (annualised) | -8.14 | -3.55 | -2.96 |
| Months up / worst month ₹ lakh | 1/23 / -3.7 | 6/25 / -1.4 | 2/25 / -0.8 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -30.8 / -9.6 / -3.1 | -2.9 / -8.1 / -5.1 | -1.2 / -3.6 / -2.4 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -40.3 (+0.2) | -6.4 (+4.6) | -2.2 (+2.5) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -3.7 (220, 32.7%) | -1.0 (22, 4.5%) | -0.3 (5, 20.0%) |
| Live trades the backtest reproduces / same exit | 41% / 96% | 54% / 92% | 40% / 100% |
| Verdict | None | None | None |

**Reading it.** Fading a 15-minute stretch from VWAP loses even before costs (−2.7 bp, t −3.8): intraday stretches keep going more often than they come back. Of all 54 strategies this is the one most clearly wrong in direction.

### RSI(2) Extreme — `iv2_rsi2_*`
**Rule.** BUY when RSI(2) < 5 with the close above EMA50; SELL when RSI(2) > 95 below EMA50. Stop 1.2 ATR, target 1.0 ATR (reward : risk 0.83). Priority = depth.

**Code review.** Correct. There is no "first bar" condition, so 32–34% of signals repeat on the next bar. A reward : risk of 0.83 needs a win rate above 55% before costs. It wins 43–44%.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 43.9 | 17.3 | 16.2 |
| Stop / target, median bp | 50 / 42 | 95 / 79 | 109 / 90 |
| Planned reward : risk | 0.83 | 0.83 | 0.83 |
| Signals in the first hour (to 10:15) | 9.8% | 28.2% | 28.3% |
| Same signal on the bar before | 34.3% | 32.0% | 32.7% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 21,743 | 8,552 | 8,021 |
| Edge before costs, bp (t, clustered by day) | -2.16 (-2.84) | -1.82 (-1.11) | -1.22 (-0.73) |
| Same edge with every day weighted equally, bp | -0.65 | +0.84 | +2.47 |
| Slippage + charges, bp | 5.7 + 4.0 | 6.0 + 4.0 | 6.2 + 4.0 |
| Net per trade, bp (t, clustered by day) | -11.83 (-15.15) | -11.81 (-7.1) | -11.47 (-6.74) |
| Win rate / direction right | 43.5% / 48.6% | 44.2% / 49.6% | 42.9% / 49.8% |
| Average win ÷ average loss | 0.75 | 0.86 | 0.91 |
| Exits: target / stop / time / close | 36 / 39 / 14 / 11 % | 25 / 22 / 30 / 23 % | 18 / 15 / 29 / 38 % |
| Median hold, minutes | 60 | 120 | 135 |
| Net bp: first 18 months / last 6 months | -11.9 / -11.7 | -11.3 / -12.9 | -10.8 / -12.8 |
| **Solo book (₹50 lakh):** trades | 3,258 | 2,638 | 2,511 |
| 2-year P&L, ₹ lakh (return) | -40.3 (-80.7%) | -25.8 (-51.5%) | -26.6 (-53.3%) |
| Win rate / profit factor | 43.8% / 0.56 | 46.3% / 0.733 | 43.1% / 0.704 |
| Max drawdown, ₹ lakh (% of capital) | 40.3 (80.7%) | 26.2 (52.5%) | 26.6 (53.3%) |
| Sharpe (annualised) | -8.75 | -4.1 | -4.36 |
| Months up / worst month ₹ lakh | 0/23 / -3.6 | 4/25 / -2.3 | 3/25 / -2.6 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -25.4 / -14.9 / -4.8 | -13.6 / -12.2 / -8.3 | -14.4 / -12.2 / -7.5 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -40.3 (-0.0) | -23.7 (+2.1) | -25.6 (+1.0) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.7 (273, 48.0%) | -2.3 (139, 42.4%) | -1.2 (112, 45.5%) |
| Live trades the backtest reproduces / same exit | 57% / 90% | 76% / 95% | 71% / 94% |
| Verdict | None | None | None |

### Bollinger Snap-Back — `iv2_bollinger_snap_*`
**Rule.** BUY when the previous close was below the lower band (SMA20 − 2 SD) and this close is back inside; target = SMA20 (the middle band), stop 1.0 ATR. SELL is the mirror.

**Code review.** Correct. Bollinger uses the population SD, as standard, and matches the reference exactly. 2.4% of signals are skipped because the fill is already past the middle band.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 133.9 | 43.0 | 32.8 |
| Stop / target, median bp | 49 / 76 | 79 / 132 | 88 / 149 |
| Planned reward : risk | 1.59 | 1.7 | 1.72 |
| Signals in the first hour (to 10:15) | 37.6% | 7.4% | 10.1% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 97.7% | 97.6% | 97.6% |
| **Every signal as a trade:** trades | 64,773 | 20,770 | 15,857 |
| Edge before costs, bp (t, clustered by day) | +0.14 (0.24) | +1.64 (1.28) | +2.88 (1.99) |
| Same edge with every day weighted equally, bp | +0.33 | +2.07 | +2.37 |
| Slippage + charges, bp | 6.0 + 4.0 | 6.4 + 4.0 | 6.5 + 4.0 |
| Net per trade, bp (t, clustered by day) | -9.90 (-16.58) | -8.78 (-6.8) | -7.65 (-5.28) |
| Win rate / direction right | 42.1% / 46.8% | 43.7% / 50.3% | 43.6% / 51.4% |
| Average win ÷ average loss | 0.91 | 0.94 | 0.97 |
| Exits: target / stop / time / close | 25 / 43 / 28 / 4 % | 14 / 25 / 27 / 35 % | 11 / 17 / 21 / 51 % |
| Median hold, minutes | 60 | 120 | 105 |
| Net bp: first 18 months / last 6 months | -10.1 / -9.4 | -8.0 / -10.4 | -6.9 / -9.2 |
| **Solo book (₹50 lakh):** trades | 4,336 | 2,994 | 3,224 |
| 2-year P&L, ₹ lakh (return) | -35.2 (-70.3%) | -26.7 (-53.3%) | -20.7 (-41.4%) |
| Win rate / profit factor | 43.3% / 0.709 | 44.1% / 0.727 | 45.4% / 0.78 |
| Max drawdown, ₹ lakh (% of capital) | 35.2 (70.3%) | 27.1 (54.1%) | 20.7 (41.4%) |
| Sharpe (annualised) | -5.67 | -4.36 | -3.42 |
| Months up / worst month ₹ lakh | 2/25 / -4.2 | 4/25 / -2.6 | 4/25 / -3.1 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -24.7 / -10.5 / -2.5 | -16.1 / -10.5 / -4.3 | -11.4 / -9.3 / -6.8 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -33.5 (+1.6) | -26.4 (+0.2) | -20.5 (+0.2) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -0.9 (303, 50.5%) | -2.0 (144, 43.1%) | -2.0 (132, 43.9%) |
| Live trades the backtest reproduces / same exit | 48% / 97% | 65% / 97% | 67% / 98% |
| Verdict | Weak | Weak | Weak |

### Z-Score Fade in Range — `iv2_zscore_*`
**Rule.** Only when ADX(14) < 25. With z = (close − SMA20) / SD20, BUY when z ≤ −2.5 and SELL when z ≥ +2.5; target = SMA20, stop 1.2 ATR. Priority = |z|.

**Code review.** The "range" filter uses the fast ADX (§1.2), which reads higher than the standard one, so the filter lets fewer bars through than "ADX < 25" means on a chart. Signals repeat on the next bar 9–16% of the time.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 11.0 | 4.4 | 3.4 |
| Stop / target, median bp | 56 / 81 | 92 / 149 | 106 / 170 |
| Planned reward : risk | 1.46 | 1.61 | 1.61 |
| Signals in the first hour (to 10:15) | 49.1% | 47.1% | 54.3% |
| Same signal on the bar before | 16.3% | 10.5% | 8.9% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 5,450 | 2,200 | 1,684 |
| Edge before costs, bp (t, clustered by day) | -2.27 (-1.54) | -1.93 (-0.81) | -5.73 (-2.05) |
| Same edge with every day weighted equally, bp | -1.80 | -0.11 | +0.80 |
| Slippage + charges, bp | 6.2 + 4.0 | 6.5 + 4.0 | 6.7 + 4.0 |
| Net per trade, bp (t, clustered by day) | -12.47 (-8.32) | -12.47 (-5.2) | -16.41 (-5.83) |
| Win rate / direction right | 39.6% / 44.9% | 42.9% / 47.5% | 41.8% / 47.9% |
| Average win ÷ average loss | 0.95 | 0.91 | 0.85 |
| Exits: target / stop / time / close | 21 / 42 / 31 / 5 % | 9 / 27 / 48 / 16 % | 6 / 21 / 50 / 23 % |
| Median hold, minutes | 75 | 165 | 180 |
| Net bp: first 18 months / last 6 months | -12.3 / -12.8 | -13.7 / -10.1 | -16.5 / -16.2 |
| **Solo book (₹50 lakh):** trades | 2,426 | 1,495 | 1,206 |
| 2-year P&L, ₹ lakh (return) | -30.9 (-61.8%) | -14.5 (-29.1%) | -16.1 (-32.3%) |
| Win rate / profit factor | 38.5% / 0.607 | 43.7% / 0.747 | 42.4% / 0.663 |
| Max drawdown, ₹ lakh (% of capital) | 30.9 (61.9%) | 15.0 (30.0%) | 16.7 (33.5%) |
| Sharpe (annualised) | -6.33 | -2.9 | -3.38 |
| Months up / worst month ₹ lakh | 1/25 / -3.5 | 4/25 / -2.0 | 6/25 / -2.3 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -19.7 / -11.2 / -4.8 | -7.6 / -7.0 / -2.1 | -7.4 / -8.7 / -3.4 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -30.5 (+0.4) | -14.4 (+0.2) | -14.1 (+2.1) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.3 (193, 40.9%) | -0.9 (90, 47.8%) | -0.8 (62, 41.9%) |
| Live trades the backtest reproduces / same exit | 84% / 97% | 96% / 100% | 79% / 98% |
| Verdict | None | None | None |

### Stochastic Range Turn — `iv2_stoch_range_*`
**Rule.** Only when ADX(14) < 20. BUY when fast %K(14) crosses above %D(3) below 20; SELL when it crosses below %D above 80. Stop 1.0 ATR, target 1.0 ATR.

**Code review.**
- This is the fast stochastic (%K unsmoothed), not the slow one most platforms show by default.
- The ADX < 20 filter uses the fast ADX: it passes 7–11% of bars against 27–28% for standard ADX. So the "range" this rule trades is narrower than its name suggests.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 9.2 | 2.2 | 1.8 |
| Stop / target, median bp | 39 / 39 | 70 / 70 | 82 / 82 |
| Planned reward : risk | 1.0 | 1.0 | 1.0 |
| Signals in the first hour (to 10:15) | 6.4% | 11.0% | 14.4% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 4,575 | 1,109 | 886 |
| Edge before costs, bp (t, clustered by day) | -2.18 (-2.91) | -2.18 (-0.97) | +1.85 (0.82) |
| Same edge with every day weighted equally, bp | -2.61 | -0.53 | +2.84 |
| Slippage + charges, bp | 5.7 + 4.0 | 6.2 + 4.0 | 6.5 + 4.0 |
| Net per trade, bp (t, clustered by day) | -11.93 (-15.43) | -12.44 (-5.45) | -8.62 (-3.75) |
| Win rate / direction right | 39.9% / 44.4% | 39.6% / 45.4% | 38.6% / 48.4% |
| Average win ÷ average loss | 0.8 | 0.92 | 1.08 |
| Exits: target / stop / time / close | 34 / 46 / 12 / 8 % | 21 / 26 / 13 / 41 % | 14 / 14 / 10 / 62 % |
| Median hold, minutes | 45 | 105 | 105 |
| Net bp: first 18 months / last 6 months | -11.1 / -13.4 | -11.4 / -14.2 | -8.1 / -9.4 |
| **Solo book (₹50 lakh):** trades | 2,651 | 950 | 783 |
| 2-year P&L, ₹ lakh (return) | -32.8 (-65.7%) | -11.1 (-22.3%) | -6.3 (-12.7%) |
| Win rate / profit factor | 39.5% / 0.516 | 40.3% / 0.623 | 39.2% / 0.7 |
| Max drawdown, ₹ lakh (% of capital) | 32.9 (65.7%) | 11.5 (23.1%) | 6.5 (12.9%) |
| Sharpe (annualised) | -9.52 | -3.56 | -2.45 |
| Months up / worst month ₹ lakh | 0/25 / -2.5 | 5/25 / -1.8 | 6/25 / -1.6 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -13.3 / -19.6 / -10.4 | -3.6 / -7.5 / -4.3 | -1.9 / -4.5 / -3.1 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -29.2 (+3.7) | -9.6 (+1.5) | -3.9 (+2.4) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.7 (193, 37.3%) | -1.1 (79, 38.0%) | -0.5 (67, 41.8%) |
| Live trades the backtest reproduces / same exit | 61% / 92% | 75% / 98% | 76% / 98% |
| Verdict | None | None | Weak |

### CCI ±200 Return — `iv2_cci_extreme_*`
**Rule.** BUY when CCI(20) comes back up through −200; SELL when it comes back down through +200. Stop 1.2 ATR, target 1.0 ATR (reward : risk 0.83).

**Code review.** Correct. CCI uses 0.015 × the mean absolute deviation and matches the reference exactly.

| | 15 min | 45 min | 1 hour |
|---|---:|---:|---:|
| Signals per session | 77.6 | 22.5 | 16.1 |
| Stop / target, median bp | 62 / 52 | 97 / 81 | 108 / 90 |
| Planned reward : risk | 0.83 | 0.83 | 0.83 |
| Signals in the first hour (to 10:15) | 49.4% | 7.7% | 10.9% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 100.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 38,398 | 11,157 | 7,982 |
| Edge before costs, bp (t, clustered by day) | +0.14 (0.19) | +1.04 (0.75) | +2.62 (1.55) |
| Same edge with every day weighted equally, bp | +0.31 | +2.41 | +2.66 |
| Slippage + charges, bp | 5.5 + 4.0 | 6.1 + 4.0 | 6.3 + 4.0 |
| Net per trade, bp (t, clustered by day) | -9.44 (-13.17) | -9.05 (-6.44) | -7.72 (-4.53) |
| Win rate / direction right | 46.9% / 51.0% | 44.1% / 50.6% | 43.8% / 50.9% |
| Average win ÷ average loss | 0.79 | 0.93 | 0.97 |
| Exits: target / stop / time / close | 38 / 35 / 24 / 3 % | 23 / 18 / 26 / 33 % | 16 / 12 / 17 / 55 % |
| Median hold, minutes | 60 | 135 | 105 |
| Net bp: first 18 months / last 6 months | -9.9 / -8.4 | -8.3 / -10.5 | -6.6 / -9.9 |
| **Solo book (₹50 lakh):** trades | 4,380 | 2,647 | 2,584 |
| 2-year P&L, ₹ lakh (return) | -31.9 (-63.7%) | -22.0 (-43.9%) | -21.1 (-42.2%) |
| Win rate / profit factor | 47.8% / 0.748 | 43.8% / 0.757 | 44.0% / 0.746 |
| Max drawdown, ₹ lakh (% of capital) | 32.0 (63.9%) | 23.2 (46.3%) | 21.7 (43.3%) |
| Sharpe (annualised) | -5.41 | -3.67 | -3.58 |
| Months up / worst month ₹ lakh | 3/25 / -3.6 | 4/25 / -2.9 | 4/25 / -2.5 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -24.0 / -7.8 / -3.4 | -12.7 / -9.3 / -5.1 | -11.6 / -9.5 / -7.6 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -31.8 (+0.1) | -17.6 (+4.4) | -16.5 (+4.5) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | -2.2 (252, 47.2%) | -0.6 (119, 42.9%) | -0.5 (111, 46.8%) |
| Live trades the backtest reproduces / same exit | 61% / 93% | 69% / 96% | 64% / 94% |
| Verdict | Weak | Weak | Weak |

## Day setups (6 strategies, decided once on the 09:45 read)

**ORB Stocks-in-Play, stop 10% / 25% of ATR** — `iv2_orb_inplay_10`, `iv2_orb_inplay_25`.
- **Rule.** At 09:45, take the 20 stocks with the highest relative volume (≥ 1.0). If the 09:15–09:45 candle closed up, place a buy-stop at its high; if down, a sell-stop at its low; a doji gets none. The order fills on the first cross until 14:30. Stop = 10% (or 25%) of the 14-session daily ATR. No target: held to the square-off.
- **Code review.** Correct as written. It departs from the paper it cites (Zarattini, Barbon & Aziz 2024) in three deliberate ways:
  - a 30-minute range, not the first 5 minutes;
  - a fixed ₹10 lakh, not 1% risk sizing;
  - NSE stocks with Indian costs.
- **The cost problem.** With a 10% ATR stop the median stop is 26 bp, so the 10.7 bp round trip is 41% of the risk.

**Gap and Go** — `iv2_gap_go`.
- **Rule.** At 09:45, with relative volume ≥ 2.0: a gap of at least +1%, the whole 30-minute range above yesterday's close, and a green 30-minute candle → BUY at the 09:45 close. Stop = max(close − range low, 0.15 daily ATR); target 2 × stop; otherwise held to the close. SELL is the mirror.
- **Code review.** Correct. "Yesterday's close" is the last 15m close (§1.6).

**Gap Fade** — `iv2_gap_fade`.
- **Rule.** At 09:45, with relative volume < 1.2: a gap of at least +1.5% that has sold off to between yesterday's close and today's open → SELL. Stop = max(range high − close, 0.15 daily ATR); target = the smaller of the rest of the gap and 2 × stop. BUY is the mirror.
- **Code review.** Correct. When most of the gap has filled by 09:45, the target can be smaller than the trade's own cost: that happens in 1.4% of signals.

| | ORB in play 10% | ORB in play 25% | Gap and Go | Gap Fade |
|---|---:|---:|---:|---:|
| Signals per session | 17.5 | 17.5 | 2.6 | 2.2 |
| Stop / target, median bp | 26 / none (close) | 65 / none (close) | 194 / 388 | 140 / 110 |
| Planned reward : risk | — | — | 2.0 | 0.91 |
| Signals in the first hour (to 10:15) | 100.0% | 100.0% | 100.0% | 100.0% |
| Same signal on the bar before | 0.0% | 0.0% | 0.0% | 0.0% |
| Signals that became trades | 67.0% | 67.0% | 100.0% | 100.0% |
| **Every signal as a trade:** trades | 5,807 | 5,807 | 1,264 | 1,105 |
| Edge before costs, bp (t, clustered by day) | -15.98 (-24.26) | -6.32 (-3.77) | +8.89 (1.32) | -5.44 (-0.61) |
| Same edge with every day weighted equally, bp | -15.80 | -6.57 | +0.74 | -2.52 |
| Slippage + charges, bp | 6.7 + 4.0 | 6.7 + 4.0 | 6.4 + 4.0 | 5.7 + 4.0 |
| Net per trade, bp (t, clustered by day) | -26.69 (-40.4) | -17.04 (-10.16) | -1.58 (-0.23) | -15.17 (-1.69) |
| Win rate / direction right | 5.3% / 5.5% | 28.7% / 30.4% | 45.2% / 47.8% | 49.5% / 52.0% |
| Average win ÷ average loss | 3.61 | 1.65 | 1.19 | 0.74 |
| Exits: target / stop / time / close | 0 / 94 / 0 / 6 % | 0 / 64 / 0 / 36 % | 7 / 26 / 0 / 67 % | 38 / 34 / 0 / 28 % |
| Median hold, minutes | 15 | 75 | 315 | 135 |
| Net bp: first 18 months / last 6 months | -25.8 / -28.9 | -15.8 / -20.2 | -0.5 / -3.6 | -19.0 / -4.2 |
| **Solo book (₹50 lakh):** trades | 1,611 | 2,256 | 887 | 454 |
| 2-year P&L, ₹ lakh (return) | -40.4 (-80.7%) | -39.6 (-79.1%) | -2.8 (-5.5%) | -2.6 (-5.3%) |
| Win rate / profit factor | 5.7% / 0.186 | 28.0% / 0.647 | 44.6% / 0.955 | 52.4% / 0.88 |
| Max drawdown, ₹ lakh (% of capital) | 40.4 (80.7%) | 40.2 (80.4%) | 6.7 (13.5%) | 4.3 (8.7%) |
| Sharpe (annualised) | -11.03 | -5.16 | -0.35 | -0.68 |
| Months up / worst month ₹ lakh | 0/18 / -5.2 | 2/25 / -3.6 | 8/24 / -2.5 | 10/25 / -1.3 |
| Year 1 / year 2 / last 6 months, ₹ lakh | -37.9 / -2.5 / -0.1 | -19.4 / -20.2 / -10.6 | -3.8 / +1.1 / +0.5 | -1.4 / -1.2 / -0.3 |
| **Tournament:** 2-year ₹ lakh (vs solo) | -40.3 (+0.1) | -32.3 (+7.2) | -10.8 (-8.0) | -2.6 (+0.0) |
| **Live paper** 6 Oct–3 Nov: ₹ lakh (trades, win %) | +0.5 (125, 22.4%) | +1.9 (64, 43.8%) | +1.5 (66, 50.0%) | +0.4 (24, 54.2%) |
| Live trades the backtest reproduces / same exit | 67% / 82% | 66% / 86% | 73% / 92% | 100% / 96% |
| Verdict | None | None | Weak | None |

**Reading it.**
- **ORB 10%.** The stop is hit on 94% of trades in the backtest's pessimistic reading (−26.7 bp a trade) and the optimistic reading still loses −6.5 bp. ORB 25% loses −17.0 bp (pessimistic) and −2.3 bp (optimistic). The live record (+₹0.5 lakh and +₹1.9 lakh) sits between the two readings, at the old, lower costs.
- **Gap and Go comes closest to break-even** (−1.6 bp a trade; −₹2.8 lakh over two years; +₹1.1 lakh in year 2). It has the largest edge before costs (+8.9 bp), but on 2.6 signals a session that edge is noise (t 1.3).

**Selected ORB 30 / 15** — `iv2_orb_sel30`, `iv2_orb_sel15`.
- **Rule.** Pre-registered 2 Oct 2026 and frozen. Take the five stocks with the highest expected move and opening volume ≥ 1.5×. Both edges of the 30- or 15-minute range get stop entries; the first one crossed cancels the other, and a minute crossing both is no trade.
  - **sel30:** stop 0.5 daily ATR, target 2R.
  - **sel15:** stop at the opposite edge, held to the close, entries from 09:30.
- **Book.** Each has its own book (exempt from the per-stock cap) and keeps the old cost model, so its forward record stays comparable with its registration.
- **Code review.** Correct, including the both-edges-in-one-minute rule.
- **Not replayable here.** These rules need the Scanner Board's expected-move ranking, which this backtest cannot rebuild. Their evidence is the S4 study recorded in the code: development / holdout +21.7 / +21.1 bp (sel30) and +36.1 / +18.6 bp (sel15) a trade, net of the old costs.
- **Live so far:** sel30 −₹0.65 lakh (48 trades, 44% won); sel15 +₹1.72 lakh (28 trades, 57% won). That is too few trades to judge; the pre-registration says when it will be judged.

---

# Part 1 — Master table (all 54)

| # | Strategy | TF | Signals / day | Edge before costs bp (t, clustered by day) | Costs bp | Net / trade bp | Win % | Solo 2-yr ₹L | Return % | Max DD % | Months up | Last 6 mo ₹L | Tournament 2-yr ₹L | Live 20 d ₹L (trades) | Verdict |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | Donchian 20 Breakout · 15 min | 15m | 95.9 | +0.76 (0.87) | 10.4 | -9.63 | 36.6 | -36.4 | -72.8 | 75.2 | 4/25 | -2.4 | -34.2 | -2.0 (309) | Weak |
| 2 | Donchian 20 Breakout · 45 min | 45m | 52.3 | +2.54 (1.71) | 10.6 | -8.07 | 41.6 | -16.1 | -32.3 | 36.3 | 7/25 | -3.1 | -22.5 | -1.8 (143) | Weak |
| 3 | Donchian 20 Breakout · 1 hour | 1h | 45.3 | +3.64 (2.44) | 10.7 | -7.04 | 42.8 | -13.9 | -27.8 | 34.5 | 11/25 | +0.5 | -20.4 | +1.1 (138) | Small, unproven |
| 4 | EMA Trend Pullback · 15 min | 15m | 169.5 | +0.14 (0.28) | 10.3 | -10.21 | 36.0 | -36.0 | -72.0 | 72.6 | 2/25 | -5.0 | -37.4 | -2.9 (294) | Weak |
| 5 | EMA Trend Pullback · 45 min | 45m | 60.1 | +1.45 (1.47) | 10.7 | -9.21 | 41.0 | -22.6 | -45.3 | 48.5 | 5/25 | -2.4 | -27.1 | -0.3 (174) | Weak |
| 6 | EMA Trend Pullback · 1 hour | 1h | 48.7 | +1.39 (1.23) | 10.8 | -9.38 | 41.4 | -31.5 | -63.0 | 65.6 | 4/25 | -5.8 | -32.6 | -0.1 (157) | Weak |
| 7 | MACD Trend Turn · 15 min | 15m | 79.8 | +1.29 (2.09) | 10.4 | -9.13 | 39.0 | -32.7 | -65.4 | 66.3 | 4/25 | -6.1 | -32.1 | -2.7 (263) | Small, unproven |
| 8 | MACD Trend Turn · 45 min | 45m | 35.5 | +1.06 (0.74) | 10.7 | -9.60 | 41.8 | -24.2 | -48.3 | 50.7 | 5/25 | -2.9 | -27.1 | -1.0 (147) | Weak |
| 9 | MACD Trend Turn · 1 hour | 1h | 29.6 | +3.42 (2.11) | 10.8 | -7.34 | 42.8 | -14.9 | -29.8 | 31.3 | 9/25 | -2.3 | -21.4 | +1.6 (159) | Small, unproven |
| 10 | Keltner Breakout · 15 min | 15m | 92.4 | +0.99 (1.34) | 10.4 | -9.40 | 36.9 | -37.6 | -75.2 | 76.8 | 4/25 | -6.7 | -38.1 | -0.8 (295) | Weak |
| 11 | Keltner Breakout · 45 min | 45m | 38.8 | +2.86 (1.89) | 10.6 | -7.78 | 42.0 | -20.1 | -40.3 | 48.3 | 10/25 | +2.3 | -21.5 | +1.3 (160) | Weak |
| 12 | Keltner Breakout · 1 hour | 1h | 32.3 | +3.41 (2.2) | 10.7 | -7.30 | 42.4 | -25.9 | -51.7 | 52.7 | 5/25 | -1.1 | -23.9 | +1.4 (152) | Small, unproven |
| 13 | Supertrend Flip · 15 min | 15m | 46.0 | +0.94 (0.95) | 10.6 | -9.67 | 40.5 | -33.4 | -66.7 | 67.8 | 0/25 | -6.9 | -30.2 | +0.1 (227) | Weak |
| 14 | Supertrend Flip · 45 min | 45m | 27.7 | +1.74 (1.01) | 10.8 | -9.01 | 42.9 | -17.2 | -34.4 | 40.7 | 7/25 | -5.3 | -20.0 | +2.3 (138) | Weak |
| 15 | Supertrend Flip · 1 hour | 1h | 23.0 | +3.85 (2.19) | 10.8 | -6.94 | 43.9 | -18.6 | -37.2 | 41.7 | 7/25 | -2.5 | -24.1 | +1.3 (129) | Small, unproven |
| 16 | ADX Trend Start · 15 min | 15m | 59.6 | +1.81 (2.97) | 10.6 | -8.76 | 38.1 | -30.6 | -61.1 | 63.2 | 3/25 | -6.7 | -31.6 | -1.0 (254) | Small, unproven |
| 17 | ADX Trend Start · 45 min | 45m | 26.4 | +1.72 (1.3) | 10.8 | -9.04 | 41.9 | -20.7 | -41.4 | 41.4 | 5/25 | -4.3 | -20.7 | -0.1 (133) | Weak |
| 18 | ADX Trend Start · 1 hour | 1h | 22.2 | +0.55 (0.41) | 10.8 | -10.26 | 41.3 | -29.2 | -58.4 | 59.0 | 3/25 | -5.9 | -26.1 | -0.1 (137) | Weak |
| 19 | RSI Momentum 60/40 · 15 min | 15m | 158.3 | +0.97 (2.02) | 10.4 | -9.46 | 36.2 | -36.8 | -73.6 | 76.0 | 3/25 | -5.0 | -35.1 | -2.5 (285) | Small, unproven |
| 20 | RSI Momentum 60/40 · 45 min | 45m | 69.2 | +2.48 (2.4) | 10.7 | -8.19 | 41.4 | -20.6 | -41.2 | 43.9 | 5/25 | -5.6 | -21.3 | -2.1 (152) | Small, unproven |
| 21 | RSI Momentum 60/40 · 1 hour | 1h | 57.4 | +2.57 (2.42) | 10.7 | -8.16 | 41.9 | -24.9 | -49.8 | 50.5 | 2/25 | -5.0 | -25.3 | +0.2 (157) | Small, unproven |
| 22 | VWAP Reclaim · 15 min | 15m | 42.8 | +1.01 (1.82) | 10.3 | -9.31 | 38.2 | -31.8 | -63.7 | 65.8 | 4/25 | -6.7 | -33.0 | -1.8 (227) | Weak |
| 23 | VWAP Reclaim · 45 min | 45m | 47.8 | +3.13 (3.51) | 10.6 | -7.48 | 42.5 | -17.5 | -34.9 | 38.8 | 9/25 | -2.8 | -13.5 | +1.2 (117) | Real, below costs |
| 24 | VWAP Reclaim · 1 hour | 1h | 68.6 | +2.83 (3.75) | 10.6 | -7.80 | 42.9 | -16.6 | -33.1 | 34.8 | 8/25 | -2.8 | -22.4 | -0.9 (147) | Real, below costs |
| 25 | Prior-Day High/Low Break · 15 min | 15m | 23.3 | -0.54 (-0.44) | 10.4 | -10.96 | 35.4 | -40.2 | -80.4 | 80.4 | 1/24 | -6.1 | -34.3 | -2.1 (209) | None |
| 26 | Prior-Day High/Low Break · 45 min | 45m | 46.8 | +1.31 (0.8) | 10.6 | -9.29 | 40.8 | -14.9 | -29.8 | 38.5 | 9/25 | +0.2 | -17.0 | -1.2 (100) | Weak |
| 27 | Prior-Day High/Low Break · 1 hour | 1h | 45.8 | +1.92 (1.18) | 10.7 | -8.77 | 42.1 | -25.0 | -49.9 | 52.3 | 5/25 | -1.2 | -15.9 | +0.4 (100) | Weak |
| 28 | Opening-Range Close Break · 15 min | 15m | 24.7 | +0.59 (0.58) | 10.4 | -9.77 | 38.4 | -30.4 | -60.9 | 64.1 | 5/25 | -6.4 | -29.6 | -2.0 (167) | Weak |
| 29 | Opening-Range Close Break · 45 min | 45m | 22.7 | +1.39 (0.98) | 10.6 | -9.19 | 42.5 | -24.1 | -48.3 | 54.3 | 7/25 | -5.1 | -15.0 | -0.8 (86) | Weak |
| 30 | Opening-Range Close Break · 1 hour | 1h | 22.8 | +2.27 (1.7) | 10.7 | -8.39 | 43.2 | -20.4 | -40.8 | 48.5 | 6/25 | +1.2 | -10.6 | +1.0 (82) | Weak |
| 31 | VWAP Reversion · 15 min | 15m | 191.1 | -2.70 (-3.81) | 10.5 | -13.19 | 33.1 | -40.5 | -80.9 | 81.1 | 1/23 | -3.1 | -40.3 | -3.7 (220) | None |
| 32 | VWAP Reversion · 45 min | 45m | 2.0 | -2.14 (-0.64) | 10.8 | -12.96 | 39.2 | -11.0 | -22.1 | 22.4 | 6/25 | -5.1 | -6.4 | -1.0 (22) | None |
| 33 | VWAP Reversion · 1 hour | 1h | 0.7 | -4.08 (-0.94) | 10.9 | -14.97 | 35.2 | -4.8 | -9.5 | 9.5 | 2/25 | -2.4 | -2.2 | -0.3 (5) | None |
| 34 | RSI(2) Extreme · 15 min | 15m | 43.9 | -2.16 (-2.84) | 9.7 | -11.83 | 43.5 | -40.3 | -80.7 | 80.7 | 0/23 | -4.8 | -40.3 | -2.7 (273) | None |
| 35 | RSI(2) Extreme · 45 min | 45m | 17.3 | -1.82 (-1.11) | 10.0 | -11.81 | 44.2 | -25.8 | -51.5 | 52.5 | 4/25 | -8.3 | -23.7 | -2.3 (139) | None |
| 36 | RSI(2) Extreme · 1 hour | 1h | 16.2 | -1.22 (-0.73) | 10.2 | -11.47 | 42.9 | -26.6 | -53.3 | 53.3 | 3/25 | -7.5 | -25.6 | -1.2 (112) | None |
| 37 | Bollinger Snap-Back · 15 min | 15m | 133.9 | +0.14 (0.24) | 10.0 | -9.90 | 42.1 | -35.2 | -70.3 | 70.3 | 2/25 | -2.5 | -33.5 | -0.9 (303) | Weak |
| 38 | Bollinger Snap-Back · 45 min | 45m | 43.0 | +1.64 (1.28) | 10.4 | -8.78 | 43.7 | -26.7 | -53.3 | 54.1 | 4/25 | -4.3 | -26.4 | -2.0 (144) | Weak |
| 39 | Bollinger Snap-Back · 1 hour | 1h | 32.8 | +2.88 (1.99) | 10.5 | -7.65 | 43.6 | -20.7 | -41.4 | 41.4 | 4/25 | -6.8 | -20.5 | -2.0 (132) | Weak |
| 40 | Z-Score Fade in Range · 15 min | 15m | 11.0 | -2.27 (-1.54) | 10.2 | -12.47 | 39.6 | -30.9 | -61.8 | 61.9 | 1/25 | -4.8 | -30.5 | -2.3 (193) | None |
| 41 | Z-Score Fade in Range · 45 min | 45m | 4.4 | -1.93 (-0.81) | 10.6 | -12.47 | 42.9 | -14.5 | -29.1 | 30.0 | 4/25 | -2.1 | -14.4 | -0.9 (90) | None |
| 42 | Z-Score Fade in Range · 1 hour | 1h | 3.4 | -5.73 (-2.05) | 10.7 | -16.41 | 41.8 | -16.1 | -32.3 | 33.5 | 6/25 | -3.4 | -14.1 | -0.8 (62) | None |
| 43 | Stochastic Range Turn · 15 min | 15m | 9.2 | -2.18 (-2.91) | 9.8 | -11.93 | 39.9 | -32.8 | -65.7 | 65.7 | 0/25 | -10.4 | -29.2 | -2.7 (193) | None |
| 44 | Stochastic Range Turn · 45 min | 45m | 2.2 | -2.18 (-0.97) | 10.3 | -12.44 | 39.6 | -11.1 | -22.3 | 23.1 | 5/25 | -4.3 | -9.6 | -1.1 (79) | None |
| 45 | Stochastic Range Turn · 1 hour | 1h | 1.8 | +1.85 (0.82) | 10.5 | -8.62 | 38.6 | -6.3 | -12.7 | 12.9 | 6/25 | -3.1 | -3.9 | -0.5 (67) | Weak |
| 46 | CCI ±200 Return · 15 min | 15m | 77.6 | +0.14 (0.19) | 9.6 | -9.44 | 46.9 | -31.9 | -63.7 | 63.9 | 3/25 | -3.4 | -31.8 | -2.2 (252) | Weak |
| 47 | CCI ±200 Return · 45 min | 45m | 22.5 | +1.04 (0.75) | 10.1 | -9.05 | 44.1 | -22.0 | -43.9 | 46.3 | 4/25 | -5.1 | -17.6 | -0.6 (119) | Weak |
| 48 | CCI ±200 Return · 1 hour | 1h | 16.1 | +2.62 (1.55) | 10.3 | -7.72 | 43.8 | -21.1 | -42.2 | 43.3 | 4/25 | -7.6 | -16.5 | -0.5 (111) | Weak |
| 49 | ORB Stocks-in-Play (stop 10% ATR) | day | 17.5 | -15.98 (-24.26) | 10.7 | -26.69 | 5.3 | -40.4 | -80.7 | 80.7 | 0/18 | -0.1 | -40.3 | +0.5 (125) | None |
| 50 | ORB Stocks-in-Play (stop 25% ATR) | day | 17.5 | -6.32 (-3.77) | 10.7 | -17.04 | 28.7 | -39.6 | -79.1 | 80.4 | 2/25 | -10.6 | -32.3 | +1.9 (64) | None |
| 51 | Gap and Go | day | 2.6 | +8.89 (1.32) | 10.5 | -1.58 | 45.2 | -2.8 | -5.5 | 13.5 | 8/24 | +0.5 | -10.8 | +1.5 (66) | Weak |
| 52 | Gap Fade | day | 2.2 | -5.44 (-0.61) | 9.7 | -15.17 | 49.5 | -2.6 | -5.3 | 8.7 | 10/25 | -0.3 | -2.6 | +0.4 (24) | None |
| 53 | Selected ORB 30-min (top-5 expected move) | day | — | — | — | — | — | — | — | — | — | — | — | -0.6 (48) | Pre-registered (forward test) |
| 54 | Selected ORB 15-min (top-5 expected move) | day | — | — | — | — | — | — | — | — | — | — | — | +1.7 (28) | Pre-registered (forward test) |

**Verdict column:** **None** — no edge even before costs (raw <= 0 bp); **Weak** — raw > 0 but t < 2 (indistinguishable from luck); **Small, unproven** — raw > 0 with 2 <= t < 3.3 (with 52 rules tested, about 3.3 is needed before an edge is believable); **Real, below costs** — raw > 0 with t >= 3.3 but smaller than the ~10.5 bp a round trip costs; t is day-clustered. Every replayable rule loses money after costs.

---

# Part 1 — Issues register

| # | Severity | Strategies | Issue | Evidence |
|---|---|---|---|---|
| 1 | **High (results)** | all 52 replayable | No strategy earns its costs: the best edge before costs is a third of the 10.5 bp round trip | every-trade view; solo books all negative; live record agrees |
| 2 | Medium (definition) | ADX Trend Start ×3; Z-Score ×3 and Stochastic ×3 (filters) | ADX smoothed with an EMA (α 2/15), not Wilder's (α 1/14): values higher, crossings at different bars than any chart shows | below 20 on 7–11% of bars vs 27–28%; 4.5% of its crossings of 25 match a standard one |
| 3 | Medium (logic) | Donchian ×3 | The "fresh breakout" condition is always true; repeat signals on running breakouts | 42% / 27% / 25% of signals had broken out on the bar before |
| 4 | Medium (logic) | VWAP Reclaim ×3 | Previous close compared with the current VWAP; 45m skips the first bar; 1h's first check uses yesterday's close | 1.2–6.0% repeat signals; 0% of 45m signals before 10:15 |
| 5 | Medium (book) | all | `priority` mixes units across families, and it decides who takes a stock under the two-per-stock cap | priority medians 0.6–3.5 by family |
| 6 | Medium (fidelity) | ORB ×2 | Trigger-minute stops unseen live, pessimistic in the backtest | same 84 trades: backtest −₹2.39 lakh, live +₹0.73 lakh |
| 7 | Low (definition) | ATR-based stops (all), Keltner, Supertrend | ATR and Supertrend use the EMA ATR; stops differ by about ±10% from Wilder's | 80% of ATR readings within −13% … +12% of Wilder's; 20–24% of Supertrend flips are not standard flips |
| 8 | Low (data) | 45m / 1h ×16 | The 15-minute stub bar at 15:15 enters every 45m / 1h indicator | a 15-minute bar with 58–69% of a full bar's range and 69–95% of its volume |
| 9 | Low (filter) | Donchian, PDH/PDL | The volume filter is not time-of-day adjusted: the first bar passes far more often | passes 50% of 09:30 bars and 10–14% midday (15m); 60–62% of the first 45m / 1h bar, 14–24% later |
| 10 | Low (fidelity) | all with targets | Targets fill on touch with no slippage (live paper and backtest) | standard limit-order caveat |
| 11 | Low (real money) | all | No circuit-limit handling for non-F&O names, no ASM/GSM screen, no tick rounding | §1.6 |
| 12 | Low (docs) | module, Donchian, Keltner, EMA Pullback | Text says NIFTY alignment / "first dip"; the code does neither | short version, cards |
| 13 | Info | Gap Fade | Target smaller than the cost of reaching it | 1.4% of signals |
| 14 | Info | all | `evaluate()` hides IndexError / ValueError / ZeroDivisionError / TypeError as "no signal" | none occurred at 24,768 closes |

---

# Part 2 — Recommendations (separate; nothing here has been applied)

The rules above stay exactly as they are. Each idea below would create a **new** strategy version: a new id, a pre-registration written and committed before its test, and one look at the six-month holdout. The current 54 keep running unchanged so their records stay comparable. This is how every test in the AI-upgrade plan was run, and it matters more than any single idea. With 54 rules already tried, a fix that "works" on the same two years is the likeliest way to fool ourselves.

### A. Correct the defects (as new versions, never in place)
1. **ADX.** Add a Wilder ADX(14) and run ADX Trend Start, Z-Score and Stochastic on it as `_v2` rules next to the current ones. Expect different signals, not necessarily better ones.
2. **Donchian.** Make the fresh-break test compare the previous close with the channel *as it stood one bar earlier* (the bars i−21 … i−2), so only the first close beyond the channel fires.
3. **VWAP Reclaim.** Compare the previous close with the VWAP as of that bar. Let the 45m rule use its first bar. Start the 1h rule's comparison from today's bars.
4. **Priority.** Rank candidates for the per-stock cap on one scale for all families, for example each family's own percentile of its priority, or the measured edge per family. Better still, remove the cap's dependence on order by deciding crowded stocks by rule version, fixed in advance.

### B. Make the measurements sharper (no rule changes)
5. **ORB fills.** Replay ORB entries on 1-minute or 5-minute bars (5-minute history is already exported for research). This removes the ambiguous trigger bar, and the live exit scan should start at the fill minute itself.
6. **Targets.** Fill a target only when the price trades *through* it by a tick (or record both readings), in the backtest and the live paper desk alike.
7. **Report every result with day-clustered t** and the number of rules tested, as this audit does. Here, trade-count t's overstate certainty about twice over (median; up to 4.4×).
8. **Stub bar.** Record ATR and volume averages with and without the 15:15 bar for the 45m and 1h rules, so the effect is known before anyone changes it.

### C. Before any real money (no rule changes)
9. Exclude non-F&O names, or model circuit limits so a locked stock cannot fill a stop.
10. Screen ASM / GSM stages from NSE's daily lists (the `nse_events` collector already fetches NSE archives).
11. Round every stop and target to the stock's tick size.
12. Use NSE's official previous close for the gap rules (the bhavcopy already downloaded each evening has it).

### D. Where an edge might come from (research, pre-registered)
13. **Fewer, larger moves.**
    - The rules that come closest are the slowest ones. In 11 of the 16 families, the 1-hour version has both the largest edge before costs and the smallest loss after costs.
    - The best day setup, Gap and Go, aims at a 388 bp target. In each case the cost is a smaller share of the move.
    - Any new idea should target moves of 40 bp or more a trade. That is about four times the round trip.
14. **Cost first.** Limit entries were tested in Phase 3 and saved about 1.3 bp a signal: real, but not enough. Larger stocks cost 1.5 bp a side against 4.1 bp in the thinnest band. A rule restricted to the ≥ ₹1,000 cr band would pay about 7 bp a round trip instead of 10.5. That is a hypothesis to pre-register, not a filter to apply.
15. **Stop adding variants.** Every extra rule raises the bar (t ≈ 3.3 for 52 rules). The October and November searches, the AI scorer and the context filters found nothing that survives costs. The honest next step is to let the two pre-registered Selected ORB rules finish their forward test before building more.

---

## Appendix — reproduce, and the descriptive splits

```
cd backend/research/intraday_ai
python audit54.py --name audit54 --start 2024-11-04        # replay (~7 min on a desktop)
python audit54_checks.py --symbols 40 --days 20            # code checks
python audit54_checks.py --symbols 10 --days 5 --order-only
python fidelity.py fid_live10L > <data>/runs/audit54/fidelity.txt
python audit54_analyze.py && python audit54_tables.py      # tables.json, tables.md
```
Data: `INTRADAY_AI_DATA` (default `D:/intraday_ai_data`), the exports described in [backend/research/intraday_ai/README.md](backend/research/intraday_ai/README.md). Nothing here touches the server or the database.

**First hour against later, F&O against non-F&O** (every signal as a trade). This is descriptive, and it must not be used as a filter without pre-registration: picking the better half of a split on the same data is exactly the overfitting the gate exists to stop.

| Strategy | First hour: n, raw, net bp | Later: n, raw, net bp | F&O (CAS): n, net bp | Non-F&O: n, net bp |
|---|---:|---:|---:|---:|
| Donchian 20 Breakout · 15 min | 16,620, +0.3, -10.1 | 30,871, +1.0, -9.4 | 41,341, -9.6 | 6,150, -9.9 |
| Donchian 20 Breakout · 45 min | 13,241, +2.5, -8.1 | 12,658, +2.6, -8.0 | 22,766, -8.5 | 3,133, -4.7 |
| Donchian 20 Breakout · 1 hour | 12,491, +4.1, -6.6 | 9,920, +3.1, -7.6 | 19,724, -7.4 | 2,687, -4.2 |
| EMA Trend Pullback · 15 min | 21,906, +1.0, -9.2 | 62,007, -0.2, -10.6 | 75,221, -10.5 | 8,692, -7.5 |
| EMA Trend Pullback · 45 min | 6,058, +3.0, -7.5 | 23,671, +1.1, -9.6 | 26,688, -9.5 | 3,041, -6.4 |
| EMA Trend Pullback · 1 hour | 5,321, +1.6, -9.1 | 18,809, +1.3, -9.5 | 21,631, -9.1 | 2,499, -11.7 |
| MACD Trend Turn · 15 min | 10,195, +0.6, -9.8 | 29,324, +1.5, -8.9 | 35,359, -9.2 | 4,160, -8.8 |
| MACD Trend Turn · 45 min | 6,347, +1.9, -8.7 | 11,230, +0.6, -10.1 | 15,656, -9.8 | 1,921, -7.8 |
| MACD Trend Turn · 1 hour | 5,334, +4.0, -6.7 | 9,326, +3.1, -7.7 | 13,132, -8.1 | 1,528, -1.0 |
| Keltner Breakout · 15 min | 8,573, -0.4, -10.8 | 37,154, +1.3, -9.1 | 40,524, -9.4 | 5,203, -9.0 |
| Keltner Breakout · 45 min | 7,254, +4.8, -5.7 | 11,930, +1.7, -9.0 | 16,958, -7.7 | 2,226, -8.1 |
| Keltner Breakout · 1 hour | 6,491, +6.7, -3.9 | 9,519, +1.2, -9.6 | 14,186, -7.6 | 1,824, -5.0 |
| Supertrend Flip · 15 min | 6,888, -0.5, -11.1 | 15,873, +1.6, -9.0 | 20,340, -9.7 | 2,421, -9.1 |
| Supertrend Flip · 45 min | 6,462, -0.1, -10.9 | 7,252, +3.4, -7.4 | 12,242, -9.3 | 1,472, -7.0 |
| Supertrend Flip · 1 hour | 5,561, +3.6, -7.2 | 5,829, +4.1, -6.7 | 10,154, -7.9 | 1,236, +0.7 |
| ADX Trend Start · 15 min | 7,576, +1.1, -9.4 | 21,903, +2.0, -8.6 | 26,366, -8.6 | 3,113, -10.2 |
| ADX Trend Start · 45 min | 4,366, +3.6, -7.1 | 8,703, +0.8, -10.0 | 11,716, -9.5 | 1,353, -4.9 |
| ADX Trend Start · 1 hour | 3,832, +1.9, -8.9 | 7,175, -0.2, -11.0 | 9,880, -10.7 | 1,127, -6.7 |
| RSI Momentum 60/40 · 15 min | 15,502, +0.5, -9.9 | 62,867, +1.1, -9.4 | 69,897, -9.8 | 8,472, -6.3 |
| RSI Momentum 60/40 · 45 min | 14,045, +3.3, -7.2 | 20,229, +1.9, -8.8 | 30,584, -8.6 | 3,690, -4.8 |
| RSI Momentum 60/40 · 1 hour | 12,520, +3.9, -6.8 | 15,878, +1.6, -9.3 | 25,314, -8.5 | 3,084, -5.6 |
| VWAP Reclaim · 15 min | 2,353, +0.6, -9.7 | 18,846, +1.1, -9.3 | 19,559, -9.2 | 1,640, -10.5 |
| VWAP Reclaim · 45 min | — | 23,637, +3.1, -7.5 | 21,757, -7.9 | 1,880, -3.1 |
| VWAP Reclaim · 1 hour | 11,784, +3.4, -7.2 | 22,156, +2.5, -8.1 | 31,114, -8.2 | 2,826, -3.5 |
| Prior-Day High/Low Break · 15 min | 5,769, -0.8, -11.2 | 5,758, -0.3, -10.7 | 9,913, -11.2 | 1,614, -9.7 |
| Prior-Day High/Low Break · 45 min | 18,026, +1.7, -8.8 | 5,152, -0.2, -10.8 | 20,217, -9.7 | 2,961, -6.4 |
| Prior-Day High/Low Break · 1 hour | 18,093, +2.7, -7.9 | 4,560, -1.3, -12.1 | 19,804, -9.0 | 2,849, -7.2 |
| Opening-Range Close Break · 15 min | 5,258, -0.3, -10.7 | 6,979, +1.3, -9.1 | 11,167, -10.2 | 1,070, -5.1 |
| Opening-Range Close Break · 45 min | 3,483, -0.2, -10.7 | 7,737, +2.1, -8.5 | 10,253, -9.0 | 967, -11.3 |
| Opening-Range Close Break · 1 hour | 4,515, +3.2, -7.4 | 6,769, +1.6, -9.1 | 10,283, -8.8 | 1,001, -4.4 |
| VWAP Reversion · 15 min | 287, -9.2, -19.4 | 94,302, -2.7, -13.2 | 81,727, -12.5 | 12,862, -17.6 |
| VWAP Reversion · 45 min | — | 1,012, -2.1, -13.0 | 873, -9.9 | 139, -32.1 |
| VWAP Reversion · 1 hour | — | 332, -4.1, -15.0 | 281, -14.7 | 51, -16.7 |
| RSI(2) Extreme · 15 min | 2,129, +1.3, -8.1 | 19,614, -2.5, -12.2 | 19,213, -11.5 | 2,530, -14.4 |
| RSI(2) Extreme · 45 min | 2,414, +1.4, -8.3 | 6,138, -3.1, -13.2 | 7,441, -10.7 | 1,111, -19.1 |
| RSI(2) Extreme · 1 hour | 2,268, +2.5, -7.5 | 5,753, -2.7, -13.0 | 6,958, -10.2 | 1,063, -19.9 |
| Bollinger Snap-Back · 15 min | 23,846, +0.4, -9.4 | 40,927, +0.0, -10.2 | 57,447, -9.6 | 7,326, -12.3 |
| Bollinger Snap-Back · 45 min | 1,281, +2.7, -7.2 | 19,489, +1.6, -8.9 | 18,407, -8.5 | 2,363, -11.2 |
| Bollinger Snap-Back · 1 hour | 1,400, +3.3, -6.9 | 14,457, +2.8, -7.7 | 14,143, -7.7 | 1,714, -7.2 |
| Z-Score Fade in Range · 15 min | 2,675, -3.6, -13.8 | 2,775, -1.0, -11.2 | 4,874, -11.6 | 576, -19.6 |
| Z-Score Fade in Range · 45 min | 1,037, -3.6, -14.1 | 1,163, -0.4, -11.0 | 1,984, -10.5 | 216, -30.9 |
| Z-Score Fade in Range · 1 hour | 915, -8.4, -19.1 | 769, -2.5, -13.2 | 1,518, -14.9 | 166, -30.4 |
| Stochastic Range Turn · 15 min | 295, -0.3, -10.0 | 4,280, -2.3, -12.1 | 3,961, -11.4 | 614, -15.0 |
| Stochastic Range Turn · 45 min | 122, +0.1, -9.8 | 987, -2.5, -12.8 | 970, -12.8 | 139, -10.2 |
| Stochastic Range Turn · 1 hour | 128, +0.2, -9.8 | 758, +2.1, -8.4 | 759, -8.3 | 127, -10.3 |
| CCI ±200 Return · 15 min | 18,976, +0.2, -9.3 | 19,422, +0.0, -9.6 | 33,718, -9.4 | 4,680, -9.9 |
| CCI ±200 Return · 45 min | 854, +7.9, -2.0 | 10,303, +0.5, -9.6 | 9,897, -8.3 | 1,260, -15.0 |
| CCI ±200 Return · 1 hour | 867, +3.1, -7.1 | 7,115, +2.6, -7.8 | 7,094, -7.6 | 888, -8.4 |
| ORB Stocks-in-Play (stop 10% ATR) | 4,200, -15.8, -26.5 | 1,607, -16.5, -27.2 | 5,191, -25.0 | 616, -41.1 |
| ORB Stocks-in-Play (stop 25% ATR) | 4,200, -7.4, -18.2 | 1,607, -3.4, -14.1 | 5,191, -16.8 | 616, -19.2 |
| Gap and Go | 1,264, +8.9, -1.6 | — | 1,129, -2.8 | 135, +8.5 |
| Gap Fade | 1,105, -5.4, -15.2 | — | 885, -14.6 | 220, -17.6 |

**Sources for the 2026 rate card:** Budget 2026-27 raised STT on futures (0.02% → 0.05%) and options (0.10% → 0.15%) from 1 April 2026, and left equity intraday and delivery STT unchanged ([Finnovate](https://www.finnovate.in/learn/blog/budget-2026-stt-hike-fno-trades-explained), [Business Standard](https://www.business-standard.com/markets/news/markets-fm-hikes-stt-on-fo-trades-surprise-move-126020100888_1.html)).
