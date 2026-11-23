# Premium Intraday Strategies (Premium Strategies → Premium Intraday Strategies)

An independent research and **paper-only** desk for NSE cash equities. Each trading morning it ranks sectors against
NIFTY, shortlists stocks, picks the strategy that fits the conditions, publishes a 09:45 trade plan, and enters a paper
trade only when that strategy's trigger fires on a closed five-minute bar inside its entry range.

| Part | Where |
|---|---|
| Decision logic: workflow, six strategies, sectors, fills, risk, costs | `pis/` (the replay and the live desk run this same code) |
| Live worker: scheduler, feed client, the desk's own store, observers | `pis/live/` |
| Container | `docker/Dockerfile.premium_intraday`, compose service `premium-intraday` |
| Backend (read-only feed + dashboard reads + the desk's switch) | `backend/app/api/routes/premium_intraday.py`, one guarded include in `main.py` |
| Page | `frontend/app/premium-strategies/intraday/` (sidebar child of Premium Strategies) |
| Research: register, pre-registration, replays, Top 25 | `backend/research/premium_intraday_2026_11/` |
| Tests | `tests/test_desk.py` (22 checks) |

## Isolation (the first requirement)
- **Own everything.** Own container (160 MB cap, CPU weight 128 vs the backend's 1024), own scheduler, own database
  `alpha_engine_premium_intraday` (box MongoDB, `FACTORY_MONGO_URL`), own paper books, risk limits, logs and ON/OFF.
- **Reads only.** Today's bars come from the backend's memory through `/api/premium-intraday/feed/bars` (incremental,
  ~48 KB a poll); history, official closes, the F&O list and NSE announcements from the bar volume mounted read-only.
  It never asks Intraday Stocks or Stock Momentum Trading to scan, refresh, backtest or approve anything.
- **No broker.** No broker client is installed, no `.env` or broker key is passed in; `tests/test_desk.py` fails if any
  broker or order call appears in the code.
- **Writes only its own database.** Every write goes through `pis/live/store.py`; the test records every database
  command and fails on any write elsewhere. The one foreign read (the tournament's decision ledger) is `find()` only.
- **The parent page loads nothing of it.** The route is its own code split; both links to it have prefetch off.
- **Main Control.** The desk is not in `module_registry` (a new entry would change a shared, live file); its own switch
  is on its page. The shared page header is not used there because its Main Control switch matches `/premium-strategies/*`.

## Schedule (IST, NSE trading days from `tradingai_shared.nse_calendar`)
08:40 PRE · 09:15 opening snapshot · every bar close + 20 s: 09:20, 09:30, 09:40 screens, 09:45 plan, then triggers,
entries and exits · no entries after 14:30 · square-off 15:05, retry 15:10, else a failed exit with an alert · 15:31 close.
OFF stops new scans and entries; open paper positions are still managed to their exits. A restart restores today's
positions and never enters anything in the past.

## Status of the strategies (22 Nov 2026)
None is Portfolio Eligible: 0 of 12 new strategy sides passed the frozen backtest criteria, 0 of the imported 25. The
shared portfolio therefore places no trade; every strategy is followed in its own Rs 10 lakh observation book.

## Removing the desk
1. Stop and remove the container: `docker-compose stop premium-intraday && docker-compose rm -f premium-intraday`.
2. Delete the compose block, `docker/Dockerfile.premium_intraday` and `premium-intraday-service/`.
3. Delete `backend/app/api/routes/premium_intraday.py` and its `try:` include in `backend/app/main.py`.
4. Delete `frontend/app/premium-strategies/intraday/`, the sidebar child entry and the tab link on the parent page.
5. Optionally drop the database `alpha_engine_premium_intraday`. Nothing else in the app refers to any of these.

## Tests
`python tests/test_desk.py` (needs the research copy of the bars at `D:/intraday_ai_data/intraday` and the panel built by
`backend/research/premium_intraday_2026_11/make_panel.py`). Covers: costs equal the app's fee card; replay equals live on
five days; restart with and without a gap; missing data; duplicate bars and duplicate signals; OFF with open positions;
failed square-off; writes confined to the desk's database; feed routes only; the backend route leaves the bar store's
memory unchanged; the Stock Momentum desk's decisions are identical with the desk running; CPU, memory and write counts.
