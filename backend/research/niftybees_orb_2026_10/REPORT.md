# NIFTYBEES opening-range breakout: five-year backtest

NSE: NIFTYBEES, 5-minute candles, 25 Oct 2021 to 23 Oct 2026 (1,225 sessions). Angel One data, Angel One intraday charges, ₹10 lakh a trade. Code and every output are in this folder; `python -I orb_report.py` rebuilds this file.

## Verdict

**The rules lose money after costs.** They took 1,205 trades, and 40.7% made money. Net −₹5,48,885 on a ₹10,00,000 account (−54.9%, about −11.0% a year). Profit factor 0.77. The maximum drawdown was ₹6,05,212 (60.5% of the account), from the peak on 25 Jan 2022 to 7 Oct 2026, and it was not recovered.

Before costs the same trades made +₹1,92,872, or +₹160 a trade (1.6 bp, +0.032R). Charges took ₹4,84,357 (₹402 a trade) and slippage ₹2,57,400 (₹214 a trade). After them, the average trade is −0.159R, with t = −3.70. STT alone, 0.025% of the sell, is about ₹250 a trade, more than the whole pre-cost edge. Before costs the edge is not statistically different from zero (t = 1.33 for the run with no costs at all).

**Wider targets do not help.** At 1:3, 1:4, 1:5 and 1:6 the target is rarely reached, and every ratio loses between ₹5,00,417 and ₹5,30,909 (section Wider targets).

## Results, primary rules

| | |
|---|---|
| Sessions tested | 1,225 (25 Oct 2021 to 23 Oct 2026) |
| Trades | 1,205 (622 long, 583 short); a trade on 98.4% of sessions |
| Win rate (net P&L above zero) | 40.7% (491 trades) |
| Exits | target 157 (13.0%), stop-loss 523 (43.4%), 15:15 close 525 (43.6%; 63.6% of these made money) |
| Net profit / loss | −₹5,48,885 (−54.9% of ₹10 lakh) |
| Before costs | +₹1,92,872 |
| Charges (Angel One) | ₹4,84,357 |
| Slippage | ₹2,57,400 |
| Profit factor | 0.77 |
| Maximum drawdown | ₹6,05,212: 60.5% of the account (59.3% of the peak), 25 Jan 2022 to 7 Oct 2026, not recovered |
| Lowest account value | ₹4,16,111 on 7 Oct 2026 |
| Average trade | −₹456 (−0.159R); 95% interval −₹697 to −₹214 |
| Average win / loss | +₹3,816 / −₹3,393 |
| Median stop distance (1R) | 35.6 bp of price |
| Average holding time | 206 minutes |
| Longest losing streak | 10 trades |
| Sharpe ratio (daily, annualised) | −1.66 |

## Year by year

Calendar years; 2021 starts on 25 October and 2026 ends on 23 October. Return is on the ₹10 lakh account. Before costs = the same trades at the trigger, stop and 15:15 prices, with no slippage and no charges.

| Year | Sessions | Trades | Win rate | Target / stop / 15:15 | Before costs | Costs | Net P&L | Return | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 (from 25 Oct) | 46 | 46 | 45.7% | 13 / 22 / 11 | +₹30,729 | −₹26,832 | +₹3,897 | +0.4% | 1.03 | ₹37,790 |
| 2022 | 246 | 246 | 42.3% | 41 / 113 / 92 | +₹87,046 | −₹1,49,270 | −₹62,224 | −6.2% | 0.88 | ₹1,00,691 |
| 2023 | 244 | 241 | 35.7% | 33 / 125 / 83 | −₹24,538 | −₹1,53,736 | −₹1,78,274 | −17.8% | 0.60 | ₹1,99,077 |
| 2024 | 245 | 238 | 40.8% | 31 / 103 / 104 | +₹97,017 | −₹1,47,015 | −₹49,998 | −5.0% | 0.89 | ₹67,142 |
| 2025 | 245 | 240 | 45.0% | 17 / 81 / 142 | +₹39,667 | −₹1,46,835 | −₹1,07,168 | −10.7% | 0.75 | ₹1,14,792 |
| 2026 (to 23 Oct) | 199 | 194 | 38.7% | 22 / 79 / 93 | −₹37,048 | −₹1,18,069 | −₹1,55,118 | −15.5% | 0.66 | ₹1,96,952 |
| **All** | 1,225 | 1,205 | 40.7% | 157 / 523 / 525 | +₹1,92,872 | −₹7,41,757 | **−₹5,48,885** | −54.9% | 0.77 | ₹6,05,212 |

