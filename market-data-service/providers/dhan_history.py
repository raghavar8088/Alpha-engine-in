"""Dhan historical-data provider — the first real DataProvider implementation.

Request/response shapes follow the official DhanHQ-py SDK (DhanHQ-py/src/dhanhq/
_historical_data.py): POST /charts/historical for daily candles, POST /charts/intraday
for 1/5/15/60-minute candles; both return parallel arrays (open/high/low/close/volume/
timestamp[, open_interest]). Sync (requests) to match the rest of this service."""

import time
from datetime import datetime, timedelta, timezone

import requests

from tradingai_shared.contracts import DataProvider
from tradingai_shared.domain import AssetClass, Bar, Instrument, Timeframe

DHAN_BASE_URL = "https://api.dhan.co/v2"
# Dhan v2 caps one intraday request at 90 days; stay under it.
INTRADAY_CHUNK_DAYS = 75
# Data APIs are rate-limited; brief pause between chunked requests.
REQUEST_GAP_SECONDS = 0.4

# Dhan's `instrument` field for the charts endpoints, from our asset class.
_INSTRUMENT_TYPE = {
    AssetClass.EQUITY: "EQUITY",
    AssetClass.ETF: "EQUITY",
    AssetClass.INDEX: "INDEX",
    AssetClass.EQUITY_FUTURE: "FUTSTK",
    AssetClass.INDEX_FUTURE: "FUTIDX",
    AssetClass.EQUITY_OPTION: "OPTSTK",
    AssetClass.INDEX_OPTION: "OPTIDX",
    AssetClass.COMMODITY_FUTURE: "FUTCOM",
    AssetClass.COMMODITY_OPTION: "OPTFUT",
}


class DhanHistoryProvider(DataProvider):
    def __init__(self, client_id: str, access_token: str):
        self.headers = {
            "access-token": access_token,
            "client-id": client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_history(
        self, instrument: Instrument, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        if timeframe == Timeframe.W1:
            return _aggregate_weekly(self.get_history(instrument, Timeframe.D1, start, end))
        if timeframe == Timeframe.D1:
            candles = self._fetch(
                "/charts/historical", instrument, start, end, extra={"expiryCode": 0}
            )
        else:
            candles = []
            chunk_start = start
            while chunk_start < end:
                chunk_end = min(chunk_start + timedelta(days=INTRADAY_CHUNK_DAYS), end)
                candles.append(
                    self._fetch(
                        "/charts/intraday",
                        instrument,
                        chunk_start,
                        chunk_end,
                        extra={"interval": timeframe.dhan_interval},
                    )
                )
                chunk_start = chunk_end
                time.sleep(REQUEST_GAP_SECONDS)
        return _to_bars(instrument.symbol, timeframe, candles)

    def _fetch(
        self, path: str, instrument: Instrument, start: datetime, end: datetime, extra: dict
    ) -> dict:
        wants_oi = instrument.asset_class in (
            AssetClass.EQUITY_FUTURE,
            AssetClass.INDEX_FUTURE,
            AssetClass.EQUITY_OPTION,
            AssetClass.INDEX_OPTION,
        )
        payload = {
            "securityId": instrument.security_id,
            "exchangeSegment": instrument.exchange_segment.value,
            "instrument": _INSTRUMENT_TYPE[instrument.asset_class],
            "oi": wants_oi,
            "fromDate": start.strftime("%Y-%m-%d"),
            "toDate": end.strftime("%Y-%m-%d"),
            **extra,
        }
        for attempt in range(3):
            response = requests.post(
                f"{DHAN_BASE_URL}{path}", json=payload, headers=self.headers, timeout=30
            )
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2**attempt)
                continue
            break
        data = response.json()
        if response.status_code >= 300 or (isinstance(data, dict) and data.get("status") == "failure"):
            detail = data.get("remarks") or data.get("errorMessage") if isinstance(data, dict) else None
            raise RuntimeError(
                f"Dhan {path} failed for {instrument.symbol}: {detail or response.status_code}"
            )
        return data


def _to_bars(symbol: str, timeframe: Timeframe, candles: dict | list) -> list[Bar]:
    """Dhan returns parallel arrays; an empty/absent timestamp array means no data
    (e.g. weekends-only range), which is not an error."""
    if isinstance(candles, list):  # chunked intraday: merge per-chunk dicts
        merged: dict[str, list] = {}
        for chunk in candles:
            for key, values in chunk.items():
                merged.setdefault(key, []).extend(values or [])
        candles = merged
    timestamps = candles.get("timestamp") or []
    oi_values = candles.get("open_interest") or [None] * len(timestamps)
    bars = [
        Bar(
            symbol=symbol,
            timeframe=timeframe,
            ts=datetime.fromtimestamp(timestamps[i], tz=timezone.utc),
            open=candles["open"][i],
            high=candles["high"][i],
            low=candles["low"][i],
            close=candles["close"][i],
            volume=int(candles["volume"][i] or 0),
            oi=int(oi_values[i]) if oi_values[i] else None,
        )
        for i in range(len(timestamps))
    ]
    bars.sort(key=lambda b: b.ts)
    return bars


def _aggregate_weekly(daily: list[Bar]) -> list[Bar]:
    """Roll daily bars into ISO-week candles locally — Dhan has no weekly endpoint."""
    weeks: dict[tuple[int, int], list[Bar]] = {}
    for bar in daily:
        iso = bar.ts.isocalendar()
        weeks.setdefault((iso.year, iso.week), []).append(bar)
    weekly = []
    for _, group in sorted(weeks.items()):
        weekly.append(
            Bar(
                symbol=group[0].symbol,
                timeframe=Timeframe.W1,
                ts=group[0].ts,  # week opens at its first trading day
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            )
        )
    return weekly
