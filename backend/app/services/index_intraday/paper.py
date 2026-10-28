"""Indian Index Intraday — the paper trading engine. It never places a real order.

WHAT RUNS
A DEPLOYMENT is one catalogued strategy (catalog.json — the research's 1,208 registered trials)
switched on by the user, with an execution model:
  index  the index level itself, simulated: fills at index points, charged what the matching
         ETF would cost (the research's own route). An index cannot be bought — this is a model.
  etf    the cash-market ETF that tracks the index: fills at its live bid / ask (Angel full quote),
         whole units, Angel's intraday charges on the actual turnover, the order capped at a share
         of the ETF's typical minute volume. BANKEX has no ETF and cannot use this model.
No strategy reached "Paper Trading Approved" in the research, so nothing is switched on by
default: a user who runs one runs it as OBSERVATION, labelled with its status.

ONE RULE BOOK WITH THE BACKTEST
Every minute (a few seconds after it completes) the engine rebuilds each index's recent history
plus today's session so far (future minutes blank) and calls the SAME family function the
backtest used; an open position is walked over the newly completed minutes by `live_exit.step`,
which is held to `engine.walk_exit` by a test. Differences from the backtest are only these, all
toward realism: a market order fills at the live price a few seconds into its minute (not the
minute's recorded open); the ETF model fills at the live touch; a signal more than two minutes
old (a restart) is logged as missed and never entered late.

RISK (risk.py) gates every entry and never an exit; 15:12 squares everything off.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np

from app.core.db import db

from . import catalog as cat
from . import factory as FX
from . import factory_lib as FL
from . import families as F
from . import risk as R
from .costs import ROUTE, fee_rt_bp, max_etf_order
from .data import SESSION_MIN, load_recent, minute_of, with_today
from .engine import ENTRY_CUTOFF, SQUARE_OFF
from .feed import INSTRUMENTS, feed
from .live_exit import Live, step

logger = logging.getLogger("index_intraday.paper")

IST = timezone(timedelta(hours=5, minutes=30))
STATE = db["idx_intraday_state"]
POS = db["idx_intraday_positions"]
TRADES = db["idx_intraday_trades"]
EQUITY = db["idx_intraday_equity"]
EVENTS = db["idx_intraday_events"]
STALE_SIGNAL_MIN = 2
LAST_HALF_HOUR = {"imom": "14:45"}
# History the engine rebuilds each family on: >= 250 sessions, because the VIX regime compares
# yesterday's VIX with its trailing 250-session median over the INDEX's days (and ATR settles).
# With less, a VIX-filtered strategy would pick different days than the one that was tested.
HISTORY_DAYS = 420
MAX_DEPLOYMENTS = 40                       # each one is recomputed every minute


def now_ist() -> datetime:
    return datetime.now(IST)


async def ensure_indexes() -> None:
    """Small collections, but read every minute. Each index is created on its own and may fail
    (Atlas quota) without stopping anything — the queries still work, only slower."""
    for coll, keys, kw in ((POS, [("status", 1), ("sid", 1)], {}), (TRADES, [("day", 1), ("sid", 1)], {}),
                           (TRADES, [("closed_at", -1)], {}), (EQUITY, [("at", 1)], {"unique": True}),
                           (EVENTS, [("at", -1)], {})):
        try:
            await coll.create_index(keys, **kw)
        except Exception:  # noqa: BLE001
            logger.warning("index %s on %s not created", keys, coll.name, exc_info=True)


def session_minute(now: datetime) -> int:
    """Minutes since 09:15 (the index of the minute in progress)."""
    return (now.hour * 60 + now.minute) - (9 * 60 + 15)


# ── configuration ────────────────────────────────────────────────────────────────


async def get_config() -> R.RiskConfig:
    doc = await STATE.find_one({"_id": "risk"}) or {}
    doc.pop("_id", None)
    return R.RiskConfig.from_doc(doc)


async def set_config(values: dict) -> tuple[R.RiskConfig, list[str]]:
    cur = await get_config()
    cfg = R.RiskConfig.from_doc({**cur.as_dict(), **values})
    problems = cfg.validate()
    if not problems:
        await STATE.update_one({"_id": "risk"}, {"$set": cfg.as_dict()}, upsert=True)
    return cfg, problems


async def get_day(day: date, equity: float) -> R.DayState:
    doc = await STATE.find_one({"_id": f"day:{day.isoformat()}"})
    if doc is None:
        prev = await STATE.find_one({"_id": "peak"}) or {}
        st = R.DayState(day.isoformat(), peak_equity=max(float(prev.get("peak_equity", 0.0)), equity),
                        halted=bool(prev.get("halted", False)))
        await save_day(st)
        return st
    doc.pop("_id", None)
    return R.DayState(**{k: v for k, v in doc.items() if k in R.DayState.__dataclass_fields__})


async def save_day(st: R.DayState) -> None:
    await STATE.update_one({"_id": f"day:{st.day}"}, {"$set": st.__dict__}, upsert=True)
    await STATE.update_one({"_id": "peak"}, {"$set": {"peak_equity": st.peak_equity, "halted": st.halted}}, upsert=True)


async def deployments() -> list[dict]:
    doc = await STATE.find_one({"_id": "deployments"}) or {}
    return list(doc.get("items") or [])


async def set_deployment(sid: str, enabled: bool, model: str = "etf") -> list[dict]:
    if not enabled:                                  # switching off never depends on the catalogue
        items = [d for d in await deployments() if d["sid"] != sid]
        await STATE.update_one({"_id": "deployments"}, {"$set": {"items": items}}, upsert=True)
        await event("deployment", f"{sid} OFF")
        return items
    fx = FX.parse_sid(sid)
    if fx is not None:                               # a Strategy Factory strategy on an index (factory.py)
        strat, index = fx
        lib = FL.get(sid) or {}
        s = {"key": sid, "family": "sf", "params": {"sf": strat.strategy_id}, "exit": f"sf_{strat.timeframe}",
             "index": index, "status": lib.get("status") or "Experimental", "grade": lib.get("grade"),
             "name": strat.name}
    else:
        s = cat.get(sid)
    if s is None:
        raise ValueError(f"no strategy {sid}")
    if model == "etf" and not ROUTE[s["index"]][0]:
        raise ValueError(f"{s['index']} has no ETF — it can run on the index model only (a simulation)")
    if model not in ("etf", "index"):
        raise ValueError("model must be 'etf' or 'index'")
    items = [d for d in await deployments() if d["sid"] != sid]
    if enabled and len(items) >= MAX_DEPLOYMENTS:
        raise ValueError(f"at most {MAX_DEPLOYMENTS} strategies in paper at once — each is recomputed every minute")
    if enabled:
        items.append({"sid": sid, "key": s["key"], "family": s["family"], "params": s["params"], "exit": s["exit"],
                      "index": s["index"], "model": model, "status": s["status"],
                      **({"name": s["name"], "grade": s.get("grade")} if s["family"] == "sf" else {}),
                      "added_at": datetime.now(timezone.utc).isoformat()})
    await STATE.update_one({"_id": "deployments"}, {"$set": {"items": items}}, upsert=True)
    await event("deployment", f"{sid} {'ON' if enabled else 'OFF'} ({model}) — status {s['status']}")
    return items


async def event(kind: str, text: str, **extra) -> None:
    await EVENTS.insert_one({"at": datetime.now(timezone.utc), "kind": kind, "text": text, **extra})


# ── account ──────────────────────────────────────────────────────────────────────


async def account(cfg: R.RiskConfig | None = None) -> dict:
    cfg = cfg or await get_config()
    realized = 0.0
    async for t in TRADES.aggregate([{"$group": {"_id": None, "net": {"$sum": "$net"}}}]):
        realized = float(t["net"])
    unreal = 0.0
    n_open = 0
    async for p in POS.find({"status": "OPEN"}):
        unreal += float(p.get("unrealized") or 0.0)
        n_open += 1
    return {"capital": cfg.capital, "realized": realized, "unrealized": unreal, "equity": cfg.capital + realized + unreal,
            "open_positions": n_open}


# ── prices ───────────────────────────────────────────────────────────────────────


async def etf_touch(etf: str) -> dict | None:
    """Live bid / ask for an ETF (Angel full quote). None when there is no two-sided market."""
    from app.services.angel_client import angel_client
    exch, tok, _k, _t = INSTRUMENTS[etf]
    try:
        q = (await angel_client.full_quote({exch: [tok]})).get(tok) or {}
    except Exception as exc:  # noqa: BLE001
        logger.info("ETF quote failed for %s: %s", etf, exc)
        return None
    bid, ask = q.get("bid"), q.get("ask")
    if not bid or not ask or ask < bid:
        return None
    return {"bid": float(bid), "ask": float(ask), "ltp": q.get("ltp")}


# ── the engine ───────────────────────────────────────────────────────────────────


class Engine:
    def __init__(self) -> None:
        self.hist: dict[str, tuple[date, object]] = {}
        self.last_tick_minute: int | None = None
        self.notes: list[str] = []

    async def history(self, symbol: str, day: date):
        got = self.hist.get(symbol)
        if got is None or got[0] != day:
            d = await asyncio.to_thread(load_recent, symbol, HISTORY_DAYS)   # file reads: off the event loop
            keep = d.dates < np.datetime64(day.isoformat())          # history only: never today
            d.dates, d.o, d.h, d.l, d.c, d.v = d.dates[keep], d.o[keep], d.h[keep], d.l[keep], d.c[keep], d.v[keep]
            self.hist[symbol] = (day, d)
        return self.hist[symbol][1]

    async def warm(self, day: date) -> list[str]:
        """Before the open: fill any missing history day, then load the day's history for every
        deployed index (and VIX)."""
        deps = await deployments()
        need = {d["index"] for d in deps} | {p["index"] async for p in POS.find({"status": "OPEN"})}
        # a factory strategy reads its ETF's volume (factory.py), so that ETF's history is kept too
        etfs = {ROUTE[d["index"]][0] for d in deps if d.get("family") == "sf" and ROUTE[d["index"]][0]}
        syms = sorted(need | etfs | ({"INDIAVIX"} if need else set()))
        if syms:
            try:
                await feed.heal(syms)
            except Exception:  # noqa: BLE001 - a failed heal must not stop the warm-up
                logger.exception("history heal before the open failed")
        for sym in syms:
            self.hist.pop(sym, None)
            await self.history(sym, day)
        for sym in [s for s in self.hist if s not in need and s not in etfs and s != "INDIAVIX"]:
            self.hist.pop(sym, None)                                 # switched off: drop its history
        return sorted(need)

    async def today_days(self, symbol: str, now: datetime, upto: int):
        if feed.holes(symbol, now) > 0:
            await feed.backfill(symbol, now)
        return with_today(await self.history(symbol, now.date()), feed.today(symbol, now), now.date(), upto)

    async def tick(self, now: datetime | None = None, entries_allowed: bool = True) -> dict:
        from app.services import market_calendar
        now = now or now_ist()
        out = {"at": now.isoformat(), "opened": 0, "closed": 0, "notes": []}
        if not market_calendar.is_trading_day(now):
            return {**out, "notes": ["not a trading day"]}
        upto = session_minute(now)                      # minutes [0, upto) are complete
        if upto <= 0 or upto > SESSION_MIN:
            return {**out, "notes": ["outside the session"]}
        cfg = await get_config()
        deps = {d["sid"]: d for d in await deployments()}
        open_pos = [p async for p in POS.find({"status": "OPEN"})]
        acct = await account(cfg)
        st = await get_day(now.date(), acct["equity"])
        need = {d["index"] for d in deps.values()} | {p["index"] for p in open_pos}
        if not need:
            return {**out, "notes": ["nothing deployed"]}
        vix = await self.today_days("INDIAVIX", now, upto)
        built: dict[str, tuple] = {}
        sf_idx = ({d["index"] for d in deps.values() if d["family"] == "sf"}
                  | {p["index"] for p in open_pos if p["family"] == "sf"})
        for idx in need:
            D = await self.today_days(idx, now, upto)
            ctx = F.Ctx(D, vix)
            ctx.live = True                              # factory strategies: decisions cached per completed bar
            ctx.etf = None
            if idx in sf_idx and ROUTE[idx][0]:
                try:
                    ctx.etf = await self.today_days(ROUTE[idx][0], now, upto)
                except FileNotFoundError:
                    ctx.etf = None                       # volume-dependent factory rules then cannot fire
            built[idx] = (D, ctx)
        sq = minute_of(cfg.square_off)
        # 1) open positions: walk the minutes that just completed
        for p in open_pos:
            D, ctx = built[p["index"]]
            i = len(D.dates) - 1
            fam = F.FAMILIES[p["family"]](ctx, p["params"])
            xcfg = F.EXITS[p["exit"]]
            sig_exit = None
            if xcfg.signal_exit and fam[1] is not None:
                sig_exit = fam[1](i)(p["entry_min"], p["side"])
            hold_end = p["entry_min"] + xcfg.max_hold if xcfg.max_hold else None
            live = Live(p["side"], p["entry_min"], p["entry_raw"], p["entry_kind"], p.get("stop"), p.get("target"),
                        p.get("trail"), float(p["best"]), int(p["next_min"]))
            emergency = cfg.emergency_stop
            ex = None if emergency else step(live, D.o[i], D.h[i], D.l[i], upto, min(sq, SQUARE_OFF), sig_exit, hold_end)
            if emergency:
                ex = (upto, None, "emergency_stop")
            if ex is None:
                # the index model marks at the index; an ETF position only ever at an ETF price
                fallback = float(D.c[i][upto - 1]) if p["model"] == "index" else float(p.get("mark") or p["fill"])
                mark = feed.ltp(p["instrument"]) or fallback
                await POS.update_one({"_id": p["_id"]}, {"$set": {
                    "best": live.best, "next_min": live.next_min, "mark": mark,
                    "unrealized": self._unrealized(p, mark), "updated_at": datetime.now(timezone.utc)}})
                continue
            await self._close(p, ex, D, upto, now, cfg, st)
            out["closed"] += 1
        # 2) entries
        if entries_allowed and not cfg.emergency_stop:
            for sid, dep in deps.items():
                if await POS.count_documents({"sid": sid, "status": "OPEN"}):
                    continue
                D, ctx = built[dep["index"]]
                i = len(D.dates) - 1
                day_specs, _day_exit, max_trades = F.FAMILIES[dep["family"]](ctx, dep["params"])
                done = [t async for t in TRADES.find({"sid": sid, "day": now.date().isoformat()})]
                if len(done) >= max_trades:
                    continue
                after = max([t["exit_min"] + 1 for t in done], default=0)
                if dep["family"] == "sf":                  # the factory's evaluate() is Python bar by bar: off the loop
                    spec = await asyncio.to_thread(day_specs(i), after)
                else:
                    spec = day_specs(i)(after)
                if spec is None or spec.minute > upto:
                    continue
                if spec.minute < upto - STALE_SIGNAL_MIN:
                    key = f"missed:{sid}:{now.date()}:{spec.minute}"
                    if not await STATE.find_one({"_id": key}):
                        await STATE.insert_one({"_id": key, "at": datetime.now(timezone.utc)})
                        await event("missed", f"{sid}: a signal at {self._hhmm(spec.minute)} was seen too late — not entered")
                    continue
                acct = await account(cfg)
                fam_until = LAST_HALF_HOUR.get(dep["family"])
                last_exit = self._hhmm(max(t["exit_min"] for t in done)) if done else None
                ok, why = R.allow(cfg, st, now, acct["open_positions"], acct["unrealized"], acct["equity"],
                                  last_exit_hhmm=last_exit, family_until=fam_until)
                if not ok:
                    out["notes"].append(f"{sid}: {why}")
                    continue
                if await self._open(dep, spec, D, ctx, i, upto, now, cfg, acct["equity"], st):
                    out["opened"] += 1
        await save_day(st)
        await self._snapshot(now)
        out["notes"] = out["notes"][:20]
        await STATE.update_one({"_id": "engine"}, {"$set": {"last_tick": datetime.now(timezone.utc), "notes": out["notes"],
                                                            "last_opened": out["opened"], "last_closed": out["closed"]}},
                               upsert=True)
        return out

    @staticmethod
    def _hhmm(m: int) -> str:
        t = 9 * 60 + 15 + m
        return f"{t // 60:02d}:{t % 60:02d}"

    @staticmethod
    def _unrealized(p: dict, mark: float) -> float:
        side, units = p["side"], float(p["units"])
        return side * (mark - float(p["fill"])) * units - float(p.get("entry_cost") or 0.0)

    async def _open(self, dep, spec, D, ctx, i, upto, now, cfg, equity, st) -> bool:
        idx, model = dep["index"], dep["model"]
        etf = ROUTE[idx][0]
        xcfg = F.EXITS[dep["exit"]]
        atr = float(ctx.day_atr[i]) if ctx.day_atr[i] == ctx.day_atr[i] else 0.0
        live_px = feed.ltp(idx)
        if spec.kind == "stop":
            o_m = float(D.o[i][spec.minute]) if spec.minute < upto else (live_px or spec.level)
            gapped = o_m >= spec.level if spec.side > 0 else o_m <= spec.level
            raw = o_m if gapped else float(spec.level)
        else:
            raw = float(live_px) if live_px else float(D.c[i][upto - 1])
        stop = spec.stop
        sf_target, sf_signal = None, None
        if isinstance(spec, FX.SFSpec):                  # the factory's own levels, re-anchored to this fill
            stop = raw - spec.side * spec.stop_dist
            sf_target = raw + spec.side * spec.target_dist
            sf_signal = spec.signal
        if stop is None and xcfg.stop == "atr" and atr > 0:
            stop = raw - spec.side * xcfg.stop_mult * atr
        elif stop is None and xcfg.stop == "pct":
            stop = raw * (1 - spec.side * xcfg.stop_mult / 100)
        risk_pts = abs(raw - stop) if stop is not None else None
        target = raw + spec.side * xcfg.target_r * risk_pts if (xcfg.target_r and risk_pts) else None
        if sf_target is not None:
            target = sf_target
        trail = (xcfg.trail_mult * atr) if xcfg.trail == "atr" and atr > 0 else (
            raw * xcfg.trail_mult / 100 if xcfg.trail == "pct" else None)
        notional, how = R.size(cfg, equity, raw, stop, atr)
        etf_px, slip = ROUTE[idx][1], ROUTE[idx][2]
        if model == "etf":
            q = await etf_touch(etf)
            if q is None:
                await event("refused", f"{dep['sid']}: no two-sided {etf} market — not entered")
                return False
            fill = q["ask"] if spec.side > 0 else q["bid"]
            notional = min(notional, max_etf_order(etf))
            units = R.units_for(notional, fill, whole=True)
            if units < 1:
                await event("refused", f"{dep['sid']}: {etf} liquidity allows no position (cap Rs{max_etf_order(etf):,.0f})")
                return False
            instrument, entry_cost = etf, 0.0                        # charges booked at the close
        else:
            fill = raw * (1 + spec.side * slip / 1e4)
            units = R.units_for(notional, fill, whole=False)
            instrument = idx
            entry_cost = 0.0
        doc = {
            "sid": dep["sid"], "key": dep["key"], "family": dep["family"], "params": dep["params"], "exit": dep["exit"],
            "index": idx, "model": model, "instrument": instrument, "status": "OPEN", "side": spec.side,
            "day": now.date().isoformat(), "entry_min": int(spec.minute), "entry_time": now.isoformat(),
            "entry_kind": spec.kind, "entry_raw": raw, "fill": fill, "units": units, "notional": units * fill,
            "stop": stop, "target": target, "trail": trail, "best": raw, "next_min": int(spec.minute),
            "entry_cost": entry_cost, "sizing": how, "unrealized": 0.0, "mark": fill,
            "research_status": dep.get("status"), "opened_at": datetime.now(timezone.utc),
            **({"name": dep.get("name"), "grade": dep.get("grade"), "signal": sf_signal} if sf_signal is not None else {}),
        }
        await POS.insert_one(doc)
        st.trades += 1
        await event("entry", f"{dep['sid']} {'BUY' if spec.side > 0 else 'SELL'} {units:,.2f} {instrument} @ {fill:,.2f} "
                             f"({spec.kind} entry, {how})"
                             + (f" — {sf_signal.get('pattern')}" if sf_signal else ""),
                    sid=dep["sid"], family=dep["family"])
        return True

    async def _close(self, p, ex, D, upto, now, cfg, st) -> None:
        x_min, x_raw, reason = ex
        i = len(D.dates) - 1
        if x_raw is None or (isinstance(x_raw, float) and math.isnan(x_raw)) or x_min >= upto:
            # an exit at the open of the minute in progress: the live price is that open
            x_raw = feed.ltp(p["index"]) or float(D.c[i][upto - 1])
        side, units = p["side"], float(p["units"])
        idx = p["index"]
        if p["model"] == "etf":
            etf = ROUTE[idx][0]
            q = await etf_touch(etf)
            if q is None:
                last = feed.ltp(etf) or float(p["mark"])
                half = ROUTE[idx][2] / 1e4
                exit_px = last * (1 - half) if side > 0 else last * (1 + half)
                basis = "ETF last price less the measured half-spread (no live quote)"
            else:
                exit_px = q["bid"] if side > 0 else q["ask"]
                basis = "ETF touch"
            from app.services.angel_fees import round_trip
            fb = round_trip(float(p["fill"]), exit_px, int(units), "BUY" if side > 0 else "SELL", "INTRADAY")
            costs = fb.total
        else:
            slip = ROUTE[idx][2] / 1e4
            exit_px = x_raw * (1 - side * (0.0 if reason == "target" else slip))
            costs = float(p["notional"]) * fee_rt_bp(ROUTE[idx][1], float(p["notional"])) / 1e4
            basis = "index level (simulation), the ETF's charges"
        gross = side * (exit_px - float(p["fill"])) * units
        net = gross - costs
        trade = {
            "sid": p["sid"], "key": p["key"], "family": p["family"], "index": idx, "model": p["model"],
            "instrument": p["instrument"], "side": side, "units": units, "day": p["day"],
            "entry_min": p["entry_min"], "exit_min": int(min(x_min, SESSION_MIN - 1)),
            "entry_time": p["entry_time"], "exit_time": now.isoformat(), "entry": float(p["fill"]), "exit": exit_px,
            "entry_kind": p["entry_kind"], "exit_reason": reason, "exit_basis": basis, "gross": round(gross, 2),
            "costs": round(costs, 2), "net": round(net, 2),
            "net_bp": round(net / float(p["notional"]) * 1e4, 3) if p["notional"] else None,
            "notional": p["notional"], "stop": p.get("stop"), "target": p.get("target"), "sizing": p.get("sizing"),
            "research_status": p.get("research_status"), "closed_at": datetime.now(timezone.utc),
            **({"name": p.get("name"), "grade": p.get("grade"), "signal": p.get("signal")} if p.get("family") == "sf" else {}),
        }
        await TRADES.insert_one(trade)
        await POS.update_one({"_id": p["_id"]}, {"$set": {"status": "CLOSED", "exit_px": exit_px, "exit_reason": reason,
                                                          "net": round(net, 2), "closed_at": datetime.now(timezone.utc)}})
        acct = await account(cfg)
        R.after_close(cfg, st, net, now, acct["equity"])
        await event("exit", f"{p['sid']} {reason} {p['instrument']} @ {exit_px:,.2f} net Rs{net:,.2f}",
                    sid=p["sid"], family=p.get("family"))

    async def _snapshot(self, now: datetime) -> None:
        if now.minute % 5:
            return
        acct = await account()
        await EQUITY.update_one({"at": now.replace(second=0, microsecond=0).isoformat()},
                                {"$set": {"equity": acct["equity"], "realized": acct["realized"],
                                          "unrealized": acct["unrealized"], "open": acct["open_positions"]}},
                                upsert=True)

    async def flatten_all(self, reason: str = "manual_flatten") -> dict:
        now = now_ist()
        cfg = await get_config()
        upto = max(1, min(session_minute(now), SESSION_MIN))
        acct = await account(cfg)
        st = await get_day(now.date(), acct["equity"])
        n = 0
        async for p in POS.find({"status": "OPEN"}):
            D = await self.today_days(p["index"], now, upto)
            await self._close(p, (upto, None, reason), D, upto, now, cfg, st)
            n += 1
        await save_day(st)
        return {"closed": n}


engine = Engine()
