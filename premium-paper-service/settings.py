"""Settings of the Premium Strategies paper desk. Everything is an environment variable so a dry run on other
dates or another database cannot touch the real ledger."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = timezone(timedelta(hours=5, minutes=30))
NY = ZoneInfo("America/New_York")

PAPER_START = date.fromisoformat(os.getenv("PREMIUM_PAPER_START", "2026-11-09"))
CAPITAL = float(os.getenv("PREMIUM_CAPITAL", "1000000"))        # Rs 10 lakh per strategy
# The bitcoin books (Delta Exchange BTCUSD) trade from this moment, asked for on 8 Nov 2026 ("start from now");
# bitcoin trades all week, so they do not wait for Monday. Nothing before it is back-filled.
BTC_START_T = int(datetime.fromisoformat(os.getenv("PREMIUM_BTC_START", "2026-11-08T11:00:00+00:00")).timestamp())
BTC_START_DATE = datetime.fromtimestamp(BTC_START_T, timezone.utc).date()
# The Sniper-headshot books (sniper.py), asked for on 8 Nov 2026 "for the live trading", trade bitcoin forward from
# this moment, flat at the start; nothing before it is back-filled.
SH_START_T = int(datetime.fromisoformat(os.getenv("PREMIUM_SH_START", "2026-11-08T16:30:00+00:00")).timestamp())
SH_START_DATE = datetime.fromtimestamp(SH_START_T, timezone.utc).date()
# The 11-channel books (catalog.YC_STRATEGIES) trade every market forward from this moment, flat at the start; nothing
# before it is back-filled. Bitcoin's books need longer history for their indicators (EMA 200 on 4-hour candles).
YC_START_T = int(datetime.fromisoformat(os.getenv("PREMIUM_YC_START", "2026-11-09T10:00:00+00:00")).timestamp())
YC_START_DATE = datetime.fromtimestamp(YC_START_T, IST).date()
YC_BTC_WARM_DAYS = 150
# The 20-channel books (catalog.YC2_STRATEGIES; backend/research/youtube_channels20_2026_11) trade forward from their
# activation, flat at the start: indicators warm up on earlier bars, but no earlier signal ever becomes a trade.
YC2_START_T = int(datetime.fromisoformat(os.getenv("PREMIUM_YC2_START", "2026-11-09T21:45:00+00:00")).timestamp())
# the earlier of its IST and UTC dates: bitcoin days are UTC dates, NSE days IST dates (entries still start at YC2_START_T)
YC2_START_DATE = min(datetime.fromtimestamp(YC2_START_T, IST).date(), datetime.fromtimestamp(YC2_START_T, timezone.utc).date())
YC2_LATE_S = {"daily": 2 * 86400, "stocks": 1800, "index": 1200, "global": 1200}   # see cycle._fresh_only

MONGO_URL = os.getenv("FACTORY_MONGO_URL", "").strip()
MONGO_DB = os.getenv("PREMIUM_MONGO_DB", "alpha_engine_premium")
DATA = Path(os.getenv("PREMIUM_DATA_DIR", "/data/premium"))
INTRADAY = Path(os.getenv("INTRADAY_DATA_DIR", "/data/intraday"))
BACKEND = os.getenv("PREMIUM_BACKEND_URL", "http://backend:8080").rstrip("/")
APP_SECRET = os.getenv("APP_SHARED_SECRET", "").strip()

# A session's bars are final (Angel's candles have replaced the stream's) by this time in the evening.
NSE_FINAL_HHMM = "17:30"
WARM_SESSIONS = {"index": 60, "global": 30, "stocks": 30}
DAILY_WARM_DAYS = 700           # calendar days before the first paper day, for the 200-day averages


def now_ist() -> datetime:
    return datetime.now(IST)


def now_ny() -> datetime:
    return datetime.now(NY)
