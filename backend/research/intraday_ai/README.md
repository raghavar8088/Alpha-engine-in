# Intraday Stocks research harness (Phase 2 of `INTRADAY_STOCKS_AI_UPGRADE_PLAN.md`)

One repeatable way to test an idea on two years of history, off the server. The backend box
has 1.9 GB of RAM and the backend sits near its 800 MB limit, so research never runs there.

| File | What it does |
|---|---|
| `stubpkg.py` | Builds a runnable copy of the backtest **from a git commit** (never the working copy). The database and live services are replaced by read-only stand-ins that serve the exports. |
| `export_box.py` | Read-only exports. Database exports run in a throwaway container on the box, so the credential stays there; bar files are streamed as a tar. |
| `runner.py` | Runs the production backtest over a date range: optional live rules (`--live-rules`), the stored daily universe (`--live-universe`), and per-signal feature rows (`--features six`). |
| `features.py` | Point-in-time features of each signal, from the context the rule itself read, plus the simulated outcome as the label. |
| `fidelity.py` | Backtest vs the live tournament, trade by trade, over the live period. |
| `prereg.py`, `prereg/` | Pre-registrations: the hypothesis, metric, sample and decision rule are written and committed **before** a test runs, and never edited. |

Data lives outside the repo, in `INTRADAY_AI_DATA` (default `D:/intraday_ai_data`):
`intraday/15m`, `intraday/5m`, `intraday/nse`, `exports/*`, `pkg/<commit>`, `runs/<name>`.

```
set BOX_HOST=ubuntu@<box>  &  set BOX_SSH_KEY=<key.pem>
python export_box.py files 15m          # bar files
python export_box.py bars1d 2024-08-01 2026-11-05
python export_box.py members            # today's universe + CAS flags
python runner.py --name y2 --start 2024-11-04 --live-rules --features six
```

Rules: every test is pre-registered before its result is read; the most recent 6 months
are the holdout, opened once per test; results are judged on net profit per trade after the
measured costs, never on win rate.
