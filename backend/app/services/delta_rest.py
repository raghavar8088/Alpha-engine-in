"""Delta Exchange India REST client for the Premium real-money desk (premium_live, 2026-11-13).

A port of the antigravity engine's Go client (engine/internal/delta), which placed real orders on Delta India in
July-August 2026. Every lesson that client documents is kept:

- Signature = HMAC-SHA256(secret, METHOD + timestamp + path-with-query + body); headers api-key, timestamp, signature.
- Protective orders go to POST /v2/orders/bracket, on a position that already exists; on the entry order Delta
  rejected every one. Each leg needs a trigger AND a limit. The stop's limit sits PAST its trigger by 20% of the stop
  distance (at least 2 ticks): a stop-limit at its own trigger was left unfilled when the price gapped through it.
  Triggers use the last traded price, not the mark.
- Prices are printed to the tick's own decimals. Float noise such as 0.012860000000000001 made Delta refuse a
  stop, leaving the position unprotected.
- Leverage is a per-product account setting (POST /v2/products/{id}/orders/leverage), never an order field. BTCUSD
  defaults to 200x, which liquidates at about a 0.25% move, inside every stop the desk's strategies use.
- Numbers come back quoted or bare, and ids as numbers, strings or UUIDs; everything is parsed defensively.
- When a position is flat, its leftover bracket legs are cancelled. Delta nets by product, so an old leg could
  arm against the next position.

Keys are never in the repository. They come from the environment (DELTA_API_KEY, DELTA_API_SECRET) or from the
secrets file the deploy script writes inside the container (DELTA_LIVE_SECRETS, one KEY=value per line). Nothing
here decides a trade; premium_live does, and only it calls the order methods.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import httpx

logger = logging.getLogger("delta_rest")

# The host the Go client placed real orders through; api.india.delta.exchange serves the same API.
BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn.india.deltaex.org").rstrip("/")
PUBLIC_URL = os.getenv("DELTA_PUBLIC_URL", "https://api.india.delta.exchange").rstrip("/")
SECRETS_FILE = Path(os.getenv("DELTA_LIVE_SECRETS", "/app/backend/.delta_live_secrets"))
UA = {"User-Agent": "rest-client", "Accept": "application/json"}
TIMEOUT = float(os.getenv("DELTA_TIMEOUT_S", "10"))


class DeltaError(RuntimeError):
    """A request Delta refused or did not answer; the message says which.

    `ambiguous` is True when the request may still have been carried out: no answer arrived (a timeout, a dropped
    connection) or Delta failed on its side (HTTP 5xx). An order that failed this way must be checked against the
    account, never assumed not to exist."""

    def __init__(self, msg: str, ambiguous: bool = False):
        super().__init__(msg)
        self.ambiguous = ambiguous


def secrets() -> dict[str, str]:
    """The desk's secrets: the environment first, then the secrets file. Re-read every call (it is small)."""
    out: dict[str, str] = {}
    try:
        for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and k and not k.startswith("#"):
                out[k.strip()] = v.strip()
    except OSError:
        pass
    for k in ("DELTA_API_KEY", "DELTA_API_SECRET"):
        if os.getenv(k, "").strip():
            out[k] = os.environ[k].strip()
    return out


def configured() -> bool:
    s = secrets()
    return bool(s.get("DELTA_API_KEY") and s.get("DELTA_API_SECRET"))


def num(v, default: float = 0.0) -> float:
    """A number Delta sent quoted, bare or not at all."""
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def sign(secret: str, method: str, timestamp: str, path: str, body: str) -> str:
    return hmac.new(secret.encode(), (method + timestamp + path + body).encode(), hashlib.sha256).hexdigest()


def fmt_tick(price: float, tick: float) -> str:
    """The price on the product's tick grid, printed with exactly the tick's decimals."""
    t = Decimal(str(tick)).normalize()
    n = (Decimal(str(price)) / t).to_integral_value(rounding=ROUND_HALF_UP)
    places = max(0, -t.as_tuple().exponent)
    return f"{n * t:.{places}f}"


