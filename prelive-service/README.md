# prelive-service — Pre-Live Paper Desk

Automatically trades the **top-20 audited NIFTY option-buying basket** every market day,
on **live Dhan data**, in a **paper account** (no real orders) but at **real option
premiums**. Modeled on antigravity's `pre_live` desk: consume real data, execute on
paper, keep a per-strategy scoreboard, so any future promotion to real money rests on a
forward, real-premium track record — the one thing a historical backtest cannot produce
(Dhan purges expired-contract price history).

## What it does, each trading day

1. Wakes at **09:15 IST** (Mon–Fri); sleeps otherwise.
2. Bootstraps each strategy's warmup history from the `bars` collection.
3. Every 15s: pulls the live NIFTY spot from Dhan, rolls it into 5m/15m/1h bars.
4. On each **finalized** bar, runs that timeframe's strategies. A BUY → buys the ATM
   **CE**; a SELL → buys the ATM **PE**, of the current weekly expiry, at its **live
   Dhan LTP**.
5. Re-prices open positions on their live option LTP each cycle; exits on the style's
   premium **stop / target**, or squares off at **15:15 IST**.
6. Writes trades, equity snapshots, the daily P&L, and updates the strategy leaderboard.

Everything is paper. No `place_order` is ever called.

## Run it

```
cd prelive-service
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt   # first time
copy .env.example .env         # set BROKER_ENCRYPTION_KEY or rely on dhan_config.py
python main.py                 # leave running; it self-manages market hours
```

A fresh **Dhan access token** must be connected each day (via `/settings/broker` or the
root `dhan_config.py`) — Dhan tokens expire ~24h. The daemon re-reads credentials every
day, so just refresh the token before 09:15.

To keep it running across reboots, wrap `python main.py` with NSSM (Windows service) or
Task Scheduler → "At log on".

## Collections (all `prelive_*`, segregated from real broker data)

`prelive_trades` · `prelive_positions` · `prelive_equity` · `prelive_daily_pnl` ·
`prelive_strategy_scores` (leaderboard) · `prelive_state` (heartbeat).

## Where to watch it

The **Pre-Live Desk** page in the app (sidebar → Trading → Pre-Live Desk): engine
heartbeat, today's P&L/ROI, open positions live-marked, the strategy leaderboard, daily
P&L history, and the paper-trade blotter. Backend routes: `GET /api/prelive/{status,
leaderboard,trades,equity,daily}`.

## The point

After a few weeks this desk answers the only question the backtests can't: do these 20
strategies still make money when filled at real, live option premiums with real timing?
That evidence — not the backtest — is what should decide whether any of them ever trades
real capital.
