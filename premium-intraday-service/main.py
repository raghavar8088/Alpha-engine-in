"""Premium Intraday Strategies paper desk (Premium Strategies -> Premium Intraday Strategies).

Runs in its own container (compose service premium-intraday): its own scheduler, database, paper books, risk
limits, logs and switch. Paper only: no broker client is installed and no broker credential is passed in.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, "/app/shared"):
    if p not in sys.path and os.path.isdir(p):
        sys.path.insert(0, p)

from pis.live.worker import main  # noqa: E402

if __name__ == "__main__":
    main()
