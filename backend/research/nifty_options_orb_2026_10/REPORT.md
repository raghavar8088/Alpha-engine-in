# NIFTY 50 ATM option opening-range breakout, buying and selling: five-year backtest

NSE: NIFTY 50 weekly options, at the money, same-week expiry, 25 Oct 2021 to 23 Oct 2026 (1,222 sessions), one lot of 65. `python -I nopt_report.py` rebuilds this file.

## Verdict

**Buying loses at every ratio.** At 1:2 the 1,218 trades made −₹2,71,175 on one lot (−₹4,445 a month, −2.22% a month on a ₹2,00,000 account; t = −2.23). 1:3 to 1:6 lost between ₹2,05,370 and ₹2,58,776. Before any cost the options already lost ₹1,56,115: time decay costs more than the breakouts earn.

**Selling (the mirror) is about break-even after costs.** Doing the opposite earns the buyer's pre-cost loss, +₹1,56,115, but pays the spread and the charges again (₹1,15,317): net +₹40,798 at 1:2 (+₹669 a month, +0.33% a month on ₹2,00,000; t = +0.33, not significant). It ranges from −₹25,343 to +₹40,798 across the ratios.

**The seller's small profit is not reliable.** It all comes from expiry-day trades (+₹49,664), the one place the model is still off, and off in the seller's favour (it lets expiry-day options decay 7–11% of their premium faster than the recorded real quotes). Without expiry-day trades the seller made −₹8,866; selling next week's expiry instead made −₹1,31,564.

## Investment and monthly return (1:2)

| | Buying | Selling (mirror) |
|---|---|---|
| What one trade ties up | the premium: ₹7,125 a lot on average (expiry day ~₹4,013, 2-4 days out ~₹8,684) | the margin: ₹1,24,468 a lot on average (expiry day ~₹1,48,907 with the extra 2% ELM), up to ₹1,84,177 |
| Trades a month | 20, one at a time | 20, one at a time |
| Premium spent / margin blocked over a month | ₹1,42,263 of premium in total (recycled; never more than one lot at once) | ₹1,24,468 blocked during each trade; the premium received, ~₹7,094, is credited |
| Net P&L a month (average) | −₹4,445 | +₹669 |
| Return a month on a ₹2,00,000 account | −2.22% | +0.33% |
| Monthly net as a share of what one trade ties up | −62.4% of one lot's premium | +0.54% of one lot's margin |
| Months up | 23 of 61 | 34 of 61 |
| Median / best / worst month | −₹6,575 / +₹29,092 / −₹30,620 | +₹2,839 / +₹26,466 / −₹32,181 |
| Five years in total | −₹2,71,175; max drawdown ₹3,45,184; a ₹2 lakh account hits zero on 2 Feb 2026 | +₹40,798; max drawdown ₹92,791 |

## Buying: results by risk : reward

| Risk : reward | Trades | Win rate | Index target / stop / 15:15 | Before costs | Spread & slippage | Charges | Net P&L | Profit factor | Max drawdown | Net a month | % a month on ₹2L |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1:2 | 1,218 | 35.6% | 200 / 548 / 470 | −₹1,56,115 | −₹37,618 | −₹77,442 | **−₹2,71,175** | 0.85 | ₹3,45,184 | −₹4,445 | −2.22% |
| 1:3 | 1,218 | 33.7% | 85 / 558 / 575 | −₹1,43,685 | −₹37,626 | −₹77,465 | **−₹2,58,776** | 0.86 | ₹3,45,708 | −₹4,242 | −2.12% |
| 1:4 | 1,218 | 33.7% | 40 / 558 / 620 | −₹90,096 | −₹37,704 | −₹77,570 | **−₹2,05,370** | 0.89 | ₹2,83,511 | −₹3,367 | −1.68% |
| 1:5 | 1,218 | 33.7% | 19 / 559 / 640 | −₹93,946 | −₹37,692 | −₹77,558 | **−₹2,09,196** | 0.89 | ₹2,90,011 | −₹3,429 | −1.71% |
| 1:6 | 1,218 | 33.6% | 10 / 559 / 649 | −₹99,467 | −₹37,693 | −₹77,549 | **−₹2,14,709** | 0.89 | ₹2,98,866 | −₹3,520 | −1.76% |

Net P&L by year:

| Year | 1:2 | 1:3 | 1:4 | 1:5 | 1:6 |
|---|---:|---:|---:|---:|---:|
| 2021 (from 25 Oct) | +₹14,865 | +₹27,507 | +₹28,623 | +₹30,377 | +₹32,323 |
| 2022 | −₹44,901 | −₹38,901 | −₹23,194 | −₹6,481 | −₹6,420 |
| 2023 | −₹92,663 | −₹81,436 | −₹78,787 | −₹84,667 | −₹80,885 |
| 2024 | −₹7,663 | −₹3,509 | +₹29,321 | +₹15,693 | −₹2,261 |
| 2025 | −₹62,761 | −₹85,706 | −₹78,853 | −₹84,458 | −₹77,452 |
| 2026 (to 23 Oct) | −₹78,053 | −₹76,731 | −₹82,480 | −₹79,661 | −₹80,014 |

