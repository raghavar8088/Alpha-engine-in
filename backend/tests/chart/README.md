# Chart module verification

This repo has no pytest/jest setup for its own services, so these are plain
runnable scripts rather than a framework suite — run them directly.

They cover the parts of the Chart module where being wrong is silent: indicator
maths, cache freshness rules, structural analysis, and the HTTP surface.

## Running

Backend scripts need the backend's dependencies importable and a Fernet key
(any valid one — nothing is decrypted here):

```bash
cd backend
export BROKER_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

python tests/chart/verify_structure.py   # Phase 6: S/R zones, channel fit, swing structure
python tests/chart/verify_cache.py       # Phase 3/4: TTL freshness rules, session hours, merge
python tests/chart/verify_api.py         # all phases: real FastAPI app, faked Mongo/Redis/Dhan
```

Frontend indicator maths:

```bash
cd frontend
npx tsc app/chart/__tests__/verify_indicators.ts app/chart/indicators.ts \
  --outDir /tmp/charttest --module commonjs --target es2020 --strict
# tsc mirrors the source tree under --outDir, so the entry point keeps its
# __tests__/ segment:
node /tmp/charttest/__tests__/verify_indicators.js
```

Each script prints one PASS/FAIL line per check and exits non-zero on failure.

## What they do and don't prove

`verify_structure.py`, `verify_cache.py` and `verify_indicators.ts` test pure
functions and prove real behaviour: EMA/RSI/MACD/Bollinger/Supertrend against
hand-computed values, that a repeatedly-tested level clusters into a multi-touch
zone, that an MCX contract's 21:00 IST candle is still treated as live while an
equity's is not.

`verify_api.py` runs the actual FastAPI app with in-memory fakes for Mongo,
Redis and Dhan. It proves routing, validation and response shapes — an option
chart requests `instrument=OPTIDX`, a `crosses_above` alert fires only on a real
upward cross and never twice, overlays are scoped to one instrument. It does
**not** prove anything about real Dhan responses; the fakes return synthetic
candles.

The one thing no script here can settle is the epoch convention in
`chart_stream.bar_epoch` — whether Dhan's chart timestamps read as UTC or as IST
wall-clock. That needs one live intraday chart during market hours. The frontend
is written so a wrong guess degrades to "stream won't merge, chart re-pulls
history" with a visible `LIVE · resyncing` pill, rather than drawing a candle at
the wrong time.
