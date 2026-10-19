# Application Reset & Upgrade Plan: protect the money, stop the hunt, test one idea at a time

**Date:** 2026-10-19 (Monday)

**Scope:**
- the whole app: backend, frontend, and the two Pre-Live daemons;
- both broker accounts;
- the money decision behind them.

**Status:** plan only. This document changes no code.

**Sources:**
- Every production number below was read on 2026-10-19 from the live API through the public proxy, using read-only GETs.
- Every market, tax and product fact was checked against a current source on the same day (§12).
- Where a source was third-party or unclear, the text says so.

> **In one paragraph.** More than 10,000 strategy variants have been tested here since February 2026. None survived an honest test: real costs, data the strategy never saw, and a correction for the number of tries. That is the normal result for retail short-term trading in India, not a coding failure. So the app changes its job:
> 1. Real money is locked in code.
> 2. The 26 modules (plus 2 daemons) that only repeat the same experiment are switched off.
> 3. The forward tests that already have frozen rules run on to their decision dates.
> 4. Your money goes into a NIFTY 50 SIP plus a little gold, tracked by a new Wealth page.
> 5. Research continues only as one pre-registered question at a time, each with a written decision rule and a date. First comes a monthly momentum study, then defined-risk option selling.
>
> **Terms used throughout:**
> - **Pre-registered:** the rule, the data, the costs and the pass/fail test are written down and frozen *before* any result exists.
> - **Defined-risk:** the worst possible loss is known and capped when the trade is opened.

---

## 0. Executive summary

### 0.1 What the evidence says

1. **Nothing passed, everywhere.** No strategy cleared an honest gate. That covers:
   - intraday stocks;
   - index intraday (0 of 1,464 trials);
   - NIFTY option scalping, buying and selling;
   - stock options;
   - MCX commodities (0 of 81);
   - gold (157 variants);
   - BANKNIFTY;
   - the crypto app (0 of 400).

   Several desks look profitable only because they charge no costs (Zero-Hero) or because a leaderboard picked lucky rows after the fact. §1.1 has the table.
2. **This is the base rate.** In SEBI's FY26 study:
   - 87.7% of individual F&O traders lost money;
   - 82.1% lost even **before** costs;
   - the loss share rises to more than 95% among people who kept trading four or more years in a row.

   Experience does not fix it (§1.2).