By days to expiry (1:2): expiry day (0DTE): 259 trades, −₹89,800 net (−₹69,780 before costs); 1 session left: 260 trades, −₹66,690 net (−₹43,781 before costs); 2-4 sessions left: 697 trades, −₹1,12,901 net (−₹41,063 before costs); 5+ sessions left: 2 trades, −₹1,785 net (−₹1,491 before costs).

## Selling (the mirror): results by risk : reward

| Risk : reward | Trades | Win rate | Index target / stop / 15:15 | Before costs | Spread & slippage | Charges | Net P&L | Profit factor | Max drawdown | Net a month | % a month on ₹2L |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1:2 | 1,218 | 63.1% | 200 / 548 / 470 | +₹1,56,115 | −₹37,617 | −₹77,700 | **+₹40,798** | 1.02 | ₹92,791 | +₹669 | +0.33% |
| 1:3 | 1,218 | 64.9% | 85 / 558 / 575 | +₹1,43,685 | −₹37,618 | −₹77,715 | **+₹28,352** | 1.02 | ₹1,00,406 | +₹465 | +0.23% |
| 1:4 | 1,218 | 64.9% | 40 / 558 / 620 | +₹90,096 | −₹37,696 | −₹77,743 | **−₹25,343** | 0.99 | ₹1,43,667 | −₹415 | −0.21% |
| 1:5 | 1,218 | 65.0% | 19 / 559 / 640 | +₹93,946 | −₹37,698 | −₹77,742 | **−₹21,494** | 0.99 | ₹1,42,828 | −₹352 | −0.18% |
| 1:6 | 1,218 | 65.1% | 10 / 559 / 649 | +₹99,467 | −₹37,698 | −₹77,741 | **−₹15,972** | 0.99 | ₹1,38,222 | −₹262 | −0.13% |

Net P&L by year:

| Year | 1:2 | 1:3 | 1:4 | 1:5 | 1:6 |
|---|---:|---:|---:|---:|---:|
| 2021 (from 25 Oct) | −₹23,373 | −₹36,079 | −₹37,197 | −₹38,959 | −₹40,920 |
| 2022 | −₹1,863 | −₹7,892 | −₹23,682 | −₹40,489 | −₹40,553 |
| 2023 | +₹52,708 | +₹41,426 | +₹38,763 | +₹44,677 | +₹40,873 |
| 2024 | −₹40,414 | −₹44,574 | −₹77,587 | −₹63,882 | −₹45,837 |
| 2025 | +₹16,559 | +₹39,631 | +₹32,744 | +₹38,376 | +₹31,327 |
| 2026 (to 23 Oct) | +₹37,182 | +₹35,840 | +₹41,616 | +₹38,784 | +₹39,138 |

By days to expiry (1:2): expiry day (0DTE): 259 trades, +₹49,664 net (+₹69,780 before costs); 1 session left: 260 trades, +₹20,773 net (+₹43,781 before costs); 2-4 sessions left: 697 trades, −₹30,836 net (+₹41,063 before costs); 5+ sessions left: 2 trades, +₹1,197 net (+₹1,491 before costs).

## The rules as tested

