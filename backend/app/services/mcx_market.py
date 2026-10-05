"""MCX contract rules and honest quotes — shared by every commodity desk.

THREE THINGS THE DESKS GOT WRONG, FIXED IN ONE PLACE
----------------------------------------------------
1. **Which contract.** `front_month_universe` took the nearest expiry on or after today. For
   bullion and base metals that means trading a contract inside its delivery window: MCX
   gold, silver, copper and zinc futures are STAGGERED-DELIVERY contracts, and a position
   left open into the tender days becomes a delivery obligation with extra margin.
   Brokers force-close days before (Zerodha bulletins, Feb/May 2026: GOLDM close by the
   4th trading day before expiry, SILVER/SILVERM by the 6th, base metals by the 4th).
   Crude oil and natural gas settle in cash, but liquidity leaves the expiring month in its
   last days. So each underlying has an EXIT WINDOW in trading days; a contract inside it
   takes no new entries and every position in it is closed at ITS OWN price.
2. **Whose price.** Open positions were marked at the CURRENT front month of their
   underlying. After a roll that is a different contract, so a position opened on
   COPPER-Sep was closed at COPPER-Oct's price — 148 trades closed that way, one CRUDEOILM
   short "made" 1,017 bp on the calendar spread. Quotes here are per CONTRACT (token).
3. **Is the price live.** A quote endpoint answers on a holiday with the last traded price.
   Angel's FULL quote carries `exchTradeTime`, the time of the last trade; a quote whose
   last trade is older than the current session's open, or older than `STALE_AFTER_MIN`
   inside a session, is FROZEN and nothing may fill on it. (`exchFeedTime` is the feed's
   own clock and reads "now" even on a holiday, so it cannot tell.)

Every fresh quote with a two-sided book is also sampled into `mcx_quote_log` (at most once
per contract per `QUOTE_LOG_EVERY_S`), so the desks' assumed slippage can be checked
against the spread the market actually showed.
"""

from __future__ import annotations

import logging
import os
import time as _time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

from tradingai_shared import mcx_calendar as cal

from app.core.db import db, instruments_collection
from app.services.angel_client import angel_client

logger = logging.getLogger("mcx_market")

IST = cal.IST

# ── contract rules ───────────────────────────────────────────────────────────────

# Trading days before expiry (expiry day counted as 1) at which a held position must be
# OUT and no new entry may be taken. `trading_days_to(expiry) <= EXIT_DAYS[u]` = inside.
EXIT_DAYS: dict[str, int] = {
    # bullion — staggered delivery. Gold's tender is the last 3 days, silver's the last 5;
    # one extra day so the exit happens on the broker's deadline day, not after it.
    "GOLD": 4, "GOLDM": 4, "GOLDTEN": 4, "GOLDPETAL": 4, "GOLDGUINEA": 4,
    "SILVER": 6, "SILVERM": 6, "SILVERMIC": 6, "SILVER100": 6,
    # base metals — staggered delivery, 3 tender days
    "COPPER": 4, "ZINC": 4, "ZINCMINI": 4, "ALUMINIUM": 4, "ALUMINI": 4,
    "LEAD": 4, "LEADMINI": 4, "NICKEL": 4,
    # energy — cash settled; leave before liquidity migrates
    "CRUDEOIL": 2, "CRUDEOILM": 2, "NATURALGAS": 2, "NATGASMINI": 2,
}
DEFAULT_EXIT_DAYS = int(os.getenv("MCX_DEFAULT_EXIT_DAYS", "4"))
CASH_SETTLED = {"CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI"}


def exit_days(underlying: str) -> int:
    return EXIT_DAYS.get((underlying or "").upper(), DEFAULT_EXIT_DAYS)


def settlement(underlying: str) -> str:
    return "cash" if (underlying or "").upper() in CASH_SETTLED else "physical (staggered delivery)"


def in_exit_window(underlying: str, expiry: str | None, today: date | None = None) -> bool:
    """True when a contract is inside its exit window — or already expired."""
    if not expiry:
        return False
    return cal.trading_days_to(expiry, today or cal.as_date(None)) <= exit_days(underlying)


def tradable_contract(contracts: list[dict], underlying: str, today: date | None = None) -> dict | None:
    """The nearest-expiry contract that is OUTSIDE its exit window."""
    t = today or cal.as_date(None)
    best = None
    for d in contracts:
        exp = d.get("expiry")
        if not exp or exp < t.isoformat() or in_exit_window(underlying, exp, t):
            continue
        if best is None or exp < best["expiry"]:
            best = d
    return best


