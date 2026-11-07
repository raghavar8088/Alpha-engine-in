# T04vDiuAG4w: Simple VWAP Intraday Trading Strategy for Beginners

- **Video:** https://www.youtube.com/watch?v=T04vDiuAG4w · Nov 2026 (an example dated 4 Jun 2026; the broker offer runs to 20 Nov) · 6:52 · Hindi · track `hi-orig`
- **Family:** F06 VWAP · **Priority:** P1 · **Market:** Nifty (he buys puts; says Nifty data is precise because it comes only from NSE)
- **Evidence:** full transcript (1,796 words). No frames. A PDF of examples is offered on Telegram.
- **Earlier test:** the 6 Nov VWAP study (`D:\NSE-Intraday-Research\vwap`, NSE-VWAP-01, then U1–U4) ran this on **NSE stocks**. The video's examples are Nifty, so that test used a different market.

## Rules

| # | Rule | Type | Evidence |
|---|---|---|---|
| 1 | TradingView VWAP with the upper/lower bands and fill switched off; inputs unchanged | E | 01:00 |
| 2 | **Use 1, dynamic support/resistance:** breakout then retest above VWAP → buy; breakdown then retest below → sell | E | 01:30, 03:00 |
| 3 | **Use 2, mean reversion / target:** after a liquidity sweep, take the trade with VWAP as the target, at 1:2 | E | 01:30–02:00, 05:00 |
| 4 | **Side filter:** buy only above VWAP, sell only below, unless VWAP is the target | E | 03:30 |
| 5 | Price near VWAP → trade the retest or breakout; price far from VWAP → use VWAP as the target | E | 03:30–04:00 |
| 6 | No direct breakouts; breakout-and-retest only | E | 03:00 |
| 7 | **Levels:** important levels and zones, with double and triple bottoms swept on the wick | E | 02:30, 05:00 |
| 8 | **Timeframe:** 5-minute for beginners, 3-minute if experienced, 15-minute for slower or swing trading | E | 04:00–04:30 |
| 9 | Breakeven once price reaches 50% of the target | E | 04:30 |
| 10 | Roughly 1–2 trades a day in his VIP channel | E | 02:00 |

## Unclear or missing

- Stop placement.
- Which "important levels" (presumably those from the liquidity-sweep video).
- Retest tolerance.
- **Volume source:** the Nifty index has no volume, so VWAP must come from the futures chart (inferred).

## Promotional content

01:30–02:30 and 05:30–06:30: broker offer (₹1 crore brokerage pool, laptops), VIP channel "fee ₹60,000, now free", Zoom masterclass.

## Testability

**Testable with assumptions.** It needs a VWAP source for Nifty (futures volume), which is not in the minute store. The stocks version was already tested (no edge).
