"""Zero Hero Trades — expiry-day deep-OTM index option BUYING, on paper.

WHAT THIS IS, STATED HONESTLY
A "zero to hero" trade buys a nearly worthless deep-OTM index option in the back half of
expiry day for a rupee or three, betting that one sharp move turns it into fifty. The
payoff is genuinely asymmetric — risk is 100% of a tiny premium, reward can be 20-100x —
but the BASE RATE IS AWFUL: most of these expire at exactly zero, theta on expiry day is
brutal, and this is a lottery ticket, not an edge. SEBI's own data has ~90% of retail F&O
traders losing money, with expiry-day speculation a large part of it.

So this desk exists to MEASURE that, not to assume it. Every strategy runs on its own
Rs1,00,000 paper account with real Angel One premiums, and the leaderboard is designed to
show the thing that actually matters for a lottery: not win rate (which will be
horrifying), but whether the rare winners pay for the many losers — profit factor and
expectancy. A strategy here earns nothing by being clever; it earns it by surviving a
forward record.

MECHANICS
  * Trades ONLY on a given index's expiry day — that is the whole premise.
  * Entry only inside the strategy's time window, only if the option is inside its cheap-
    premium band (that is what makes it a "zero"), never at a price a real fill couldn't get.
  * Exit on a target multiple, a premium stop, or the 15:20 IST square-off; anything still
    OTM at expiry is worth zero, and the desk books that honestly rather than pretending.
  * Position size is capped per trade so one lottery ticket can never consume the account.

Data is Angel One throughout, batched to the 50-token quote cap and paced.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    zero_hero_equity_collection,
    zero_hero_positions_collection,
    zero_hero_scores_collection,
    zero_hero_signals_collection,
    zero_hero_state_collection,
    zero_hero_trades_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.stock_options import batched_ltp

logger = logging.getLogger("zero_hero")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "engine"

PER_STRATEGY_CAPITAL = float(os.getenv("ZERO_HERO_CAPITAL", "100000"))   # ₹1 lakh each
# A lottery ticket must never be able to eat the account: cap each trade's premium outlay.
MAX_TRADE_PCT = float(os.getenv("ZERO_HERO_MAX_TRADE_PCT", "0.10"))      # 10% of ₹1L = ₹10k
MAX_OPEN_PER_STRATEGY = int(os.getenv("ZERO_HERO_MAX_OPEN_PER_STRATEGY", "2"))
SQUAREOFF_HHMM = os.getenv("ZERO_HERO_SQUAREOFF", "15:20")
QUOTE_PACE = 0.15

# Index spot tokens live on Angel's NSE segment; options on NFO.
INDEX_META = {
    "NIFTY": {"step": 50},
    "BANKNIFTY": {"step": 100},
    "FINNIFTY": {"step": 50},
    "MIDCPNIFTY": {"step": 25},
}


class ZeroHeroError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return date.today().isoformat()


def _hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


# ── the 50 strategies ────────────────────────────────────────────────────────────
# A zero-hero strategy is fully described by five choices, so the library is a grid rather
# than 50 hand-written files: which index, how far OTM, how cheap the ticket must be, when
# in the expiry session to buy it, and what makes it fire. Each row is a distinct, testable
# bet; the grid keeps them comparable so the leaderboard is measuring the CHOICES, not
# incidental differences in implementation.

# trigger semantics:
#   momentum  — index is up on the day beyond `thr`% -> buy CE; down beyond -> buy PE
#   reversal  — index up beyond thr -> buy PE (fade), down -> buy CE
#   breakout  — price takes out the session high (CE) / low (PE)
#   both      — buy BOTH the OTM CE and PE (a cheap strangle; needs a move either way)

_WINDOWS = {
    "early": ("09:30", "11:00"),
    "mid": ("11:00", "13:00"),
    "late": ("13:00", "14:00"),
    "final": ("14:00", "14:45"),
}

_GRID: list[tuple] = [
    # (index, otm_pct, max_premium, window, trigger, thr_pct, target_mult, stop_pct)
    ("NIFTY", 0.005, 10.0, "late", "momentum", 0.25, 3.0, 0.5),
    ("NIFTY", 0.0075, 8.0, "late", "momentum", 0.30, 4.0, 0.5),
    ("NIFTY", 0.010, 5.0, "late", "momentum", 0.35, 5.0, 0.5),
    ("NIFTY", 0.015, 3.0, "late", "momentum", 0.40, 8.0, 0.6),
    ("NIFTY", 0.020, 2.0, "late", "momentum", 0.50, 10.0, 0.7),
    ("NIFTY", 0.005, 10.0, "final", "momentum", 0.25, 3.0, 0.5),
    ("NIFTY", 0.0075, 8.0, "final", "momentum", 0.30, 4.0, 0.5),
    ("NIFTY", 0.010, 5.0, "final", "momentum", 0.35, 5.0, 0.6),
    ("NIFTY", 0.015, 3.0, "final", "momentum", 0.40, 8.0, 0.7),
    ("NIFTY", 0.020, 2.0, "final", "momentum", 0.50, 12.0, 0.8),
    ("NIFTY", 0.0075, 8.0, "mid", "momentum", 0.30, 4.0, 0.5),
    ("NIFTY", 0.010, 5.0, "mid", "breakout", 0.0, 5.0, 0.5),
    ("NIFTY", 0.010, 5.0, "late", "breakout", 0.0, 5.0, 0.5),
    ("NIFTY", 0.015, 3.0, "final", "breakout", 0.0, 8.0, 0.6),
    ("NIFTY", 0.010, 5.0, "late", "reversal", 0.40, 5.0, 0.5),
    ("NIFTY", 0.015, 3.0, "final", "reversal", 0.50, 8.0, 0.6),
    ("NIFTY", 0.010, 6.0, "late", "both", 0.0, 5.0, 0.6),
    ("NIFTY", 0.015, 4.0, "final", "both", 0.0, 8.0, 0.7),
    ("NIFTY", 0.020, 2.5, "final", "both", 0.0, 10.0, 0.8),
    ("NIFTY", 0.0125, 4.0, "early", "momentum", 0.35, 6.0, 0.5),

    ("BANKNIFTY", 0.005, 12.0, "late", "momentum", 0.30, 3.0, 0.5),
    ("BANKNIFTY", 0.0075, 10.0, "late", "momentum", 0.35, 4.0, 0.5),
    ("BANKNIFTY", 0.010, 6.0, "late", "momentum", 0.40, 5.0, 0.6),
    ("BANKNIFTY", 0.015, 4.0, "late", "momentum", 0.50, 8.0, 0.6),
    ("BANKNIFTY", 0.020, 2.5, "late", "momentum", 0.60, 10.0, 0.7),
    ("BANKNIFTY", 0.005, 12.0, "final", "momentum", 0.30, 3.0, 0.5),
    ("BANKNIFTY", 0.0075, 10.0, "final", "momentum", 0.35, 4.0, 0.6),
    ("BANKNIFTY", 0.010, 6.0, "final", "momentum", 0.40, 6.0, 0.6),
    ("BANKNIFTY", 0.015, 4.0, "final", "momentum", 0.50, 10.0, 0.7),
    ("BANKNIFTY", 0.020, 2.5, "final", "momentum", 0.60, 15.0, 0.8),
    ("BANKNIFTY", 0.010, 6.0, "mid", "momentum", 0.40, 5.0, 0.5),
    ("BANKNIFTY", 0.010, 6.0, "late", "breakout", 0.0, 5.0, 0.5),
    ("BANKNIFTY", 0.015, 4.0, "final", "breakout", 0.0, 8.0, 0.6),
    ("BANKNIFTY", 0.0075, 10.0, "mid", "breakout", 0.0, 4.0, 0.5),
    ("BANKNIFTY", 0.010, 6.0, "late", "reversal", 0.50, 5.0, 0.5),
    ("BANKNIFTY", 0.015, 4.0, "final", "reversal", 0.60, 8.0, 0.6),
    ("BANKNIFTY", 0.010, 8.0, "late", "both", 0.0, 5.0, 0.6),
    ("BANKNIFTY", 0.015, 5.0, "final", "both", 0.0, 8.0, 0.7),
    ("BANKNIFTY", 0.020, 3.0, "final", "both", 0.0, 12.0, 0.8),
    ("BANKNIFTY", 0.0125, 5.0, "early", "momentum", 0.40, 6.0, 0.5),

    ("FINNIFTY", 0.0075, 8.0, "late", "momentum", 0.30, 4.0, 0.5),
    ("FINNIFTY", 0.010, 5.0, "late", "momentum", 0.40, 5.0, 0.6),
    ("FINNIFTY", 0.015, 3.0, "final", "momentum", 0.50, 8.0, 0.7),
    ("FINNIFTY", 0.010, 5.0, "final", "breakout", 0.0, 6.0, 0.6),
    ("FINNIFTY", 0.0125, 4.0, "late", "both", 0.0, 6.0, 0.6),

    ("MIDCPNIFTY", 0.0075, 8.0, "late", "momentum", 0.35, 4.0, 0.5),
    ("MIDCPNIFTY", 0.010, 5.0, "late", "momentum", 0.45, 5.0, 0.6),
    ("MIDCPNIFTY", 0.015, 3.0, "final", "momentum", 0.55, 8.0, 0.7),
    ("MIDCPNIFTY", 0.010, 5.0, "final", "breakout", 0.0, 6.0, 0.6),
    ("MIDCPNIFTY", 0.0125, 4.0, "late", "both", 0.0, 6.0, 0.6),
]


class ZeroHeroStrategy:
    __slots__ = ("strategy_id", "name", "index", "otm_pct", "max_premium", "window",
                 "trigger", "thr_pct", "target_mult", "stop_pct")

    def __init__(self, i: int, row: tuple):
        (self.index, self.otm_pct, self.max_premium, self.window,
         self.trigger, self.thr_pct, self.target_mult, self.stop_pct) = row
        self.strategy_id = f"zh_{i:03d}"
        self.name = (f"{self.index} {self.otm_pct * 100:g}% OTM ≤₹{self.max_premium:g} "
                     f"{self.window} {self.trigger} {self.target_mult:g}x")

    @property
    def window_range(self) -> tuple[str, str]:
        return _WINDOWS[self.window]

    def as_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id, "name": self.name, "index": self.index,
            "otm_pct": self.otm_pct, "max_premium": self.max_premium,
            "window": self.window, "window_from": self.window_range[0],
            "window_to": self.window_range[1], "trigger": self.trigger,
            "threshold_pct": self.thr_pct, "target_mult": self.target_mult,
            "stop_pct": self.stop_pct,
        }


STRATEGIES: list[ZeroHeroStrategy] = [ZeroHeroStrategy(i + 1, r) for i, r in enumerate(_GRID)]
BY_ID = {s.strategy_id: s for s in STRATEGIES}


# ── market helpers ───────────────────────────────────────────────────────────────


async def _index_spots() -> dict[str, dict]:
    """Spot + day open/high/low for each index, in one batched FULL quote."""
    docs = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "INDEX", "symbol": {"$in": list(INDEX_META)}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1})}
    if not docs:
        return {}
    by_ex: dict[str, list[str]] = {}
    tok2sym = {}
    for sym, d in docs.items():
        tok = str(d["angel_token"])
        by_ex.setdefault(d.get("angel_exchange") or "NSE", []).append(tok)
        tok2sym[tok] = sym
    try:
        await angel_client._session()
        quotes = await angel_client.full_quote(by_ex)
    except (AngelAPIError, Exception) as exc:
        logger.warning("zero_hero: index quotes failed (%s)", exc)
        return {}
    out = {}
    for tok, q in quotes.items():
        sym = tok2sym.get(tok)
        if sym and q.get("ltp"):
            out[sym] = {"ltp": float(q["ltp"]), "open": q.get("open"), "high": q.get("high"),
                        "low": q.get("low"), "close": q.get("close")}
    return out


async def expiry_today(index: str) -> str | None:
    """The index's expiry falling TODAY, or None. Zero-hero is an expiry-day trade — if
    today is not expiry for this index, the strategy simply does not participate."""
    today = _today()
    n = await instruments_collection.count_documents(
        {"asset_class": "INDEX_OPTION", "underlying_symbol": index, "expiry": today})
    return today if n else None


async def _pick_contract(index: str, expiry: str, kind: str, target_strike: float) -> dict | None:
    """The listed strike nearest the target that Angel can actually quote."""
    rows = [d async for d in instruments_collection.find(
        {"asset_class": "INDEX_OPTION", "underlying_symbol": index, "expiry": expiry,
         "option_type": kind, "angel_token": {"$ne": None}},
        {"symbol": 1, "strike": 1, "option_type": 1, "lot_size": 1,
         "angel_token": 1, "angel_tradingsymbol": 1})]
    if not rows:
        return None
    return min(rows, key=lambda r: abs(r["strike"] - target_strike))


def _sides(s: ZeroHeroStrategy, spot: dict) -> list[str]:
    """Which option side(s) this strategy's trigger says to buy right now."""
    ltp, op = spot["ltp"], spot.get("open")
    hi, lo = spot.get("high"), spot.get("low")
    if not op:
        return []
    chg = (ltp / op - 1) * 100
    if s.trigger == "momentum":
        if chg >= s.thr_pct:
            return ["CE"]
        if chg <= -s.thr_pct:
            return ["PE"]
        return []
    if s.trigger == "reversal":
        if chg >= s.thr_pct:
            return ["PE"]
        if chg <= -s.thr_pct:
            return ["CE"]
        return []
    if s.trigger == "breakout":
        if hi and ltp >= hi * 0.9995:
            return ["CE"]
        if lo and ltp <= lo * 1.0005:
            return ["PE"]
        return []
    if s.trigger == "both":
        return ["CE", "PE"]
    return []