async def listed_futures(underlyings: list[str]) -> dict[str, list[dict]]:
    """{underlying: [contract docs with an Angel token, unexpired]}."""
    today = cal.as_date(None).isoformat()
    out: dict[str, list[dict]] = {u: [] for u in underlyings}
    async for d in instruments_collection.find({
        "asset_class": "COMMODITY_FUTURE", "expiry": {"$gte": today},
        "underlying_symbol": {"$in": underlyings}, "angel_token": {"$ne": None},
    }):
        out.setdefault(d["underlying_symbol"], []).append(d)
    for u in out:
        out[u].sort(key=lambda d: d.get("expiry") or "9999")
    return out


async def tradable_universe(underlyings: list[str]) -> dict[str, dict]:
    """{underlying: the contract new entries go to} — the roll-aware front month."""
    listed = await listed_futures(underlyings)
    out = {}
    for u, rows in listed.items():
        c = tradable_contract(rows, u)
        if c is not None:
            out[u] = c
    return out


async def contract_by_security_id(security_id: str) -> dict | None:
    return await instruments_collection.find_one({"security_id": str(security_id)})


def position_contract(pos: dict) -> dict:
    """The contract a position actually holds, as stamped on it at entry."""
    inst = dict(pos.get("instrument") or {})
    inst.setdefault("underlying_symbol", pos.get("symbol"))
    return inst


def position_token(pos: dict) -> str:
    inst = pos.get("instrument") or {}
    return str(inst.get("angel_token") or inst.get("security_id") or "")


def forced_exit(pos: dict, today: date | None = None) -> str | None:
    """Why a position must close regardless of its own target and stop, if it must:
    "contract_expired" (its contract is gone) or "roll_exit" (inside the exit window)."""
    t = today or cal.as_date(None)
    exp = (pos.get("instrument") or {}).get("expiry")
    if not exp:
        return None
    if exp < t.isoformat():
        return "contract_expired"
    if in_exit_window(pos.get("symbol") or "", exp, t):
        return "roll_exit"
    return None


# ── honest quotes ────────────────────────────────────────────────────────────────

STALE_AFTER_MIN = float(os.getenv("MCX_STALE_AFTER_MIN", "10"))
QUOTE_LOG_EVERY_S = float(os.getenv("MCX_QUOTE_LOG_EVERY_S", "300"))
QUOTE_LOG_TTL_DAYS = int(os.getenv("MCX_QUOTE_LOG_TTL_DAYS", "180"))
quote_log_collection = db["mcx_quote_log"]
_last_logged: dict[str, float] = {}


@dataclass
class McxQuote:
    token: str
    ltp: float | None
    bid: float | None = None
    ask: float | None = None
    bid_qty: int | None = None
    ask_qty: int | None = None
    oi: float | None = None
    volume: float | None = None
    trade_time: str | None = None         # ISO, IST
    fresh: bool = False
    why: str = ""
    session: str | None = None

    @property
    def mid(self) -> float | None:
        if self.bid and self.ask and self.ask >= self.bid > 0:
            return (self.bid + self.ask) / 2
        return None

    @property
    def spread_bp(self) -> float | None:
        m = self.mid
        return (self.ask - self.bid) / m * 1e4 if m else None

    def touch(self, side: str) -> float | None:
        """The price a market order on `side` would pay: BUY lifts the ask, SELL hits the bid."""
        if not self.fresh:
            return None
        return self.ask if side == "BUY" else self.bid

    def as_doc(self) -> dict:
        d = asdict(self)
        d["spread_bp"] = round(self.spread_bp, 2) if self.spread_bp is not None else None
        return d


def parse_trade_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def judge(trade_time: datetime | None, now: datetime | None = None) -> tuple[bool, str, str | None]:
    """(fresh, why, session) for a quote whose last trade printed at `trade_time`."""
    now = (now or datetime.now(IST)).astimezone(IST)
    session = cal.session_at(now)
    if session is None:
        h = cal.holiday(now)
        return False, (f"MCX closed ({h['name']})" if h else "MCX closed"), None
    if trade_time is None:
        return False, "no last-trade time on the quote", session
    start = cal.current_session_start(now)
    if start is not None and trade_time < start:
        return False, f"no trade yet this session (last {trade_time:%d %b %H:%M})", session
    age = (now - trade_time).total_seconds() / 60.0
    if age > STALE_AFTER_MIN:
        return False, f"no trade for {age:.0f} min (last {trade_time:%H:%M})", session
    return True, "", session


