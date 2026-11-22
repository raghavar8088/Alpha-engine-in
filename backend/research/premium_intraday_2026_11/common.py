"""Shared setup for the research scripts: import the desk's own package (premium-intraday-service/pis) so replay
and the live desk run the same code, and fix the data locations."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "premium-intraday-service"
if str(SERVICE) not in sys.path:
    sys.path.insert(0, str(SERVICE))

DATA = os.getenv("PIS_RESEARCH_DATA", "D:/intraday_ai_data/intraday")       # bars, NSE archives, announcements
WORK = Path(os.getenv("PIS_RESEARCH_WORK", "D:/premium_intraday_data"))      # panel, runs (never committed)
PANEL = WORK / "panel"
RUNS = WORK / "runs"
HERE = Path(__file__).resolve().parent

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
