"""Download MCX's official bhavcopy history for the OTHER MCX option markets (A5): every option
expiry of GOLD, SILVER, COPPER, ZINC, NICKEL, GOLDM and SILVERM, plus the futures that underlie
them. Same endpoint, pacing and gzip cache as download_mcx.py; resumable.

    python download_more.py <data_dir> <today yyyy-mm-dd>
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
DATA, TODAY = sys.argv[1], datetime.strptime(sys.argv[2], "%Y-%m-%d")
sys.argv = [sys.argv[0], DATA]          # download_mcx reads its data dir from argv at import
import download_mcx as D  # noqa: E402

D.TODAY = TODAY
SYMS = ("GOLD", "SILVER", "COPPER", "ZINC", "NICKEL", "GOLDM", "SILVERM")


def tasks():
    ex = json.load(open(os.path.join(HERE, "expiries5.json")))
    out = []
    for sym in SYMS:
        opts = [datetime.strptime(e, "%d%b%Y") for e in ex[f"OPTFUT:{sym}"]]
        listed = [e for e in opts if e - timedelta(days=D.LIFE_DAYS["OPTFUT"]) <= TODAY]
        out += [("OPTFUT", sym, e.strftime("%d%b%Y").upper()) for e in listed]
        lo, hi = min(listed) - timedelta(days=5), max(listed) + timedelta(days=70)
        for e in ex[f"FUTCOM:{sym}"]:
            ed = datetime.strptime(e, "%d%b%Y")
            if lo <= ed <= hi and ed - timedelta(days=D.LIFE_DAYS["FUTCOM"]) <= TODAY:
                out.append(("FUTCOM", sym, e))
    return out


def main():
    todo = tasks()
    D.log(f"other markets: {len(todo)} contracts")
    s, done = D.session(), 0
    for n, (inst, sym, e) in enumerate(todo, 1):
        path = os.path.join(DATA, inst, sym, f"{e}.json.gz")
        if os.path.exists(path):
            done += 1
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
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
    D.log(f"finished: {done}/{len(todo)} on disk")


if __name__ == "__main__":
    main()