async def quotes(contracts: list[dict]) -> dict[str, McxQuote]:
    """{token: McxQuote} for MCX contract docs (instrument docs or a position's stamped
    instrument). Keyed by Angel token, which on MCX equals the security id."""
    toks: list[str] = []
    meta: dict[str, dict] = {}
    for c in contracts:
        tok = str(c.get("angel_token") or c.get("security_id") or "")
        if tok and tok not in meta:
            toks.append(tok)
            meta[tok] = c
    out: dict[str, McxQuote] = {}
    if not toks:
        return out
    raw: dict[str, dict] = {}
    try:
        for i in range(0, len(toks), 50):
            raw.update(await angel_client.full_quote({"MCX": toks[i:i + 50]}))
    except Exception as exc:  # noqa: BLE001 — an unpriceable contract is skipped, not invented
        logger.warning("MCX full quote failed: %s", str(exc)[:160])
    now = datetime.now(IST)
    logs = []
    for tok in toks:
        r = raw.get(tok)
        if not r:
            out[tok] = McxQuote(token=tok, ltp=None, fresh=False, why="no quote returned")
            continue
        tt = parse_trade_time(r.get("trade_time"))
        fresh, why, session = judge(tt, now)
        q = McxQuote(token=tok, ltp=r.get("ltp"), bid=r.get("bid"), ask=r.get("ask"),
                     bid_qty=r.get("bid_qty"), ask_qty=r.get("ask_qty"), oi=r.get("oi"),
                     volume=r.get("volume"), trade_time=tt.isoformat() if tt else None,
                     fresh=fresh, why=why, session=session)
        # A one-sided or crossed book is not a market to fill against.
        if q.fresh and (q.mid is None):
            q.fresh, q.why = False, "one-sided or crossed book"
        out[tok] = q
        mono = _time.monotonic()
        if q.fresh and mono - _last_logged.get(tok, 0.0) >= QUOTE_LOG_EVERY_S:
            _last_logged[tok] = mono
            c = meta[tok]
            logs.append({"token": tok, "symbol": c.get("symbol"),
                         "underlying": c.get("underlying_symbol") or c.get("underlying"),
                         "expiry": c.get("expiry"), "ts": datetime.now(timezone.utc),
                         "session": session, **{k: v for k, v in q.as_doc().items()
                                                if k in ("ltp", "bid", "ask", "bid_qty", "ask_qty",
                                                         "oi", "volume", "spread_bp", "trade_time")}})
    if logs:
        try:
            await quote_log_collection.insert_many(logs, ordered=False)
        except Exception as exc:  # noqa: BLE001 — a log row is never worth a failed cycle
            logger.info("quote log write skipped: %s", str(exc)[:120])
    return out


async def ensure_indexes() -> None:
    """Best-effort; never raises (a raising startup hook once took the whole backend down)."""
    try:
        await quote_log_collection.create_index([("token", 1), ("ts", -1)], name="mql_token_ts", background=True)
        await quote_log_collection.create_index("ts", name="mql_ttl", expireAfterSeconds=QUOTE_LOG_TTL_DAYS * 86400,
                                                background=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcx_quote_log indexes skipped: %s", exc)


async def spread_stats(days: int = 30) -> list[dict]:
    """Median and 90th-percentile quoted spread per contract family over the last `days`."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    groups: dict[str, list[float]] = {}
    async for r in quote_log_collection.find({"ts": {"$gte": since}, "spread_bp": {"$ne": None}},
                                             {"underlying": 1, "spread_bp": 1, "session": 1}):
        groups.setdefault(r.get("underlying") or "?", []).append(float(r["spread_bp"]))
    out = []
    for u, xs in sorted(groups.items()):
        xs.sort()
        n = len(xs)
        out.append({"underlying": u, "samples": n, "median_bp": round(xs[n // 2], 2),
                    "p90_bp": round(xs[min(n - 1, int(n * 0.9))], 2), "half_spread_bp": round(xs[n // 2] / 2, 2)})
    return out


def describe_rules(underlyings: list[str]) -> list[dict]:
    return [{"underlying": u, "settlement": settlement(u), "exit_days": exit_days(u)} for u in underlyings]
