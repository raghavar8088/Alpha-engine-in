# The 20-channel study: final report

Research, rules and code: this folder. Channel selection: registry/SELECTION.md. Rules with evidence and
assumptions: specs/RULES.md (from analyses/<channel>.md). Backtests: results/BACKTEST.md. Checks: results/checks.json.
Paper desk snapshot quoted below: results/paper_snapshot_20261110T0109Z.json (2026-11-10 01:09 UTC). Paper only: simulated orders on real market data; the
desk has no real-money execution.

## 1. Coverage

- Channels: 417 found by search; the 70 covered by earlier studies removed; 40 shortlisted by their share of
  strategy videos; 20 selected (section 2) and 20 skipped with reasons (registry/SELECTION.md).
- Uploads catalogued for the 20 channels: 9,021. Videos selected and analysed: 117, all from transcripts; 4 through
  Whisper because the caption track was missing (EGyyxeQgLfw, ioDiVekuOTs) or in the wrong language (pCmJ8wsAS_w,
  2NI44nAh3co). No selected video was left unread; the Hindi Whisper transcript of ioDiVekuOTs is poor but classifiable.
- Playlists: 65 strategy-like playlists opened; they list 240 videos missing from the upload catalogues (mostly
  Shorts and older uploads). They are queued in registry/playlist_entries.json and were NOT analysed in this cycle.

## 2. The 20 channels

