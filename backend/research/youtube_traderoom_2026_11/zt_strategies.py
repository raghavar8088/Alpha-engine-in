"""The Trade Room study's strategies (15 Nov 2026), added to the 11-channel registry (yc_strategies) so yc_run runs them
unchanged: the same signal conventions, fill engine, daily limits and forced exits as every channel book on the paper
desk. The TR prefix is already The Trade Room's in that registry (TR-01, 9 Nov 2026); these are new ids.

Every record is version v1: a changed rule or number is a new version, never an edit of v1. readiness "assumptions" =
coded with the A rules in zt_spec.py, shown on the app's tab next to the stated (E) and inferred (I) ones.

    import zt_strategies   # registers the records; then yc_run.run(sid, market, m, cache) works for them
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
for _p in (HERE, RESEARCH / "youtube_channels11_2026_11", RESEARCH / "youtube_top20_2026_11",
           RESEARCH / "booming_bulls_2026_11", RESEARCH / "crypto_playlist_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import yc_strategies as YS  # noqa: E402
from yc_strategies import YC  # noqa: E402
from yt_engine import Limits  # noqa: E402

import zt_traderoom as Z  # noqa: E402

SOURCE = "youtube_traderoom"
STUDY = "youtube_traderoom_2026_11"
A = "assumptions"
L3 = Limits(3, False, False)                       # three trades a day, one position at a time (episode 1)
TR01_LIMITS = Limits(4, False, False, 2)           # TR-01's own: four a day, none after two stops

_NEW = [
    YC("TR-02", "Daily EMA 9 side, a 5-minute supply or demand box, one of three entry candles, candle stop, 1:2, three "
       "trades a day", Z.tr02, Z.tr02_x, ("NIFTY", "BANKNIFTY"), (5,), L3, readiness=A),
    YC("TR-03", "Momentum candle through the EMA 9 and 15: a limit at its 50%, the stop beyond it, 1:2 (15 minutes)",
       Z.tr03, Z.tr03_x, ("BTCUSD", "XAUUSD"), (15,), L3, readiness=A),
    YC("TR-04", "TR-01's EMA 9/15 three-candle scalp on Delta gold and bitcoin (15 minutes)", Z.tr04, Z.tr04_x,
       ("BTCUSD", "XAUUSD"), (15,), TR01_LIMITS, readiness=A),
]
NEW = [r.sid for r in _NEW]
VIDEO = {"TR-02": "TU88i946Bgw", "TR-03": "egPhH9jaylo", "TR-04": "RMwUsnJB40c"}

for _rec in _NEW:
    _rec.version = "v1"
    if _rec.sid in YS.STRATEGIES and YS.STRATEGIES[_rec.sid] is not _rec:
        raise RuntimeError(f"{_rec.sid} is already registered by another study")
    YS.STRATEGIES[_rec.sid] = _rec
