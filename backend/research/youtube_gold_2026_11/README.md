# Gold channels 21-40 (22 Nov 2026)

The owner's second list of 20 YouTube channels for gold strategies (numbers 21-40): their gold videos read in full from
the captions, each clearly defined method written as exact rules, and each coded strategy paper trading its own
Rs 10 lakh account on the Premium Strategies desk (source `youtube_gold`, Delta Exchange XAUTUSD candles, from the gold
week that opens Sunday 22 Nov 2026 17:00 New York). None is backtested; paper trading is their first test.

| Step | Tool | Output |
| --- | --- | --- |
| Find the channels and their uploads | `node zg_channels.mjs resolve`, `catalogue`, `gold [key]` | `catalogue/channels.json`, the Video Lab's channel files |
| Pick the videos | by hand from the gold titles and the list's notes | `catalogue/picks.tsv` (59) |
| Save captions (no media) | `node zg_fetch.mjs` (`--status`) | the Video Lab's `evidence/<id>-<time>/` |
| Read | `node zg_read.mjs <id> [--rules]` | |
| Rules, quotes, what was not coded | by hand | `zg_spec.py` |
| Code | `zg_gold.py`, registered by `zg_strategies.py` into the 11-channel registry | |
| Quotes against the transcripts | `python -I zg_quotes.py` | 95 quotes, 0 problems |
| Look-ahead and fill checks | `python -I zg_checks.py 12 120` | `results/checks.json` (16 of 16 pass) |
| App data | `python -I zg_export.py` | `frontend/app/premium-strategies/goldYtData.ts`, `analyses/gold_channels_21_40.md` |
| Desk plumbing test | `premium-paper-service/test_yc5.py` | |

Every record is version v1: a changed rule or number is a new version, never an edit of v1. Rules are tagged E (stated
in the video), I (inferred) or A (our assumption so the rule can run); the app shows all three. Transcript text is
untrusted source material.

Not coded (17): order-flow and order-book methods (footprint, delta, DOM, tape), the CFTC report, paid closed indicators,
repeats of a coded strategy, and videos that teach no testable rule. Each is listed with its reason in `zg_spec.py`.
