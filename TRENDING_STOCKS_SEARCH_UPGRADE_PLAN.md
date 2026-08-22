# Trending Stocks — Search Upgrade Plan

The "Name the stocks" box is a bare `<textarea>`. You type tickers blind, get no feedback,
and find out whether the desk can even trade the name hours later — or never.

This plan replaces it with a **⌘K instrument console**: ranked, typo-tolerant, enriched with
what the app already knows, and honest about whether a stock is tradable *before* it enters
the basket.

Status: **BUILT AND DEPLOYED** (2026-08-22). All six phases shipped. The build report is
immediately below; everything after it is the plan as written, with the measurements that
motivated it.

---

## BUILD REPORT

### Shipped

| Phase | What | Where |
|---|---|---|
| 0 | `re.escape` on the shared search + the endpoint finally wired to the UI | `manual_positions.py` |
| 1 | In-process index, alias map, ranking function | `services/instrument_search/{index,aliases,scoring}.py` |
| 2 | Enrichment + the tradability verdict | `instrument_search/enrich.py` |
| 3 | ⌘K palette, mounted once app-wide, zero-query "Trending now" | `components/CommandPalette.tsx` |
| 4 | Every result says whether the desk would trade it, before you add | `enrich.tradability()` |
| 5 | English → filter → deterministic execution | `instrument_search/nlq.py` |
| — | API | `GET /api/search/{instruments,trending,resolve,stats}`, `POST /api/search/{natural,reindex}` |
| — | Tests | `backend/tests/instrument_search/verify_{ranking,nlq}.py` — 60 assertions |

### The same queries, re-probed on production after deploying

| Query | Before | After |
|---|---|---|
| `reliance` | RPOWER, **RELIANCE**, RIIL | **RELIANCE**, RPOWER, RIIL |
| `RELI` | RELIGARE, RPOWER, RELIABLE, **RELIANCE** | **RELIANCE**, RPOWER, RIIL |
| `tata` | TCS, NPBET, TATAINVEST *(no Tata Motors)* | TATASTEEL, TATATECH, TATACONSUM, TATACAP, TATAPOWER |
| `bank` | FEDERALBNK, PNB *(no HDFC/ICICI)* | BANKBARODA, BANKINDIA, AXISBANK, **HDFCBANK**, **ICICIBANK** |
| `RELINCE` | *nothing* | **RELIANCE**, RPOWER, RIIL |
| `(` `[` `a{100000}` `.*` | **500 OperationFailure** | handled, no error |

Index warm on boot: **2,457 instruments, 39 aliases, screener snapshot 2026-08-21 (499 symbols)**.
Natural language is **live on Groq** (`llama-3.3-70b-versatile`); Cerebras, DeepSeek, Mistral
and XAI are configured as fallbacks.

### Two things the build changed about the plan

1. **Demotion became its own axis.** The plan scored illiquid and bar-less names down with
   large negative numbers. That is wrong: a penalty big enough to demote reliably is big
   enough to push the total below zero, and the result is then dropped. `balkrishna paper`
   scored 476, took −300 for no bars and −250 for illiquidity, and returned **nothing** —
   the exact silent failure this upgrade exists to remove, one layer down. Results now sort
   on `(demotion, -score)`: blocked names fall below tradable ones and nothing is deleted
   by arithmetic.
