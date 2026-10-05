"""Run the Commodity Lab (C4). A JOB, not part of the API process: replaying the daily
templates over 22 years of five commodities is a few minutes of CPU the web worker must
not spend.

    docker run --rm ... alpha-engine-backend python -m app.services.commodity_lab_job [--no-refresh]

Fetches fresh history (Yahoo, FRED; cached in `commodity_lab_history`), evaluates every
trial, writes the run to `commodity_lab_runs`, the per-candidate verdicts to
`commodity_lab_verdicts`, and grows the trial registry (`commodity_lab_trials`). Then the
pre-registered hypotheses (commodity_hypotheses) are re-evaluated against the new history.
"""

from __future__ import annotations

import argparse
import asyncio
import json


async def main(refresh: bool) -> dict:
    from app.services.commodity_lab import run

    out = await run(refresh_data=refresh)
    try:
        from app.services.commodity_hypotheses import evaluate_all

        out["hypotheses"] = await evaluate_all()
    except Exception as exc:  # noqa: BLE001 — the Lab run stands even if the registry pass fails
        out["hypotheses_error"] = str(exc)[:300]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-refresh", action="store_true")
    a = ap.parse_args()
    res = asyncio.run(main(not a.no_refresh))
    top = [{k: r.get(k) for k in ("key", "dsr", "heldout", "alpha", "feasible_legs", "passes_history")}
           for r in res.get("candidates", [])[:12]]
    print(json.dumps({k: res.get(k) for k in ("fetch", "data_span", "n_trials_registry", "pbo", "passed_history",
                                                 "verdict_counts", "benchmark", "hypotheses", "hypotheses_error")},
                     default=str, indent=1))
    print(json.dumps(top, default=str, indent=1))