| Channel | Markets | Why chosen | Coded / blocked |
|---|---|---|---|
| Dhan (UCEzHCpvFWoF85UabbzKTkOQ) | Indian equity intraday, Nifty / Bank Nifty options | a broker channel whose traders show complete rule sets on charts (entry, stop, target, window); 35% of 1,512 uploads are strategy videos | 8 / 0 |
| AbhishekXTrades (UCUJmHX01pQAsP8yQ_TfsmZw) | Nifty intraday and options, bitcoin | numbered rule lists demonstrated candle by candle; 44% strategy share; recent uploads | 6 / 0 |
| Upsurge Club (UCQQojT_AmVWGb4Eg-QniuBA) | Indian options and stocks | interviews in which named traders explain a full rule set; 38% strategy share | 6 / 1 |
| Delta Exchange (UCaw-1cUd74wvEatvZna0TzQ) | Bitcoin and ether futures and options, gold | the exchange the paper desk prices crypto and gold on; rule-based scalps and AlgoTest option setups | 5 / 3 |
| Trade with Pat (UC04-HvUvHG4hpMnQx07ObYQ) | Gold, forex and US index futures | fixed-time, mechanical ORB and FVG rules shown bar by bar; gold-focused | 6 / 0 |
| Data Trader (UCwIsRM8qBXobpAnzVJ0c4IQ) | Bitcoin, gold, forex | exact indicator settings and fixed R targets in every video; 64% strategy share | 8 / 0 |
| TradingLab (UCCbv0qixG-cyokxEY3kELtg) | Crypto, forex, stocks | short videos with exact settings, stops and targets; widely copied crypto indicator sets | 4 / 1 |
| Jesse Rogers (Casper Trading) (UCEAq-8Ih0WI6R7wYoCFiWmA) | US index futures (applied to bitcoin and gold here) | fully mechanical, fixed-time rules (9:30 New York) that map directly onto 24-hour markets | 5 / 0 |
| Devansh Rai (UCRem0cxZp0CNrJaFGRB2Tpw) | Bitcoin and ether on Delta, gold | crypto on Delta Exchange (the desk's venue) and gold, with one consistent rule system | 4 / 0 |
| Stock Investment Academy (Amar Bhatia) (UCPtgdNLXi2QglhJBidB6QNw) | Indian equity intraday and swing | a SEBI-registered analyst teaching explicit entry / stop / target rules on charts | 5 / 0 |
| The Trading School (UCUzGUWt1zx8krC5i3Lzv7rA) | Nifty intraday, gold, bitcoin | rule-based Indian index price action plus gold and bitcoin setups | 5 / 0 |
| HOLD with Priyank (UCRI4NNcBZzBdVzfSlXdGwCw) | Nifty intraday, crypto | explicit trigger-candle rules for Nifty and an SMC scalp for crypto | 3 / 1 |
| TRADING RUSH (UCgY_eHY4NCTcRnU6CCZXWng) | Forex and crypto | every video states exact entry, stop and 1.5R target, and reports its own test (claims) | 4 / 0 |
| TradBuilder (UCIaCP4uF4NpYXnx1Nq7JK-Q) | Nifty index and options | rule-based Nifty strategies with spreadsheet backtests shown on screen; 72% strategy share | 3 / 4 |
| Pro Trading School (UCB5dISM93_Vr5i5AvZgTGFg) | Gold, forex, crypto | gold price action and SMC rules demonstrated on charts; 73% strategy share | 4 / 0 |
| Transparent Fx Academy (UC-vGMbd-jPqGpsuaObDHvmA) | Gold and forex | gold coverage with order-flow (COT) and volume-profile ideas (most proved incomplete: no stop or exit) | 1 / 3 |
| Trading Data (UCV9hkwgSFkAwS4hN_0oxinA) | Gold, bitcoin, EURUSD | 2026 videos with exact indicator settings on gold and bitcoin; 59% strategy share | 5 / 1 |
| Vijay Thakkar (MastersInOne) (UCHvscyzKoKxhLcaz1LQ6mHg) | Indian options and stocks (swing) | long interviews in which Indian traders give their complete rule sets | 3 / 0 |
| Faiz SMC (UC9N9JnSg9aL2w4D0kITQcaw) | Gold | time-anchored gold rules that can be coded without discretion | 2 / 1 |
| Mulham Trading (UCJFDZ3Xab4vXDSQJrvaFXIw) | Gold and forex | checklist-style gold ICT setups with explicit entries, stops and targets | 3 / 0 |

## 3. Strategies

- Coded: 90, version v1 each: 11 with every rule stated, 79 with documented
  research assumptions (the [A] lines of each analysis).
- Blocked: 15 (section 6). Duplicates of the existing library: 4. Second-source videos
  merged into a strategy: 10. Videos that teach no strategy: 2.
- Indian option strategies trade the index (or the stock) as a labelled proxy: the desk has no intraday option
  premiums. Strategies that need the premiums themselves are blocked.
- Checks: the truncation (look-ahead) test at 3 random cuts and the fill test pass for all 90.
- Fixed before activation: UP-06's order-side check was inverted (it gave no signal); its band became Supertrend's
  ratcheted band (analyses/upsurgeclub.md).

By section:

- Indian Market - Equity Intraday (26): DH-01, DH-02, DH-03, DH-04, DH-05, DH-06, DH-08, AX-01, AX-03, AX-05, AB-01, AB-02, AB-03, AB-04, TS-01, TS-02, TS-03, PV-02, PV-03, UP-03, UP-05, UP-06, VT-02, VT-03, TB-01, TB-04
- Indian Market - Options (9): DH-07, AX-02, AX-04, AB-06, UP-01, UP-02, UP-04, VT-01, TB-02
- Crypto (13): AX-06, TS-05, PV-04, DE-01, DE-02, DE-03, DE-07, DT-04, DT-05, TL-03, JR-02, DR-03, DR-04
- Gold (10): TS-04, DE-04, TP-01, TP-01H, TP-02, PT-01, PT-02, FZ-01, FZ-02, MH-01
- Crypto and Gold (shown in both sections) (32): TP-03, TP-04, TP-05, DT-01, DT-02, DT-03, DT-06, DT-07, DT-08, TL-01, TL-02, TL-04, JR-01, JR-03, JR-04, JR-05, DR-01, DR-02, RU-01, RU-02, RU-03, RU-04, PT-03, PT-04, TF-01, TD-01, TD-02, TD-03, TD-04, TD-05, MH-02, MH-03

## 4. Activation

- All 90 accounts (128 strategy-market books, Rs 10 lakh each) started at 2026-11-09 20:20 UTC (10 Nov 01:50 IST),
  flat. Indicators warm up on earlier bars; only signals after that minute trade, and a trade the desk has not seen
  before is taken only if its entry bar is fresh (bars that arrive late after a stale feed never become entries).
- Data: Delta Exchange India 1-minute candles (BTCUSD, ETHUSD, XAUTUSD, read every 2 minutes); Angel One through the
  app's backend (Nifty 50 and Nifty Bank minutes, NSE stocks on 5-minute bars); NSE bhavcopy (daily stocks); Nifty
  daily from the stored minutes. Gold trades XAUTUSD at 0.001 contracts, bitcoin BTCUSD at 0.001 BTC, ether ETHUSD
  at 0.01 ETH.
- Book states at 2026-11-10 01:09 UTC: 73 running, 38 armed, 12 in trade, 5 live (armed = waiting for the NSE open at 09:15 IST; daily books act on the next daily bar).

## 5. Backtests (net of costs, in-sample)

Through the desk's own code (next-row fills at the bid/ask, slippage, fees). The windows include the years the
videos were made in, so a positive result is not evidence of an edge.

| Strategy | Market | Trades | Net R / trade | t | Note |
|---|---|---|---|---|---|
| DE-04 | XAUUSD | 57 | +0.959 | 2.02 | long-only gold trend; R = 1% of price (no stop) |
| TB-04 | NIFTY_D | 48 | +0.751 | 2.5 | long-only daily Nifty; R = 3% of price |
| TP-01H | XAUUSD | 12 | +0.598 | 1.66 | too few trades |
| DT-04 | BTCUSD | 24 | +0.578 | 0.48 | long-only daily bitcoin; R = 1% of price; too few trades |
| VT-02 | NSED | 213 | +0.517 | 3.63 | long-only weekly stocks in a rising market |
| RU-01 | XAUUSD | 115 | +0.142 | 1.2 |  |
| DT-01 | XAUUSD | 223 | +0.118 | 1.39 |  |
| MH-01 | XAUUSD | 451 | +0.087 | 1.32 |  |
| VT-03 | NSED | 2076 | +0.083 | 1.63 | long-only swing stocks in a rising market |
| RU-03 | XAUUSD | 316 | +0.044 | 0.81 |  |
| RU-04 | XAUUSD | 832 | +0.039 | 1.1 |  |
| DT-02 | XAUUSD | 680 | +0.015 | 0.38 |  |

Positive after costs: 12 of 128 books; the rest lose, most of them to costs on short stops
(scalps on 1- to 5-minute bars). Full table: results/BACKTEST.md.

## 6. Blocked (no account)

- DE-05 BTC daily-expiry short strangle at 23:30 IST (Delta Exchange; dK3FCfA6PcI): needs Delta BTC option premiums by strike (history and live); the desk has no option-price path
- DE-06 BTC short strangle at 21:00 IST, 70% decay target (Delta Exchange; nI3xJ1SZuJ0): needs Delta BTC option premiums by strike; the desk has no option-price path
- DE-08 Tokyo close / New York open session strategy (Delta Exchange; fWtaHzVCln0): trend and levels come from adaptive community indicators whose formulas are not given; levels chosen by eye
- TL-05 Chandelier Exit + BJ SuperScript + RSI 25/SMA 150 + EMA 200 (TradingLab; cxZOD1iOKVc): the entry needs the 'BJ SuperScript' community indicator, whose formula is not given
- UP-07 Change-in-OI PCR after 11:00, entry at the option's VWAP (Upsurge Club; u_TGW73x9Uk): needs the NSE option chain (open interest by strike) and option premium bars, history and live
- TB-03 NIFTY weekly call sold at 09:25 (premium near Rs 30) (TradBuilder; H6snDCl6iR0): premium-based option selling: needs NIFTY option premiums by strike
- TB-05 SENSEX weekly call bought at 14:30 (premium >= Rs 100) (TradBuilder; gXhm3UI0aT8): premium-based: needs SENSEX option premiums
- TB-06 NIFTY ADX above 50 before 10:00, long ATM straddle (TradBuilder; v0IUgWuqn-g): a straddle priced in premiums: needs NIFTY option premiums
- TB-07 Intraday rolling short straddle with leg re-entries (TradBuilder; U0df-RTI5tg): option selling on premiums: needs NIFTY option premiums
- PV-01 Opening-gap two-sided fill theory (HOLD with Priyank; _mBknFCgnoQ): a level concept with no entry trigger, stop or timeframe
- TF-02 Daily pivot points, two trades a day (Transparent Fx Academy; 4QB6f7LvbbI): the author calls it concepts, not a complete strategy: no stop, the entry is a rejection read by eye
- TF-03 Gold 10/20 EMA zone retests with COT net positioning (Transparent Fx Academy; njjug8HxiUM): an 'idea' with no stop or target; direction from weekly CFTC COT data the desk does not have
- TF-04 Gold point-of-control scalps with COT (Transparent Fx Academy; c6cayyYx9bM): a hand-picked daily swing, no exchange volume for spot gold, rules left to the viewer
- TD-06 9/20 EMA cross after two working crosses; 9/20 EMA pullback (Trading Data; S15vYdGEm7o): no stop, target or exit given; 'worked' is not defined
- FZ-03 Turtle soup inside 4-hour order flow (Faiz SMC; oPxktw8-NM4): 4-hour order blocks picked by eye and no target rule; the sweep-and-shift core is CP-26 (turtle soup)

Duplicates of the library:

- KSCBybE9dVw (Stock Investment Academy (Amar Bhatia)): 5 EMA alert candle (AB-05) - duplicate of YT-01 (5 EMA alert candle)
- MjN06gyjKK8 (Pro Trading School): ICT candle range theory - duplicate of BG-08 (gold CRT) / NJ-32 (BTC CRT 2.0)
- YmOrNIX2B78 (Faiz SMC): ICT Silver Bullet with the draw on liquidity - duplicate of CP-28 / YT-04 / BG-07
- oiArTaTBEkI (Mulham Trading): ICT Silver Bullet (10:00-11:00 NY) - duplicate of YT-04 / BG-07 / CP-28

## 7. Paper results at 2026-11-10 01:09 UTC

- 20 of 90 accounts have traded: 23 closed trades (4 winners), 12 open.
- Combined P&L of the 90 accounts: Rs -235,363 (realised Rs -186,556, unrealised Rs -48,807).
- Far too early to judge any strategy; the page's 20 channels tab shows each account live.