# ── capital / scoring ────────────────────────────────────────────────────────────


async def _realized(sid: str) -> float:
    total = 0.0
    async for p in zero_hero_positions_collection.find(
            {"strategy_id": sid, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


async def _deployed(sid: str) -> float:
    total = 0.0
    async for p in zero_hero_positions_collection.find(
            {"strategy_id": sid, "status": "OPEN"}, {"capital_deployed": 1}):
        total += p.get("capital_deployed") or 0.0
    return total


async def _update_score(sid: str) -> None:
    s = BY_ID.get(sid)
    closed = [p async for p in zero_hero_positions_collection.find(
        {"strategy_id": sid, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1})]
    n = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net = sum(p.get("realized_pnl") or 0 for p in closed)
    gw = sum(p["realized_pnl"] for p in closed if (p.get("realized_pnl") or 0) > 0)
    gl = -sum(p["realized_pnl"] for p in closed if (p.get("realized_pnl") or 0) < 0)
    best = max((p.get("realized_pnl") or 0) for p in closed) if closed else 0.0
    await zero_hero_scores_collection.update_one(
        {"strategy_id": sid},
        {"$set": {
            "strategy_id": sid, "name": s.name if s else sid,
            "index": s.index if s else None, "trigger": s.trigger if s else None,
            "window": s.window if s else None,
            "otm_pct": s.otm_pct if s else None, "target_mult": s.target_mult if s else None,
            "trades": n, "wins": wins, "win_rate": round(wins / n, 4) if n else 0.0,
            "net_pnl": round(net, 2),
            # For a lottery payoff these two matter far more than win rate.
            "profit_factor": round(gw / gl, 2) if gl > 0 else None,
            "expectancy": round(net / n, 2) if n else 0.0,
            "best_trade": round(best, 2),
            "capital": round(PER_STRATEGY_CAPITAL + net, 2),
            "updated_at": _now(),
        }},
        upsert=True,
    )


# ── cycle ────────────────────────────────────────────────────────────────────────


async def run_cycle() -> dict:
    notes: list[str] = []
    managed = await _manage()

    hhmm = _hhmm()
    spots = await _index_spots()
    if not spots:
        notes.append("No live index quotes this cycle.")
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "signals": 0, "notes": notes}

    expiries = {ix: await expiry_today(ix) for ix in INDEX_META}
    active = [ix for ix, e in expiries.items() if e]
    if not active:
        notes.append("No index expires today — zero-hero is an expiry-day trade, so nothing is opened.")
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "signals": 0, "notes": notes}
    notes.append(f"Expiring today: {', '.join(active)}")

    # 1) collect signals (no network)
    wants: list[tuple[ZeroHeroStrategy, str, dict]] = []
    for s in STRATEGIES:
        exp = expiries.get(s.index)
        spot = spots.get(s.index)
        if not exp or not spot:
            continue
        lo, hi = s.window_range
        if not (lo <= hhmm <= hi):
            continue
        if await zero_hero_positions_collection.count_documents(
                {"strategy_id": s.strategy_id, "status": "OPEN"}) >= MAX_OPEN_PER_STRATEGY:
            continue
        for kind in _sides(s, spot):
            wants.append((s, kind, spot))

    if not wants:
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "signals": 0, "notes": notes}

    # 2) resolve contracts, then price every candidate in batched requests
    cands: list[dict] = []
    tokens: list[str] = []
    for s, kind, spot in wants:
        target = spot["ltp"] * (1 + s.otm_pct) if kind == "CE" else spot["ltp"] * (1 - s.otm_pct)
        c = await _pick_contract(s.index, expiries[s.index], kind, target)
        if not c:
            continue
        cands.append({"s": s, "kind": kind, "contract": c, "spot": spot["ltp"], "target_strike": target})
        tokens.append(str(c["angel_token"]))
    prices = await batched_ltp({"NFO": tokens}) if tokens else {}

    opened = 0
    for c in cands:
        if await _open(c, prices):
            opened += 1
    await _persist(opened, managed, notes)
    return {"opened": opened, "managed": managed, "signals": len(cands), "notes": notes}


