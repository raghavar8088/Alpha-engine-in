# 99fQ_As8Wuo: What is VOLUME PROFILE & POC || Full Guide

- **Video:** https://www.youtube.com/watch?v=99fQ_As8Wuo · May 2026 · 23:55 · Hindi · track `hi-orig`
- **Family:** F05 volume profile · **Priority:** P1 · **Market:** gold, using COMEX gold futures (GC) for volume; also silver (SI), crude (CL), BTC (Binance)
- **Evidence:** full transcript (4,785 words). No frames.
- **Earlier coding:** D4 `bb_volume_profile_poc` (POC fade/accept on a time-at-price proxy) was coded from the title. The video does not trade the POC.

## Rules

| # | Rule | Type | Evidence |
|---|---|---|---|
| 1 | Read volume from the **exchange futures** chart (COMEX GC, SI; CL; Binance for BTC), not from broker CFD prices (which he calls "fabricated") | E | 00:00–03:00 |
| 2 | **Volume reading:** price up with volume up = strong trend; volume up while price falls = trend change; price up while volume turns down = trap coming; price down with volume falling = a trap to the upside. Volume EMA as the average line | E | 03:30–04:30, 06:00 |
| 3 | **Profile:** TradingView Fixed Range Volume Profile (default settings) over the **previous session** (Friday's for Monday); data up to 16:00 is fine | E | 08:30–09:30, 22:00 |
| 4 | Profile shape: P-shape (volume on top) = mild bullish bias; b-shape = bearish. "Can't fully trust it" | E | 10:00–10:30, 21:30 |
| 5 | Mark **low-volume nodes (LVN)** and **high-volume nodes (HVN)**, extended into the next day; POC is the red line; the developing POC is useless | E | 10:30–13:00, 21:00 |
| 6 | **LVN = breakout level:** do not respect it as support/resistance; trade when price **breaks** an LVN, with candle confirmation | E | 13:00–14:30, 17:30–18:00 |
| 7 | **HVN = reversal level:** trade traps or liquidity sweeps there; never treat an HVN as a breakout level | E | 14:30–15:00, 20:30–21:00 |
| 8 | **Session:** his gold trades are from about 16:00–17:00 India time (5–6 pm, sometimes 21:00), not early morning | E | 16:30–17:30 |
| 9 | **Timeframe:** 5-minute for everything, bias included | E | 22:30 |
| 10 | **Frequency:** the LVN breakout "works about twice a week" | E (claim) | 20:30 |

## Unclear or missing

- **Stop:** not stated.
- **Target:** examples ran to the next LVN ($18–$42); no fixed rule.
- **LVN/HVN selection:** made by eye ("I took three").
- **Breakout confirmation:** whether a close beyond the LVN suffices.

## Conflict with other videos

- rFrFhpwJJOc (Jul 2026) trades sweeps of the value-area high/low instead.
- IOBoaM71MUA (Oct 2026) names the value-area high/low as his favourite levels.

These are three different uses of the profile; the latest teaching is the value-area sweep.

## Promotional content

12:00: Exness and another broker; Zoom classes; like target.

## Testability

**Testable with research assumptions only**, and with low fidelity:
- **Volume:** COMEX futures intraday volume is not on disk; Dukascopy spot tick volume would be a proxy.
- **Nodes:** LVN/HVN extraction must be defined by me.
- **Exits:** the stop and target must be added.

Lower priority than the value-area sweep.