## Wider targets: 1:3, 1:4, 1:5 and 1:6

Only the target changes: 3, 4, 5 or 6 times the distance from the entry fill to the stop. Everything else is as in the rules below, and 1:2 is the test above. The wider the target, the less often price reaches it: 157 at 1:2, 67 at 1:3, 30 at 1:4, 14 at 1:5, 10 at 1:6, out of 1,205 trades. Most trades end at 15:15 instead, so the wider ratios lose almost the same, between ₹5,00,417 and ₹5,30,909. Costs of about ₹625 a trade decide the result whatever the target. The order inside a 5-minute candle decided 8 trades at every ratio, and walking the 1-minute candles moves each result by at most ₹16,193.

| Risk : reward | Trades | Win rate | Target / stop / 15:15 | Before costs | Net P&L | Return | Profit factor | Max drawdown | Net R a trade | Same test on 1-minute candles |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1:2 (the test above) | 1,205 | 40.7% | 157 / 523 / 525 | +₹1,92,872 | **−₹5,48,885** | −54.9% | 0.77 | ₹6,05,212 (60.5%) | −0.159 | −₹5,52,890 |
| **1:3** | 1,205 | 39.9% | 67 / 531 / 607 | +₹2,21,156 | **−₹5,30,909** | −53.1% | 0.78 | ₹6,18,801 (61.9%) | −0.148 | −₹5,47,102 |
| **1:4** | 1,205 | 39.8% | 30 / 531 / 644 | +₹2,47,978 | **−₹5,08,368** | −50.8% | 0.79 | ₹6,07,036 (60.7%) | −0.135 | −₹5,23,485 |
| **1:5** | 1,205 | 39.8% | 14 / 531 / 660 | +₹2,39,720 | **−₹5,18,458** | −51.8% | 0.79 | ₹5,98,401 (59.8%) | −0.135 | −₹5,25,516 |
| **1:6** | 1,205 | 39.8% | 10 / 531 / 664 | +₹2,58,200 | **−₹5,00,417** | −50.0% | 0.80 | ₹5,83,271 (58.3%) | −0.128 | −₹5,07,475 |

Net P&L by calendar year:

| Year | 1:2 | 1:3 | 1:4 | 1:5 | 1:6 |
|---|---:|---:|---:|---:|---:|
| 2021 (from 25 Oct) | +₹3,897 | +₹24,234 | +₹37,161 | +₹20,222 | +₹21,857 |
| 2022 | −₹62,224 | −₹57,442 | −₹44,003 | −₹44,725 | −₹35,241 |
| 2023 | −₹1,78,274 | −₹1,98,816 | −₹1,88,973 | −₹1,88,119 | −₹1,85,128 |
| 2024 | −₹49,998 | −₹54,356 | −₹60,304 | −₹54,548 | −₹50,543 |
| 2025 | −₹1,07,168 | −₹1,03,258 | −₹98,327 | −₹94,383 | −₹94,458 |
| 2026 (to 23 Oct) | −₹1,55,118 | −₹1,41,271 | −₹1,53,922 | −₹1,56,904 | −₹1,56,904 |
| **All** | **−₹5,48,885** | **−₹5,30,909** | **−₹5,08,368** | **−₹5,18,458** | **−₹5,00,417** |

### 1:3 year by year