async def _open(cand: dict, prices: dict[str, float]) -> bool:
    s: ZeroHeroStrategy = cand["s"]
    c = cand["contract"]
    tok = str(c["angel_token"])
    prem = prices.get(tok)
    lot = int(c.get("lot_size") or 0)
    if lot <= 0:
        return False

    # Log EVERY evaluated candidate, filled or not — the signal history is how you later
    # tell "the strategy never fired" apart from "it fired and lost".
    sig = {
        "signal_id": uuid4().hex[:12], "ts": _now(), "session": _today(),
        "strategy_id": s.strategy_id, "strategy_name": s.name, "index": s.index,
        "option_type": cand["kind"], "strike": c["strike"], "spot": round(cand["spot"], 2),
        "premium": prem, "max_premium": s.max_premium, "taken": False, "reason": None,
    }
    if prem is None:
        sig["reason"] = "no live premium"
    elif prem <= 0:
        sig["reason"] = "premium is zero — untradable"
    elif prem > s.max_premium:
        sig["reason"] = f"premium ₹{prem:g} above the ≤₹{s.max_premium:g} cheap-ticket band"
    if sig["reason"]:
        await zero_hero_signals_collection.insert_one(sig)
        return False

    cash = PER_STRATEGY_CAPITAL + await _realized(s.strategy_id) - await _deployed(s.strategy_id)
    budget = min(PER_STRATEGY_CAPITAL * MAX_TRADE_PCT, cash)
    lots = int(budget // (prem * lot))
    if lots < 1:
        sig["reason"] = "budget cannot afford one lot"
        await zero_hero_signals_collection.insert_one(sig)
        return False

    qty = lots * lot
    sig["taken"] = True
    sig["lots"] = lots
    await zero_hero_signals_collection.insert_one(sig)

    await zero_hero_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "strategy_id": s.strategy_id, "strategy_name": s.name,
        "index": s.index, "option_type": cand["kind"], "strike": c["strike"],
        "expiry": _today(), "angel_tradingsymbol": c.get("angel_tradingsymbol"),
        "token": tok, "lot_size": lot, "lots": lots, "qty": qty,
        "spot_at_entry": round(cand["spot"], 2),
        "entry_premium": round(prem, 2), "ltp": round(prem, 2),
        "capital_deployed": round(prem * qty, 2),
        "target_premium": round(prem * s.target_mult, 2),
        "stop_premium": round(prem * (1 - s.stop_pct), 2),
        "unrealized_pnl": 0.0, "realized_pnl": None, "exit_premium": None,
        "exit_reason": None, "status": "OPEN",
        "opened_at": _now(), "session": _today(), "updated_at": _now(), "closed_at": None,
    })
    return True


