"""The studies' own modules, imported rather than copied: a paper trade is produced by the code that produced
the backtest. In the image they sit at /app/backend/research/<study>/, the same relative place as in the repo."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(os.getenv("PREMIUM_REPO_ROOT") or Path(__file__).resolve().parents[1])
RESEARCH = ROOT / "backend" / "research"
sys.path.insert(0, str(RESEARCH / "youtube_top20_2026_11"))
sys.path.insert(0, str(RESEARCH / "booming_bulls_2026_11"))
sys.path.insert(0, str(RESEARCH / "crypto_playlist_2026_11"))
sys.path.insert(0, str(RESEARCH / "youtube_channels11_2026_11"))
sys.path.insert(0, str(RESEARCH / "youtube_channels20_2026_11"))

import bb_engine as BE  # noqa: E402
import bb_markets as BM  # noqa: E402
import bb_strategies as BS  # noqa: E402
import yt_engine as YE  # noqa: E402
import yt_markets as YM  # noqa: E402
import yt_strategies as YS  # noqa: E402
import cp_markets as CPM  # noqa: E402
import cp_strategies as CS  # noqa: E402
import yc_run as YCR  # noqa: E402
import yc_strategies as YCS  # noqa: E402
import zc_strategies as ZCS  # noqa: E402,F401  (adds the 20-channel strategies to YCS.STRATEGIES)

_spec = importlib.util.spec_from_file_location("ii_data", ROOT / "backend" / "app" / "services" / "index_intraday" / "data.py")
II = importlib.util.module_from_spec(_spec)     # the app's own index-minute cleaner, without importing the app
sys.modules["ii_data"] = II
_spec.loader.exec_module(II)
