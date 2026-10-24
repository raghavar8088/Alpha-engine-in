"""Re-fetch the cached MCX bhavcopy of every contract that was still trading at the last download,
so the data runs to `today`. Finished contracts are never touched.

    python refresh_mcx.py <data_dir> <today yyyy-mm-dd> <live_since yyyy-mm-dd>

A contract is refreshed when its expiry is on or after `live_since` and it was already listed
by `today`. Uses download_mcx's own fetch (curl_cffi, Chrome impersonation, same pacing).
"""
import gzip
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
DATA, TODAY, SINCE = sys.argv[1], datetime.strptime(sys.argv[2], "%Y-%m-%d"), datetime.strptime(sys.argv[3], "%Y-%m-%d")
sys.argv = [sys.argv[0], DATA]          # download_mcx reads its data dir from argv at import
import download_mcx as D  # noqa: E402

D.TODAY = TODAY


def main():
    ex = json.load(open(os.path.join(HERE, "..", "expiries.json")))
    tasks = []
    for sym in ("CRUDEOILM", "NATGASMINI", "NATURALGAS", "CRUDEOIL"):
        for inst in ("OPTFUT", "FUTCOM"):
            for e in ex[f"{inst}:{sym}"]:
                ed = datetime.strptime(e, "%d%b%Y")
                if ed < SINCE or ed - timedelta(days=D.LIFE_DAYS[inst]) > TODAY:
                    continue
                if inst == "FUTCOM" and ed < D.FUT_FROM[sym]:
                    continue
                tasks.append((inst, sym, e))
    D.log(f"refresh to {TODAY.date()}: {len(tasks)} live contracts")
    s = D.session()
    for n, (inst, sym, e) in enumerate(tasks, 1):
        path = os.path.join(DATA, inst, sym, f"{e}.json.gz")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for attempt in range(4):
            try:
                rows = D.fetch(s, inst, sym, e)
                with gzip.open(path + ".tmp", "wt", encoding="utf-8") as fh:
                    json.dump(rows, fh, separators=(",", ":"))
                os.replace(path + ".tmp", path)
                last = max((r["Date"] for r in rows), default=None)
                D.log(f"refreshed {inst} {sym} {e}: {len(rows)} rows, last {last} ({n}/{len(tasks)})")
                break
            except Exception as exc:  # noqa: BLE001
                D.log(f"retry {attempt + 1} {inst} {sym} {e}: {exc}")
                time.sleep(15 * (attempt + 1))
                s = D.session()
        time.sleep(1.5 + random.random())
    D.log("refresh finished")


if __name__ == "__main__":
    main()