| Year | Trades | Win rate | Target / stop / 15:15 | Before costs | Net P&L | Return | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 (from 25 Oct) | 46 | 45.7% | 9 / 22 / 15 | +₹51,485 | +₹24,234 | +2.4% | 1.22 | ₹39,347 |
| 2022 | 246 | 40.2% | 20 / 117 / 109 | +₹94,165 | −₹57,442 | −5.7% | 0.89 | ₹1,09,730 |
| 2023 | 241 | 34.4% | 14 / 127 / 100 | −₹42,751 | −₹1,98,816 | −19.9% | 0.57 | ₹2,10,629 |
| 2024 | 238 | 39.9% | 12 / 105 / 121 | +₹94,883 | −₹54,356 | −5.4% | 0.88 | ₹75,757 |
| 2025 | 240 | 45.0% | 5 / 81 / 154 | +₹44,915 | −₹1,03,258 | −10.3% | 0.76 | ₹1,13,719 |
| 2026 (to 23 Oct) | 194 | 38.7% | 7 / 79 / 108 | −₹21,540 | −₹1,41,271 | −14.1% | 0.69 | ₹1,85,688 |

### 1:4 year by year

| Year | Trades | Win rate | Target / stop / 15:15 | Before costs | Net P&L | Return | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 (from 25 Oct) | 46 | 45.7% | 4 / 22 / 20 | +₹64,945 | +₹37,161 | +3.7% | 1.33 | ₹37,712 |
| 2022 | 246 | 40.2% | 12 / 117 / 117 | +₹1,08,595 | −₹44,003 | −4.4% | 0.92 | ₹99,979 |
| 2023 | 241 | 34.4% | 5 / 127 / 109 | −₹31,818 | −₹1,88,973 | −18.9% | 0.59 | ₹2,00,786 |
| 2024 | 238 | 39.5% | 6 / 105 / 127 | +₹89,597 | −₹60,304 | −6.0% | 0.87 | ₹83,623 |
| 2025 | 240 | 45.0% | 2 / 81 / 157 | +₹50,184 | −₹98,327 | −9.8% | 0.77 | ₹1,11,624 |
| 2026 (to 23 Oct) | 194 | 38.7% | 1 / 79 / 114 | −₹33,524 | −₹1,53,922 | −15.4% | 0.66 | ₹1,90,999 |

### 1:5 year by year

| Year | Trades | Win rate | Target / stop / 15:15 | Before costs | Net P&L | Return | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 (from 25 Oct) | 46 | 45.7% | 1 / 22 / 23 | +₹48,327 | +₹20,222 | +2.0% | 1.18 | ₹36,077 |
| 2022 | 246 | 40.2% | 6 / 117 / 123 | +₹1,08,533 | −₹44,725 | −4.5% | 0.92 | ₹1,01,396 |
| 2023 | 241 | 34.4% | 2 / 127 / 112 | −₹30,584 | −₹1,88,119 | −18.8% | 0.59 | ₹1,99,932 |
| 2024 | 238 | 39.5% | 4 / 105 / 129 | +₹95,598 | −₹54,548 | −5.5% | 0.88 | ₹79,784 |
| 2025 | 240 | 45.0% | 1 / 81 / 158 | +₹54,243 | −₹94,383 | −9.4% | 0.78 | ₹1,10,517 |
| 2026 (to 23 Oct) | 194 | 38.7% | 0 / 79 / 115 | −₹36,397 | −₹1,56,904 | −15.7% | 0.66 | ₹1,93,980 |

### 1:6 year by year

| Year | Trades | Win rate | Target / stop / 15:15 | Before costs | Net P&L | Return | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 (from 25 Oct) | 46 | 45.7% | 1 / 22 / 23 | +₹49,962 | +₹21,857 | +2.2% | 1.20 | ₹34,441 |
| 2022 | 246 | 40.2% | 4 / 117 / 125 | +₹1,18,223 | −₹35,241 | −3.5% | 0.93 | ₹91,287 |
| 2023 | 241 | 34.4% | 2 / 127 / 112 | −₹27,592 | −₹1,85,128 | −18.5% | 0.60 | ₹1,96,941 |
| 2024 | 238 | 39.5% | 3 / 105 / 130 | +₹99,724 | −₹50,543 | −5.1% | 0.89 | ₹77,698 |
| 2025 | 240 | 45.0% | 0 / 81 / 159 | +₹54,280 | −₹94,458 | −9.4% | 0.78 | ₹1,10,517 |
| 2026 (to 23 Oct) | 194 | 38.7% | 0 / 79 / 115 | −₹36,397 | −₹1,56,904 | −15.7% | 0.66 | ₹1,93,980 |

