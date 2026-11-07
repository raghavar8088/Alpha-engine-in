"""The Premium Strategies paper desk's supervisor: decides which group of books is due and runs it as a separate short
process, one at a time and at low priority, so a cycle's memory returns to the box the moment it ends.

Paper only. Nothing in this service can reach a broker: it reads bars and writes its own database.

Main Control: when the `premium_strategies` module is OFF, no cycle runs. If the backend cannot say, it fails open. A
session missed while OFF is replayed when switched back on, as far as its bars are still available.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import ledger as L
from settings import APP_SECRET, BACKEND, now_ist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("premium.main")
HERE = Path(__file__).resolve().parent
TIMEOUT_S = {"index": 300, "stocks": 900, "global": 900, "daily": 900}
MODULE = "premium_strategies"


def switch_on() -> bool:
    try:
        req = urllib.request.Request(f"{BACKEND}/api/main-control", headers={"x-app-secret": APP_SECRET} if APP_SECRET else {})
        with urllib.request.urlopen(req, timeout=20) as r:
            mods = json.load(r).get("modules") or []
        for m in mods:
            if m.get("module") == MODULE:
                return bool(m.get("enabled", True))
    except Exception as exc:  # noqa: BLE001 - a control plane that cannot decide lets work through
        log.info("main control unreadable (%s): carrying on", exc)
    return True


def interval_s(group: str) -> int:
    """How often a group is worth running now (IST). A cycle with no new bars ends after one cheap check."""
    now = now_ist()
    hhmm, weekday = now.strftime("%H:%M"), now.weekday()
    session = weekday < 5 and "09:15" <= hhmm <= "15:45"
    if group == "index":
        return 300 if session else 1800
    if group == "stocks":
        return 900 if session else 3600
    if group == "global":
        closed = weekday == 6 or (weekday == 5 and hhmm >= "04:00") or (weekday == 0 and hhmm < "03:00")
        return 3600 if closed else 600
    return 3600


def run(group: str) -> None:
    t0 = time.time()
    try:
        p = subprocess.run(["nice", "-n", "10", sys.executable, str(HERE / "cycle.py"), group], cwd=HERE, timeout=TIMEOUT_S[group])
        log.info("%s exited %s after %.0fs", group, p.returncode, time.time() - t0)
    except subprocess.TimeoutExpired:
        log.warning("%s killed after %ss", group, TIMEOUT_S[group])
    except Exception:  # noqa: BLE001
        log.exception("%s could not start", group)


def main() -> None:
    log.info("premium paper desk starting")
    try:
        db = L.database()
        L.ensure_indexes(db)
        L.update_accounts(db)           # every account visible from the first minute, at Rs 10 lakh
        db.client.close()
    except Exception:  # noqa: BLE001 - never die on start; the next cycle will try again
        log.exception("startup")
    last = {g: 0.0 for g in TIMEOUT_S}
    while True:
        try:
            due = [g for g in ("index", "stocks", "global", "daily") if time.time() - last[g] >= interval_s(g)]
            if due and switch_on():
                for g in due:
                    last[g] = time.time()
                    run(g)
        except Exception:  # noqa: BLE001
            log.exception("loop")
        time.sleep(20)


if __name__ == "__main__":
    main()
