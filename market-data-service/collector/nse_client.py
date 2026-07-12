import requests


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    return float(str(value).replace(",", ""))


NSE_BASE_URL = "https://www.nseindia.com"
LIVE_INDICES_URL = "https://iislliveblob.niftyindices.com/jsonfiles/LiveIndicesWatch.json"

HEADERS = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
    ),
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
}


class NSEClient:
    """Thin wrapper around NSE's public JSON endpoints (no API key required).

    Index quotes come from niftyindices.com's public live-watch feed (no cookies needed).
    Equity quotes come from nseindia.com and require session cookies obtained by first
    visiting the homepage and the option-chain page, matching how browsers establish
    them - hitting the API cold returns 403.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._warmed_up = False

    def _warm_up(self) -> None:
        self._session.get(NSE_BASE_URL, timeout=10)
        self._session.get(f"{NSE_BASE_URL}/option-chain", timeout=10)
        self._warmed_up = True

    def _get_nse(self, path: str) -> dict:
        if not self._warmed_up:
            self._warm_up()
        resp = self._session.get(f"{NSE_BASE_URL}{path}", timeout=10)
        if resp.status_code != 200:
            self._warmed_up = False
            resp.raise_for_status()
        return resp.json()

    def get_index_quote(self, index_name: str) -> dict | None:
        resp = self._session.get(LIVE_INDICES_URL, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        for row in payload.get("data", []):
            if row.get("indexName", "").upper() == index_name.upper():
                last = _to_float(row["last"])
                previous_close = _to_float(row["previousClose"])
                change = last - previous_close if last is not None and previous_close is not None else None
                return {
                    "symbol": index_name,
                    "price": last,
                    "change": change,
                    "pct_change": _to_float(row.get("percChange")),
                    "volume": None,
                }
        return None

    def get_equity_quote(self, symbol: str) -> dict | None:
        """Not used by the default watchlist: nseindia.com's quote-equity endpoint sits
        behind an Akamai WAF that returns 403 to non-browser clients regardless of
        cookies/TLS-impersonation. Kept for Phase 2+ once a real browser session or
        licensed data source is available."""
        symbol = symbol.replace("&", "%26")
        data = self._get_nse(f"/api/quote-equity?symbol={symbol.upper()}")
        price_info = data.get("priceInfo", {})
        if not price_info:
            return None
        return {
            "symbol": symbol.upper(),
            "price": price_info.get("lastPrice"),
            "change": price_info.get("change"),
            "pct_change": price_info.get("pChange"),
            "volume": data.get("securityWiseDP", {}).get("quantityTraded"),
        }
