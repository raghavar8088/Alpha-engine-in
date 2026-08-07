"""Pure Angel One protocol helpers — no HTTP client bundled, so the async and sync
transports share exactly the same auth, batching and parsing logic.

Everything the two clients had in common lives here: endpoint paths, the TOTP + login
payload/response shape, JWT expiry, the 50-token batch chunking, and the LTP/FULL quote
row parsing. The transports (`rest_async.py` httpx, `rest_sync.py` requests) only differ
in how they make the POST.
"""

import base64
import json

import pyotp

# --- endpoints ---
LOGIN_PATH = "/rest/auth/angelbroking/user/v1/loginByPassword"
QUOTE_PATH = "/rest/secure/angelbroking/market/v1/quote"
CANDLE_PATH = "/rest/secure/angelbroking/historical/v1/getCandleData"
ORDER_PATH = "/rest/secure/angelbroking/order/v1/placeOrder"  # SmartAPI order placement

# Angel caps a quote request at 50 tokens; chunk anything larger.
QUOTE_BATCH_SIZE = 50
# Refresh the session a little before the JWT actually lapses.
SESSION_REFRESH_MARGIN_SECONDS = 10 * 60

# TradingView-ish resolution -> Angel interval name.
ANGEL_INTERVALS = {
    "1": "ONE_MINUTE",
    "5": "FIVE_MINUTE",
    "15": "FIFTEEN_MINUTE",
    "60": "ONE_HOUR",
    "D": "ONE_DAY",
}


class AngelAPIError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def totp_now(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def client_headers(api_key: str, public_ip: str, jwt: str | None = None) -> dict:
    """Angel rejects requests missing the client-info headers, even though the values
    aren't verified — the public IP must match a whitelisted one."""
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": public_ip or "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": api_key,
    }
    if jwt:
        h["Authorization"] = f"Bearer {jwt}"
    return h


def login_payload(client_code: str, pin: str, totp: str) -> dict:
    return {"clientcode": client_code, "password": pin, "totp": totp}


def parse_session(body: dict, status_code: int) -> dict:
    """jwt + feedToken + refreshToken from a loginByPassword response, or raise.

    `feed_token` is captured here even though only the (future) WebSocket stream needs it:
    it arrives in this same login response, so there is no separate feed-token call to make
    — the old clients simply discarded it.
    """
    data = (body.get("data") or {}) if isinstance(body, dict) else {}
    jwt = data.get("jwtToken")
    if not jwt:
        raise AngelAPIError(
            f"Angel login failed: {(body or {}).get('message') or (body or {}).get('errorcode') or status_code}"
        )
    return {
        "jwt": jwt.replace("Bearer ", ""),
        "feed_token": data.get("feedToken"),
        "refresh_token": data.get("refreshToken"),
    }


def jwt_expiry(token: str) -> float | None:
    """`exp` off Angel's JWT. Unverified decode — Angel validates it server-side; we only
    need to know when to log in again."""
    try:
        seg = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
        exp = payload.get("exp")
        return float(exp) if exp else None
    except Exception:
        return None


def batches(tokens_by_exchange: dict[str, list[str]], size: int = QUOTE_BATCH_SIZE):
    """Yield `{exchange: [tokens]}` chunks of at most `size` tokens total, preserving the
    exchange grouping Angel's quote endpoint expects."""
    flat = [(ex, t) for ex, toks in tokens_by_exchange.items() for t in toks]
    for i in range(0, len(flat), size):
        grouped: dict[str, list[str]] = {}
        for ex, t in flat[i : i + size]:
            grouped.setdefault(ex, []).append(t)
        yield grouped


def parse_ltp(body: dict) -> dict[str, float]:
    """LTP-mode quote body -> {token: last_price}. Missing/illiquid tokens are simply
    absent, so callers can tell "no price" from "price is 0"."""
    out: dict[str, float] = {}
    for row in (body.get("data") or {}).get("fetched") or []:
        token, price = row.get("symbolToken"), row.get("ltp")
        if token is not None and price is not None:
            out[str(token)] = float(price)
    return out


def parse_full(body: dict) -> dict[str, dict]:
    """FULL-mode quote body -> {token: {ltp, open, high, low, close, volume, oi}}. FULL
    mode carries the day OHLC, traded volume AND open interest (for F&O) that LTP mode
    does not — the OI is what an option chain needs for PCR / max-pain."""
    out: dict[str, dict] = {}
    for row in (body.get("data") or {}).get("fetched") or []:
        token, ltp = row.get("symbolToken"), row.get("ltp")
        if token is None or ltp is None:
            continue
        out[str(token)] = {
            "ltp": float(ltp),
            "open": float(row["open"]) if row.get("open") else None,
            "high": float(row["high"]) if row.get("high") else None,
            "low": float(row["low"]) if row.get("low") else None,
            "close": float(row["close"]) if row.get("close") else None,
            "volume": float(row.get("tradeVolume") or 0),
            "oi": float(row.get("opnInterest") or 0),
        }
    return out