## The rules as tested

The rules you gave, and the execution rules this test added. All were fixed before any result was seen.

- **Data.** NIFTYBEES (NSE) 5-minute candles, 09:15 to 15:30 IST, built from Angel One's 1-minute candles. 1,225 sessions, 25 Oct 2021 to 23 Oct 2026.
- **Opening range.** The highest high and lowest low of the 09:15, 09:20 and 09:25 candles (09:15:00 to 09:29:59), after stray pre-open prints are removed (see Data and gaps). No entry before 09:30.
- **Breakout.** By price crossing, not by a candle close. From 09:30 a buy-stop rests ₹0.01 above the range high and a sell-stop ₹0.01 below the range low. When one fills, the other is cancelled.
- **Entry fill.** At the trigger price, or at the candle's open when the candle opens beyond the trigger, plus slippage.
- **Stop-loss.** A long's stop is the range low and a short's the range high. It triggers when price touches it and fills at that price, or at a worse candle open, less slippage.
- **Target.** Twice the distance from the actual entry fill to the stop (1:2). It is a resting limit order, so it has no slippage, but it counts as filled only when price trades ₹0.01 through it.
- **Trades a day.** One. After an exit there is no re-entry and no reversal.
- **Entry window.** 09:30 to 15:00. Entry orders not filled by 15:00 are cancelled.
- **End of day.** Anything still open is closed at 15:15, at the close of the 15:10 to 15:15 candle, less slippage.
- **Position size.** ₹10,00,000 of NIFTYBEES a trade in whole units (3,366 to 6,023 units), on a ₹10,00,000 account. No leverage and no compounding.
- **Charges.** Angel One's intraday rate card from the app's fee model (`backend/app/services/angel_fees.py`): brokerage the lower of ₹20 and 0.25% an order, STT 0.025% on the sell, NSE 0.00297%, SEBI and IPFT 0.0001% each, stamp duty 0.003% on the buy, GST 18% on brokerage and fees. About ₹402 a round trip (4.0 bp). Today's schedule is charged in every year; the older schedules differ by less than 0.1 bp.
- **Slippage.** 1 bp of price on every market or stop fill (the entry, a stop-loss and the 15:15 exit), rounded to the next ₹0.01 tick against the trade: ₹0.02 to ₹0.04 a unit. 1 bp is the effective half-spread the app's index module measured from NIFTYBEES's own minute prices (2024 to 2026).
- **Inside a candle.** The order of the high and the low is unknown, so each candle is walked both ways and the way worse for the account is used. See the section on candles that touch both levels.

## Where the money went

Charges on one round trip of 4,044 units at ₹247.24 (the median entry price, about ₹10 lakh), from the app's Angel One fee model:

| Charge | ₹ | bp of ₹10 lakh |
|---|---:|---:|
| Brokerage (₹20 an order, two orders) | 40.00 | 0.40 |
| STT (0.025% of the sell) | 249.96 | 2.50 |
| NSE transaction charge (0.00297%, both legs) | 59.39 | 0.59 |
| SEBI fee | 2.00 | 0.02 |
| NSE IPFT | 2.00 | 0.02 |
| Stamp duty (0.003% of the buy) | 30.00 | 0.30 |
| GST (18% of brokerage, exchange, SEBI and IPFT) | 18.61 | 0.19 |
| **Total** | **401.95** | **4.02** |

Slippage averaged ₹214 a trade (1 bp a side on the entry and on a stop or 15:15 exit, rounded to whole ticks; targets have none). With the charges that is ₹616 a trade, 6.2 bp. At the median stop of 35.6 bp, costs come to about 0.19R a trade. The trades make +0.032R before costs.

## Candles that touch both the stop and the target

