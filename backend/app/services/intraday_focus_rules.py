"""Deterministic accounting for Focus Five. No I/O and no broker-order code.

An account (cash, positions, realised totals and archive outbox) is one versioned
Mongo document. Committing that document is the sole financial state transition.
"""
from __future__ import annotations

import copy
import math
from datetime import datetime, timedelta, timezone
from hashlib import sha256

IST = timezone(timedelta(hours=5, minutes=30))
CAPITAL = 1_000_000.0
SLOTS = 5
SLOT_CAPITAL = CAPITAL / SLOTS
DAILY_LOSS_LIMIT = CAPITAL * 0.03
MODEL_VERSION = 1
MAX_QUOTE_AGE = 30.0
STRATEGIES = (
    ("iv2_macd_trend_1h", "MACD Trend", "1h", "MACD momentum turn confirmed by EMA50; 1.2 ATR stop, 2 ATR target."),
    ("iv2_donchian_1h", "Donchian Breakout", "1h", "20-bar high/low breakout with volume; 1 ATR stop, 2 ATR target."),
    ("iv2_ema_pullback_45m", "EMA Trend Pullback", "45m", "EMA9/21/50 trend and pullback recovery; 1 ATR stop, 1.8 ATR target."),
    ("iv2_supertrend_1h", "Supertrend Flip", "1h", "Supertrend(10,3) direction change; 1.5 ATR stop, 2.5 ATR target."),
    ("iv2_keltner_1h", "Keltner Breakout", "1h", "EMA20 plus/minus 2 ATR channel breakout; 1 ATR stop, 2 ATR target."),
)
BY_ID = {s[0]: s for s in STRATEGIES}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def day(value: datetime) -> str:
    return utc(value).astimezone(IST).date().isoformat()


def fresh_quote(price, received_at, now: datetime) -> bool:
    try:
        age = utc(now).timestamp() - float(received_at)
        return math.isfinite(float(price)) and float(price) > 0 and 0 <= age <= MAX_QUOTE_AGE
    except (ValueError, TypeError, OverflowError):
        return False


def new_account(strategy_id: str, started_at: datetime) -> dict:
    if strategy_id not in BY_ID:
        raise ValueError("Unknown Focus Five strategy")
    return {"_id": strategy_id, "version": 0, "model_version": MODEL_VERSION,
            "initial_capital": CAPITAL, "started_at": utc(started_at),
            "positions": [], "outbox": [], "daily": {}, "realized_pnl": 0.0,
            "gross_pnl": 0.0, "fees": 0.0, "trades": 0, "wins": 0,
            "last_boundary": 0, "last_skip": None}


def valid_account(account: dict) -> bool:
    return (account.get("_id") in BY_ID and account.get("model_version") == MODEL_VERSION
            and account.get("initial_capital") == CAPITAL)


def available_cash(account: dict) -> float:
    return round(CAPITAL + account["realized_pnl"] - sum(
        p["capital_deployed"] + p["fee_reserve"] for p in account["positions"]), 2)


def mark_position(p: dict, price: float, fee_fn) -> tuple[float, float]:
    """Liquidation estimate, including modeled market-exit slippage and both fees."""
    sign = 1 if p["side"] == "BUY" else -1
    exit_price = round(price * (1 - sign * p["slippage_pct"] / 100), 2)
    gross = sign * (exit_price - p["entry_price"]) * p["qty"]
    net = round(gross - fee_fn(p["entry_price"], exit_price, p["qty"], p["side"])[0], 2)
    return net, round(net / p["capital_deployed"] * 100, 4)


def daily_pnl(account: dict, now: datetime) -> float:
    return account["daily"].get(day(now), {}).get("realized_pnl", 0) + sum(
        p.get("unrealized_pnl", 0) for p in account["positions"])