@dataclass(frozen=True)
class Product:
    id: int
    symbol: str
    contract_value: float      # underlying units per contract (BTCUSD 0.001 BTC, XAUTUSD 0.001 XAUT)
    tick: float
    maintenance_pct: float     # maintenance margin, % of notional
    taker_rate: float          # commission rate, before GST


class Delta:
    """One account's REST client. All methods are async and raise DeltaError on a refusal."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=TIMEOUT, headers=UA)
        return self._client

    async def request(self, method: str, path: str, body: dict | None = None, signed: bool = True):
        s = secrets()
        if signed and not (s.get("DELTA_API_KEY") and s.get("DELTA_API_SECRET")):
            raise DeltaError("Delta API keys are not configured on this server")
        payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
        headers = {"Content-Type": "application/json"}
        if signed:
            ts = str(int(time.time()))
            headers.update({"api-key": s["DELTA_API_KEY"], "timestamp": ts,
                            "signature": sign(s["DELTA_API_SECRET"], method, ts, path, payload)})
        http = await self._http()
        try:
            r = await http.request(method, (BASE_URL if signed else PUBLIC_URL) + path, content=payload or None,
                                   headers=headers)
        except httpx.HTTPError as exc:
            raise DeltaError(f"{method} {path.split('?')[0]}: no answer ({exc.__class__.__name__})", ambiguous=True) from exc
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code not in (200, 201) or (isinstance(data, dict) and data.get("success") is False):
            err = data.get("error") if isinstance(data, dict) else None
            raise DeltaError(f"{method} {path.split('?')[0]}: HTTP {r.status_code} {json.dumps(err)[:300] if err else r.text[:300]}",
                             ambiguous=r.status_code >= 500)
        return data.get("result") if isinstance(data, dict) and "result" in data else data

    # -- public ------------------------------------------------------------------------------------

    async def product(self, symbol: str) -> Product:
        p = await self.request("GET", f"/v2/products/{symbol}", signed=False)
        cv, tick = num(p.get("contract_value")), num(p.get("tick_size"))
        if not p.get("id") or cv <= 0 or tick <= 0 or p.get("contract_type") != "perpetual_futures":
            raise DeltaError(f"{symbol}: no usable perpetual spec (contract value {cv}, tick {tick})")
        return Product(int(p["id"]), str(p.get("symbol") or symbol), cv, tick,
                       num(p.get("maintenance_margin"), 1.0), num(p.get("taker_commission_rate"), 0.0005))

    async def ticker(self, symbol: str) -> dict:
        t = await self.request("GET", f"/v2/tickers/{symbol}", signed=False)
        q = t.get("quotes") or {}
        bid, ask = num(q.get("best_bid")), num(q.get("best_ask"))
        mark = num(t.get("mark_price")) or num(t.get("close"))
        if bid <= 0 or ask <= 0 or ask < bid:
            raise DeltaError(f"{symbol}: no two-sided quote")
        return {"bid": bid, "ask": ask, "mark": mark or (bid + ask) / 2, "at": time.time()}

    # -- account -----------------------------------------------------------------------------------

    async def positions(self) -> dict[int, dict]:
        """Open positions by product id: signed size in contracts, entry, mark, unrealised P&L."""
        out: dict[int, dict] = {}
        for p in await self.request("GET", "/v2/positions/margined") or []:
            size = int(round(num(p.get("size"))))
            if size:
                out[int(num(p.get("product_id")))] = {
                    "size": size, "symbol": p.get("product_symbol") or p.get("symbol"),
                    "entry": num(p.get("entry_price")), "mark": num(p.get("mark_price")),
                    "unrealised": num(p.get("unrealised_pnl")), "margin": num(p.get("margin"))}
        return out

    async def wallet(self) -> dict:
        """The USD balance: total, available (not posted as margin) and blocked."""
        for w in await self.request("GET", "/v2/wallet/balances") or []:
            if str(w.get("asset_symbol") or "").upper() in ("USD", "USDT"):
                return {"asset": w.get("asset_symbol"), "balance": num(w.get("balance")),
                        "available": num(w.get("available_balance")), "blocked": num(w.get("blocked_margin"))}
        return {"asset": None, "balance": 0.0, "available": 0.0, "blocked": 0.0}

    async def leverage(self, product_id: int) -> float:
        r = await self.request("GET", f"/v2/products/{product_id}/orders/leverage")
        return num((r or {}).get("leverage"))

    async def set_leverage(self, product_id: int, leverage: int) -> float:
        r = await self.request("POST", f"/v2/products/{product_id}/orders/leverage", {"leverage": str(int(leverage))})
        return num((r or {}).get("leverage"), float(leverage))

    async def fills(self, product_id: int, since_s: float) -> list[dict]:
        rows = await self.request("GET", f"/v2/fills?product_ids={product_id}&start_time={int(since_s * 1e6)}&page_size=100")
        out = []
        for f in rows or []:
            out.append({"order_id": str(f.get("order_id") or ""), "side": f.get("side"), "size": int(round(num(f.get("size")))),
                        "price": num(f.get("price")), "commission": num(f.get("commission")),
                        "created_at": f.get("created_at")})
        return out

    # -- orders ------------------------------------------------------------------------------------

    async def market(self, product_id: int, size: int, side: str, reduce_only: bool = False,
                     client_order_id: str | None = None) -> dict:
        """A market order; returns what filled. Only premium_live calls this."""
        if size < 1 or side not in ("buy", "sell"):
            raise DeltaError(f"refusing a market order of {size} contracts, side {side!r}")
        body = {"product_id": product_id, "size": int(size), "side": side, "order_type": "market_order"}
        if reduce_only:
            body["reduce_only"] = True
        if client_order_id:
            body["client_order_id"] = client_order_id[:32]
        o = await self.request("POST", "/v2/orders", body)
        size_ = int(round(num(o.get("size"))))
        unfilled = int(round(num(o.get("unfilled_size"))))
        return {"id": str(o.get("id") or ""), "state": o.get("state"), "filled": max(0, size_ - unfilled),
                "avg_price": num(o.get("average_fill_price")), "commission": num(o.get("paid_commission"))}

    async def bracket(self, product: Product, side: str, entry: float, stop: float, target: float | None) -> dict:
        """Venue-side stop (and target) on an open position. `side` is the POSITION's side."""
        if side not in ("buy", "sell") or entry <= 0 or stop <= 0:
            raise DeltaError("bracket: bad side or level")
        long_ = side == "buy"
        if (long_ and stop >= entry) or (not long_ and stop <= entry):
            raise DeltaError(f"bracket: stop {stop} is on the wrong side of {entry}")
        if target is not None and ((long_ and target <= entry) or (not long_ and target >= entry)):
            raise DeltaError(f"bracket: target {target} is on the wrong side of {entry}")
        if abs(entry - stop) < 2 * product.tick:
            raise DeltaError("bracket: the stop is under two ticks from the entry")
        slip = max(abs(entry - stop) * 0.20, 2 * product.tick)
        legs = {"stop_loss_order": {"order_type": "limit_order", "stop_price": fmt_tick(stop, product.tick),
                                    "limit_price": fmt_tick(stop - slip if long_ else stop + slip, product.tick)}}
        if target is not None:
            legs["take_profit_order"] = {"order_type": "limit_order", "stop_price": fmt_tick(target, product.tick),
                                         "limit_price": fmt_tick(target, product.tick)}
        body = {"product_id": product.id, "product_symbol": product.symbol, **legs,
                "bracket_stop_trigger_method": "last_traded_price"}
        await self.request("POST", "/v2/orders/bracket", body)
        return {k: v for k, v in legs.items()}

    async def cancel_stops(self, product_id: int) -> None:
        """Remove every resting stop / reduce-only leg on the product (never a plain limit order)."""
        await self.request("DELETE", "/v2/orders/all", {"product_id": product_id, "cancel_limit_orders": "false",
                                                        "cancel_stop_orders": "true", "cancel_reduce_only": "true"})
