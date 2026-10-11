# Gold Desk audit and research — 2026-10-10

Scripts behind [`GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md`](../../../GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md). Nothing here writes to the database.

The desk has never placed a trade (both books ship OFF and were never switched on), so its profitability is measured by **replaying the desk's own catalogue on gold history** — the desk's own `evaluate()`, on closed bars, filled honestly, costed as measured.

| Script | Where it runs | Settles |
|---|---|---|
| `gd_audit.py` | backend image (read-only) | the desk's record (0 positions, 0 trades on both venues since 2026-09-29); switches; 7,127 flat equity samples; bar-store coverage; MCX spreads logged for gold (`mcx_quote_log`: GOLDM front month median 1.28 bp, GOLD 2.21 bp); the MCX curve (GOLDM Nov → Dec +0.87%) |
| `gd_export_mcx.py` | backend image (read-only) | exports the stored MCX GOLD/GOLDM bars, every contract (91,830 rows) |
| `gd_fetch.py` | local | public data: Delta XAUTUSD/PAXGUSD 1m since launch + `FUNDING:` series + product specs; Binance PAXGUSDT 1m since 2020-08; Yahoo COMEX GC=F 1h/1d and USD/INR |
| `gd_l2_sampler.py` | AWS host (stdlib, 72 h from 2026-10-10 22:00 IST, `/tmp/gd_l2.jsonl`) | Delta order books every 60 s: XAUT quoted 0.072 bp, a $1,667 slot crosses for 0.036 bp a side; PAXG 0.239 / 0.12 bp (weekend) |
| `gd_quality.py` | local | which history can be trusted for what: Binance PAXG 49–81% dead minutes before 2025 (hourly corr with COMEX 0.67 in 2024 → 0.985 in 2026); Delta tokens 0.98; MCX GOLDM vs world gold 0.87 hourly, 0.82 at 15m, 0.62 at 1m; Delta funding a constant 0.005 on 96–100% of hours; XAUT/PAXG basis sd 13 bp |
| `gd_replay.py` | local, 8 processes, ~98 min | stages 0–2: bars built exactly as the live stores build them; every signal of every strategy on six histories (8.8 M), each with its honest outcome and the desk-as-built polled outcome |
| `gd_replay_small.py` | local, 4 processes | the replay's small jobs (MCX histories, 15m+) run first, beside the main run; identical output |
| `gd_analyse.py` | local | stage 3: one position per strategy (2,977,769 trades); gross / desk-charged / measured costs; per-strategy stats, halves, DSR, PBO, drift-adjusted excess, regime and holding-time cuts. Below 4h every timeframe on every history is negative after costs; 0 strategies reach DSR 0.95 |
| `gd_benchmark.py` | local | the Commodity Lab's criterion 4 on gold alone (COMEX 2000–2026): 39 of 40 daily templates lose to holding gold (held-out Sharpe 0.64); Bollinger Squeeze passes (alpha t 2.37) |
| `gd_book.py` | local | each book as a system (shared balance, slots in scan order, sizing, breakers): Delta $10k and MCX ₹30 L both hit the 50% floor within weeks; 1m/5m take 100% of slots; MCX held long and short GOLDM at once 31–45% of open hours |
| `gd_forming.py` | local | defect D1 sized on Delta XAUT: as built, 40–62% of the desk's 15m–1d trades are signals that never exist on the closed bar, losing −2.6 to −20.1 bp before costs |
| `gd_luck.py` | local | the desk's READY gate on zero-edge (sign-randomised) records: 3–6% of eligible strategies pass by luck |
| `gd_hypotheses.py` | local | three pre-registered gold alternatives: intraday momentum (reject), session drift (reject), XAUT/PAXG basis reversion (+5.4 bp gross, +0.4 net — too thin) |
| `gd_strategy_table.py` | local | the 46-template and 353-strategy tables with the mechanical decision rule → `gd_strategy_table_out.md` |
| `gd_data.py` | — | shared loaders and the two bar builders (UTC-anchored 24/7, 09:00 IST-anchored MCX) |

Run order: `gd_fetch.py` → (box) `gd_audit.py`, `gd_export_mcx.py` → `gd_quality.py` → `gd_replay.py build` → `gd_replay.py run 8` (optionally `gd_replay_small.py 4` beside it) → `gd_analyse.py` → `gd_benchmark.py`, `gd_book.py`, `gd_forming.py`, `gd_luck.py`, `gd_strategy_table.py`; `gd_hypotheses.py` any time.

Data lands in `./data/` and is not committed (`data/.gitignore`). The sampler on the AWS host exits by itself after 72 hours.
