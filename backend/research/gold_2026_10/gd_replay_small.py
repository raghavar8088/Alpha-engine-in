"""Run the replay's small jobs first, beside the main run (which is busy with the 1m series).

    python backend/research/gold_2026_10/gd_replay_small.py [N]

The MCX histories (C_GC, D_GOLDM, E_GCD) and the higher timeframes of the 24/7 histories, so
their analysis can start while the one-minute jobs are still running. Deterministic: the main
run later rewrites the same files with identical content.
"""

import sys
import time
from multiprocessing import Pool

import gd_replay as R


def main() -> None:
    from app.services.commodity_patterns import COMMODITY_CATALOG

    want = []
    for ds, cfg in R.DATASETS.items():
        for tf in cfg["tfs"]:
            small = ds in ("C_GC", "D_GOLDM", "E_GCD") or tf in ("15m", "30m", "45m", "1h", "4h", "1d")
            if not small or not (R.BARS / f"{ds}__{tf}.npz").exists():
                continue
            temps = tuple(s.template for s in COMMODITY_CATALOG if s.timeframe == tf
                          and not (R.OUT / f"{ds}__{tf}__{s.template}.npz").exists())
            if temps:
                want.append((ds, tf, temps))
    print(f"{len(want)} small jobs", flush=True)
    t0 = time.time()
    with Pool(int(sys.argv[1]) if len(sys.argv) > 1 else 4) as pool:
        for k, r in enumerate(pool.imap_unordered(R.run_job, want), 1):
            print(f"[{k}/{len(want)} {time.time() - t0:6.0f}s] {r}", flush=True)
    print("done", round(time.time() - t0), "s", flush=True)


if __name__ == "__main__":
    main()
