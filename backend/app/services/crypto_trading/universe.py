"""The ten cryptocurrencies: the largest by market capitalisation that are a cryptocurrency's own
market, listed on the venue, liquid enough and with enough history - every candidate's verdict kept.

Order of screens (each candidate stops at the first it fails, and the reason is recorded):
  1. stablecoin            - pegged to a fiat currency (listed id, or a $1 peg with a USD/dollar name)
  2. wrapped / staked      - a second claim on an asset (listed id, or the name says so)
  3. tokenised asset       - gold, a loan book: not a cryptocurrency's own market
  4. duplicate underlying  - maps to a venue contract already selected
  5. not on the venue      - no live USD perpetual on Delta Exchange India
  6. liquidity             - 24h turnover below MIN_TURNOVER_24H_USD or open interest below MIN_OPEN_INTEREST_USD
  7. history               - fewer than MIN_HISTORY_DAYS of daily candles on the venue
  8. live data             - no 1-minute candle in the last 15 minutes
The first TOP_N to pass are selected, in market-cap order.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime

from . import delta
from .config import (
    ACCOUNT_CAPITAL_USD, CANDIDATES, COINGECKO_URL, FALLBACK_SLIPPAGE_BPS, MIN_HISTORY_DAYS,
    MIN_OPEN_INTEREST_USD, MIN_SLIPPAGE_BPS, MIN_TURNOVER_24H_USD, NAME_SCREENS, RANKING_SOURCE,
    STABLECOIN_IDS, TOKENISED_ASSET_IDS, TOP_N, UTC, VENUE, WRAPPED_OR_STAKED_IDS,
)


def coingecko(n: int = CANDIDATES) -> list[dict]:
    q = urllib.parse.urlencode({"vs_currency": "usd", "order": "market_cap_desc", "per_page": n, "page": 1,
                                "sparkline": "false", "price_change_percentage": "24h"})
    req = urllib.request.Request(f"{COINGECKO_URL}?{q}", headers={"Accept": "application/json",
                                                                 "User-Agent": "TradingAI-CryptoTrading/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                rows = json.load(r)
            if isinstance(rows, list):
                return rows
        except Exception:  # noqa: BLE001 - CoinGecko rate-limits keyless callers; back off and retry
            pass
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("CoinGecko did not answer with a market-cap ranking")


def _stable(c: dict) -> bool:
    if c.get("id") in STABLECOIN_IDS:
        return True
    name = f" {(c.get('name') or '').lower()} "
    sym = (c.get("symbol") or "").lower()
    px = c.get("current_price") or 0
    pegged = abs(px - 1.0) <= 0.02 and abs(c.get("price_change_percentage_24h") or 0) < 1.0
    return pegged and ("usd" in sym or "usd" in name or "dollar" in name or "eur" in sym)


def _wrapped(c: dict) -> bool:
    if c.get("id") in WRAPPED_OR_STAKED_IDS:
        return True
    name = f" {(c.get('name') or '').lower()} "
    return any(s in name for s in NAME_SCREENS if s != " usd")


def _venue_symbol(sym: str, products: dict[str, dict]) -> str | None:
    """The coin's USD perpetual on the venue: SYMUSD, or a 1000-coin contract (1000SHIBUSD)."""
    for cand in (f"{sym}USD", f"1000{sym}USD"):
        if cand in products and (products[cand].get("state") or "live") == "live":
            return cand
    return None


def slippage_bps(symbol: str, contract_value: float, mid: float | None) -> tuple[float, dict]:
    """Half the quoted spread plus the impact of a $10,000 market order walked through the real
    book, in basis points of mid, averaged over both sides; never below MIN_SLIPPAGE_BPS."""
    try:
        book = delta.l2_book(symbol, 50)
    except Exception:  # noqa: BLE001
        return FALLBACK_SLIPPAGE_BPS, {"basis": "fallback (no order book)"}
    if not book["buy"] or not book["sell"]:
        return FALLBACK_SLIPPAGE_BPS, {"basis": "fallback (one-sided book)"}
    bid, ask = book["buy"][0][0], book["sell"][0][0]
    mid = (bid + ask) / 2
    contracts = max(1.0, ACCOUNT_CAPITAL_USD / (mid * contract_value))
    buy_px, got_b = delta.walk(book["sell"], contracts)
    sell_px, got_s = delta.walk(book["buy"], contracts)
    if buy_px is None or sell_px is None or got_b < contracts or got_s < contracts:
        return FALLBACK_SLIPPAGE_BPS, {"basis": "fallback (book thinner than $10k)", "bid": bid, "ask": ask}
    bps = ((buy_px - mid) + (mid - sell_px)) / 2 / mid * 1e4
    return round(max(MIN_SLIPPAGE_BPS, bps), 2), {
        "basis": "half-spread + $10k impact on the live book", "bid": bid, "ask": ask,
        "spread_bps": round((ask - bid) / mid * 1e4, 2), "contracts_for_10k": round(contracts, 2),
        "buy_avg": buy_px, "sell_avg": sell_px}