async def _manage() -> int:
    pos = [p async for p in zero_hero_positions_collection.find({"status": "OPEN"})]
    if not pos:
        return 0
    prices = await batched_ltp({"NFO": [p["token"] for p in pos]})
    hhmm = _hhmm()
    today = _today()
    touched: set[str] = set()
    updated = 0
    for p in pos:
        cur = prices.get(p["token"])
        # An expiry-day option that can no longer be quoted after the session is worth
        # exactly zero — that is the honest mark, and refusing to book it would flatter
        # every losing ticket on this desk.
        expired = p.get("expiry", today) < today or (p.get("expiry") == today and hhmm >= SQUAREOFF_HHMM)
        if cur is None:
            if not expired:
                continue
            cur = 0.0
        unreal = round((cur - p["entry_premium"]) * p["qty"], 2)
        # Order matters for the RECORD, not the money (P&L is always marked at `cur`).
        # A ticket that decayed to zero by expiry is "expired worthless" — it is not a stop
        # that saved anything, and this desk exists precisely to count how often that
        # happens. So expiry outranks the stop label; a genuine target still wins, and the
        # stop only labels an exit taken while the session was still live.
        reason = None
        if cur >= p["target_premium"]:
            reason = "target"
        elif expired:
            reason = "expired_worthless" if cur <= 0.05 else "expiry_squareoff"
        elif cur <= p["stop_premium"]:
            reason = "stoploss"

        changes = {"ltp": round(cur, 2), "unrealized_pnl": unreal, "updated_at": _now()}
        if reason:
            changes.update({"status": "CLOSED", "exit_premium": round(cur, 2),
                            "exit_reason": reason, "realized_pnl": unreal,
                            "unrealized_pnl": 0.0, "closed_at": _now()})
            await zero_hero_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "strategy_id": p["strategy_id"],
                "strategy_name": p.get("strategy_name"), "index": p.get("index"),
                "option_type": p.get("option_type"), "strike": p.get("strike"),
                "qty": p["qty"], "lots": p.get("lots"),
                "entry_premium": p["entry_premium"], "exit_premium": round(cur, 2),
                "multiple": round(cur / p["entry_premium"], 2) if p["entry_premium"] else None,
                "realized_pnl": unreal, "exit_reason": reason, "session": p.get("session"),
                "opened_at": p["opened_at"], "closed_at": _now(),
            })
            touched.add(p["strategy_id"])
        await zero_hero_positions_collection.update_one({"_id": p["_id"]}, {"$set": changes})
        updated += 1
    for sid in touched:
        await _update_score(sid)
    return updated