A 5-minute candle gives its high and low but not which came first. The simulator walks every candle both ways, open to high to low to close and open to low to high to close, and keeps the way that leaves the account worse at the candle's close. So a candle that reaches both the stop and the target counts as a stop-loss. An entry candle that also reaches the stop counts as stopped in that candle. A candle that triggers both the long and the short counts as whichever loses more, and only one trade is taken.

It decided 8 of 1,205 trades. 6 were candles that triggered both breakouts and 2 were entry candles that also reached the stop. No open trade had its stop and its target inside one 5-minute candle, because the target sits about 71 bp away. All 8 were scored as stop-losses.

The 1-minute candles inside them show 6 were stop-losses, 1 was stopped on the other side, and 1 actually lasted to 15:15. Using the 1-minute order on these 8 trades adds +₹4,208. Running the whole test on 1-minute candles gives −₹5,52,890, against −₹5,48,885 on 5-minute candles. That run is a little worse because 1-minute candles show small jumps between minutes, so a few entries and stops fill some paise worse than the smooth path a 5-minute candle assumes. Taking the better order in every 5-minute candle gives −₹5,44,647. No candle was still ambiguous at 1 minute. For this strategy the assumption does not change the answer.

## Data and gaps

**Source.** Angel One's 1-minute candles for NSE NIFTYBEES (token 10576), the app's licensed broker feed, turned into 5-minute candles anchored at 09:15 (75 a session): open of the first minute, highest high, lowest low, close of the last minute, summed volume. Angel's own 5-minute candles are built from the same trades. The 1-minute candles were kept to check what happened inside a 5-minute candle. Sessions up to 9 Oct 2026 come from the bulk download of 11 Oct 2026, and 12 to 23 Oct 2026 from the app's daily store on the server.

**Calendar.** The window holds 1,235 NSE sessions: weekdays, less 75 exchange holidays, plus 5 weekend sessions (20 Jan 2024, 2 Mar 2024, 18 May 2024, 1 Feb 2025 and 1 Feb 2026). NIFTYBEES has data on every one of them. Its only other prints are the Diwali Muhurat hours, which are not regular sessions: evening sessions in 2021 to 2024, outside 09:15 to 15:30, and 13:45 to 14:45 on 21 Oct 2025. 1,225 sessions are used. The table below lists the 10 expected sessions left out, and the 2025 Muhurat hour.

**Inside the sessions used.** 6 minutes are missing in all (7 Mar 2022: 09:25, 09:27, 09:28, 09:30; 16 Mar 2022: 15:00, 15:02). Each is filled flat at the previous close with no volume, so no move is invented. 1 minute printed with zero volume. There are no duplicate minutes and no zero, negative or more-than-15%-off prints.

**Stray opening prints.** Angel's 09:15 candle begins with NIFTYBEES's pre-open auction price, which is set before 09:15 by a thin book. Its open lies a median 0.49% from where NIFTY 50 puts the ETF, and on 1 day in 10 more than 2.3% away. By comparison, the 09:15 close lies 0.04% away, and minutes from 09:45 lie 0.02% away (99% within 0.17%). On 11 May 2022 the 09:15 minute printed ₹153.30 and ₹181.90 while NIFTY put the ETF at about ₹176.6. Taken raw, these prints set the opening range on most days: its median width is 94 bp, against 34 bp for NIFTY 50 itself. So each 09:15 to 09:29 print more than 0.2% outside the range NIFTY implies for that minute is replaced by the same minute's in-band open or close. Every level stays a NIFTYBEES price. That gives a median width of 34.4 bp; it changed the range on 1,044 of 1,225 sessions, almost all through the 09:15 minute. The band was fixed before any backtest ran. The raw range and a 0.5% band were run as well (see If one rule changes): both lose.

**Second vendor.** Yahoo's 5-minute NIFTYBEES candles for the last 60 sessions (29 Jul 2026 to 23 Oct 2026) agree with these candles to the paisa on 77% of highs and 57% of lows, and within one tick on 89% and 72%. Volumes match (median ratio 1.00). Where they differ, Angel's candles hold the extra extremes: Angel's high is above Yahoo's in 23% of candles and below it in 0.3%, and its low is below Yahoo's in 42% and above in 0.1%. Yahoo's 09:15 candles carry none of the stray opening prints: their median opening range is 27 bp, against 84 bp raw and 34 bp cleaned here.

