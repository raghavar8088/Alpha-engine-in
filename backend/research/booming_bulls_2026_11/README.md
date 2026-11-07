# Booming Bulls strategy research (Nov 2026)

The owner asked for every strategy taught on the Booming Bulls YouTube channel to be found and analysed with the project's YouTube Video Explainer app. The strategies were then to be turned into testable rules and backtested. The brief has ten phases, and this folder is the full research package.

**Status, 7 Nov 2026: complete.**
- **Result:** 18 strategies were built. 17 were backtested (25 strategy-market books); BB-15 is blocked on data. **None passes, and all 25 are "not supported".** Before costs they are near zero; after realistic costs every one loses.
- **Full results:** [REPORT.md](REPORT.md).
- **Scope:** research only. Nothing here is registered in the app, wired to a desk or able to trade.

## Layout

| Path | What | In git |
|---|---|---|
| `catalogue/` | **Phase 1:** `CATALOGUE.md` (readable index of the 222 selected uploads by family), plus `catalogue.csv` / `.json` (all 2,965 public uploads, labelled, with analysis status) | yes |
| `analyses/` | **Phase 2:** timestamped analyses of the 96 strategy videos and the 13 worked examples. Each rule is tagged explicit (E) or inferred (I), with contradictions and missing pieces | yes |
| `specs/LIBRARY.md` | **Phase 3:** the deduplicated strategy library, the untestable list with reasons, and duplicates | yes |
| `specs/PREREGISTRATION.md` | **Phases 4, 6–8:** measurable rules, variants, costs, data, splits and gates, locked before any run (`PREREG_HASH.txt`) | yes |
| `bb_markets.py` | Minute data for 8 markets in one layout; bars, indicators, data-quality report | yes |
| `bb_engine.py` | Fill engine: next-minute fills at the bid/ask, stop first, gaps, breakeven, trailing, partials, forced exits, costs | yes |
| `bb_strategies.py` | The 17 runnable strategies, with every signal on completed bars only | yes |
| `bb_checks.py` | Verification: engine unit tests, look-ahead truncation test, BB-01 fidelity check against the video's own replay | yes |
| `bb_run.py` | Backtests, variant choice on development + validation, hold-out, robustness, walk-forward, Holm, gates | yes |
| `bb_report.py` | Builds `REPORT.md` | yes |
| `results/` | `summary.json`, `runs/*.json` (one per strategy-market), `trades/*.csv.gz`, `equity/*.csv.gz`, `checks.json`, `data_quality.json` | yes |
| `bb_*.mjs` | YouTube side (Node 22+, yt-dlp, Deno, FFmpeg) | yes |
| `bb_fetch_dukascopy.py` | US30/AAPL minute fetch (blocked by Dukascopy throttling on 7 Nov) | yes |
| `data/` | Raw listings, metadata, transcripts, market-data caches: YouTube content and licensed data | **no** (`data/.gitignore`) |

Transcripts and frames stay out of git, because the repository is public and they are the channel's content.

**Hold-out discipline.** Each variant was chosen from development + validation trades before any hold-out number existed. Only V0 and the chosen variant have hold-out trades in `results/trades/`; other variants' hold-out trades were dropped unread.

## Reproduce

Run everything from this folder.
- **Tools:** yt-dlp, Deno and FFmpeg must be on PATH (installed with winget on 6 Nov 2026).
- **Python:** run with `python -I`. The scripts add their own folder to the path.

| Step | Command | Does |
|---|---|---|
| 1 | `node bb_fetch_catalogue.mjs` | Lists every public upload (Videos, Shorts, Live) into `data/catalogue/raw/` |
| 2 | `node bb_inspect_listing.mjs` | One-line-per-upload title files for the manual labelling |
| 3 | (manual) `bb_labels.mjs` | Hand labels: family, market, priority and note for each strategy-related upload |
| 4 | `node bb_fetch_meta.mjs` | Exact date, language, caption tracks, chapters and description for each labelled upload |
| 5 | `node bb_extract_batch.mjs P1` (then `P2`, `P3`) | Runs the app's own `extract.mjs` on each video, then `bb_prepare_transcript.mjs` |
| 6 | `node bb_build_catalogue.mjs` | Rebuilds `catalogue/` with the current analysis status |
| 7 | `python -I bb_markets.py` | Builds the market caches and `results/data_quality.json` |
| 8 | `python -I bb_checks.py` | Unit tests, look-ahead test, fidelity check → `results/checks.json` |
| 9 | `python -I bb_run.py` | Every backtest → `results/runs/`, `trades/`, `equity/` |
| 10 | `python -I bb_run.py --summary` | Opens the hold-out, applies Holm and the gates → `results/summary.json` |
| 11 | `python -I bb_report.py` | Writes `REPORT.md` |

**Transcript preparation.** `bb_prepare_transcript.mjs` changes no words:
- it collapses YouTube's rolling auto-captions, where each phrase appears about three times;
- it romanizes Devanagari for reading;
- it groups the text into 30-second blocks.

`bb_rule_digest.mjs <id>` prints the opening block plus the highest-scoring rule blocks. Each analysis says whether it came from a full read or a digest.

## Changes made to the Video Explainer app

`youtube-video-explainer-reviewed/extract.mjs` (the app folder is untracked):
- **Caption language:** it picks the caption track in the video's own language. It used to take the first `-orig` track, which on auto-dubbed videos was a dub: iTWMIaqYLJg came back in Bengali instead of Hindi.
- **`--lang=hi`:** forces a caption language, and a warning appears when the declared language has no track. This is for auto-dubbed videos that declare the wrong language: nPVISNpXmtQ declares `en-US`, has no English track, and came back in Arabic until it was re-run with `--lang=hi`.