async def _persist(opened: int, managed: int, notes: list[str]) -> None:
    snap = await summary()
    await zero_hero_equity_collection.insert_one({
        "ts": _now(), "session": _today(), "equity": snap["equity"],
        "realized": snap["realized_pnl"], "unrealized": snap["unrealized_pnl"],
        "open_positions": snap["open_positions"],
    })
    await zero_hero_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {"last_run_at": _now(), "last_opened": opened, "last_managed": managed,
                  "last_notes": notes, "strategy_count": len(STRATEGIES)}},
        upsert=True,
    )


# ── read models ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    deployed = realized = unreal = 0.0
    async for p in zero_hero_positions_collection.find({"status": "OPEN"},
                                                       {"capital_deployed": 1, "unrealized_pnl": 1}):
        deployed += p.get("capital_deployed") or 0.0
        unreal += p.get("unrealized_pnl") or 0.0
    async for p in zero_hero_positions_collection.find({"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    initial = PER_STRATEGY_CAPITAL * len(STRATEGIES)
    st = await zero_hero_state_collection.find_one({"_id": STATE_ID}) or {}
    closed = await zero_hero_positions_collection.count_documents({"status": {"$ne": "OPEN"}})
    wins = await zero_hero_positions_collection.count_documents(
        {"status": {"$ne": "OPEN"}, "realized_pnl": {"$gt": 0}})
    expiring = [ix for ix in INDEX_META if await expiry_today(ix)]
    return {
        "mode": "paper",
        "strategy_count": len(STRATEGIES),
        "per_strategy_capital": PER_STRATEGY_CAPITAL,
        "initial_capital": initial,
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unreal, 2),
        "equity": round(initial + realized + unreal, 2),
        "open_positions": await zero_hero_positions_collection.count_documents({"status": "OPEN"}),
        "closed_positions": closed,
        "wins": wins,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "expiring_today": expiring,
        "max_trade_budget": round(PER_STRATEGY_CAPITAL * MAX_TRADE_PCT, 2),
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_notes": st.get("last_notes", []),
    }


async def leaderboard() -> list[dict]:
    scores = {s["strategy_id"]: s async for s in zero_hero_scores_collection.find({})}
    rows = []
    for s in STRATEGIES:
        sc = scores.get(s.strategy_id) or {}
        rows.append({
            **s.as_dict(),
            "trades": sc.get("trades", 0) or 0,
            "wins": sc.get("wins", 0) or 0,
            "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(sc.get("net_pnl", 0.0) or 0.0, 2),
            "profit_factor": sc.get("profit_factor"),
            "expectancy": sc.get("expectancy", 0.0) or 0.0,
            "best_trade": sc.get("best_trade", 0.0) or 0.0,
            "capital": round(sc.get("capital", PER_STRATEGY_CAPITAL) or PER_STRATEGY_CAPITAL, 2),
        })
    rows.sort(key=lambda r: r["net_pnl"], reverse=True)
    return rows


def _ser(d: dict, ts_fields: tuple[str, ...]) -> dict:
    d.pop("_id", None)
    for k in ts_fields:
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


async def positions(status: str = "OPEN", limit: int = 300) -> list[dict]:
    q = {"status": status.upper()} if status else {}
    return [_ser(p, ("opened_at", "updated_at", "closed_at"))
            async for p in zero_hero_positions_collection.find(q).sort("opened_at", -1).limit(limit)]


async def trades(limit: int = 300) -> list[dict]:
    return [_ser(t, ("opened_at", "closed_at"))
            async for t in zero_hero_trades_collection.find({}).sort("closed_at", -1).limit(limit)]


async def signals(limit: int = 300, taken: bool | None = None) -> list[dict]:
    q = {} if taken is None else {"taken": taken}
    return [_ser(s, ("ts",))
            async for s in zero_hero_signals_collection.find(q).sort("ts", -1).limit(limit)]


async def daily_pnl(limit: int = 60) -> list[dict]:
    """Realised P&L per session, newest first."""
    rows = []
    async for r in zero_hero_trades_collection.aggregate([
        {"$group": {"_id": "$session", "net_pnl": {"$sum": "$realized_pnl"},
                    "trades": {"$sum": 1},
                    "wins": {"$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}},
                    "best": {"$max": "$realized_pnl"}}},
        {"$sort": {"_id": -1}}, {"$limit": limit},
    ]):
        rows.append({"session": r["_id"], "net_pnl": round(r["net_pnl"] or 0, 2),
                     "trades": r["trades"], "wins": r["wins"],
                     "win_rate": round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0,
                     "best_trade": round(r.get("best") or 0, 2)})
    return rows