Sessions not used:

| Date | Present | Why it is not used |
|---|---|---|
| 16 Dec 2021 | 13:25 to 15:29 only (125 minutes) | The bulk download lost the morning: it is the first day of a 30-day request, and Angel returned the newest 8,000 or so minutes. No opening range. |
| 14 Jun 2022 | 13:25 to 15:29 only (125 minutes) | The bulk download lost the morning: it is the first day of a 30-day request, and Angel returned the newest 8,000 or so minutes. No opening range. |
| 10 May 2023 | 13:25 to 15:29 only (125 minutes) | The bulk download lost the morning: it is the first day of a 30-day request, and Angel returned the newest 8,000 or so minutes. No opening range. |
| 2 Mar 2024 | 116 minutes | Saturday disaster-recovery drill: two short sessions, not a full day. |
| 18 May 2024 | 105 minutes | Saturday disaster-recovery drill: two short sessions, not a full day. |
| 30 Dec 2024 | 13:25 to 15:29 only (125 minutes) | The bulk download lost the morning: it is the first day of a 30-day request, and Angel returned the newest 8,000 or so minutes. No opening range. |
| 29 Jan 2025 | 13:25 to 15:29 only (125 minutes) | The bulk download lost the morning: it is the first day of a 30-day request, and Angel returned the newest 8,000 or so minutes. No opening range. |
| 29 May 2025 | 13:25 to 15:29 only (125 minutes) | The bulk download lost the morning: it is the first day of a 30-day request, and Angel returned the newest 8,000 or so minutes. No opening range. |
| 21 Oct 2025 | 13:45 to 14:44 (60 minutes) | Diwali Muhurat session, not a regular session (the exchange holiday list counts the day as closed). |
| 25 Nov 2025 | 13:25 to 15:29 only (125 minutes) | The bulk download lost the morning: it is the first day of a 30-day request, and Angel returned the newest 8,000 or so minutes. No opening range. |
| 23 Jul 2026 | 13:25 to 15:29 only (125 minutes) | The bulk download lost the morning: it is the first day of a 30-day request, and Angel returned the newest 8,000 or so minutes. No opening range. |

## If one rule changes

Each row changes one rule of the primary test and keeps the rest; all were fixed before the first run. None was chosen for its result. R is the trade's risk, from the entry fill to the stop.