def plan_entries(account: dict, candidates: list[dict], boundary: datetime,
                 now: datetime, fee_fn) -> dict:
    """All entries at one boundary are committed together; retrying cannot duplicate them.

    Quotes and member metadata are supplied by the real feed adapter, not manufactured
    here. A candidate's price is the current quote, NEVER its signal-bar close.
    """
    out = copy.deepcopy(account)
    stamp = int(utc(boundary).timestamp())
    if not valid_account(out):
        raise ValueError("Unsupported account configuration; migration required")
    if stamp <= out["last_boundary"]:
        return out
    age = (utc(now) - utc(boundary)).total_seconds()
    hhmm = utc(now).astimezone(IST).strftime("%H:%M")
    if (age < 0 or age >= 120 or utc(boundary) < utc(out["started_at"])
            or day(boundary) != day(now) or not "09:45" <= hhmm < "14:30"):
        out["last_skip"] = "Signal outside the fresh entry window"
        return out
    out["last_boundary"] = stamp
    out["last_skip"] = None
    if len(out["outbox"]) >= 100:
        out["last_skip"] = "Trade archive unavailable; entries paused"
        return out
    if any(p.get("price_status") != "LIVE" for p in out["positions"]):
        out["last_skip"] = "Open-position prices stale; risk cannot be measured"
        return out
    if daily_pnl(out, now) <= -DAILY_LOSS_LIMIT:
        out["last_skip"] = "3% strategy daily loss limit reached"
        return out
    for c in sorted(candidates, key=lambda x: (-x.get("priority", 0), x["symbol"])):
        if len(out["positions"]) >= SLOTS:
            out["last_skip"] = "Five position slots occupied"
            break
        if c.get("strategy_id") != out["_id"]:
            continue
        if any(p["symbol"] == c["symbol"] for p in out["positions"]):
            continue
        if not fresh_quote(c.get("price"), c.get("quote_at"), now):
            out["last_skip"] = "Missing or stale live quote"
            continue
        if c.get("side") not in ("BUY", "SELL"):
            continue
        sign = 1 if c["side"] == "BUY" else -1
        slip = c["slippage_pct"]
        dist, target_dist = c["stop_dist"], c["target_dist"]
        if not all(math.isfinite(x) and x > 0 for x in (dist, target_dist)) or not 0 <= slip <= 1:
            continue
        fill = round(c["price"] * (1 + sign * slip / 100), 2)
        stop, target = round(fill - sign * dist, 2), round(fill + sign * target_dist, 2)
        if min(fill, stop, target) <= 0 or sign * (fill - stop) <= 0 or sign * (target - fill) <= 0:
            continue
        budget = min(SLOT_CAPITAL, max(available_cash(out), 0))
        # Reserve the estimated round-trip charges, including the capped brokerage.
        lo, hi = 0, int(budget // fill)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            fees = fee_fn(fill, fill, mid, c["side"])[0]
            if fill * mid + fees <= budget:
                lo = mid
            else:
                hi = mid - 1
        qty = lo
        if qty < 1:
            out["last_skip"] = "Insufficient cash for one share plus costs"
            continue
        pid = sha256(f"focus-v1:{out['_id']}:{c['symbol']}:{stamp}".encode()).hexdigest()[:28]
        p = {"position_id": pid, "strategy_id": out["_id"], "strategy_name": BY_ID[out["_id"]][1],
             "symbol": c["symbol"], "side": c["side"], "qty": qty, "entry_price": fill,
             "signal_price": c.get("signal_price"), "signal_at": utc(boundary),
             "ltp": c["price"], "quote_at": c["quote_at"], "price_status": "LIVE",
             "stoploss": stop, "target": target, "capital_deployed": round(fill * qty, 2),
             "fee_reserve": fee_fn(fill, fill, qty, c["side"])[0], "slippage_pct": slip,
             "max_hold_seconds": c["max_hold_seconds"], "opened_at": utc(now), "opened_on": day(now),
             "checked_through": int(utc(now).timestamp()) // 60 * 60 + 60,
             "rationale": c.get("rationale", ""), "mode": "PAPER"}
        p["unrealized_pnl"], p["return_pct"] = mark_position(p, p["ltp"], fee_fn)
        out["positions"].append(p)
        if daily_pnl(out, now) <= -DAILY_LOSS_LIMIT:
            out["last_skip"] = "3% strategy daily loss limit reached"
            break
    return out


def exit_decision(p: dict, minutes: list[tuple], price: float | None, now: datetime,
                  squareoff: bool) -> tuple[str, float, bool] | None:
    """Stop first on ambiguous bars. Ignore every pre-entry/partial-entry minute.

    Current quotes also check the entry minute, without borrowing its pre-entry extremes.
    Limit-target profits are capped at the target even if a later quote gaps beyond it.
    """
    sign = 1 if p["side"] == "BUY" else -1
    start = max(p["checked_through"], int(utc(p["opened_at"]).timestamp()) // 60 * 60 + 60)
    for ts, op, high, low, _close in sorted(minutes):
        if ts < start or ts > utc(now).timestamp():
            continue
        vals = (op, high, low, _close)
        if not all(math.isfinite(v) and v > 0 for v in vals):
            continue
        if sign * (op - p["stoploss"]) <= 0:
            return "stoploss", op, True
        if sign * (op - p["target"]) >= 0:
            return "target", p["target"], False
        adverse_extreme, favorable = (low, high) if sign > 0 else (high, low)
        if sign * (adverse_extreme - p["stoploss"]) <= 0:
            return "stoploss", p["stoploss"], True
        if sign * (favorable - p["target"]) >= 0:
            return "target", p["target"], False
    if price is None:
        return None
    if sign * (price - p["stoploss"]) <= 0:
        return "stoploss", price, True
    if sign * (price - p["target"]) >= 0:
        return "target", p["target"], False
    # Missed EOD is an explicit recovery, not backdated to yesterday's close.
    if day(p["opened_at"]) < day(now):
        return "missed_eod_recovery", price, True
    if squareoff:
        return "eod", price, True
    if (utc(now) - utc(p["opened_at"])).total_seconds() >= p["max_hold_seconds"]:
        return "time", price, True
    return None


def close_position(account: dict, pid: str, decision: tuple, now: datetime, fee_fn) -> dict:
    out = copy.deepcopy(account)
    p = next((p for p in out["positions"] if p["position_id"] == pid), None)
    if p is None:
        return out
    reason, price, market = decision
    sign = 1 if p["side"] == "BUY" else -1
    fill = round(price * (1 - sign * p["slippage_pct"] / 100), 2) if market else price
    gross = round(sign * (fill - p["entry_price"]) * p["qty"], 2)
    fees, breakdown = fee_fn(p["entry_price"], fill, p["qty"], p["side"])
    net = round(gross - fees, 2)
    trade = {**p, "status": "CLOSED", "exit_price": fill, "exit_reason": reason,
             "closed_at": utc(now), "closed_on": day(now), "gross_pnl": gross,
             "fees": fees, "fee_breakdown": breakdown, "realized_pnl": net,
             "return_pct": round(net / p["capital_deployed"] * 100, 4), "unrealized_pnl": 0.0}
    out["positions"] = [x for x in out["positions"] if x["position_id"] != pid]
    out["outbox"].append(trade)
    for key, value in (("realized_pnl", net), ("gross_pnl", gross), ("fees", fees)):
        out[key] = round(out[key] + value, 2)
    out["trades"] += 1
    out["wins"] += int(net > 0)
    d = out["daily"].setdefault(day(now), {"trades": 0, "gross_pnl": 0.0, "fees": 0.0, "realized_pnl": 0.0})
    d["trades"] += 1
    for key, value in (("gross_pnl", gross), ("fees", fees), ("realized_pnl", net)):
        d[key] = round(d[key] + value, 2)
    return out


def account_summary(a: dict) -> dict:
    sid = a["_id"]
    unrealized = round(sum(p.get("unrealized_pnl", 0) for p in a["positions"]), 2)
    total = round(a["realized_pnl"] + unrealized, 2)
    return {"strategy_id": sid, "name": BY_ID[sid][1], "timeframe": BY_ID[sid][2],
            "description": BY_ID[sid][3], "initial_capital": CAPITAL, "equity": round(CAPITAL + total, 2),
            "available_cash": available_cash(a), "deployed_capital": round(sum(p["capital_deployed"] for p in a["positions"]), 2),
            "fee_reserve": round(sum(p["fee_reserve"] for p in a["positions"]), 2),
            "realized_pnl": a["realized_pnl"], "unrealized_pnl": unrealized,
            "total_pnl": total, "return_pct": round(total / CAPITAL * 100, 4),
            "trades": a["trades"], "win_rate": a["wins"] / a["trades"] if a["trades"] else 0,
            "open_positions": len(a["positions"]), "status": "PAPER · UNVALIDATED",
            "last_skip": a.get("last_skip")}
