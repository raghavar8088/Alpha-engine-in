# "Prop-firm" 1:1 strategy: Lb4yel3nCws (Nasdaq) and NwCyONUCsC0 (gold)

Both Hindi, track `hi-orig`, full transcripts read. No frames. Family F19 (F09 candle pattern), priority P1. **One rule set shown on two markets.** He calls it the "negative RR / 1:1 strategy" for prop-firm (funded) accounts.

## Shared rules

| # | Rule | Type | Evidence |
|---|---|---|---|
| 1 | 5-minute chart | E | Lb 02:30; Nw 04:30 |
| 2 | **Long setup:** a red candle, then a smaller candle whose body closes inside the first candle's body; the **3rd or 4th candle** breaks (closes beyond) the first candle's high → buy. **Short:** mirror (green candle, smaller inside candle, 3rd/4th candle breaks the low) | E | Lb 03:00–04:30, 05:00; Nw 01:30, 02:30, 04:30–05:00, 06:30–07:00 |
| 3 | If the break doesn't come by the 4th candle, the setup is void; look for a new one | E | Lb 04:30; Nw 02:30, 08:30 |
| 4 | **"70-30" rule:** the entry candle must be at least 70% in the trade direction; the adverse wick at most 20–30% of the candle | E | Lb 10:00–11:30; Nw 02:30–03:00, 04:30 |
| 5 | **Stop:** beyond the entry candle (or two candles), "genuine, not tight" | E | Lb 04:00–04:30, 07:30, 09:00; Nw 02:00 |
| 6 | **Target:** 1:1 on prop-firm accounts (win rate matters most); own-capital traders 1:1.5–1:3; trail with the 9 EMA after 1:2 | E | Lb 00:00–00:30, 04:30, 07:30; Nw 00:00–00:30, 03:00, 05:30, 13:00 |
| 7 | **One trade a day** per instrument; avoid event candles | E | Lb 06:30; Nw 01:00, 03:00 |
| 8 | **Risk:** about 1–2% of the funded account a trade | E | Lb 06:30 |

## Market-specific rules

- **Lb4yel3nCws:** "Best Trading Strategy for Prop Firms with Notes and Examples!", Feb 2026, 14:03.
  - **Nasdaq 100** (analysed on the NDQ chart, traded as NAS100).
  - **Start:** do nothing for the first **30 minutes after the US open** (19:00 or 20:00 India time, by daylight saving); trades only after that line (02:30–03:00).
  - **His monthly tallies (unverified):** Feb 3/3; Jan about 60%; Dec 14 targets with "no SL", 73%; Dec/Nov 17T/6SL/2BE and 12T/12SL (01:30–02:00).
- **NwCyONUCsC0:** "Prop Firm Trading Strategy || Funding Companies Hack", Dec 2025, 16:15.
  - **Gold**, during the **New York session** (TradingView "Sessions [LuxAlgo]", New York only) until **22:00 India time** (02:00–02:30, 09:30).
  - Wait up to about 6 candles (30 minutes) for a definitive candle (05:00).
  - **His claims:** monthly win rates of 60–88% at 1:1 (02:00); replay 21 Oct–15 Nov 2025.

## Unclear

- Whether the "inside" candle must be the opposite colour (his examples alternate).
- **Entry trigger:** the close of the breaking candle vs a stop order at the high/low.
- Whether a stop allows a second trade the same day.

## Promotional content

Funded Friday (code ANEESH10), Telegram notes.

## Testability

**Ready to test, with a few assumptions:**
- gold from Dukascopy;
- Nasdaq from the HistData NSXUSD minute data on disk;
- New York session start 13:30 UTC (DST-aware), with the 30-minute wait on Nasdaq;
- 1:1 as the source-faithful exit; 1:2 as a declared variant.
