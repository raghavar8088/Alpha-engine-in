"""One-off: bar files -> per-day panel (D:/premium_intraday_data/panel). About 2 minutes."""
import time

from common import DATA, PANEL
from pis.replay import build_panel

if __name__ == "__main__":
    t = time.time()
    print(build_panel(DATA, str(PANEL)), f"{time.time() - t:.0f}s")