2. **Alias validation caught a corporate action.** Three curated aliases were auto-dropped
   at index build because their targets no longer exist. `TATAMOTORS` is gone — the company
   demerged into **TMCV** ("Tata Motors Ltd.") and **TMPV** ("Tata Motors Passenger Vehicles
   Ltd."), and typing "tata motors" already finds both through the name rules, ranked TMCV
   first. LTIMindtree is absent from this master entirely. All three were removed rather
   than repointed: hardcoding one side of a demerger would silently choose for you.

Every number in the sections below was measured on production on 2026-08-22, not assumed.

---

## 1. What is actually broken — with receipts

### 1.1 The search endpoint exists and the page never calls it

I built `GET /api/trending-stocks/basket/search` and `searchTSInstruments()` in `api.ts` in
the last build, then shipped a raw textarea that calls neither. That is my miss, and it is
the largest single cause of the experience you are looking at. The autocomplete was never
wired in.

### 1.2 The underlying search crashes on ordinary input

`manual_positions.search_instruments` interpolates the raw query into a Mongo `$regex`
with no escaping. Probed on production:

| Query | Result |
|---|---|
| `(` | **`OperationFailure: Regular expression is invalid: missing closing parenthesis`** |
| `[` | **`OperationFailure: missing terminating ] for character class`** |
| `a{100000}` | **`OperationFailure: number too big in {} quantifier`** |
| `.*` | returns arbitrary rows — the wildcard is executed |

So the endpoint 500s on a stray bracket, and a crafted query is a regex-injection /
ReDoS vector. **This function is shared by the Watchlist and Positions modules**, so this
is an app-wide bug, not a Trending Stocks one.

### 1.3 The ranking is wrong in the way that matters most

There is no ranking at all — Mongo returns natural order. Measured:

| Query | Returns | The problem |
|---|---|---|
| `reliance` | `RPOWER`, **`RELIANCE`**, `RIIL`, `RELCHEMQ` | the exact company ranks **second**, behind Reliance Power |
| `RELI` | `RELIGARE`, `RPOWER`, `RELIABLE`, **`RELIANCE`** | the ticker you typed the prefix of ranks **fourth** |
| `tata` | `TCS`, `NPBET`, `TATAINVEST`, `TATATECH`, `TATAGOLD` | **TATAMOTORS, TATASTEEL and TATAPOWER do not appear at all** |
| `bank` | `FEDERALBNK`, `PNB`, `UNIONBANK`, `CANBK`, `TMB` | **HDFCBANK and ICICIBANK are absent** |
| `RELINCE` | *(nothing)* | one transposed letter and you get zero results |

### 1.4 The names it shows are truncated garbage

The broker scrip master truncates at ~25 characters. Real rows from production:

```
ARE&M       AMARA RAJA ENERGY MOB LTD
BALKRISHNA  BALKRISHNA PAPER MILLS L      <- cut mid-word
GODREJCP    GODREJ CONSUMER PRODUCTS
```

Meanwhile `stock_universe` holds the clean version for the Nifty 500 —
`Adani Enterprises Ltd.`, with **sector** and **index membership** — and the search does
not touch it.

### 1.5 It will happily let you add a stock the desk refuses to trade

2,457 NSE equities/ETFs are searchable. Only **500** are in the Nifty 500. The desk's own
liquidity pillar vetoes anything under ₹5 crore median turnover, and only **508 symbols
have daily bars** while **3 have 15-minute bars**. So today you can add a name that will
produce silence forever, and nothing tells you why. That is the cruellest failure mode in
the whole module.

---

## 2. What the app already knows (and the search ignores)

Everything below is populated on production **right now**:

| Source | Rows | What it gives a search result |
|---|---:|---|
| `instruments` | 2,457 (2,396 with Angel tokens) | tradability — no token, no candles, no quote |
| `stock_universe` | 500 | **clean name, sector, index membership**, `tightest_index` |
| `screener_momentum` | 499/day | returns 1d / 1w / 1m / 6m per symbol, vs a NIFTY benchmark |
| `screener_sectors` | daily | sector returns, breadth, **rank change**, leader/laggard |
| `stock_highs` | 499 | all-time high + date → "8% below its ATH" |
| `stock_fundamentals` | 1,726 | market cap → cap tier; PE, ROE, debt/equity |
| `bars` | 508 daily / 3 intraday | coverage badge, and median turnover for the liquidity check |
| `research_signals` | 121 | recent headlines mentioning the name |
| `evidence.py` (this module) | — | **the seven pillars, runnable before you add** |

The last row is the important one. This module can already answer *"would the desk trade
this, and why not"* — it just never asks the question until after you have committed.

---

## 3. What "futuristic" honestly means here

I checked what would be needed for the two things that usually get called futuristic:

**Vector / semantic search — NOT viable, and I will not pretend otherwise.** Qdrant is
running on the box but holds **zero collections**. There is no local embedding library
(`sentence_transformers`, `fastembed`, `sklearn` all absent), and `ai_service`'s provider
is Anthropic-only whose `embed()` raises by design — Anthropic has no embeddings endpoint.
So semantic search means a new dependency, a model download, and an index build, to solve a
problem that a good lexical index solves better. **For 2,457 tickers, embeddings are the
wrong tool**: they are fuzzy where you need exact, and slower than a hash lookup.

**Natural-language querying — viable, with a caveat.** `ANTHROPIC_API_KEY` is **not set**
on production, so `ai_service.provider.configured` is `False`. But **Groq, Mistral,
DeepSeek, Cerebras and XAI keys are all set** — the provider class simply cannot use them.
The published pattern for this ([StocksTalk](https://arxiv.org/html/2608.18105),
[multi-agent screeners](https://medium.com/@wintersweet001/customized-smart-stock-screener-built-in-less-than-4-hours-d112e80863d4))
is the right one and matches this codebase's values exactly:

> **the model never picks stocks — it only translates English into a structured filter,
> which the app then executes deterministically and explains.**

So "IT stocks up more than 10% this month near their highs" becomes
`{sector: "IT", ret_1m: {gte: 10}, pct_from_ath: {gte: -5}}`, run against
`screener_momentum` + `stock_highs` by ordinary code. If no provider is reachable the box
degrades to lexical search and **says so** — it never guesses.

Also worth fixing while in there: `ai_service.provider.DEFAULT_MODEL` is `claude-opus-4-8`,
which is not the current model.

---

## 4. The design — a ⌘K instrument console

Per the [command palette](https://uxpatterns.dev/patterns/advanced/command-palette)
[conventions](https://solomon.io/designing-command-palettes/): keyboard-first, ⌘K plus a
visible control so it is not folklore, grouped sections rather than a flat list, and every
row reachable without a mouse.

```
┌─ ⌘K ──────────────────────────────────────────────────────────────────────┐
│  reli                                                          [Esc] close │
├────────────────────────────────────────────────────────────────────────────┤
│  BEST MATCH                                                                │
│  ● RELIANCE   Reliance Industries Ltd.        Nifty 50 · Energy            │
│    ₹1,412.60  +0.8%   1M +6.2%   4% below ATH   ₹842cr turnover            │
│    ✓ tradable · 7/8 timeframes have bars · 6 of 7 pillars support today    │
│                                                                            │
│  ALSO MATCHING                                                             │
│    RPOWER     Reliance Power Ltd.             Nifty 500 · Utilities        │
│      ⚠ ₹3.1cr turnover — below the ₹5cr floor, the desk would veto it      │
│    RELINFRA   Reliance Infrastructure Ltd.    — · Construction             │
│      ⚠ no daily bars yet — would be a data gap, not a signal               │
│                                                                            │
│  TRENDING NOW (no query needed)                                            │
│    URBANCO  +7.3% 1d   ·  TRENT  −1.6% 1d   ·  Consumer Services ▲12 ranks │
│                                                                            │
│  ACTIONS   ⏎ add · ⇧⏎ add + backfill · ⌘⏎ preview research · ⌘B backtest   │
└────────────────────────────────────────────────────────────────────────────┘
```

Five things this does that the textarea cannot:

1. **Ranks the obvious answer first.** `reli` → RELIANCE, not RPOWER.
2. **Shows the clean name, sector and index** from `stock_universe`.
3. **Tells you it is trending** — returns straight from `screener_momentum`, which is the
   entire point of a module called Trending Stocks.
4. **Warns before you add**, not after: below the turnover floor, no bars, no Angel token.
5. **Empty query is a discovery surface** — today's movers and the rotating sectors, so the
   box answers "what should I even name?"

---

## 5. Architecture

```
backend/app/services/instrument_search/
    __init__.py
    index.py      in-process inverted index + trigrams, built at startup, refreshed daily
    aliases.py    the awkward-ticker map and the normalisation rules
    scoring.py    the ranking function (below)
    enrich.py     joins universe / screener / highs / fundamentals / bars onto a hit
    nlq.py        natural-language -> structured filter (provider-agnostic, degrades)
backend/app/api/routes/instrument_search.py    GET /api/search/instruments  (app-wide)
frontend/components/CommandPalette.tsx         ⌘K, usable from any page
```

**Why an in-process index rather than a cleverer database.** 2,457 instruments is a few
hundred kilobytes. Mongo 8 is self-hosted here, so Atlas Search / `$search` is unavailable,
and `$text` is word-based with no prefix or fuzzy support. A dict of postings plus trigram
sets answers in **microseconds**, is deterministic, ranks exactly how we choose, and adds
no infrastructure. It is rebuilt from Mongo on startup and on a daily timer.

### 5.1 The ranking function

Scores are additive and every component is inspectable — a result can explain why it ranked
where it did, in the same spirit as the desk's rejection ledger.

| Signal | Score |
|---|---:|
| exact symbol match | 1000 |
| alias exact (`M&M` → Mahindra, `Amara Raja` → `ARE&M`) | 900 |
| symbol prefix | 700 − 4×(length gap) |
| name word-prefix (`hdfc ba` → HDFC Bank) | 500 |
| symbol substring | 380 |
| name substring | 300 |
| trigram similarity, only if nothing above fired | 0–220 × Dice coefficient |
| **boost** Nifty 50 / 100 / 500 membership | +90 / +55 / +25 |
| **boost** in today's screener top 50 by 1M return | +60 |
| **boost** full bar coverage | +30 |
| **penalty** below the ₹5cr turnover floor | −250, and flagged |
| **penalty** no daily bars | −300, and flagged |
| **exclude** no Angel token | not tradable, hidden behind a toggle |

`RELINCE` finds RELIANCE through trigrams; `bank` surfaces HDFCBANK and ICICIBANK because
the Nifty 50 boost outranks alphabetical accident.

### 5.2 Aliases — the part that is genuinely hard

The scrip master fights you: `ARE&M` for Amara Raja, truncated names, `&` versus `and`,
`LTD`/`LIMITED`/`INDIA` noise. `aliases.py` normalises (case, punctuation, `&`↔`and`,
suffix stripping) and carries a small curated map for the tickers no rule can reach.
Its correctness is testable, so it gets a fixture list of "what a human would type" →
"what they meant".

### 5.3 Safety

`search_instruments` gets `re.escape()` and a length cap — a one-line fix that also
repairs Watchlist and Positions. The new endpoint never builds a regex from user input at
all; it hits the in-memory index.

---

## 6. Phases

| Phase | Deliverable | Done when |
|---|---|---|
| **0** | Escape the regex in `manual_positions.search_instruments`; wire the *existing* endpoint into the basket box as a plain autocomplete | `(`, `[`, `a{100000}` return results instead of a 500; you can pick a stock from a dropdown instead of typing blind. Ships same day. |
| **1** | `instrument_search` package: index, aliases, scoring | The five failing queries in §1.3 all return the right answer first; `RELINCE` finds RELIANCE; a fixture suite covers the alias map |
| **2** | Enrichment join — clean name, sector, index, returns, ATH distance, turnover, coverage | Every result carries the badges in the §4 mock, and the tradability warning is correct against `evidence.liquidity_pillar` |
| **3** | ⌘K palette component, usable app-wide; zero-query "Trending now" from `screener_momentum` | Keyboard-only operation; opening with an empty box shows today's movers and sector rotation |
| **4** | Pillar preview on ⌘⏎ — the seven pillars for a candidate *before* adding it | The preview matches what the desk decides at scan time |
| **5** | Natural-language filter via a provider-agnostic client (Groq first, since a key exists) | "IT stocks up 10% this month near their highs" produces a structured filter, the filter is **shown** to you, and results come from deterministic execution. No provider → lexical mode with an explicit banner |

Phase 0 is worth shipping on its own — it fixes a crash and the blind-typing problem in a
few lines.

---

## 7. What I am deliberately not building

- **Embeddings / Qdrant semantic search.** Wrong tool for 2,457 tickers, and it would need
  new infrastructure to do worse than §5.1. Revisit only if search widens to news or
  filings, where meaning actually matters.
- **An LLM that picks stocks.** The model translates a query into a filter and nothing
  else. Stock selection stays in code that can be replayed and argued with.
- **Fuzzy matching on the money path.** Typo tolerance is for *finding* a symbol. Adding
  one to the basket always requires an exact, resolved instrument.

---

## 8. Open question for you

Phase 5 needs a provider. Anthropic is unset, but **Groq, Mistral, DeepSeek, Cerebras and
XAI keys are all already on the box** — the `ai_service` provider class is just hardcoded to
Anthropic. I would make it provider-agnostic and default to Groq for this (it is fast and
cheap, and the Telegram signal service already uses it). Say if you would rather add an
`ANTHROPIC_API_KEY` and keep one provider everywhere.

Sources consulted: [command palette patterns](https://uxpatterns.dev/patterns/advanced/command-palette),
[designing command palettes](https://solomon.io/designing-command-palettes/),
[Mobbin command palette guide](https://mobbin.com/glossary/command-palette),
[fuzzy matching algorithms](https://redis.io/blog/what-is-fuzzy-matching/),
[company-name→ticker matching](https://site.financialmodelingprep.com/how-to/how-to-match-company-names-to-tradable-symbols-using-a-free-api),
[StocksTalk: NL→structured screening queries](https://arxiv.org/html/2608.18105).