3. **Real money is mostly, but not entirely, locked.** Four order paths need a CONFIRMED forward verdict, and none exists. One more (the Live Engine's LIVE mode) is unreachable only because a deploy flag is off. **The manual Orders ticket can still place a real Dhan order today**: the Dhan session is valid, and unticking "paper" is the only step (§1.3).
4. **The box is overloaded by desks that cannot teach anything new.** All 51 modules are ON. After 26 hours of uptime the backend held 770 MB of its 800 MB limit, with 52 MB in swap. Angel's candle endpoint refused 1,731 calls in 52 hours (§1.5).
5. **Eight forward tests are running with frozen rules** and should finish. They include Gold H1, the MCX trend book HC1, the two option straddle tests H1/H1b and the two Selected ORB strategies. Their dates run from November 2026 to October 2028 (§1.4).

### 0.2 The plan

| Phase | What | When | Result you can check |
|---|---|---|---|
| **0** | Real-money lockdown | 19–23 Oct 2026 | One master lock in front of all six order paths, failing closed. LIVE mode retired. Status card on Main Control. |
| **1** | Switch off the desks; keep the forward tests | 20–30 Oct 2026 | 26 modules + 2 daemons off. Forward tests, data recorders and tools kept. Memory and Angel load measured before and after. |
| **2** | The money decision + Wealth module | 26 Oct – 15 Nov 2026 | SIP plan, ledger, XIRR, allocation drift, rebalance and tax assistant. No order placement. |
| **3** | Evidence Registry | 2 – 20 Nov 2026 | One page listing every forward test: its rule, progress, next decision date and real-money eligibility. |
| **4** | Monthly momentum study (pre-registered) | 9 Nov – 31 Dec 2026 | A yes/no answer: does a monthly NIFTY 500 momentum portfolio beat a momentum index fund after costs **and tax**? |
| **5** | Defined-risk NIFTY option selling | data recorder now. Study Jan–Feb 2027. Paper and pilot dates in §7.10. | A yes/no answer on put spreads and iron condors after STT at 0.15% and real bid/ask. |
| **6** | Governance | from today | Ten rules, at most one idea per stage, a decision calendar, a stop rule. The rules also go into a project `CLAUDE.md` so every future session reads them. |

### 0.3 Defaults I will apply unless you say otherwise

1. **The manual Orders ticket is locked too.** A real order needs a timed unlock (24 hours at most) plus a typed confirmation.
2. **Allocation: 85% NIFTY 50, 15% gold.**
   - SIP into a direct-plan index fund, or NIFTYBEES if you prefer an ETF.
   - Rebalance once a year, and only when drift exceeds 5 percentage points.
   - Rebalance first with new SIP money, not sales.
3. **Forward tests run to their dates.** HC3 decides on 31 Dec 2026, so the MCX pattern desk stays on until then and goes off on 1 Jan 2027. HC1 gets its own switch first, so it keeps running.
4. **Freeze the strategy-building work left uncommitted in the working tree.** That includes:
   - the commodity options lab and the commodity mini lab;
   - the stock lab;
   - the new five-strategy intraday desk.

   Nothing new gets finished. (§1.6)
5. **Phase 5 starts only its data recorder now.** The study waits for the Phase 4 decision.
6. **Nothing destructive** (no collection drops, no history deletion) without your explicit OK.

### 0.4 Do not

- Add strategies, timeframes, books, copies of books, or desks.
- Re-tune a rule on the same history.
- Arm anything for real money because a paper number looks good.
- Read the `ANTI-*` leaderboard rows as results: they are computed at read time and never traded.
- Trust any paper P&L that charges no costs.
- Sell naked options.
- Buy options within a day of expiry (H2 confirmed that this loses more).
- Copy tips from Telegram or YouTube.

---

## 1. Where things stand on 2026-10-19

### 1.1 What was tested, and what it showed

| Area | Tested | Honest result | Status |
|---|---|---|---|
| Intraday stocks (tournament, Patterns, books) | 52 tournament strategies, 548 Patterns strategies, many books | 2-year walk-forward **−₹11.51 crore**. Live paper: tournament books −₹28.2 lakh, Patterns −₹33.3 lakh. Real-slippage test H1 is **NO-GO** for all three best candidates: median cost 2.6–2.8 bp against a break-even of 1.3–1.8 bp. | closed |
| Index intraday | 1,464 registered trials | **0 validated**. Holdout never opened. | closed |
| NIFTY option scalping | 400 strategies | Gross +₹1.38 lakh, charges ₹25.3 lakh, **net −₹24 lakh** | closed |
| NIFTY option buying | 167-strategy tournament, H1–H3 | **−₹27.9 lakh**. H2 CONFIRMED: buying 0–1 day from expiry lost ₹310 a trade, against +₹75 further out (t −2.36). | H1/H1b incubating |
| BANKNIFTY option buying | Tier A/B research, 10-strategy desk | 0 qualified. The protocol was changed after results were seen. | closed |
| NIFTY option selling | 393 strategies | +₹7.68 lakh on ₹39.3 crore (0.2%), **with no charges**. The 16-strategy book that does charge: gross −₹16,095, charges ₹21,585, **net −₹37,680 (−3.8%)**. | not pre-registered |
| Stock options (buy + sell) | 220 + 312 strategies | ₹10 lakh book **−34.8%** after ₹56k charges. HS1 and HS4 rejected on real NSE prices. | HS2/HS3 registered |
| MCX commodities | 311 patterns, 22-year Lab | Paper **−₹3.08 crore**. Lab gate 0 of 81. HC2 rejected. HC3 fade t −5.41. | HC1/HC3/HC4 running |
| Gold | 157 variants | 0 proven better than simply holding gold | H1 + Gold Lab collecting |
| Strategy Factory / Trending / Momentum desk | 546 / 678 / 37 | **0 trades**: no setup ever passed their own gates | closed |
| Live Engine paper | 21 strategies | **−20.2%** | closed |
| Zero-Hero | 50 strategies | +₹4.86 lakh realised. But it fills at LTP, charges nothing and wins 12% of trades, so this is **not evidence**. | closed |
| Crypto (separate app) | 400 + 17 + 66 | 0 of 400. 17 of 17 and 66 of 66 lost after fees. | closed |
| **Real money** (Angel, Aug 2026) | 78 orders, 14 strategies | **−₹2,507.52**. 61 trades are still on estimated charges until the contract notes are imported. | disarmed |

### 1.2 This is the base rate, not bad luck

| Study (SEBI) | Finding |
|---|---|
| FY26 (published Aug–Sep 2026) | 87.7% of individual F&O traders lost money. Aggregate loss ≈ ₹91,685 crore; average ≈ ₹1.17 lakh. Options ≈ 92% of losses. **82.1% lost before costs.** The loss share rises from about 91% (first-year traders) to more than 95% (four or more consecutive years). |
| FY25 (July 2025) | About 91% lost. Net losses ₹1,05,603 crore, later revised to ₹1,11,788 crore. |
| FY22–FY24 (23 Sep 2024) | 93% of more than 1 crore traders lost about ₹2 lakh each, more than ₹1.8 lakh crore in total. About 7.2% made any profit; about 1% made more than ₹1 lakh after costs. More than 75% of loss-makers kept trading. |
| Intraday cash, FY23 (July 2024) | About 7 in 10 individual intraday traders lost. Loss-makers paid a further 57% of their losses in trading costs. |

The app reproduced these numbers on paper, which shows it measures honestly. It does not show a missing trick.

### 1.3 Every path to real money

| # | Path | Broker | What guards it today | State on 19 Oct | Phase 0 action |
|---|---|---|---|---|---|
| 1 | Live Trading desk: `live_trading_engine.py:573` | Angel | Arming needs a registry CONFIRMED verdict, plus the kill switch and the module switch | **DISARMED** ("manual disarm"). 0 of 14 strategies registered. Angel cash ₹5,272.79. | master lock; module OFF |
| 2 | Index option executor (H1/H1b): `live_options_executor.py:179` | Angel | CONFIRMED verdict + `LIVE_OPTIONS_ENABLED=1` + arm + `LIVE_OPTIONS_DRY_RUN=0` | disarmed, env off, dry-run | master lock |
| 3 | MCX executor (HC1): `mcx_live_executor.py:235` | Angel | Quarantine + CONFIRMED + `MCX_LIVE_ENABLED` + a real 1-lot quantity proof + arm | disarmed, quarantined | master lock |
| 4 | Stock option executor (HS2): `stock_options_executor.py:154` | Angel | CONFIRMED + env + arm, per its docstring | **uncommitted file**; no route in production (404) | master lock when committed |
| 5 | Live Engine LIVE mode: `live_engine.py:67-93` → `strategy_runner.py:71` | Dhan | The router is mounted only if `ENABLE_LIVE_TRADING=true` (`main.py:1061`; default false, `core/config.py:32`). After that the only checks are `confirm_live` and the kill switch. **No evidence gate**, and real fills are never reconciled. | not mounted (`/api/live/runs` → 404) | retire LIVE mode |
| 6 | Manual order ticket: `POST /api/broker/orders`, `broker.py:200` | Dhan | Risk kill switch only. The page's "paper" box is ticked by default (`orders/page.tsx:19`). | **REACHABLE.** The Dhan session is valid: available −₹52.33, collateral ₹3,591. | master lock + typed confirmation |

**Paper only (no broker order anywhere):**
- Zero-Hero;
- F&O Positions (`fno_positions.place_order`) and manual positions;
- Paper Broker;
- Commodity Positions;
- every Pre-Live desk and every book.

### 1.4 Forward tests that are already running

| ID | Rule (short) | Since | Progress on 16–19 Oct | Decision rule (frozen) | Earliest decision |
|---|---|---|---|---|---|
| **Gold H1** (fp `9390f848d21dcd00`) | 9 breakout templates, 4h, Delta XAUTUSD, paper | 2026-10-11 | Week 1 of 104. 26 trades, mean −23.1 bp, 4 open. | ≥100 trades. Futility at week 52 if the mean is ≤ 0 or the weekly t is ≤ −1. Verdict at week 104. | futility ≈ 10 Oct 2027; verdict ≈ Oct 2028 |
| **Gold Lab** (fp `0b33f7dce3cc399a`) | 7 Tier-B daily strategies, paper on Delta | 2026-10-11 | collecting | record only (none was proven better than holding gold) | none |
| **HC1** | 5-commodity 12-month trend, mini lots, ₹50 lakh paper | 2026-10-05 | 1 month, −0.11% (always-long −0.24%) | Confirm: ≥24 months, t ≥ 2, beats always-long. Fail: from 12 months, t ≤ −1 or drawdown ≥ 40%. | fail check ≈ Oct 2027; confirm ≈ Oct 2028 |
| **HC3** | Fade intraday breakouts (measured, never traded) | 2026-10-05 | 2,441 trades, −10.97 bp, **t −5.41** | Pass needs t ≥ 3.0 on 31 Dec 2026 | **31 Dec 2026** (it will fail) |
| **HC4** | MCX carry (curve slope) | — | 10 of 126 curve days | then 12 months, t ≥ 2 | data ready ≈ Apr 2027 |
| **H1** | Vol-timed intraday straddle (buy) | 2026-10-02 | 8 trades, t 0.22 | ≥30 trades. Confirm at t ≥ 2. Fail at t ≤ −2, or if negative after 60 trades. | from ≈ late Nov 2026 |
| **H1b** | Same signal, held overnight | 2026-10-02 | 7 trades, t 0.43 | same as H1 | from ≈ late Nov 2026 |
| **Selected ORB 15** | Top-5 expected-move ORB, 15 min | 2026-10-02 | 9 trades, t 0.32 | ≥40 trades. Confirm: t ≥ 2 and z ≥ −1. Fail: z ≤ −2. Early fail at 20 trades if z ≤ −3. | ≈ Nov–Dec 2026 |
| **Selected ORB 30** | Same, 30 min | 2026-10-02 | 18 trades, −₹99,157, t −1.14, z −1.41 | same as ORB 15 | ≈ Nov 2026 |
| HS2 | Pre-results stock straddle | 2026-10-08 | **not collecting**: the book (`stock_hs2_book.py`, uncommitted) has no scheduler in the repo | ≥100 trades and t ≥ 2. Reject after 60 trades if the mean is ≤ 0. | blocked |
| HS3 | Trend signals as stock futures (measured) | 2026-10-08 | unverified in production | day-clustered t ≥ 2 on 29 Jan 2027 | 29 Jan 2027 |

Already decided:
- H2 CONFIRMED (near-expiry buying is worse);
- H3 rejected on history;
- the intraday H1 slippage test is NO-GO (100% sampled);
- HS1, HS4 and HC2 rejected.

### 1.5 Load on the box

- **Main Control:** 51 of 51 modules ON.
- **Backend memory:**
  - 769.6 MB of 800 MB, 51.9 MB in swap, 30 MB headroom, 26.4 hours after the last restart. That is one trading session.
  - On 18 Oct, after 52 hours, it was 702 MB with 107 MB of swap.
  - The 1.9 GB box also runs Mongo, Qdrant, MinIO, Redis, the frontend container and two daemons.
- **Angel:**
  - The candle endpoint refused 1,731 calls in 52 hours (16–18 Oct).
  - The shared intraday loop ran every 10–35 minutes instead of every 3.
- **Daemons outside Main Control:**
  - The `prelive` (buying tournament) and `prelive-selling` containers never read a switch.
  - Both heartbeated at 15:06 IST today.
  - Turning them "off" in Main Control blocks only their API.
- **Atlas M0** has a 512 MB quota. It was hit once already, and a startup crash followed. New research data must go to files, not Atlas.

### 1.6 Uncommitted work in the working tree

On 19 Oct the local tree holds **117 modified and 38 untracked files** from other sessions. They include:
- new strategy-building work: commodity options lab and backtest, commodity mini lab, replay and validation, MCX execution ledger, stock lab, release scripts;
- `stock_hypotheses.py`, `stock_hs2_book.py` and `stock_options_executor.py`. The last one is a real-money path.

Some of this may already be live on the box, because other sessions deploy by copying files.

Consequences:
- Phase 0 must lock the **deployed** versions of these files.
- Step 2 ("stop building") applies to them.
- Phase 1 touches files that carry another author's edits: `module_registry.py`, `commodity_scheduler.py`, `main.py`, `Sidebar.tsx`, `orders/page.tsx`, `main-control/page.tsx`, `mcx_live_executor.py` and `prelive-service/main_selling.py`. For these, commit only our own hunks and wire them last (Appendix C).

### 1.7 Corrections to my previous answer

1. **"Let NIFTY selling finish its forward test" was wrong.** The selling desk was never pre-registered. Its daemon charges no costs. Its ANTI rows never traded. About 65% of its trades are ₹0 expiry-day churn. The book that charges real costs is −3.8%. So it is a paper desk like the others and goes off in Phase 1. Phase 5 replaces it with a clean, pre-registered test.
2. **The Live Engine's LIVE-mode gap is real but latent.** Production does not mount that router. It is still closed in Phase 0, because one environment flag would open it.
3. **The manual Orders ticket is a live real-money path today.** It was missing from my earlier list.
4. **HS2 is "INCUBATING" but collects nothing.** Its book is not wired to any loop in the repo.

---

## 2. Phase 0: real-money lockdown (19–23 Oct 2026)

**Goal:** no real order can be sent from this app unless all of the following hold:
- a person deliberately unlocks it, for a stated time window;
- it goes through a named path;
- the order is under a size cap;
- and, for a strategy, the strategy has evidence in the registry.

Closing an existing real position is **never** blocked.

### P0.1 · One master lock in front of every real order (Critical)

**Problem.**
- There are six separate paths, and each has its own gate, written by different sessions in five files.
- Two of the paths (5 and 6) have no evidence gate at all.
- Any later edit to any one gate re-opens real money without anyone noticing.

**Solution.** A new `backend/app/services/real_money_lock.py`, called first by every path:

```python
async def require(path: str, *, opening: bool = True, strategy: str | None = None,
                  notional: float | None = None) -> None:
    """Raise RealMoneyLocked unless this real order is explicitly allowed.
    Exits (opening=False) are never blocked — a lock must not trap open risk.
    Any error while checking means LOCKED (fail closed — the opposite of Main Control,
    which fails open, on purpose: a switch that cannot be read must not stop the desks,
    and a money lock that cannot be read must not let money out)."""
```

An opening order is allowed only when **all** of these hold:
1. The server env has `REAL_MONEY_UNLOCK=1`. Nothing sets it today.
2. The Mongo doc `real_money_lock/{_id:"lock"}` has `unlocked_until` in the future.
3. The doc's `paths` list contains this path.
4. `notional ≤ max_notional`.
5. For strategy paths, the evidence registry (Phase 3) says the strategy is eligible. Until Phase 3 exists, each path's own registry check stays.

Every call writes one row to `real_money_audit`, allowed or refused, with path, strategy, notional, reasons and time. Rows expire through a TTL index after 400 days.

**API**, on the ungated `/api/main-control` prefix so it works with everything off:

| Endpoint | What it does |
|---|---|
| `GET /api/main-control/real-money` | Lock state plus all six paths (P0.5) |
| `POST /api/main-control/real-money/unlock` | Body: `{paths, hours ≤ 24, max_notional, reason, confirm: "I ACCEPT REAL LOSSES"}`. Writes the doc. It re-locks itself when the time runs out. |
| `POST /api/main-control/real-money/lock` | Always allowed; clears the doc |

**Files:**
- new `real_money_lock.py`;
- call sites: `live_trading_engine.py:573`, `live_options_executor.py:179`, `mcx_live_executor.py:235` (has another author's uncommitted edits), `stock_options_executor.py:154` (untracked; lock it when it is committed), `strategy_runner.LiveExecutor.execute` at line 71, and `broker.py:200`;
- routes in `api/routes/main_control.py`;
- `core/db.py`, for two collections.

**Steps:**
1. Write the lock and its tests offline.
2. Wire the call sites one file at a time, leaving the files with other authors' edits for last.
3. Deploy.
4. Prove that every path refuses (P0.8).

**Edge cases:**
- Mongo is unreachable: locked.
- The clocks differ: use server UTC only.
- The exit of an existing real position: allowed and audited.
- Several paths are unlocked at once: each must be listed by name.
- An unlock outlives its reason: the expiry is at most 24 hours.

**Tests:** `backend/tests/real_money/verify_lockdown.py`, offline, with `MONGO_URL` pointing at `127.0.0.1:1` (never the real cluster):
- locked by default;
- env only (no doc) → locked;
- doc only (no env) → locked;
- expired unlock → locked;
- path not listed → locked;
- notional over the cap → locked;
- Mongo down → locked;
- exit while locked → allowed;
- each of the six call sites with a recording fake broker → **0 broker calls** while locked;
- an audit row is written for every decision.

**Acceptance:**
- the tests pass;
- `GET /api/main-control/real-money` shows LOCKED with six paths;
- in production, a manual ticket with "paper" unticked returns **423 Real money locked**, and Dhan's order book is unchanged.

### P0.2 · Retire the Live Engine's LIVE mode (High)

**Problem.** LIVE needs nothing but `confirm_live`. It sends Dhan market orders and never reconciles the fills; the code itself says "isn't reconciled back into this record in v1". It is safe today only because `ENABLE_LIVE_TRADING` is unset.

**Solution:**
- `live_engine.start_run` refuses `ExecutionMode.LIVE` with the message "retired 2026-10 — real orders only through registry-gated executors".
- Remove `LiveExecutor` from `strategy_runner.py`.
- Drop the LIVE choice from `frontend/app/live/page.tsx`.
- PAPER and REPLAY are unchanged.

**Files:** `live_engine.py`, `strategy_runner.py`, `schemas/live.py` (keep `confirm_live` as an ignored field for old clients), `frontend/app/live/page.tsx`, `frontend/lib/api.ts` (has another author's edits).

**Tests:**
- a LIVE request raises an error;
- a PAPER run still produces fills with costs;
- a grep shows no `place_order` in `strategy_runner.py`.

**Acceptance:** the only Dhan `place_order` call left in the repo is the locked manual-ticket branch.

### P0.3 · Manual Orders ticket: lock plus typed confirmation (High)

**Problem.** Unticking "paper" places a real Dhan order with no confirmation step, and the Dhan session is valid.

**Solution:**
- **Backend.** The real branch of `broker.place_order` calls `require("manual_ticket", notional=qty × price)`. `PlaceOrderRequest` (`schemas/broker.py:24`) gains `confirm_text`, which must equal `REAL ORDER`.
- **Frontend.** When "paper" is unticked, show a red banner, the lock state and a text box. Submit stays disabled while the lock is on.

**Tests:**
- a paper order is unchanged;
- a real order is refused while locked;
- a real order is refused without the confirmation text;
- a real order is allowed only with the lock open, the path listed and the text given (fake client).

**Acceptance:** as in P0.1, on production.

### P0.4 · Switch Live Trading off and prove the environment (High)

1. Turn Main Control `live_trading` OFF. This blocks the arming API and the loop.
2. On the box, run:

   ```bash
   sudo docker inspect alpha-engine-backend-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E 'LIVE_OPTIONS|MCX_LIVE|STOCK_OPTIONS|ENABLE_LIVE_TRADING|DRY_RUN|REAL_MONEY'
   ```

   - Expected: nothing is set to an enabling value.
   - Check `~/alpha-engine/.env` and `docker-compose.yml` the same way.
3. Record the output in the Phase 0 report.

### P0.5 · Real-money status card (Medium)

`GET /api/main-control/real-money` returns:
- the lock state;
- for each of the six paths: armed, env flags, dry-run, the last real order time (from the audit) and the gate summary;
- broker cash for Angel and Dhan, cached for 10 minutes, because every read is a broker call.

On the frontend:
- a card at the top of `/main-control`;
- a red app-wide banner whenever anything is unlocked.

### P0.6 · Close the real-money ledger (Medium; you plus a script)

- Import Angel's contract notes for the 61 estimated trades with `scripts/live_trading_contract_notes.py`. After that the August loss of −₹2,507.52 is exact.
- Settle Dhan's −₹52.33 debit.
- Decide whether the idle ₹5,272.79 at Angel stays there or moves to the SIP.

### P0.7 · The crypto app is a separate deployment (Medium; you)

Check every exchange API key the antigravity app uses. Nothing there is CONFIRMED, so any key with **trade** permission should be cut to read-only in Delta's API settings. Paper desks only need market data.

### P0.8 · Phase 0 report

Write `REAL_MONEY_LOCKDOWN_2026_10.md` with:
- the path inventory (§1.3);
- the env proof (P0.4);
- the test output;
- the production refusal proof (P0.1);
- the md5 sums of the deployed real-money files against the commit.

---

## 3. Phase 1: switch off the desks, keep the forward tests (20–30 Oct 2026)

**Why:** a desk with no frozen rule and no decision date cannot change any decision. It only:
- spends memory, Angel calls and Atlas quota;
- produces numbers that invite the next round of picking.

**How OFF works:**
- Every switch below is reversible.
- OFF freezes a desk's open **paper** positions at their last mark. They are no longer managed.
- Reads still answer, so every page keeps showing its history (`desk_switches.py`).

### 3.1 Keep ON (22 modules + 2 new keys)

| Kind | Modules | Why |
|---|---|---|
| Forward tests | `gold_desk` (Gold H1 + Gold Lab); **new** `commodity_trend_book` (HC1); **new** `intraday_registered` (the Selected ORB pair, until its verdicts) | Frozen rules with dates |
| Tools you use | `market_data`, `chart`, `watchlist`, `screener`, `fundamentals` (lookups only), `instrument_search`, `desk_history`, `portfolio`, `broker_account` (reads; real orders locked by Phase 0), `paper_broker`, `fno_positions` (manual), `commodity_positions` (manual), `stocks_range`, `bullish_stocks`, `options`, `risk`, `ai_research` | Screens, charts and manual paper. No standing strategy. |
| Research tools | `backtesting`, `strategies`, `stock_research`, `long_horizon` (idle; becomes the Phase 4 paper engine — its catalogue sweep must **not** be run) | Needed by Phases 4–5 |

**Loops that are not switches and stay ON:**

| Loop | What it serves |
|---|---|
| `option_chain_recorder` | real NIFTY bid/ask every minute; Phase 5 needs it |
| `vol_desk` | H1/H1b |
| `mcx_curve_recorder` | HC4 |
| `intraday_data_scheduler` | stock bars and the nightly NSE archives (`nse_archives.catch_up`); NSE serves only a rolling window |
| the 15:12 intraday close-out | safety |
| memory snapshots | Phase 1 measurement |

### 3.2 Switch OFF now (26 modules) and later (3)

**OFF now:**

| Group | Modules |
|---|---|
| Trading | `ath_trading`, `swing_trading`, `live_trading`, `momentum_engine`, `trending_stocks`, `nifty_scalp`, `commodity_options`, `commodity_prelive`, `natgas_book`, `index_intraday` |
| Strategy Lab | `prelive`, `prelive_selling`, `banknifty_desk`, `selling_books`, `stock_books`, `intraday_focus`, `live_intraday`, `pattern`, `pattern_books`, `live_paper`, `strategy_factory`, `zero_hero` |
| System | `telegram_signals`, `morning_momentum`, `fno_auto_roll`, `fno_stock_roll` |

`fno_auto_roll` is a **naked** short straddle rolled every day.

**Also off now:**
- the `prelive` and `prelive-selling` **containers** (P1.3);
- `FUNDAMENTAL_BOOKS_ENABLED=0` at the next container recreate;
- the Telegram signal daemon, wherever it runs.

**OFF later:**

| Module | When |
|---|---|
| `commodity` | 1 Jan 2027, after HC3's 31 Dec decision |
| `intraday_lab` | right after the P1.2 deploy |
| `intraday_registered` | when both ORB verdicts are in (≈ Nov–Dec 2026) |
| `stock_desk` | 29 Jan 2027 if HS3 proves live on the box; otherwise now (P1.4) |

Appendix A lists every module with its reason.

### 3.3 Work items

#### P1.1 · Give HC1 its own switch (Critical; before `commodity` ever goes off)

- **Problem.** `commodity_scheduler.py:131-133` lets HC1 enter only when `is_on("commodity")` is true. Switching the 311-pattern desk off would therefore silently stop a forward test.
- **Solution:**
  - Add `_m("commodity_trend_book", "Commodity Trend Book (HC1 forward test)", "Trading", "/commodity")` to `module_registry.py`. It owns no API prefix; its summary is a read.
  - In `commodity_scheduler.py`, use `allow = await is_on("commodity_trend_book")`.
- **Files:** `module_registry.py`, `commodity_scheduler.py`. Both carry another author's edits: commit only this hunk.
- **Test:** with `commodity` OFF and `commodity_trend_book` ON, `cycle(allow_entries=True)` runs; swap the two and it runs with `False`.
- **Acceptance:** HC1 rebalances on Mon 2 Nov 2026 (the first MCX trading day of the month, from 11:00). From 1 Jan 2027 it keeps rebalancing with `commodity` OFF.

#### P1.2 · Run only the pre-registered ORB pair (High)

- **Problem.**
  - The v2 engine uses the single switch key `intraday_lab` (`intraday_v2_engine.py:69`) for the whole tournament, for the Selected ORB pair (`iv2_orb_sel15`, `iv2_orb_sel30`), and for the H1 slippage sampler, which has finished.
  - The tournament is one of the heaviest Angel users.
- **Solution:**
  - Add a key `intraday_registered`.
  - In `_open()` (`intraday_v2_engine.py:378`), the entry check uses `intraday_registered` for strategies in `intraday_v2_registry.PREREGISTERED` and `intraday_lab` for all others.
  - Turn the H1 slippage sampling off.
  - Exits are always managed.
- **Fallback, if the edit is not wanted:** keep `intraday_lab` ON until the verdicts, and add an env allowlist `INTRADAY_V2_ONLY=iv2_orb_sel15,iv2_orb_sel30`.
- **Test:** with `intraday_lab` OFF and `intraday_registered` ON, the pair opens positions and a tournament strategy cannot.
- **Acceptance:** on the first session after the deploy, only the pair opens positions, and Angel candle calls by tournament callers fall to about 0 (P1.6).

#### P1.3 · Stop the two Pre-Live daemons (High)

- **Problem.** `prelive-service/main.py` and `main_selling.py` never read a switch. They run as the containers `prelive` (`docker-compose.yml:107`, 200 MB cap) and `prelive-selling` (`:130`, profile `selling`). The local Windows tasks `TradingAI-PreLiveDesk` and `TradingAI-PreLiveWatchdog` are already Disabled.
- **Solution:**
  1. Archive first (P1.5).
  2. On the box, run `sudo docker-compose stop prelive` and `sudo docker-compose --profile selling stop prelive-selling`. Both can be reversed with `start`.
  3. Optional: a switch check in both daemons, so that a later restart honours Main Control. Each cycle reads `desk_switches/{_id:"prelive"|"prelive_selling"}` and, when it says `enabled:false`, stops new entries but still manages exits.
- **Note:** the vol desk (H1/H1b) and the chain recorder run **inside the backend** (`main.py:440-466`), not in these daemons, so they are unaffected.
- **Acceptance:** both heartbeats stop and `docker stats` no longer lists them.

#### P1.4 · HC3 and HS3: keep their protocols (Decision)

- **HC3:** keep `commodity` ON until 31 Dec 2026. Its outcome is not in doubt (t −5.41 against a pass bar of +3.0), but cutting a pre-registered test short is exactly the habit this plan ends. If memory forces it off earlier, log a **protocol deviation** with the date and reason in the Evidence Registry.
- **HS3:** first check on the box whether `stock_hypotheses` is deployed and whether its signal log is being written. If it is, keep `stock_desk` until 29 Jan 2027 and turn off only its books now. If it is not, turn `stock_desk` off now and record HS3 as "never started".

#### P1.5 · Archive every desk before switching it off (High)

- **Solution:** a script `backend/research/reset_2026_10/archive_desks.py`.
  - It makes read-only GETs of every desk summary and leaderboard through the proxy.
  - It writes `research-reports/desk_archive_2026_10/<module>.json`.
  - It writes `DESK_ARCHIVE_2026_10.md` with one row per desk: start, switch-off date, capital, trades, gross, charges, net and %, open positions frozen and their unrealised mark, whether costs were charged, whether the desk was pre-registered, and its one-line lesson.
- The archive lives in git, not in Atlas.
- **Acceptance:** a row for every switched-off module and both daemons, and the numbers match the live summaries at switch-off time.

#### P1.6 · Measure Angel usage per caller (Medium)

- `GET /api/diagnostics/angel` returns `describe()` for `candle_pacer`, `quote_pacer` and `margin_pacer` (`angel_client.py:148-151`): calls, refusals, wait time, and calls and refusals by caller.
- The same block is added to the 15:45 and 22:00 memory snapshots (`diagnostics.take_snapshot`).
- **Acceptance:** snapshots before and after the switch-off show calls by caller.

#### P1.7 · Sidebar: an "Archived (off)" group (Low)

- `set_module` and `set_many` also store `changed_at`.
- `frontend/components/Sidebar.tsx` (has another author's edits) folds OFF modules into a collapsed "Archived" group.
- An OFF page shows "OFF since <date> — numbers frozen".

#### P1.8 · Do not even load what is off (Low; only if the measurements justify it)

- The ~225 MB boot floor is imported code, and `main.py` starts every desk's loop whether it is switched on or not.
- An env `DISABLED_LOOPS=nifty_scalp,pattern,zero_hero,...` would be checked in each startup hook **before** the import.
- **Decide after P1.6 and the snapshots:** a lower floor is worth it only if headroom is still short.

#### P1.9 · Atlas housekeeping (optional; needs your explicit OK)

- After the archive is committed, list the largest collections (`collStats`).
- Then propose an export plus drop for dead paper collections and for the `*_invalid_pre_274e704` collections.
- **Never without your written OK.** This is irreversible, and `client/.env.local` points at production.

### 3.4 Runbook (in this order)

| Day | Step | Done when |
|---|---|---|
| Mon 19 – Tue 20 Oct | Let the 15:45 and 22:00 snapshots capture at least 2 sessions of the "before" state. Run P1.5. Commit the archive. | snapshots exist; archive committed |
| Wed 21 – Thu 22 Oct | Deploy P1.1, P1.2, P1.6 together with Phase 0 (Appendix C). Check that startup completes and that every forward test still writes. | all checks green |
| Fri 23 Oct, after 15:40 | One `POST /api/main-control/bulk` with `{"modules": {<26 keys>: false, "intraday_lab": false}}`. Stop both daemons. | Main Control shows the keep set only |
| Next container recreate | `FUNDAMENTAL_BOOKS_ENABLED=0`. Recreate (not just restart) so the env applies; check with `docker inspect`. | env verified |
| 26 – 30 Oct | Measure for 5 sessions | §3.5 met |

### 3.5 Acceptance

**Memory:**
- the 15:45 snapshot RSS is at least **150 MB lower** than the median of the 19–20 Oct snapshots;
- swap is 0 at both daily snapshots for 5 sessions.

**Angel:**
- fewer than 10 candle refusals per session (the baseline was about 800 a day);
- the shared intraday loop is back to about 3 minutes.

**Forward tests still producing:**
- Gold H1 trade count rising;
- HC1 rebalance done on 2 Nov;
- H1/H1b and the ORB pair still trading;
- chain-recorder rows and MCX curve days rising.

**No surprise:** no page errors on any OFF module. They render frozen numbers.

### 3.6 Rollback

- `POST /api/main-control/bulk` with the same keys set to `true`.
- `docker-compose start prelive` (and `--profile selling start prelive-selling`).
- Code changes are additive: new keys plus one changed key each in two files.

**Warning:** a re-enabled desk resumes managing positions that were frozen at old prices.

---

## 4. Phase 2: decide what the money is for, and the Wealth module (26 Oct – 15 Nov 2026)

> This is general information, not personal advice. If you want a personal plan (tax, insurance, goals), a SEBI-registered investment adviser can give one.

### 4.1 Before any investing

1. **Emergency fund.** About 6 months of expenses in a savings account or a liquid fund.
2. **Insurance.** Term life cover if anyone depends on your income, and health cover.
3. **Expensive debt first.** Pay off credit-card and personal-loan balances. No investment reliably beats their interest.
4. **Horizon.** Money you need within about 3 years stays out of equity. Money for 5 years or more can go into an equity SIP.
5. **If you still want to trade:** set a fixed **research budget**. The default is at most 10% of investable money, used only through Phases 4–5 and their rules.

### 4.2 Default policy (edit it in the Wealth page)

| Item | Default | Why |
|---|---|---|
| Core (85%) | A NIFTY 50 **index fund, direct plan, growth option**, by monthly SIP. Or NIFTYBEES if you prefer an ETF (§4.4). | The broadest, cheapest exposure to Indian large caps. No stock picking, nothing to maintain. |
| Gold (15%) | A low-cost **gold ETF** (§4.3) | Diversifies equity and hedges the rupee. Kept small because gold pays no cash flow. |
| SIP date | A fixed day each month, after your salary lands | Automatic: you never decide "is now a good time". |
| Step-up | +10% a year (optional) | Grows with income |
| Rebalance | Once a year on the SIP anniversary, **only if** an asset is more than 5 points off its target. Redirect new SIPs first; sell only what is still off after that, oldest lots first. | Keeps risk constant at the lowest tax and cost |
| Market falls | **Keep the SIP running** | Each instalment buys more units when prices are low. Stopping is the classic mistake. |

### 4.3 Verified facts (Oct 2026; re-check each year)

| Item | Fact |
|---|---|
| NIFTY 50 ETF | Nippon India ETF Nifty 50 BeES (NIFTYBEES): TER ≈ 0.04–0.05% |
| NIFTY 50 index funds (direct) | ≈ 0.13–0.30%; e.g. HSBC Nifty 50 Index Fund direct 0.15% (Aug 2026) |
| Gold ETFs | TER ≈ 0.4–0.8%. Gold BeES ≈ 0.69–0.81% in 2026 sources; several others ≈ 0.41–0.50%. Compare the current factsheets. |
| Sovereign Gold Bonds | No new tranche since February 2024; secondary market only |
| Equity tax (FY 2026-27) | Long-term (held **more than 12 months**): 12.5% on gains above **₹1.25 lakh a year**, counted across all equity gains. Short-term: 20%. Surcharge and cess come on top. |
| Gold ETF tax | Held more than 12 months: 12.5%, with **no** ₹1.25 lakh exemption. Otherwise slab rate. Gold fund-of-funds: 24 months. |
| New law | The Income Tax Act, 2025 is in force from 1 Apr 2026: same rates, new section numbers, and "tax year" replaces the old wording |
| Angel delivery brokerage | Lower of ₹20 or 0.1% per order, minimum ₹5, from 17 Nov 2025 |
| DP charge | ≈ ₹20 + GST per stock per day you sell (third-party source; confirm on Angel's rate card) |
| NAV data | AMFI publishes every NAV daily at `portal.amfiindia.com/spages/NAVAll.txt`. Checked 19 Oct: 1.5 MB, NAV date 16-Oct-2026. |

### 4.4 Index fund or ETF?

- **Index fund (direct plan).** SIPs are automatic and buy fractional units, with no demat, brokerage or DP charges. TER ≈ 0.13–0.20%.
- **ETF (NIFTYBEES).** TER ≈ 0.05%. But each purchase pays brokerage (about 0.1% on small orders, minimum ₹5), each sale pays the DP charge, and you place every order yourself.
- **Default: the index fund**, for automation. The TER difference (about 0.1% a year) is smaller than the cost of a skipped month.
- **Where to buy:** any platform that sells **direct** plans (the AMC, MF Central, or your broker's direct-MF section).
- **The app does not place these orders.** It tracks them.

### 4.5 What to build

| # | Item | Detail |
|---|---|---|
| W1 | NAV feed: `services/wealth/nav_feed.py` | Download `NAVAll.txt` nightly (23:30 IST) and parse it, using a real 19 Oct sample as the test fixture. Store **only the schemes in your plan** (`wealth_nav {code, date, nav}`) to protect the Atlas quota. ETF prices come from the NSE CM bhavcopy that `nse_archives` already ingests (add the ETF symbols to its list) or from an Angel LTP. Backfill history from AMFI's NAV-history download (verify the endpoint first) or mfapi.in. |
| W2 | Plan and ledger | `wealth_plan`: targets, SIP amount and day, step-up, band, rebalance date. `wealth_txns`: date, instrument, BUY/SELL, amount, units, NAV or price, charges, source (manual or CSV). A CAMS/KFintech CAS PDF import comes later and is optional. |
| W3 | Metrics: `metrics.py` | **XIRR** (the rate *r* that makes Σ CFᵢ/(1+r)^(daysᵢ/365) = 0; Newton's method with a bisection fallback), invested amount, value, gain, max drawdown of the value series, allocation and drift |
| W4 | Rebalance assistant | On the anniversary, or when the band is breached: the target values, how many months of redirected SIP would close the gap, and only then a sell/buy list with a FIFO lot-level tax estimate |
| W5 | Tax view: `tax_rules.py` (dated table) | Per financial year: realised STCG and LTCG by asset class, the ₹1.25 lakh exemption used, estimated tax, and the date each lot "becomes long-term". Rates live in a dated table, so a Budget change is a data edit. |
| W6 | Page `/wealth` | Cards (invested, value, gain, XIRR), allocation against target, the SIP calendar ("due 5 Nov — paid?"), the rebalance panel, the tax panel, and an illustrative projection at 6%, 10% and 12% labelled "not a forecast" |
| W7 | Wiring | `module_registry` key `wealth` (new group "Investing", first in `GROUP_ORDER`), `api/routes/wealth.py`, `frontend/lib/wealthApi.ts`, and a sidebar entry at the top |

**Out of scope:**
- placing MF or ETF orders;
- advice beyond the policy you set;
- performance comparisons against your trading history.

### 4.6 Tests: `backend/tests/wealth/verify_wealth.py` (offline, fake collections)

- XIRR against independently computed cases: a monthly SIP, a lump sum, irregular flows, an all-negative edge case.
- FIFO across financial years.
- The ₹1.25 lakh exemption is shared across all equity funds.
- Gold gets no exemption.
- The "more than 12 months" boundary, including a leap year.
- Drift and rebalance arithmetic.
- The AMFI parser against the saved sample, including its header and AMC section lines.

### 4.7 Acceptance

- You enter the plan and your first SIP, and the next morning that day's NAV is stored.
- XIRR matches a spreadsheet XIRR on the same flows to within 0.01%.
- The page loads in under 1 second.
- Tests pass.

---

## 5. Phase 3: the Evidence Registry (2 – 20 Nov 2026)

**Problem.**
- There are eight separate registries, each with its own page, API and status words: `option_hypotheses`, `commodity_hypotheses`, `stock_hypotheses`, `intraday_v2_registry`, `h1_slippage`, `gold_h1`, `gold_lab` and the Index Intraday study.
- Nobody can see in one place what is being tested, since when, by what rule, how far along it is, and when it decides.
- The real-money executors each read a different registry.

| # | Item | Detail |
|---|---|---|
| E1 | Adapters: `services/evidence/adapters.py` | One per registry. Each maps to a single schema: `{id, desk, title, kind (forward/record/decided/closed), registered_at, fingerprint, code_matches_stored, rule_summary, metric, thresholds, progress {n, needed, pct}, stat {mean, t, z}, status, next_decision_date, eligible_for_real_money, why}`. Sources are the existing endpoints: `/api/prelive/hypotheses`, `/api/commodity/hypotheses`, `/api/intraday-lab/v2/registry`, `/api/intraday-lab/v2/h1`, `/api/gold-desk/h1`, `/api/gold-desk/lab` and `/api/index-intraday/research`, plus `stock_hypotheses` once it is committed. |
| E2 | API | `GET /api/evidence` and `GET /api/evidence/{id}`, read-only, under module key `evidence` (System) |
| E3 | Page `/evidence` | **Active**, sorted by next decision date. **Decided**: confirmed or rejected, with the one-line reason. **Graveyard**: closed research families with their trial counts, so nobody re-tests them by accident. **Recorders**: the health of each data feed. |
| E4 | Integrity | Fingerprint check (the stored rule against the code). **STALLED** when there is no forward record for N trading days; this would flag HS2 today. A **protocol deviation** log, for anything stopped early or changed. |
| E5 | Eligibility API | `eligible(id) -> (bool, why)`. Only `CONFIRMED` (short-horizon) and the new `PILOT_APPROVED` (long-horizon; §6.9, §7.9) can say yes. Phase 0's lock calls it, so every executor reads the **same** answer. |
| E6 | Monthly snapshot | `research-reports/evidence/<YYYY-MM>.md`, written on the first trading day of each month |

**Tests:** each adapter against JSON fixtures saved from today's production reads; STALLED detection; next-decision-date arithmetic; `eligible()` says no for every current item.

**Acceptance:**
- every registered item appears with the status and dates shown in §1.4;
- HS2 shows STALLED (or NOT RUNNING);
- `eligible()` returns false everywhere today.

---

## 6. Phase 4: monthly momentum study, pre-registered (9 Nov – 31 Dec 2026)

### 6.1 The question

> Does a simple monthly momentum portfolio of large Indian stocks beat (a) the NIFTY 50 and (b) a NIFTY200 Momentum 30 index fund, **after every cost and after tax**, on data free of survivorship bias?

"No" is a useful answer. It means you buy the fund, or simply stay in the NIFTY 50 SIP, and the app does not trade.

### 6.2 Why this idea, and what can go wrong

**For:**
- Momentum is one of the most replicated return patterns in finance, across countries and asset classes (Jegadeesh & Titman 1993; Asness, Moskowitz & Pedersen 2013).
- NSE runs momentum indices, and funds track them cheaply, so the effect is investable.
- Holding for months makes costs a small fraction of the move, which is the opposite of what killed every intraday desk here.

**Against:**
- Momentum crashes, sharply and suddenly (Daniel & Moskowitz 2016).
- NIFTY200 Momentum 30 funds fell **about 27–30% from a Sep/Oct 2024 peak to a 14 Mar 2025 trough**, and had not recovered by Aug 2026. One of them ranked 154th of 185 index funds in calendar 2025.
- A DIY version also pays **tax every year**, because monthly turnover realises gains short-term. A fund pays nothing until you sell.

**The tax drag, worked:** ₹10 lakh for 10 years at 15% a year before tax.

| | Fund | DIY |
|---|---|---|
| Tax | One sale at the end: 12.5% above ₹1.25 lakh, plus 4% cess | Gains realised short-term every year: 20% + 4% cess |
| End value | ₹40.46 lakh − ₹3.80 lakh tax ≈ **₹36.7 lakh** (13.9% a year after tax) | ₹10 lakh × 1.1188¹⁰ ≈ **₹30.7 lakh** (11.9% a year) |

So **the DIY portfolio must beat the fund by about 2 percentage points a year just to break even**, before any trading cost. The decision rule below builds that in.

### 6.3 The pre-registration (rule **M1**, frozen before any return is computed)

| Field | Frozen value |
|---|---|
| Universe on each rebalance date *t* | Every NSE **EQ-series** stock in that day's CM bhavcopy that ranks in the **top 500 by median daily traded value over the previous 126 sessions**, has at least 252 sessions of history and closes at ₹20 or more. Point-in-time, so it **includes companies later delisted**. |
| Signal | **12-1 momentum**: the adjusted return from the close at *t*−252 to the close at *t*−21 |
| Portfolio | **30 names, equal weight**. Buffer: a holding stays while its rank is 60 or better, and vacancies fill in rank order. |
| Rebalance | Last trading day of each month, using that day's close |
| Execution | The **next session's VWAP** (bhavcopy turnover ÷ quantity) plus impact: 10 bp for the top 100 by traded value, 25 bp for the rest |
| Costs (today's rates) | Brokerage: lower of ₹20 or 0.1%, minimum ₹5. STT 0.1% on both sides. Stamp 0.015% on buys. Exchange 0.00297%. SEBI ₹10 per crore. GST 18% on brokerage + exchange + SEBI. DP ₹20 + GST per stock sold per day. |
| Tax | **Today's rules applied to the whole history** (the question is what you would earn under the rules you will face): FIFO lots, STCG 20%, LTCG 12.5% above ₹1.25 lakh a year, 4% cess, losses set off and carried forward the Indian way. Tax is paid from the portfolio at each financial-year end; full liquidation at the end. Pre-tax figures are reported too. |
| Delisting | A holding that vanishes from the bhavcopy with no matching corporate action closes at its last close **× 0.5**. Sensitivity runs at × 1.0 and × 0.0. |
| Benchmarks | NIFTY 50 TRI, NIFTY 500 TRI, NIFTY200 Momentum 30 TRI − 0.20% a year (a direct-plan fund TER), each taxed as a fund held to the end |
| Variants (declared now, reported, **never chosen from**) | V1: top 20. V2: NSE-style score (average of the 6- and 12-month returns ÷ volatility). V3: semi-annual rebalance. M1 + 3 variants = **4 trials** in the deflated Sharpe. |
| Periods | **Development: 2006-01 → 2018-12**, used only to catch bugs and data errors. **Holdout: 2019-01 → 2026-09, opened once**, after the development report is committed. It contains the 2020 crash and the 2024-25 momentum drawdown. |

**Storage:** the rule is stored as JSON with a SHA-256 fingerprint in `backend/research/momentum_2026_11/rule.json` and in the Evidence Registry **before** the first backtest runs.

### 6.4 Data

| Need | Source | Verified | Note |
|---|---|---|---|
| Daily prices for **every** NSE stock, including later-delisted ones | NSE CM bhavcopy archives: `nsearchives.nseindia.com/content/historical/EQUITIES/YYYY/MMM/cmDDMMMYYYYbhav.csv.zip` (old format); UDiFF from July 2024 | 2010-01-04 file downloaded (HTTP 200, 39 KB) | About 5,200 files for 2006–2026. Pace one every 2 seconds, about 3 hours. If the archive serves years before 2010, start in 2005. |
| Split and bonus adjustment | The bhavcopy itself: factor = `PREVCLOSE(t) / CLOSE(t−1)`. NSE adjusts the previous close on ex-dates, so any gap above 0.5% marks a corporate action. | to validate | Check against 20 known splits and bonuses, and cross-check with Angel's adjusted daily bars where they exist |
| Identity across renames | ISIN (present in the bhavcopy from about 2011), otherwise NSE's symbol-change list | to verify | |
| Dividends | Optional; the price-return version runs against TRI benchmarks | n/a | This biases the DIY result **down** by about 1% a year, so it is conservative |
| Benchmarks | niftyindices.com historical TRI downloads | to verify | NIFTY200 Momentum 30 before its launch is NSE's back-calculation |
| Storage | Compact per-day files under `backend/research/momentum_2026_11/data/` (gitignored; a manifest and checksums are committed) | n/a | **Not Atlas** (512 MB quota) |

**Data acceptance:**
- at least 99% of trading days present;
- 480–500 names in the universe on every date;
- every adjusted one-day move larger than 40% explained;
- many 2008 universe names absent in 2026, which proves delisted companies are included.

### 6.5 Decision rule (PASS = all four; otherwise FAIL)

1. **Holdout, after tax:** the M1 CAGR is at least the after-tax CAGR of the momentum fund **+ 2.0 percentage points**.
2. **Full period:** the deflated Sharpe of monthly excess returns over NIFTY 500 TRI is ≥ 0.95, counting all 4 trials.
3. **Holdout drawdown:** the maximum drawdown is no more than the momentum index's drawdown over the same period + 10 points.
4. **Cost robustness:** at **2× costs**, the holdout CAGR still beats the fund after tax.

**FAIL** is written up in `MOMENTUM_STUDY_2026_12.md` and recommends "no DIY momentum". The options are then:
- the NIFTY 50 SIP alone;
- or a momentum index fund as a small satellite, if you want the factor at all.

**No re-tuning, and no new variants.**

### 6.6 Steps and dates

| By | Step |
|---|---|
| Fri 13 Nov | `PREREGISTRATION.md` + `rule.json` + fingerprint committed and stored in the registry |
| Fri 27 Nov | Data built and accepted (§6.4) |
| Fri 11 Dec | Development report committed (2006–2018: bugs and data only) |
| Fri 18 Dec | Holdout opened **once**; full report |
| **Thu 31 Dec** | Decision recorded in the Evidence Registry |

### 6.7 If PASS: forward paper (Jan – Jun 2027)

- Reuse the `long_horizon` desk (`long_horizon_engine.py`): its basket book, delivery cost model and own capital pool.
- Change only these parts:
  1. A `PreregisteredBasket` mode reads M1 from the registry. **Do not run** the old catalogue sweep: it re-mines many rules at once, and `MIN_HISTORY_BARS = 2300` admits only names that survived nine years (survivorship).
  2. A month-end calendar, instead of counting bars.
  3. Fills at the next session's VWAP from the bhavcopy plus impact, exactly as modelled, and an Angel quote logged at 15:00 as a live-price check.
  4. A tax ledger, so the paper result is after tax.
  5. **₹10 lakh** of paper capital (realistic), not ₹1 crore.
- Six monthly rebalances.
- **Purpose: implementation parity, not proof.** Six months cannot prove a monthly strategy. Acceptance: the average monthly tracking difference against a re-run of the backtest on the same dates is ≤ 0.5%.

### 6.8 If PASS and parity holds: a small real pilot (from Jul 2027)

- **Minimum sensible size.** Each sale costs a ₹23.6 DP charge, which is 0.1% at ₹25,000 per name. So 20–30 names × ₹25,000 = **₹5–7.5 lakh**. Below that, use the fund.
- **Capital limit:** at most 10% of investable money (your choice, set in the unlock).
- **Executor.**
  - A new Angel CNC delivery executor behind Phase 0's lock.
  - The registry status must be `PILOT_APPROVED`, which is set only after §6.5 PASS and §6.7 parity.
  - It reconciles daily against Angel's holdings and imports contract notes.
- **Stop:** a pilot drawdown of 25% triggers stop and review. The fund is always the fallback.

### 6.9 Tests

- Universe point-in-time (no stock enters before its listing, delisted names appear).
- Adjustment factors on the known events.
- 12-1 computed without look-ahead.
- Buffer logic.
- VWAP fill.
- Cost and tax ledger against hand-worked cases.
- Fingerprint unchanged.
- The holdout reader refuses a second open: a `holdout_opened_at` marker in the registry.

---

## 7. Phase 5: defined-risk NIFTY option selling

### 7.1 The question

> Does selling a **defined-risk** NIFTY structure on a fixed monthly schedule earn a positive return after Angel's charges, STT at 0.15% (from 1 Apr 2026) and real bid/ask? Is its worst month survivable? Does live paper execution match the model?

### 7.2 Prior

**For:**
- Index options usually price more volatility than later occurs. This is the volatility risk premium, widely documented (e.g. Carr & Wu 2009).
- This app measured NIFTY's market-hours realised variance at about a third of what VIX implies (the H1 research). That is suggestive, but not the same measure.

**Against:**
- 87.7% of individual F&O traders lost money in FY26.
- Sellers win small and often, then lose large in crashes: NIFTY fell 12.98% on 23 Mar 2020 and 5.93% on 4 Jun 2024.
- STT at 0.15% of the premium sold, plus ₹20 an order, takes a real share of small credits.
- The old desk's number (+0.2% with no costs) is not evidence for or against.

### 7.3 P5.0: start the option-price recorder now (week 1; data only)

- **Problem.** `nse_archives.parse_fo` keeps futures only (`nse_archives.py:42-44`, docstring), so NIFTY option closes are not being kept, and NSE serves only a rolling window of recent files.
- **Solution, daily:** extend the `fo` ingest to also write `nse/fo_opt/YYYY-MM-DD.json` for **NIFTY only**. Keep expiries ≤ 70 days and strikes within ±20% of spot. Each strike keeps `[open, high, low, close, settle, OI, contracts]`, and expiry dates are taken **from the file**. The app once traded monthlies as "weekly" from a stale master, so dates are never computed.
- **Backfill, once:**
  - 2015-01 → 2026-10 from the old-format archive `…/historical/DERIVATIVES/YYYY/MMM/foDDMMMYYYYbhav.csv.zip` (23 Mar 2020 checked: HTTP 200, 514 KB) and from UDiFF after July 2024 (16 Oct 2026 checked: HTTP 200, 1.2 MB).
  - India VIX daily comes from NSE's history or the index-intraday store (from 2016).
  - Files go on disk, gzipped, not in Atlas.
- **Acceptance:**
  - at least 99% of trading days from 2015 to 2026 present;
  - 10 random dates spot-checked against NSE's own pages;
  - the daily file appears by 20:00 IST on each trading day.

### 7.4 The pre-registration (rule **S1**; frozen before the first replay)

| Field | Frozen value |
|---|---|
| Instrument | NIFTY **monthly** options. Expiry dates come from the data: last Tuesday of the month since Sep 2025, last Thursday before that. |
| Entry | The first trading day after each monthly expiry, at that day's close. Live: 15:00–15:25 IST. |
| Short put | The highest listed strike ≤ S × (1 − VIX/100 × √(D/365)), where S is the NIFTY close, VIX is the India VIX close and D is calendar days to expiry. That is about 1 standard deviation below spot, roughly a 15–16-delta put. |
| Long put | The short strike − W, where **W = 2% of S**, rounded to the strike grid. This caps the loss. |
| Management | **Hold to expiry**: no stop, no adjustment, no roll. Cash-settled at the final settlement price. |
| Size | **1 lot (65)** per cycle. Capital allocated = 3 × the maximum loss. |
| Liquidity filter | Skip the cycle if either leg traded no contracts that day |
| Variants (declared; reported; never chosen from) | V1: iron condor, adding the mirror call spread. V2: take profit at 50% of the credit, checked at the daily close. V3: short strike at 0.5 standard deviations. S1 + 3 = **4 trials**. |
| Periods | **Development: 2015-01 → 2021-12** (includes Mar 2020). **Holdout: 2022-01 → 2026-09, opened once.** |

### 7.5 Costs

- Use the dated schedules already in `shared/tradingai_shared/option_fees.py`:
  - **STT on premium sold:** 0.05%, then 0.0625% from 2023-04-01, 0.10% from 2024-10-01, 0.15% from 2026-04-01;
  - **exchange + IPFT:** ₹3,553 per crore of premium since 2024-10-01;
  - stamp 0.003% of premium bought; SEBI ₹10 per crore; GST 18%.
- Add ₹20 brokerage per order and the exercise STT (0.125% → 0.15% of intrinsic value) on an in-the-money **long** leg at expiry.
- **Bid/ask:** a half-spread model by moneyness and days to expiry, calibrated from `option_chain_recorder` (real NIFTY bid/ask every minute since 2026-10-02) and applied to the bhavcopy closes. Sensitivity at 2×.

### 7.6 Stress tests (reported whatever the result)

- Replay the worst real cycles: Feb–Mar 2020 and Jun 2024.
- Synthetic shocks: a −10% gap the day after entry; −15% over a cycle; VIX × 2 at entry.
- For each, report:
  - the loss, which can never exceed W × 65 − credit by construction;
  - the peak margin, from Angel's margin API (`margin_pacer` already exists);
  - whether the long strike existed and traded.

### 7.7 Decision rule (PASS = all four)

1. Mean net P&L per cycle is above 0 in **both** development and holdout.
2. Full period: deflated Sharpe ≥ 0.95 on per-cycle net P&L (about 140 cycles), counting 4 trials.
3. The worst 12-month net loss at 1 lot is ≤ 25% of the allocated capital.
4. The result is still net positive with spreads doubled.

**FAIL** closes option selling as a research family (recorded in the Graveyard). No re-tuning.

### 7.8 If PASS: forward paper

- At least 6 monthly cycles, priced on real bid/ask: the chain recorder and Angel depth at entry, the exchange settlement at expiry.
- **Acceptance:** each cycle's paper P&L is within ±10% of the model's P&L for the same cycle.

### 7.9 If paper parity holds: a 1-lot pilot executor

There is no new executor until then. When one is built:
- **Buy the long leg first**, then sell the short. The position is never naked, not even for a second, and the margin benefit needs the hedge in place.
- If the short leg fails, close the long.
- Both legs are one position record.
- Exit the short first, then the long.
- It sits behind Phase 0's lock and requires `PILOT_APPROVED` in the registry.
- **At most 1 lot.**
- No entries on expiry day: since Nov 2024 short options carry an extra 2% extreme-loss margin that day.
- Daily reconciliation with Angel's position book, plus contract-note import.
- Angel's API has no atomic multi-leg order, so the legs go in sequence, each one checked.

### 7.10 Timeline (one idea per stage, §8.3)

| If Phase 4… | Phase 5 study | Phase 5 paper | Phase 5 pilot |
|---|---|---|---|
| **FAILS** (31 Dec 2026) | Jan–Feb 2027 | Mar–Aug 2027 | not before **Sep 2027** |
| **PASSES** (momentum paper Jan–Jun 2027) | Jan–Feb 2027 | Jul–Dec 2027 | not before **Jan 2028** |

---

## 8. Phase 6: governance (effective today)

### 8.1 The ten rules

1. **Real money only through the master lock**, only for a registry status of `CONFIRMED` or `PILOT_APPROVED`, and only at the size set in the unlock.
2. **One idea per stage:** at most one in research, one in forward paper and one in pilot, at any time.
3. **Pre-register before the data.** Write down the rule, data, costs, metric, decision rule, date and fingerprint. Never edit them once forward data exists; `code_matches_stored` enforces this.
4. **Count every try.** Each variant is a trial, and the deflated Sharpe uses that count.
5. **Costs at the rates in force on each trade's date** (dated schedules), real bid/ask, and tax for anything held longer than a day.
6. **No leaderboards that pick winners.** ANTI mirrors are not evidence. Paper P&L without costs is not evidence.
7. **No strategies that hold for less than a week.** That family is closed (§1.1).
8. **No naked option selling**, and no option buying within a day of expiry (H2).
9. **Never cut a forward test short.** If you must, log a protocol deviation with the reason.
10. **Operations:**
    - startup hooks never raise;
    - no exact-count asserts;
    - never reset the shared database;
    - large new data goes to files, not Atlas M0;
    - commit only your own hunks when other authors have uncommitted edits.

### 8.2 Put the rules where every session reads them

- Add a project-root **`CLAUDE.md`** with the ten rules. Today the repo has none, and other sessions kept extending short-term desks (for example "copy all 548 Patterns strategies" on 15 Oct and the five-strategy intraday desk on 16 Oct).
- Every future Claude session in this repository reads it before writing code.
- Its first line: *"Before building any strategy, desk or book, read APPLICATION_RESET_AND_UPGRADE_PLAN.md §8 — new short-term strategies are closed research."*

### 8.3 The pipeline

```
research (1)  ──PASS──▶  forward paper (1)  ──parity──▶  pilot (1, size-capped)  ──▶  scale only by a new pre-registered rule
     │ FAIL                    │ fail                          │ stop rule hit
     ▼                         ▼                               ▼
  Graveyard               Graveyard                      Graveyard / fund fallback
```

### 8.4 Decision calendar

| Date | What decides |
|---|---|
| Fri 23 Oct 2026 | Phase 0 complete; switch-off done |
| Mon 2 Nov 2026 | HC1's first rebalance under its own switch |
| ≈ Nov 2026 | Selected ORB 30 verdict (40 trades). ORB 15 by ≈ Dec. |
| Fri 13 Nov 2026 | Momentum rule M1 pre-registered |
| from ≈ late Nov 2026 | H1/H1b first verdict window (30 trades) |
| Thu 31 Dec 2026 | **HC3 verdict; Phase 4 decision**; `commodity` OFF on 1 Jan |
| Fri 15 Jan 2027 | First quarterly review |
| Fri 29 Jan 2027 | HS3 decision (if it is live) |
| ≈ Apr 2027 | HC4 has enough curve data to start |
| ≈ 10 Oct 2027 | Gold H1 futility look (week 52); HC1 fail window opens (12 months) |
| ≈ Oct 2028 | Gold H1 verdict (week 104); HC1 confirm window (24 months) |

### 8.5 Reviews

- **Monthly, about 15 minutes, on the first Monday:**
  - open `/evidence`;
  - check any status changes;
  - confirm the lock still says LOCKED;
  - confirm the SIP was paid.
- **Quarterly, one page.** Four questions, each answered yes or no with a number:
  - Was any money unlocked, and why?
  - Is the SIP on plan?
  - Is every test on schedule?
  - Was any rule broken?

### 8.6 The stop rule for the whole effort

**If by 31 Dec 2027 neither Phase 4 nor Phase 5 has passed its pre-registered test, strategy research ends.**
- The app stays a wealth tracker, a set of screens and a data archive.
- The box can be downsized.

### 8.7 What not to build

- Intraday, scalping or swing strategies (holds under a week).
- New timeframes for old ideas.
- More books, or copies of desks.
- Tournaments.
- `ANTI` mirrors.
- Strategy catalogues from YouTube or Telegram.
- Commodity-options or mini-lab sweeps.
- Any "picked from the leaderboard" basket.

---

## 9. Week-by-week timeline

| Week | Dates | Work |
|---|---|---|
| 1 | 19–25 Oct | Phase 0 (P0.1–P0.8). P1.1, P1.2, P1.5, P1.6. Switch-off on Fri 23 Oct. P5.0 recorder (daily). `CLAUDE.md` rules. |
| 2 | 26 Oct – 1 Nov | Measure (§3.5). Start Phase 2 (W1–W3). P5.0 backfill. |
| 3 | 2–8 Nov | Phase 2 (W4–W7). Start Phase 3 (E1–E2). HC1 rebalance on 2 Nov. |
| 4 | 9–15 Nov | Phase 2 acceptance. Phase 3 (E3–E5). **M1 pre-registered on 13 Nov.** Start the CM bhavcopy download. |
| 5–6 | 16–29 Nov | Phase 3 acceptance. Phase 4 data built and accepted (27 Nov). ORB verdicts arriving. |
| 7–8 | 30 Nov – 13 Dec | Phase 4 development report (11 Dec) |
| 9–10 | 14–31 Dec | Holdout opened once (18 Dec). **Decision on 31 Dec.** HC3 verdict. `commodity` OFF on 1 Jan. |
| 2027 | Jan → | Branch per §7.10. Quarterly review on 15 Jan. |

---

## 10. What success looks like on 19 Oct 2027

1. **Zero** real orders sent without a deliberate, logged unlock. Audit log available.
2. The SIP has run 12 months without a missed instalment, with XIRR and allocation tracked.
3. At most about 25 modules ON. The backend has not swapped at the daily snapshots for 30 consecutive sessions.
4. A clear, written yes/no on momentum, and either a no or a paper result on spreads, each with its report.
5. **No new short-term strategy was built.**

---

## 11. Risks and trade-offs

| Risk | Mitigation |
|---|---|
| Switching off removes "practice" | Paper desks without frozen rules teach the wrong lesson: they reward picking the luckiest row. |
| Momentum's deep drawdowns (27–30% in 2024-25) tempt you to quit at the bottom | The study measures it. The decision rule caps it. The fund is always the fallback. |
| Defined-risk spreads can still lose the full width in one month | Size so that a full loss is about 1/3 of the allocated capital (1 lot). Treat the pilot as a bet with a known worst case, not a proven income. |
| Tax and STT change (Budget 2026 raised STT) | Dated rate tables. Re-run cost checks after every Budget. |
| Bhavcopy adjustment errors poison the study | Validation against known events. Big moves must be explained. Cross-check with Angel. |
| Other sessions' uncommitted edits collide | Commit only your own hunks, wire shared files last, never commit another author's edits (Appendix C). |
| Atlas quota | Research data goes to files. Archives go to git. Drops only with your OK. |
| Sunk cost: eight months of building | The hardest step is stopping. §8.6 makes stopping a rule, not a mood. |

---

## 12. Sources (checked 19 Oct 2026)

**SEBI loss studies:**
- [FY26 study coverage: 87.7% lost, 82.1% before costs](https://www.finnovate.in/learn/blog/sebi-fno-trader-losses-fy26-individual-derivatives) · [Outlook Money: costs](https://www.outlookmoney.com/invest/sebi-futures-options-study-transaction-costs-traders-losses-fy26) · [Open: ₹91,685 crore](https://openthemagazine.com/business/sebi-fo-loss-study-explained-why-9-in-10-retail-traders-lost-91685-crore-in-fy26)
- [FY25 study (Business Standard)](https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html)
- [SEBI press release, 23 Sep 2024 (FY22–FY24)](https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html) · [Taxmann summary](https://www.taxmann.com/post/blog/93-of-1-crore-fo-traders-saw-rs-2l-avg-loss-while-top-3-5-faced-rs-28l-avg-loss-incl-costs-sebi/)
- [Intraday cash FY23 (Business Standard)](https://www.business-standard.com/markets/news/7-in-10-intraday-traders-in-equity-cash-suffered-losses-in-fy23-sebi-study-124072400975_1.html)

**Costs, tax and instruments:**
- STT from 1 Apr 2026: [5paisa](https://www.5paisa.com/news/stt-hike-on-fo-to-take-effect-from-april-1-amid-rising-options-activity) · [Sansa Legal](https://www.sansalegal.com/post/stt-hike-on-futures-and-options-new-rates-effective-april-1-2026)
- Equity tax FY 2026-27: [DSP](https://www.dspim.com/knowledge-hub/personal-finance-guide/capital-gains-filing-in-india-what-to-report-where-and-how/stcg-and-ltcg-rules-in-india) · [Patron (Income Tax Act 2025)](https://www.patronaccounting.com/blog/capital-gains-rules-2026-fmv-holding-period)
- Gold ETF tax: [Zerodha Fund House](https://www.zerodhafundhouse.com/blog/gold-etf-taxation-2025/) · [Business Standard (Budget 2024)](https://www.business-standard.com/amp/budget/news/budget-2024-brings-relief-for-gold-etfs-equity-fofs-international-schemes-124072301258_1.html)
- SGB: [GoldenPi](https://goldenpi.com/blog/bond-news/sovereign-gold-bond-scheme-discontinued-for-new-issues/)
- TERs: [NIFTYBEES (Tickertape)](https://tickertape.in/etfs/nippon-india-nifty-50-bees-etf-NBES) · [HSBC Nifty 50 Index Fund note](https://www.assetmanagement.hsbc.co.in/assets/documents/mutual-funds/en/fd583044-f130-4412-a17c-899948b7b616/product-note-hsbc-nifty-50-index-fund-august-2026.pdf) · [Gold ETF TERs (GoldenPi)](https://goldenpi.com/blog/bond-news/gold-etf-expense-ratio-sbi-vs-nippon-vs-hdfc/) · [Gold ETF list (Rupeezy)](https://rupeezy.in/blogs/best-gold-etf-in-india/)
- Momentum: [NIFTY200 Momentum 30 factsheet](https://www.niftyindices.com/Factsheet/Factsheet_Nifty200_Momentum30.pdf) · [Kotak index fund, Aug 2026](https://www.kotakmf.com/factsheet/August_2026/kotak/NIFTY-200-MOMENTUM-30-INDEX-FUND.html) · [Drawdown data (Arthgyaan)](https://arthgyaan.com/fund/hdfc-nifty200-momentum-30-index-fund-direct-growth/152430)
- Broker: [Angel pricing update, Nov 2025](https://www.angelone.in/news/product-updates/pricing-update-nov-2025-b2c) · [DP charges (third-party)](https://optionx.trade/brokers/compare/zerodha-vs-angel-one)
- Contracts: [NIFTY lot 65 (NSE circular via Zerodha)](https://zerodha.com/marketintel/bulletin/429705/revision-in-lot-size-of-index-derivative-contracts-from-december-30-2025) · [NSE expiries move to Tuesday](https://www.business-standard.com/markets/news/nse-bids-adieu-to-thursday-expiry-as-dates-swap-come-into-effect-explained-125082800635_1.html) · [Weekly expiry rules](https://www.share.market/buzz/insights/weekly-expiry-days-in-indian-fo-markets/)

**Data endpoints downloaded 19 Oct 2026:** AMFI `NAVAll.txt`; NSE `cm04JAN2010bhav.csv.zip`, `fo23MAR2020bhav.csv.zip` and `BhavCopy_NSE_FO_0_0_0_20261016_F_0000.csv.zip`.

**Literature named in §6.2 and §7.2:**
- Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers*;
- Asness, Moskowitz & Pedersen (2013), *Value and Momentum Everywhere*;
- Daniel & Moskowitz (2016), *Momentum Crashes*;
- Carr & Wu (2009), *Variance Risk Premiums*.

---

## Appendix A: every module, loop and daemon, with its action

| Key | Label | Action | Reason |
|---|---|---|---|
| `market_data` | Market Data | KEEP | Shared quotes |
| `ath_trading` | All Time High Trading | **OFF** | Not pre-registered. 47 closed (+₹2.62 lakh) against −₹3.14 lakh unrealised on 83 open, about −0.1% net. The 52-week-high idea can be pre-registered later, if ever. |
| `screener` | Stock Screener | KEEP | Tool; its nightly bhavcopy is data |
| `fundamentals` | Fundamental Rating | KEEP | Lookups only. Its paper books are OFF through `FUNDAMENTAL_BOOKS_ENABLED=0`. |
| `swing_trading` | Swing Trading | **OFF** | 14 closed, −₹16.7k. Not pre-registered. |
| `live_trading` | Live Trading (REAL MONEY) | **OFF** | Disarmed; 0 of 14 strategies registered (Phase 0) |
| `paper_broker` | Stock + F&O Paper Trading | KEEP | Manual tool; never sends orders |
| `chart` | Chart | KEEP | Tool |
| `momentum_engine` | Momentum | **OFF** | 0 trades |
| `trending_stocks` | Trending Stocks | **OFF** | 0 trades |
| `nifty_scalp` | NIFTY 50 Option Scalping | **OFF** | Net −₹24 lakh (charges ₹25.3 lakh) |
| `commodity` | Commodity Trading | **OFF on 1 Jan 2027** | Hosts HC3 to 31 Dec. HC1 moves to its own key first (P1.1). |
| `commodity_options` | Commodity Options | **OFF** | Paper catalogue; another session's uncommitted build (freeze) |
| `commodity_prelive` | Pre-Live Commodity Trading | **OFF** | Lab gate 0 of 81: nothing can qualify |
| `natgas_book` | Natural Gas Paper Trading | **OFF** | −1.76%, not pre-registered |
| `gold_desk` | Gold Desk (MCX + Delta) | KEEP | Gold H1 + Gold Lab forward tests |
| `index_intraday` | Indian Index Intraday Trading | **OFF** | 0 of 1,464 validated. Stops its stream and the after-close append; history is kept. |
| `commodity_positions` | Commodity Positions | KEEP | Manual paper tool |
| `portfolio` | Portfolio | KEEP | Holdings analytics |
| `broker_account` | Orders / Positions | KEEP | Reads; real orders locked (Phase 0) |
| `stocks_range` | Stocks Range | KEEP | Screen |
| `bullish_stocks` | Bullish Stocks | KEEP | Screen |
| `fno_positions` | F&O Positions | KEEP | Manual paper tool (its auto-roll loops go OFF) |
| `watchlist` | Watchlist | KEEP | Tool |
| `strategy_factory` | Strategy Factory | **OFF** | 0 trades |
| `strategies` | Strategies | KEEP | Library viewer |
| `zero_hero` | Zero Hero Trades | **OFF** | No costs, LTP fills: not evidence |
| `backtesting` | Backtesting | KEEP | Research tool |
| `stock_research` | Stock Research | KEEP | Research tool |
| `live_paper` | Live Engine | **OFF** | −20.2%. LIVE mode retired (P0.2). |
| `prelive` | Index Option Buying | **OFF** + stop the container | H2 decided. H1/H1b live in the backend's vol desk, which is unaffected. |
| `prelive_selling` | Index Option Selling | **OFF** + stop the container | Not pre-registered; no charges; churn (§1.7) |
| `banknifty_desk` | Index Option Buying: NIFTY BANK | **OFF** | Protocol amended after results; 1 trade |
| `stock_desk` | Stock Pre-Live (buy + sell) | **Decision (P1.4)** | Keep to 29 Jan 2027 only if HS3 is live |
| `stock_books` | Stock Pre-Live Paper Books | **OFF** | −34.8% |
| `selling_books` | Index Option Selling: Paper Trading 01 | **OFF** | −3.8% net |
| `intraday_lab` | Intraday Stocks: Tournament | **OFF after the P1.2 deploy** | The ORB pair moves to `intraday_registered` |
| `intraday_focus` | Intraday Stocks: Five-Strategy Paper Desk | **OFF** | New short-term build (16 Oct); freeze |
| `live_intraday` | Intraday Stocks: Live Intraday books | **OFF** | Part of −₹28.2 lakh |
| `pattern` | Intraday Stocks: Patterns | **OFF** | −₹33.3 lakh |
| `pattern_books` | Intraday Stocks: Paper Trade books | **OFF** | Copies of Patterns |
| `long_horizon` | Long-Horizon Desk | KEEP (idle) | Becomes the Phase 4 paper engine; never run its sweep |
| `options` | Options | KEEP | Analytics (no new sweeps, rule 4) |
| `risk` | Risk | KEEP | Analytics |
| `ai_research` | AI Research | KEEP | Costs nothing unless used |
| `desk_history` | Desk History | KEEP | Shared reads |
| `instrument_search` | Instrument Search | KEEP | Shared |
| `telegram_signals` | Telegram Signals | **OFF** + stop the daemon | Tip copying (rule 6) |
| `morning_momentum` | Morning Momentum (loop) | **OFF** | Short-term |
| `fno_auto_roll` | F&O NIFTY Auto-Roll (loop) | **OFF** | Naked short straddle (rule 8) |
| `fno_stock_roll` | F&O Stock Auto-Roll (loop) | **OFF** | Short-term options roll |
| *(new)* `commodity_trend_book` | Commodity Trend Book (HC1) | KEEP | Forward test (P1.1) |
| *(new)* `intraday_registered` | Selected ORB pair | KEEP until the verdicts | Forward test (P1.2) |
| *(new, Phase 2)* `wealth` | Wealth | KEEP | §4 |
| *(new, Phase 3)* `evidence` | Evidence Registry | KEEP | §5 |

**Loops and containers that are not switches:**

| Loop or container | Action |
|---|---|
| `option_chain_recorder`, `vol_desk`, `mcx_curve_recorder`, `intraday_data_scheduler` + `nse_archives`, intraday close-out, memory snapshots | KEEP |
| `prelive` and `prelive-selling` containers | **STOP** |
| Fundamental books loop | **OFF** (env) |
| Telegram signal daemon | **STOP** |

---

## Appendix B: files touched, by phase

| Phase | New | Changed (⚠ = has another author's uncommitted edits: commit own hunks only) |
|---|---|---|
| 0 | `backend/app/services/real_money_lock.py`, `backend/tests/real_money/verify_lockdown.py`, `REAL_MONEY_LOCKDOWN_2026_10.md` | `api/routes/main_control.py`, `services/live_trading_engine.py`, `services/live_options_executor.py`, ⚠ `services/mcx_live_executor.py`, ⚠ `services/stock_options_executor.py` (untracked), `services/strategy_runner.py`, `services/live_engine.py`, `schemas/live.py`, `schemas/broker.py`, `api/routes/broker.py`, `core/db.py`, ⚠ `frontend/app/orders/page.tsx`, ⚠ `frontend/app/main-control/page.tsx`, `frontend/app/live/page.tsx`, ⚠ `frontend/lib/api.ts` |
| 1 | `backend/research/reset_2026_10/archive_desks.py`, `DESK_ARCHIVE_2026_10.md`, `research-reports/desk_archive_2026_10/*.json`, tests for P1.1, P1.2 and P1.6 | ⚠ `services/module_registry.py`, ⚠ `services/commodity_scheduler.py`, `services/intraday_v2_engine.py`, `services/desk_switches.py`, `api/routes/diagnostics.py`, ⚠ `frontend/components/Sidebar.tsx`, optional `prelive-service/main.py` + ⚠ `main_selling.py`, optional ⚠ `main.py` (P1.8) |
| 2 | `backend/app/services/wealth/{nav_feed,ledger,metrics,rebalance,tax_rules,plan}.py`, `api/routes/wealth.py`, `frontend/app/wealth/page.tsx`, `frontend/lib/wealthApi.ts`, `backend/tests/wealth/verify_wealth.py` | ⚠ `main.py` (router + nightly loop), `core/db.py`, ⚠ `module_registry.py`, ⚠ `Sidebar.tsx`, `services/nse_archives.py` (ETF symbols) |
| 3 | `backend/app/services/evidence/{adapters,status}.py`, `api/routes/evidence.py`, `frontend/app/evidence/page.tsx`, tests and fixtures | ⚠ `main.py`, ⚠ `module_registry.py`, `real_money_lock.py` (call `eligible`) |
| 4 | `backend/research/momentum_2026_11/{PREREGISTRATION.md, rule.json, fetch_cm.py, adjust.py, universe.py, backtest.py, tax.py, report.py}`, `MOMENTUM_STUDY_2026_12.md` | later: `services/long_horizon_engine.py` (`PreregisteredBasket` mode) |
| 5 | `backend/research/option_selling_2027_01/…` | `services/nse_archives.py` (`fo_opt`, now); later a new spread executor |
| 6 | `CLAUDE.md` (project root), `research-reports/evidence/` | none |

---

## Appendix C: deploy and commit procedure (unchanged)

### Commit

The working tree carries other authors' uncommitted edits, so never run `git add <file>` on a shared file. Use a **private index**:

1. `read-tree` the base.
2. `hash-object` the new contents and `update-index --cacheinfo`.
3. `write-tree`.
4. `commit-tree -p BASE`.
5. `update-ref refs/heads/main NEW BASE` (compare-and-swap).
6. `git reset -q NEW -- <own paths>`.

Commit messages end with the co-author line.

### Deploy

1. Copy only committed files to the box (`git show <sha>:<path>`) and md5-check them against the commit.
2. Run a throwaway-container import test (`docker run --rm --memory 300m …`).
3. Run `sudo docker-compose up -d --build backend` (`--force-recreate` when the env changed).
4. Confirm "startup complete" in the logs, then check the new endpoints with `curl 127.0.0.1:8000/…` on the box.

**On the box:**
- run `git status` on its own, and stop if it shows modified files;
- prove that uncommitted work is live (md5) before building;
- never chain status, pull and build.
