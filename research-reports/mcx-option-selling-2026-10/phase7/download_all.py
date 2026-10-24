"""Download MCX's official bhavcopy for EVERY futures contract of the nine A7 commodities (bullion,
base metals, energy) since each market opened. Same endpoint, pacing
and gzip cache as download_mcx.py; resumable; contracts already on disk are reused.

    python download_all.py <data_dir> <today yyyy-mm-dd> [<reuse_dir> ...]
"""
import gzip
import json
import os
import random
import shutil
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
DATA, TODAY, REUSE = sys.argv[1], datetime.strptime(sys.argv[2], "%Y-%m-%d"), sys.argv[3:]
sys.argv = [sys.argv[0], DATA]          # download_mcx reads its data dir from argv at import
import download_mcx as D  # noqa: E402

D.TODAY = TODAY
SYMS = ("GOLD", "SILVER", "COPPER", "NICKEL", "ALUMINIUM", "ZINC", "LEAD", "CRUDEOIL", "NATURALGAS")


def main():
    ex = json.load(open(os.path.join(HERE, "expiries7.json")))
    todo = []
    for sym in SYMS:
        for e in ex[f"FUTCOM:{sym}"]:
            if datetime.strptime(e, "%d%b%Y") - timedelta(days=D.LIFE_DAYS["FUTCOM"]) <= TODAY:
                todo.append(("FUTCOM", sym, e))
    D.log(f"futures history: {len(todo)} contracts")
    s, done, reused = D.session(), 0, 0
    for n, (inst, sym, e) in enumerate(todo, 1):
        path = os.path.join(DATA, inst, sym, f"{e}.json.gz")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            done += 1
            continue
        src = next((os.path.join(r, inst, sym, f"{e}.json.gz") for r in REUSE
                    if os.path.exists(os.path.join(r, inst, sym, f"{e}.json.gz"))), None)
        if src and datetime.strptime(e, "%d%b%Y") < TODAY - timedelta(days=3):
            shutil.copyfile(src, path)          # a finished contract fetched earlier: identical, reuse it
            done += 1
            reused += 1
            continue
        for attempt in range(4):
            try:
                rows = D.fetch(s, inst, sym, e)
                with gzip.open(path + ".tmp", "wt", encoding="utf-8") as fh:
                    json.dump(rows, fh, separators=(",", ":"))
                os.replace(path + ".tmp", path)
                done += 1
                D.log(f"ok {inst} {sym} {e}: {len(rows)} rows ({n}/{len(todo)})")
                break
            except Exception as exc:  # noqa: BLE001
                D.log(f"retry {attempt + 1} {inst} {sym} {e}: {exc}")
                time.sleep(15 * (attempt + 1))
                try:
                    s = D.session()
                except Exception as exc2:  # noqa: BLE001
                    D.log(f"re-warm failed: {exc2}")
        time.sleep(1.5 + random.random())
    D.log(f"finished: {done}/{len(todo)} on disk ({reused} reused from earlier downloads)")


if __name__ == "__main__":
    main()
