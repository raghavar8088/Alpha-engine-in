# Pre-Live Paper Desk — Forensic Audit

**Incident:** Zero trades placed today (and, in fact, zero trades *ever*).
**Audit time:** 2026-07-15 19:35 IST (Wednesday — a normal trading day)
**Auditor:** automated DB + code forensic sweep
**Verdict:** **Two independent, compounding failures.** The desk cannot trade today because **the daemon process is dead**, and even when it *was* last alive it placed nothing because **it was authenticating with an expired token**. Both trace back to one design gap: the prelive-service was never given its own environment/credentials wiring, and nothing supervises it.

---

## TL;DR (the two root causes)

| # | Root cause | Effect | Severity |
|---|---|---|---|
| **RC-1** | **Daemon process is not running.** Last heartbeat `2026-07-13 22:34 IST` — **~45 hours stale**. No Windows service / Task Scheduler / nssm entry exists to restart it. | No process = no 09:15 session on Tue 14th or Wed 15th = **zero trades today**. | 🔴 Critical |
| **RC-2** | **Credentials misconfiguration.** `prelive-service/` has **no `.env`**, so `BROKER_ENCRYPTION_KEY` is unset. `credentials.py` therefore skips the (valid) encrypted DB token and **falls back to the plaintext `dhan_config.py` token — which expired `2026-07-13 09:06 IST`** (9 minutes *before* Monday's open). Every Dhan `spot`/`ltp` call 401s and returns `None` **silently**. | Even on Monday, when the daemon *was* up, no bars formed → no signals → **no trades ever recorded**. | 🔴 Critical |

A valid Dhan token **exists right now** — encrypted in Mongo `broker_credentials`, good until `2026-07-16 00:05 IST` — but the daemon has no way to read it.

---

## Evidence

### 1. The daemon is down (`prelive_state`)
```
heartbeat      : 2026-07-13T22:34:26 IST   ← 2,699 min (~45h) ago  [STALE]
status         : idle          session : None
universe_size  : 10            open_positions : 0
```
- Heartbeat is written every 120 s while idle / 60 s while running. A 45-hour gap means the process exited Monday night and never came back.
- `wmic`/`tasklist`: **no `python.exe` running `main.py`.**
- `schtasks`: **no scheduled task** for prelive/tradingai → nothing restarts it on crash or reboot. README says supervision is "optional" — it was never set up.

### 2. Zero trades have ever been written
```
prelive_trades          : 0 docs
prelive_positions       : 0 docs
prelive_daily_pnl       : 0 docs
prelive_equity          : 0 docs
prelive_strategy_scores : 0 docs
```
Not "no trades today" — **the desk has never opened a single paper position in its life.** That rules out a today-only glitch and points at the auth path.

### 3. The token the daemon actually uses is expired
```
PLAINTEXT dhan_config.py token : expires 2026-07-13 09:06 IST → EXPIRED (58.5h ago)
ENCRYPTED DB token             : expires 2026-07-16 00:05 IST → VALID (usable now)
prelive-service/.env           : DOES NOT EXIST
   → os.getenv("BROKER_ENCRYPTION_KEY") = None
   → credentials.py cannot decrypt the good token
   → falls back to the EXPIRED plaintext token
```
By contrast, **`market-data-service/` *does* have its own `.env`** — the same wiring the prelive desk is missing. This asymmetry is the whole bug.

### 4. Silent failure makes it invisible
`DhanFeed.spot()` does `r.json().get("data", {}).get(...)`. A 401 response body has no `data` key, so it returns `None` **without raising** — the `[warn] spot fetch` line never even prints. The engine just quietly builds no bars and logs nothing alarming. That is why this rotted unnoticed.

### 5. Corroborating: the live-bars pipeline also died
```
bars NIFTY 5m : latest ts = 2026-07-10 13:20 (Friday)   ← no Mon/Tue/Wed bars
```
Market-data collection stopped Friday mid-session — consistent with the same token expiry wave hitting the data feed too.

---

## What is NOT the problem (ruled out)

These were checked and are **healthy** — don't waste time here:

- ✅ **Qualified universe** — 10 live-tradable strategy slots loaded from sweep `a701f8a06e65` (14 qualified, 10 on 5m/15m/1h). Not empty.
- ✅ **Instruments / expiry** — 32,073 instruments, **4,438 NIFTY option contracts**, next weekly expiry `2026-07-21` resolves fine. `atm_contract()` would find strikes.
- ✅ **MongoDB** — up (PID 6036), all `prelive_*` collections reachable.
- ✅ **Paper capital** — ₹1 cr starting balance intact, available cash ₹1 cr.
- ✅ **Encrypted broker credential exists** in Mongo and decrypts cleanly with the backend key.
- ✅ **Strategy registry / bootstrap** — universe resolves to real registered strategies.

The machine is fully loaded and ready — it simply has no running engine and no working key.

---

## Timeline

```
2026-07-10 (Fri) 13:20  Live bars stop being written (feed token wave)
2026-07-13 09:06 (Mon)  dhan_config.py plaintext token EXPIRES (9 min before open)
2026-07-13 09:15 (Mon)  Daemon runs its session, but every Dhan call 401s →
                        no bars, no signals, no trades. Idle ticks continue.
2026-07-13 22:34 (Mon)  LAST heartbeat. Process exits (crash / terminal closed / reboot).
2026-07-14 (Tue)        No process, no session, no trades.
2026-07-15 (Wed, today) No process, no session, no trades.  ← reported incident
2026-07-16 00:05        The currently-valid encrypted token will ALSO expire (recurring).
```

---

## Fixes (prioritized)

### 🔧 FIX 1 — Give the daemon the valid token (unblocks trading immediately)
Create **`prelive-service/.env`** mirroring `market-data-service/.env`:
```ini
MONGO_URL=mongodb://localhost:27017
MONGO_DB_NAME=tradingai
BROKER_ENCRYPTION_KEY=<copy the exact value from backend/.env>
DHAN_CONFIG_DIR=D:/INDIAN MARKET
```
With the key set, `credentials.py` decrypts the valid Mongo token (good until 00:05 tonight) instead of the expired plaintext file.

### 🔧 FIX 2 — Restart the daemon and keep it alive
```
cd D:/INDIAN MARKET/TradingAI/prelive-service
python main.py            # verify it prints a fresh heartbeat + "universe: 10 slots"
```
Then supervise it so RC-1 can't recur — install as a service via **nssm** (or a Windows Task Scheduler task with "restart on failure" + "run at startup"). This is the single most important durable fix: without it, any crash/reboot silently kills the desk again.

### 🔧 FIX 3 — Refresh the Dhan token daily (the recurring driver)
The token rotates ~daily (valid only to 00:05 tonight). Automate rotation so **both** the encrypted DB credential and `dhan_config.py` are refreshed before 09:15 each morning (TOTP/PIN flow via `DhanLogin.generate_token`, per `dhan_api_reference.py`). A stale token is what started this whole incident.

### 🔧 FIX 4 — Make auth failure LOUD, not silent (prevents the next silent rot)
Harden `credentials.py` / `DhanFeed`:
- On startup, validate the token (decode `exp`, or call `/fundlimit`); if expired/near-expiry, **log a red error and refuse to enter the session** instead of 401ing all day.
- In `DhanFeed.spot()`/`ltp()`, check `r.status_code`; log a clear `[error] Dhan 401 — token expired/invalid` rather than swallowing it into a `None`.
- Add a heartbeat watchdog/alert: if `prelive_state.heartbeat` is >10 min stale during market hours, notify (the dashboard already has the field — surface it).

### 🔧 FIX 5 — Same treatment for `market-data-service`
Its bars stopped Friday 13:20 from the same token wave. Confirm its token path and fold it into the daily rotation (FIX 3) so live bars resume.

---

## Post-fix verification checklist

1. `prelive-service/.env` created with the real `BROKER_ENCRYPTION_KEY`.
2. `python main.py` logs: `paper account: … ₹1,00,00,000`, `qualified universe: 10 strategy slots`, and — crucially — a **spot price prints** (no `[warn] spot fetch`).
3. `prelive_state.heartbeat` updates within 2 min and `status` flips to `running` during market hours.
4. During the session, watch for `[OPEN] …` log lines; after a signal, `prelive_trades` count goes > 0.
5. Confirm the token-rotation job populates a fresh token before next open.
6. Confirm a supervisor (nssm/Task Scheduler) restarts `main.py` after a forced kill.

---

*Audit scripts: `scratchpad/prelive_audit.py`, `scratchpad/token_check.py`. Both re-runnable against `mongodb://localhost:27017/tradingai`.*