def select() -> dict:
    """Rank, screen and pick the universe. Pure I/O on public data; the caller stores the result."""
    ranked = coingecko()
    products = delta.products()
    ticks = delta.tickers()
    now = int(time.time())
    selected: list[dict] = []
    verdicts: list[dict] = []
    taken: set[str] = set()
    for c in ranked:
        if len(selected) >= TOP_N:
            break
        sym = (c.get("symbol") or "").upper()
        row = {"rank": c.get("market_cap_rank"), "id": c.get("id"), "symbol": sym, "name": c.get("name"),
               "market_cap_usd": c.get("market_cap"), "price_usd": c.get("current_price")}
        if _stable(c):
            verdicts.append({**row, "verdict": "excluded", "reason": "stablecoin (pegged to a fiat currency)"})
            continue
        if _wrapped(c):
            verdicts.append({**row, "verdict": "excluded", "reason": "wrapped or staked representation of another asset"})
            continue
        if c.get("id") in TOKENISED_ASSET_IDS:
            verdicts.append({**row, "verdict": "excluded", "reason": "tokenised asset, not a cryptocurrency's own market"})
            continue
        vs = _venue_symbol(sym, products)
        if vs is None:
            verdicts.append({**row, "verdict": "excluded", "reason": f"no live USD perpetual on {VENUE}"})
            continue
        if vs in taken:
            verdicts.append({**row, "verdict": "excluded", "reason": f"duplicate: {vs} already selected"})
            continue
        p, t = products[vs], ticks.get(vs) or {}
        liq = {"venue_symbol": vs, "turnover_24h_usd": round(t.get("turnover_usd") or 0.0, 2),
               "open_interest_usd": round(t.get("oi_usd") or 0.0, 2)}
        if (t.get("turnover_usd") or 0) < MIN_TURNOVER_24H_USD:
            verdicts.append({**row, **liq, "verdict": "excluded",
                             "reason": f"illiquid: 24h turnover ${(t.get('turnover_usd') or 0) / 1e6:.2f}M "
                                       f"(needs ${MIN_TURNOVER_24H_USD / 1e6:.2f}M)"})
            continue
        if (t.get("oi_usd") or 0) < MIN_OPEN_INTEREST_USD:
            verdicts.append({**row, **liq, "verdict": "excluded",
                             "reason": f"illiquid: open interest ${(t.get('oi_usd') or 0) / 1e6:.2f}M "
                                       f"(needs ${MIN_OPEN_INTEREST_USD / 1e6:.2f}M)"})
            continue
        days = delta.daily_history_days(vs)
        if days < MIN_HISTORY_DAYS:
            verdicts.append({**row, **liq, "history_days": days, "verdict": "excluded",
                             "reason": f"only {days} days of history on the venue (needs {MIN_HISTORY_DAYS})"})
            continue
        recent = delta.candles(vs, "1m", now - 15 * 60, now)
        if not recent:
            verdicts.append({**row, **liq, "history_days": days, "verdict": "excluded",
                             "reason": "no 1-minute candle in the last 15 minutes (data gap)"})
            continue
        slip, slip_meta = slippage_bps(vs, p["contract_value"], t.get("mark"))
        coin = {**row, **liq, "history_days": days, "verdict": "selected",
                "contract_value": p["contract_value"], "tick_size": p["tick_size"],
                "taker_fee": p["taker_fee"], "maker_fee": p["maker_fee"],
                "funding_interval_s": p["funding_interval_s"], "launch_time": p["launch_time"],
                "max_leverage": p["max_leverage"], "slippage_bps": slip, "slippage": slip_meta}
        selected.append(coin)
        verdicts.append(coin)
        taken.add(vs)
    return {
        "selected": selected, "candidates": verdicts, "ranking_source": RANKING_SOURCE, "venue": VENUE,
        "selected_at": datetime.now(UTC).isoformat(),
        "ranking_as_of": max((c.get("last_updated") or "" for c in ranked[:20]), default=None),
        "screens": {"min_turnover_24h_usd": MIN_TURNOVER_24H_USD, "min_open_interest_usd": MIN_OPEN_INTEREST_USD,
                    "min_history_days": MIN_HISTORY_DAYS, "top_n": TOP_N},
    }
