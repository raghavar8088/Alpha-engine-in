# The 20 largest trading-strategy YouTube channels: research package (Nov 2026)

**The brief.** The owner asked for the Booming Bulls study to be repeated for "the top 20 traders on YouTube":
- select the channels;
- analyse their strategy videos with the project's YouTube Video Explainer app;
- build the strategies;
- backtest them.

**The method** is the same as `../booming_bulls_2026_11`:
- every rule is written down and hash-locked before the first run;
- each variant is chosen on development + validation data only;
- the hold-out is opened once;
- results are classified by fixed gates.

Research only: nothing here is registered in the app or wired to a trading desk.

**Results:** [REPORT.md](REPORT.md). **Library:** [specs/LIBRARY.md](specs/LIBRARY.md). **Rules:** [specs/PREREGISTRATION.md](specs/PREREGISTRATION.md).

## Layout

| Path | What | In git |
|---|---|---|
| `catalogue/` | `CATALOGUE.md` (selection evidence, the 20 channels, strategy-video pools and picks) and `catalogue.csv` (all 15,591 long-form uploads of the 20 channels) | yes |
| `analyses/` | Timestamped rule analyses of the 53 readable picked videos, 4 channels per file | yes |
| `specs/` | `LIBRARY.md` (28 strategies, the untested list with reasons), `PREREGISTRATION.md` + `PREREG_HASH.txt` | yes |
| `yt_*.mjs` | YouTube side: candidates and live counts, upload lists and the title screen, selection, picks, extraction through the app, digests, catalogue | yes |
| `yt_markets.py`, `yt_engine.py`, `yt_ind.py`, `yt_strategies.py` | Markets (incl. NSE stocks), the extended fill engine, indicators, the strategies | yes |
| `yt_checks.py`, `yt_run.py`, `yt_report.py` | Verification, backtests and gates, the report | yes |
| `yt_bhav_convert.py` | NSE daily bhavcopy → `data/nse_daily.npz` (split-adjusted; run with the NSE research environment) | yes |
| `results/` | `summary.json`, `runs/*.json`, `trades/*.csv.gz`, `equity/*.csv.gz`, `checks.json` | yes |
| `data/` | Upload lists, transcripts, market caches: YouTube content and licensed data | **no** |

## Reproduce

See the table at the end of REPORT.md.
- **Tools:** yt-dlp, Deno and FFmpeg must be on PATH (installed with winget on 6 Nov 2026).
- **Python:** run with `python -I`.

## Tooling reused, and one fix

- **Reused from the Booming Bulls study:** the transcript tools (rolling-caption collapse, Devanagari romanisation) and the market loaders. The fill engine was copied into `yt_engine.py` and extended, so the Booming Bulls results stay reproducible.
- **The fix:** the Video Explainer app's `--lang` option recovered the human-made English subtitles of the Elearnmarkets / Vishal Mehta interview (bj6hVKjweZ8), whose Hindi auto-captions were garbled.
