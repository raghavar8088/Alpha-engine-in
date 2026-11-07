# iTWMIaqYLJg: Best Nifty Intraday Trading Strategy || Beginner's Guide

- **Video:** https://www.youtube.com/watch?v=iTWMIaqYLJg · shot about 21 Oct 2026 (he says "aaj 21 aktoobar hai", 07:00) · 8:26 · Hindi original; YouTube also serves Bengali and English AI dubs · track `hi-orig`
- **Family:** F02 liquidity sweep · **Priority:** P1 · **Market:** Nifty, 5-minute, option buying
- **Evidence:** full transcript (2,066 words). No frames. The video points to a PDF of examples, shared on Telegram. The PDF was coded and tested on 6 Nov 2026 (`backend/research/liquidity_sweep_2026_11/`, strategy D9).

## Rules taught

| # | Rule | Type | Evidence |
|---|---|---|---|
| 1 | Liquidity = resting orders. Buy-side liquidity sits above resistance where price has gone sideways; sell-side liquidity at support | E | 02:00–02:30 |
| 2 | Sweep = price goes beyond the level and comes back | E | 02:30 "sveep hotaa hai ki maarket oopar jaae aur neeche gir" |
| 3 | Levels, and only these: previous-day high (PDH), low (PDL) and close (PDC); equal highs/lows touched at least twice; higher-timeframe swings such as 1-hour | E | 02:30–03:00, 04:00 "usako chhor ke kisee pe kaam naheen karoge" |
| 4 | Session highs/lows: for US and forex markets, avoided for India | E | 03:00 |
| 5 | A level may be drawn as a zone covering body and wick | E | 03:30 "bodee aur vik pe ek zon" |
| 6 | No trade on the day's first candle | E | 04:00 "pahalee kaindal pe koee tred naheen le sakate" |
| 7 | Never trade a direct breakout; trade breakout-and-retest or reversals | E | 04:30 |
| 8 | Optional confluence: 200 moving average | E | 05:00 "200 mooving evarej yooz kar sakate ho" |
| 9 | Round numbers can serve as targets | E | 06:00–06:30 |
| 10 | One trade a day, two at most | E | 05:30 "din ke sirph ek tred karate hain maiks do tred" |
| 11 | 5-minute timeframe throughout | E | 07:30 |
| 12 | Entry, stop and target placement | Missing in the video (in the PDF) | Examples say only "target hit" or "SL" |

## Examples

- **The recording day:** a PDC zone respected several times; three sweep trades gave one stop and two targets (03:30).
- **Gap-up day:** a retest that combined a liquidity sweep, a zone and the 200 MA, taken as a buy (05:00).
- **Short:** a rejection from a level plus the EMA, targeting a round number (06:00).
- **PDF:** examples dated 22–23 Sep and 19 Oct, which he stresses are recent and unpicked ("jaanaboojh ke … reesent", 06:30).

## Unclear or missing

- How many touches make "equal" highs, and within what tolerance.
- Which swing size counts on the 1-hour chart.
- How long price may stay beyond a level.
- The stop, target and entry candle are not stated in the video.

## Promotional content

01:00–02:00 and 05:30–06:00 (most of the middle third):
- a broker offer (₹1 crore brokerage pool until 20 Nov, a laptop giveaway);
- a free VIP channel, described as "SEBI registered";
- a Zoom masterclass and Telegram.

## Relation to other work

This is the source of D9 `bb_liquidity_sweep`. That coding matches every rule above. It took the stop, target and confirmation window from the PDF:
- stop at the extreme plus 0.02%;
- target 2R;
- close back inside within 30 minutes.

Run B tested the 200-EMA option. Result on 6 Nov: no edge (0R before costs, −0.4 to −0.6R after; 0 of 27 versions pass).

## Testability

Already tested (D9). It is not re-run here.