| Run | Trades | Win rate | Net P&L | Profit factor | Max drawdown | Net R a trade | R before costs |
|---|---:|---:|---:|---:|---:|---:|---:|
| Primary rules, as above | 1,205 | 40.7% | −₹5,48,885 | 0.77 | ₹6,05,212 (60.5%) | −0.159 | +0.032 |
| Primary, but the path inside each 5-min candle read from its 1-min candles | 1,205 | 40.8% | −₹5,52,890 | 0.77 | ₹6,09,136 (60.9%) | −0.159 | +0.031 |
| Primary, but ambiguous candles resolved in the trade's favour (bound) | 1,205 | 40.8% | −₹5,44,647 | 0.77 | ₹6,05,176 (60.5%) | −0.157 | +0.034 |
| Primary, but the opening range from the raw prints (no cleaning) | 870 | 45.1% | −₹4,06,417 | 0.79 | ₹5,05,823 (50.6%) | −0.046 | +0.035 |
| Primary, but opening prints cleaned with a 0.5% band instead of 0.2% | 1,115 | 43.9% | −₹4,10,757 | 0.82 | ₹4,89,305 (48.9%) | −0.109 | +0.031 |
| Entry on a 5-min close beyond the range, filled at the next candle's open | 1,181 | 43.2% | −₹4,39,083 | 0.81 | ₹5,18,481 (51.8%) | −0.109 | +0.062 |
| After a stop-loss, the opposite breakout is taken once (max 2 trades a day) | 1,706 | 40.0% | −₹8,15,112 | 0.75 | ₹8,66,767 (86.7%) | −0.165 | +0.033 |
| No slippage | 1,205 | 42.7% | −₹2,89,922 | 0.87 | ₹3,57,440 (35.7%) | −0.097 | +0.033 |
| 2 bp slippage a side | 1,205 | 38.8% | −₹7,42,680 | 0.71 | ₹7,92,652 (79.3%) | −0.198 | +0.043 |
| 3 bp slippage a side | 1,205 | 37.5% | −₹10,02,344 (account at zero on 10 Aug 2026) | 0.63 | ₹10,44,260 (104.4%) | −0.250 | +0.038 |
| No charges and no slippage (the raw price edge) | 1,205 | 45.1% | +₹1,94,461 | 1.10 | ₹1,10,900 (11.1%) | +0.033 | +0.033 |
| Target fills when price touches it (no tick through) | 1,205 | 40.9% | −₹5,37,432 | 0.78 | ₹5,93,759 (59.4%) | −0.153 | +0.038 |
| Size: lose ₹10,000 (1%) at the stop, notional capped at 5x (₹50 lakh) | 1,205 | 40.7% | −₹17,00,560 (account at zero on 28 Aug 2024) | 0.74 | ₹18,49,499 (184.9%) | −0.149 | +0.032 |
| ₹1 lakh a trade on a ₹1 lakh account (brokerage weighs more) | 1,205 | 37.8% | −₹1,06,012 (account at zero on 19 May 2026) | 0.61 | ₹1,09,040 (109.0%) | −0.291 | +0.032 |

## Trade profile

Descriptive cuts of the primary trades. Nothing was tuned on them; picking a filter from this table now would fit it to the same five years it is judged on.

| Stop distance (bp) | Trades | Win rate | R before charges | Net R | Net P&L | Reached target |
|---|---:|---:|---:|---:|---:|---:|
| 9-24 | 241 | 29.0% | −0.234 | −0.448 | −₹2,07,286 | 19.1% |
| 24-32 | 241 | 35.7% | −0.101 | −0.244 | −₹1,66,234 | 14.9% |
| 32-40 | 241 | 49.4% | +0.137 | +0.024 | +₹22,746 | 15.4% |
| 40-51 | 241 | 49.4% | +0.110 | +0.021 | +₹18,839 | 10.8% |
| 51-215 | 241 | 40.2% | −0.083 | −0.147 | −₹2,16,950 | 5.0% |

R before charges is after slippage.

| Entry time | Trades | Win rate | Net R | Net P&L |
|---|---:|---:|---:|---:|
| 09:30-09:45 | 842 | 40.1% | −0.178 | −₹3,84,275 |
| 09:45-10:15 | 215 | 41.9% | −0.145 | −₹1,10,950 |
| 10:15-11:15 | 90 | 43.3% | −0.058 | −₹33,576 |
| 11:15-13:15 | 46 | 39.1% | −0.119 | −₹20,592 |
| 13:15-15:00 | 12 | 50.0% | −0.003 | +₹508 |

## Files

- `orb_data.py`: builds the 5-minute candles, the cleaned opening ranges and results/data_quality.json
- `orb_engine.py`: the rules and the simulator
- `orb_verify.py`: 49 checks of the simulator, on hand-built sessions and on the real run
- `orb_run.py`: the primary test and the comparison runs; results/summary.json, sensitivity.csv, the trade logs, yearly tables and daily equity
- `orb_crosscheck.py`: the comparison with Yahoo's 5-minute candles (results/crosscheck_yahoo.json)
- `orb_rr.py`: the same rules with the target at 1:3, 1:4, 1:5 and 1:6 (results/rr_compare.json, trade logs and yearly tables per ratio)
- `orb_report.py`: this report and report/niftybees-orb-backtest.html
- `results/trades_primary.csv`: every trade of the primary test
- `data/`: the candles themselves (NIFTYBEES_5m.csv.gz and the minutes); not in git, because Angel's data is licensed and the repository is public

