"""The AI Approved tab's strategy leaderboard and daily table, on in-memory MongoDB (mongomock-motor).
    cd backend && python -m pytest tests/ai_gate -q
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

mm = pytest.importorskip("mongomock_motor")

from app.services import ai_gate as G  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 11, 10, 5, 0, tzinfo=UTC)          # 10:30 IST


def run(coro):
    return asyncio.run(coro)


class Module:
    """A module that has closed some positions of its own since the gate started."""
    module = "intraday"

    def __init__(self, closed):
        self.closed = closed

    async def context(self, p):
        return {"bars": [], "record": {"n": 0, "wins": 0, "net": 0.0}}

    async def outcomes(self, ids):
        return {i: {"status": "OPEN"} for i in ids}

    async def control(self, since):
        return {"INR": {"n": len(self.closed), "wins": sum(c["pnl"] > 0 for c in self.closed),
                        "net": sum(c["pnl"] for c in self.closed)}}

    async def closed_since(self, since):
        return self.closed


def par(pid, sid, name):
    return {"parent_id": pid, "strategy_id": sid, "strategy_name": name, "symbol": "SBIN", "side": "BUY", "entry": 100.0,
            "stop": 99.0, "target": 101.0, "currency": "INR", "signal_time": NOW, "opened_at": NOW - timedelta(seconds=5)}


def answer(decision):
    async def _a(prompt):
        return ({"decision": decision, "p_profit": 0.6 if decision == "take" else 0.3, "confidence": "medium",
                 "reasons": ["r"], "main_risk": "m"}, {"input_tokens": 500, "output_tokens": 100}, G.MODEL)
    return _a


@pytest.fixture()
def setup(monkeypatch):
    rp = G.MongoRepo(mm.AsyncMongoMockClient()["alpha_engine_intraday"])
    monkeypatch.setattr(G, "_repo", rp)
    closed = [
        {"strategy_id": "A", "strategy_name": "Alpha", "pnl": 900.0, "closed_at": NOW + timedelta(hours=1), "currency": "INR"},
        {"strategy_id": "A", "strategy_name": "Alpha", "pnl": -300.0, "closed_at": NOW + timedelta(hours=2), "currency": "INR"},
        {"strategy_id": "B", "strategy_name": "Beta", "pnl": -700.0, "closed_at": NOW + timedelta(hours=1), "currency": "INR"},
        {"strategy_id": "Z", "strategy_name": "Never reviewed", "pnl": 50.0, "closed_at": NOW, "currency": "INR"},
    ]
    mod = Module(closed)
    monkeypatch.setitem(G.ADAPTERS, "intraday", mod)
    run(rp.ensure())
    run(G.review("intraday", par("a1", "A", "Alpha"), rp, mod, answer("take"), NOW))
    run(G.review("intraday", par("a2", "A", "Alpha"), rp, mod, answer("skip"), NOW))
    run(G.review("intraday", par("b1", "B", "Beta"), rp, mod, answer("take"), NOW))
    run(G.review("intraday", par("b2", "B", "Beta"), rp, mod, answer("take"), NOW))
    run(rp.update_position("AI-INT-20261110-0001", {"status": "CLOSED", "pnl": 900.0, "closed_at": NOW + timedelta(hours=1)}))
    run(rp.update_position("AI-INT-20261110-0002", {"status": "CLOSED", "pnl": -700.0, "closed_at": NOW + timedelta(hours=1)}))
    return rp


def test_leaderboard(setup):
    lb = run(G.leaderboard("intraday"))
    rows = {r["strategy_id"]: r for r in lb["rows"]}
    assert [r["strategy_id"] for r in lb["rows"]] == ["A", "B"]              # ranked by the AI book's net; Z never reviewed
    a, b = rows["A"], rows["B"]
    assert (a["rank"], a["reviewed"], a["approved"], a["skipped"], a["approval_rate"]) == (1, 2, 1, 1, 50.0)
    assert (a["ai_trades"], a["ai_net"], a["ai_win_rate"], a["ai_open"]) == (1, 900.0, 100.0, 0)
    assert (a["module_trades"], a["module_net"], a["module_win_rate"]) == (2, 600.0, 50.0)
    assert (b["approved"], b["ai_trades"], b["ai_net"], b["ai_open"], b["module_net"]) == (2, 1, -700.0, 1, -700.0)
    assert a["currency"] == "INR" and a["strategy_name"] == "Alpha"


def test_daily(setup):
    d = run(G.daily("intraday"))
    assert [r["day"] for r in d["rows"]] == ["2026-11-10"]
    r = d["rows"][0]
    assert (r["ai_trades"], r["ai_net"], r["module_trades"], r["module_net"]) == (2, 200.0, 4, -50.0)


def test_gold_leaderboard_keeps_usd(monkeypatch):
    rp = G.MongoRepo(mm.AsyncMongoMockClient()["alpha_engine_intraday"])
    monkeypatch.setattr(G, "_repo", rp)
    mod = Module([{"strategy_id": "g", "strategy_name": "Breakout · 4h", "pnl": 12.5, "closed_at": NOW, "currency": "USD"}])
    mod.module = "gold"
    monkeypatch.setitem(G.ADAPTERS, "gold", mod)
    p = par("g1", "g", "Breakout · 4h") | {"currency": "USD"}
    run(G.review("gold", p, rp, mod, answer("take"), NOW))
    run(rp.update_position("AI-GLD-20261110-0001", {"status": "CLOSED", "pnl": 12.5, "currency": "USD", "closed_at": NOW}))
    row = run(G.leaderboard("gold"))["rows"][0]
    assert row["currency"] == "USD" and row["ai_net"] == 12.5 and row["module_net"] == 12.5
