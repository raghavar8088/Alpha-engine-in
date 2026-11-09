# Faiz SMC (@faizsmcfx, UC9N9JnSg9aL2w4D0kITQcaw)

English; ICT / smart-money gold teaching. Tags: **[E]** stated, **[I]** inferred, **[A]** assumption. Titles such as
"Works Every Time", "83% Winrate" and "Quit Your Job In 60 Days" are claims, not evidence.

## FZ-01 Gold 8 PM / 9 PM New York "Midas" model (15-minute sweep, 1-minute shift with displacement): KP9RnSnr4kg + 4ZY5OTWt3vU
- Sources:
  - "Use This Gold Trading Strategy To Quit Your Job In 60 Days! (Midas Model)" (2025-06-04, 16:28),
    https://youtu.be/KP9RnSnr4kg (the current version).
  - "Best ICT Gold Trading Strategy That Works Every Time! (High Winrate)" (2024-06-20, 12:53),
    https://youtu.be/4ZY5OTWt3vU (the first version).
- Rules:
  - Before 20:00 New York, mark the most recent 15-minute high and low. After 20:00, wait for one of them to be taken
    [E KP 01:30-03:00; 4Z 01:06-02:18].
  - On the 1-minute chart, wait for a market structure shift with displacement: a sharp push that breaks structure and
    leaves a fair value gap [E KP 03:00-04:00; 4Z 02:18-03:30].
  - Enter on the body close of the shift if price has not run far; otherwise wait for a retest of the order block or fair
    value gap [E].
  - Entries must come before 22:00 New York [E 4Z 03:00].
  - Stop beyond the sweep extreme [E 4Z 04:26].
  - Move to break-even at 1R; take the full profit at 2R [E KP 04:00-04:40]. (In 2024 the author closed 80% at 2R and
    trailed the other 20% [E 4Z 04:26-05:30].)
  - Second window: the 15-minute levels before 21:00, taken only when no trade is open [E KP 05:00-06:30].
- Code [A]:
  - 15-minute swings are fractals with n=2. 1-minute shift: a close beyond the last confirmed 1-minute fractal (n=2) on the
    other side, with a 1-minute fair value gap inside the shift leg.
  - Entry at the next 1-minute open. Stop = sweep extreme +/- 0.1 x ATR(15m).
  - Break-even at 1R, target 2R. One trade at a time. Flat by 16:55 New York.
  - The 2024 runner (80/20 split) is not coded separately; it differs only in the exit.
- Status: requires documented assumptions (swing size).

## FZ-02 Gold London first fair-value-gap inversion (15-minute): rXUDahzLjZM
"Best Gold Trading Strategy With 83% Winrate! (Insane Accuracy)" (2024-09-13, 18:56), https://youtu.be/rXUDahzLjZM
- Rules:
  - London session 03:00-07:00 New York, 15-minute chart [E 01:02-02:00, 08:00].
  - Take the very first fair value gap formed in London and wait for it to be "inversed": a body closes through it
    [E 01:02-03:38].
  - Enter on the retest (or straight away if the close is near). Stop beyond the candle bodies, not the wicks. Target 2R
    toward liquidity. Break-even at 1R [E 02:30-03:38, 08:00-09:30].
  - Skip high-impact news [E 05:00].
- Code [A]:
  - The inversion must come before 07:00 New York.
  - A limit at the inverted gap's near edge, valid until 07:00 New York.
  - Stop = the furthest candle body of the last 4 bars +/- 0.05 ATR.
  - Break-even at 1R, target 2R.
  - Flat at 16:55 New York.
  - News is not filtered (no calendar in the desk).
- Relation: DT-08 (Data Traders) trades an inverse FVG after a sweep with no clock. FZ-02 is time-anchored and needs no
  sweep, so it is kept as a variant.
- Status: requires documented assumptions.

## Duplicates and blocked
- **Silver Bullet with the draw on liquidity.** YmOrNIX2B78, "The Ultimate ICT Silver Bullet Trading Strategy! (79%
  WINRATE)" (2023-08-13, 14:24). The rules: a 1-hour external liquidity sweep, a 5-minute shift, then a fair value gap entry
  at 03:00-04:00 or 10:00-11:00 New York, 2R [E 00:12-06:41]. Already in the library as CP-28 (gold, a higher-timeframe
  sweep, then a shift, then an FVG in the New York hour), YT-04 and BG-07. Merged as a duplicate.
- **Turtle soup inside 4-hour order flow.** oPxktw8-NM4, "Easy ICT Turtle Soup Trading Strategy! (Highly Profitable)"
  (2023-05-23, 17:00). The sweep-and-shift core is CP-26 (turtle soup, gold). The 4-hour order blocks are picked by eye,
  and the target is "maybe this low" [E 12:15-16:00]. Blocked (discretionary); the core is a duplicate.

## Faiz SMC summary
Coded: FZ-01 and FZ-02. Duplicate: the Silver Bullet. Blocked: turtle soup with order flow.
