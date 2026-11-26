# YouTube Live Streaming survey (26-27 Nov 2026)

Data behind the app's **YouTube Live Streaming** page (`frontend/app/youtube-live/`, sidebar: directly below
NIFTY 50 Option Scalping). Who streams crypto, gold and forex trading live on YouTube; how often and when (IST); how
big the audience is; which brokers each channel links; what it sells; and which streams show a real account.

Everything is read with `yt-dlp` as **metadata only** (stream lists, titles, descriptions, subscriber counts, each
stream's start time and length). No video or audio is downloaded. Nothing here trades.

## Files

| File | What it does | Output (git-ignored) |
|---|---|---|
| `survey.py` | Pass 1: who is live now (YouTube search, Live filter, 12 queries) + each listed channel's `/streams` tab (newest 60). `--recount <target>` re-counts a channel over its newest 200 streams. | `summary.json`, `recount.json`, `raw/` |
| `survey2.py` | Pass 2: finds channels by name (channel search), the most-viewed "live trading" channels (`ytsearch40`), and reads the metadata of the streams live in pass 1. | `summary2.json`, `raw/` |
| `survey3.py` | Pass 3: the newest stream's description of each big channel (brokers, Telegram, what it sells). | `summary3.json`, `raw/video_*.json` |
| `survey4.py` | Pass 4: exact start time (`release_timestamp`) and length of each channel's streams of about the last three weeks (newest 30). | `schedule.json` |
| `channels.py` | The hand-made part: which channels the page lists, in which table, a short note, whether the stream shows the trader's own account, and the 26 Nov Booming Bulls screen reading. | - |
| `export_live.py` | Writes `frontend/app/youtube-live/liveData.ts` from all of the above. | `liveData.ts` (committed) |

## Refresh

```
cd backend/research/youtube_live_2026_11
python -I survey.py                         # ~1.5 min
python -I survey.py --recount @CryptoBanterGroup   # any channel with n30 = 60 (pass 1's cap)
python -I survey2.py                        # ~3 min
python -I survey3.py                        # ~2 min
python -I survey4.py                        # ~4 min, ~730 streams
python -I export_live.py                    # prints one line per channel to check
```

Run it in the Indian evening (19:00-23:30 IST) if the "live now" snapshot should show the Indian streams; the
channel numbers do not depend on the time of day. A new channel goes into `channels.py` under its @handle or
channel id (find the id with survey2's channel search).

## How the numbers are made

- **Lives, 30 days / 7 days**: entries of the `/streams` tab whose approximate date ("Streamed 3 days ago") falls in
  the window. Pass 1 reads 60 at most; `--recount` reads 200.
- **Avg views**: average of the last 10 past streams' view counts (live plus replay).
- **Days live, last 14**: distinct IST dates with a stream start among the 14 days before the survey night.
  A broadcast shorter than 10 minutes is an aborted start and is ignored.
- **Schedule**: Every day (13-14 of 14), Every weekday (all 10 weekdays), Weekdays (8+ weekdays, at most one weekend
  day), Most days (60%+), Some days (25%+), Rarely, Not in 14 days.
- **Avg start / end (IST)**: start times are grouped on the 24-hour clock into daily slots (a gap of more than 60
  minutes starts a new slot; a slot with under a fifth of the streams is a one-off and is dropped). Each slot's start
  and end (start + length) are circular means, so a stream that crosses midnight averages correctly. The spread is
  the circular standard deviation.
- **Markets**: a market counts when at least a fifth of the channel's stream titles of the last 30 days name it.
- **Brokers linked**: domains in the newest stream description's links (`affs.click` = XM, `vigco.co` = Vantage).
  Short links (bit.ly) hide some.
- **Sells / links**: words in that description (VIP, course, signal, robot, indicator; "no courses" etc. removed
  first), plus Telegram / WhatsApp links.
- **In your study**: the channel id appears with analysed videos in
  `frontend/app/premium-strategies/ytChannelsData.ts` (origin/main).
- **Live now kinds**: TV news and 24/7 robot channels are listed in `channels.py`; other robot streams are found
  by their titles (24/7, signals, AI, algo, chart, indicator).