- **Signal.** The NIFTYBEES study's rules, read on the NIFTY 50 index itself: the opening range is the high and low of 09:15:00 to 09:29:59; from 09:30 the first move above the high or below the low is the breakout.
- **Contract.** A break above uses the at-the-money CALL, a break below the at-the-money PUT: the strike nearest NIFTY at the breakout (50 apart), of the nearest weekly expiry on or after the trade day as NSE listed it (Thursdays to August 2025, Tuesdays after). On expiry day that is the contract expiring that afternoon.
- **Buying.** The option is bought at the breakout and sold at the exit.
- **Selling (the mirror).** The same option is SOLD at the same moment and bought back at the same exits. Nothing else changes.
- **Exits.** Levels on the index, as before: the stop is the other side of the opening range, the target 2 (3, 4, 5, 6) times the entry-to-stop distance beyond the entry. When NIFTY touches either, the option is closed at market. Anything still open is closed at 15:15. For a seller the index 'target' is the losing exit and the 'stop' the winning one.
- **Trades a day.** One. No re-entry, no reversal. No entry from 15:00.
- **Size.** One lot of 65 units (today's NIFTY lot; it was 50, then 25, then 75 during the five years).
- **Fills.** Every fill pays half the spread (0.15% of the premium) and one ₹0.05 tick: bought above the mid, sold below it. The recorded at-the-money same-week spread is a median 0.23% of the premium, so this is a little worse.
- **Charges.** Angel One's option rate card at today's rates (the app's fee model): ₹20 an order, STT 0.15% of the premium sold (a seller pays it on the opening sale), NSE 0.03503%, SEBI and stamp duty, GST 18%.
- **Margin (selling).** The app's SPAN-lite engine (±6% scan plus 3% exposure, calibrated on NIFTY), plus the extra 2% ELM on short options on their expiry day.
- **Account.** ₹2,00,000, no compounding: drawdowns and monthly returns are measured on it.

## How the option prices were obtained, and how good they are

No source this app can reach keeps intraday prices of EXPIRED NIFTY options: Angel One and Dhan serve candles only for live contracts, and the app's own option-chain recorder started on 5 Oct 2026. So every entry and exit premium is modelled, with the method the NIFTY BANK study built and validated, redone for weekly options.

Each contract's volatility comes from the previous session's REAL NSE closing prices (bhavcopy) for that very expiry; nothing from the trade day's own option prices is used. During the day it moves with India VIX (exponent 1.5, smile rule 'moneyness', chosen on 2021-23 only). Time runs on a clock of trading minutes plus 0.2 of a session a night.

Check 1, real closing prices, 2024-26 (not used for any choice): the model's day-over-day change was off by −1.40% of the premium on average over 4,060 option-days.

Check 2, the real intraday quotes the recorder kept (14 sessions, 5-23 Oct 2026, entries every 30 minutes). The first model ran the clock flat through the day; it overpriced expiry-day options at entry and decayed them too fast (change to 15:15 −14.3% of the premium on expiry day). NIFTY's variance is not flat: 15% of an expiry day's has gone by 09:30, against 4% of its minutes. So the final model counts each minute by its share of a day's variance, measured on NIFTY's own 2021-23 minutes (no option prices). Change errors with it: 2-4 days to expiry +0.6% (60 min) and +2.6% (to 15:15); 1 day −0.5% and +0.9%; expiry day still −7.2% (120 min) and −11.3% (to 15:15). Expiry-day options still decay too fast in the model: that makes buying look a little worse and selling a little better than they were.

Check 3, the strategy's own trades: 14 of its October 2026 trades fall inside the recorded sessions. At the real quotes of their minutes the buyer made +₹35,670 before costs; the model said +₹33,213 (the seller: the same amounts with the sign flipped).

The first (flat-clock) model gave buying −₹4,30,345 and selling +₹1,98,145 at 1:2. Both are reported; the conclusions are the same.

## If one assumption changes (1:2)

| Change | Buying net | Selling net |
|---|---:|---:|
| None (the results above) | −₹2,71,175 | +₹40,798 |
| VIX pass-through off (beta 0; chosen 1.5) | −₹2,35,413 | +₹5,672 |
| VIX pass-through beta 0.4 (chosen 1.5) | −₹2,46,233 | +₹16,307 |
| smile rule 'strike' (chosen 'moneyness') | −₹3,13,605 | +₹82,774 |
| double the spread (0.30% a side) | −₹2,96,885 | +₹15,119 |
| next week's expiry instead | −₹1,73,548 | −₹1,31,564 |
| no trades on the contract's expiry day | −₹1,81,375 | −₹8,866 |
| The first model (flat clock) | −₹4,30,345 | +₹1,98,145 |

## Data and gaps

- NSE F&O bhavcopies for 1,249 sessions (2021-10-01 to 2026-10-23); exchange holidays have none. 1,245 sessions gave a smile; Diwali Muhurat files are not used.
- NSE moved the 2023 Bakri Id holiday from 28 to 29 June at short notice: its files list that week's expiry as 29 June until 27 June, but the contracts expired on 28 June. The one such case; corrected.
- NIFTY 50 and India VIX 1-minute candles from Angel One. 13 sessions in the window have no 09:15 minute or are not full sessions and are left out: 30 Nov 2021, 4 Jan 2022, 7 Mar 2022, 28 Jun 2022, 1 Jul 2022, 24 May 2023, 2 Mar 2024, 18 May 2024, 14 Jan 2025, 13 May 2025, 12 Jun 2025, 21 Oct 2025, 7 Jul 2026.
- Since 3 Aug 2026 Angel serves almost no index minutes after 15:14 (NSE's closing auction); the 15:15 exit uses the 15:14 minute.
- Intraday option quotes: the app's recorder, 14 sessions, every minute, ATM ±10 strikes. Lot sizes in the window: 50, 25 (Jul-Dec 2024 in NSE's files), 75, now 65; every trade here uses 65.

