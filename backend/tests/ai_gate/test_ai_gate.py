"""AI final gate: the review, the AI position (id and timestamps), fail-closed paths, the cap, and closes.

No database and no API key: an in-memory repository, a fake module and a scripted model stand in.
    cd backend && python -m pytest tests/ai_gate -q
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import ai_gate as G

UTC = timezone.utc
NOW = datetime(2026, 11, 10, 5, 0, tzinfo=UTC)          # 10:30 IST


class MemoryRepo:
    def __init__(self):
        self.dec, self.pos, self.seq = {}, {}, {}

    async def ensure(self):
        pass

    async def expire_pending(self, before):
        n = 0
        for d in self.dec.values():
            if d["decision"] == "pending" and d["seen_at"] < before:
                d.update(decision="not_reviewed", why="interrupted by a restart")
                n += 1
        return n

    async def claim(self, doc):
        if doc["_id"] in self.dec:
            return False
        self.dec[doc["_id"]] = dict(doc)
        return True

    async def decided(self, ids):
        return {i for i in ids if i in self.dec}

    async def called_today(self, module, day):
        return sum(1 for d in self.dec.values() if d["module"] == module and d["d"] == day and d.get("called"))

    async def finish(self, dec_id, fields):
        self.dec[dec_id].update(fields)

    async def next_seq(self, module, day):
        k = (module, day)
        self.seq[k] = self.seq.get(k, 0) + 1
        return self.seq[k]

    async def add_position(self, doc):
        assert doc["_id"] not in self.pos
        self.pos[doc["_id"]] = dict(doc)

    async def open_positions(self, module):
        return [dict(p) for p in self.pos.values() if p["module"] == module and p["status"] == "OPEN"]

    async def update_position(self, ai_id, fields):
        self.pos[ai_id].update(fields)


class FakeAdapter:
    module = "intraday"

    def __init__(self, outcomes=None):
        self.out = outcomes or {}

    async def context(self, p):
        return {"bars": [[int((p["signal_time"] - timedelta(minutes=15)).timestamp()), 100, 101, 99, 100.5, 1000]],
                "bar_label": "15-minute bars", "record": {"n": 10, "wins": 4, "net": -2500.0, "window": "last 60 days"}}

    async def outcomes(self, ids):
        return {i: self.out.get(i, {"status": "OPEN"}) for i in ids}


def parent(pid="p1", opened=NOW - timedelta(seconds=20)):
    return {"parent_id": pid, "strategy_id": "iv2_supertrend_1h", "strategy_name": "Supertrend Flip · 1 hour",
            "rule": "Supertrend(10,3) changing direction", "symbol": "RELIANCE", "market": "NSE cash, intraday",
            "side": "BUY", "entry": 1412.75, "stop": 1398.1, "target": 1427.4, "qty": 707, "timeframe": "1h",
            "currency": "INR", "signal_time": opened - timedelta(seconds=5), "opened_at": opened}


def asker(decision="take", p=0.58):
    async def _ask(prompt):
        assert "RELIANCE" in prompt and "1,412.7500" in prompt
        return ({"decision": decision, "p_profit": p, "confidence": "medium", "reasons": ["with the trend"],
                 "main_risk": "late in the move"},
                {"input_tokens": 900, "output_tokens": 300, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                G.MODEL)
    return _ask


def run(coro):
    return asyncio.run(coro)


def test_bars_stop_at_the_signal():
    t0 = int(datetime(2026, 11, 10, 3, 45, tzinfo=UTC).timestamp())     # 09:15 IST
    b = SimpleNamespace(t=[t0 + 900 * i for i in range(8)], o=[1.0] * 8, h=[2.0] * 8, l=[0.5] * 8, c=[1.5] * 8, v=[10] * 8)
    cut = t0 + 900 * 4                                   # 10:15 IST: bars 09:15-10:00 have closed
    rows = G._rows_from_arrays(b, cut, 900, 26)
    assert [r[0] for r in rows] == [t0, t0 + 900, t0 + 1800, t0 + 2700]
    assert G._rows_from_arrays(b, cut + 899, 900, 26)[-1][0] == t0 + 2700    # the 10:15 bar is still forming
    objs = [SimpleNamespace(ts=datetime.fromtimestamp(t, UTC), open=1, high=2, low=0.5, close=1.5, volume=1) for t in b.t]
    assert [r[0] for r in G._rows_from_objects(objs, datetime.fromtimestamp(cut, UTC), 15, 26)] == [r[0] for r in rows]


def test_prompt_holds_the_position_and_nothing_after_it():
    p = parent()
    ctx = run(FakeAdapter().context(p))
    text = G.build_prompt("intraday", p, ctx)
    for s in ("Intraday Stocks", "Supertrend Flip", "BUY RELIANCE", "1,412.7500", "1,398.1000", "1,427.4000",
              "10 closed trades, 40% won", "reward to risk 1.00"):
        assert s in text, s


def test_parse_answer():
    a = G.parse_answer('{"decision": "TAKE", "p_profit": 1.7, "confidence": "x", "reasons": ["a", "", "b"], "main_risk": "r"}')
    assert a["decision"] == "take" and a["p_profit"] == 1.0 and a["confidence"] == "low" and a["reasons"] == ["a", "b"]
    with pytest.raises(ValueError):
        G.parse_answer('{"decision": "maybe", "p_profit": 0.5}')


def test_take_creates_an_ai_position_with_its_own_id_and_times():
    rp = MemoryRepo()
    p = parent()
    d = run(G.review("intraday", p, rp, FakeAdapter(), asker("take"), NOW))
    assert d["decision"] == "take" and d["ai_position_id"] == "AI-INT-20261110-0001"
    pos = rp.pos["AI-INT-20261110-0001"]
    assert pos["parent_id"] == "p1" and pos["status"] == "OPEN" and pos["entry_price"] == 1412.75
    assert pos["signal_time"] == p["signal_time"] and pos["parent_opened_at"] == p["opened_at"]
    assert pos["approved_at"] == pos["opened_at"] == NOW and pos["opened_on"] == "2026-11-10"
    assert d["lag_s"] == 20.0 and d["cost_usd"] == round((900 * 2 + 300 * 10) / 1e6, 6)
    # a second look at the same parent does nothing: decided once, never re-judged
    assert run(G.review("intraday", p, rp, FakeAdapter(), asker("skip"), NOW)) is None
    d2 = run(G.review("intraday", parent("p2"), rp, FakeAdapter(), asker("take"), NOW))
    assert d2["ai_position_id"] == "AI-INT-20261110-0002"


def test_skip_creates_no_ai_position():
    rp = MemoryRepo()
    d = run(G.review("intraday", parent(), rp, FakeAdapter(), asker("skip", 0.41), NOW))
    assert d["decision"] == "skip" and not rp.pos and "ai_position_id" not in d


def test_fail_closed():
    rp = MemoryRepo()

    async def broken(prompt):
        raise G.GateError("timeout")
    d = run(G.review("intraday", parent("a"), rp, FakeAdapter(), broken, NOW))
    assert d["decision"] == "not_reviewed" and d["why"] == "timeout" and d["called"] and not rp.pos

    async def crash(prompt):
        raise RuntimeError("boom")
    d = run(G.review("intraday", parent("b"), rp, FakeAdapter(), crash, NOW))
    assert d["decision"] == "not_reviewed" and d["why"].startswith("error") and not rp.pos

    old = parent("c", opened=NOW - timedelta(minutes=G.MODULES["intraday"]["lookback_min"] + 1))
    d = run(G.review("intraday", old, rp, FakeAdapter(), asker("take"), NOW))
    assert d["decision"] == "not_reviewed" and d["why"] == "seen too late to review" and not d["called"]


def test_no_key_means_not_reviewed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rp = MemoryRepo()
    d = run(G.review("intraday", parent(), rp, FakeAdapter(), None, NOW))
    assert d["decision"] == "not_reviewed" and "API key" in d["why"] and not rp.pos


def test_daily_cap(monkeypatch):
    monkeypatch.setitem(G.MODULES["intraday"], "daily_max", 2)
    rp = MemoryRepo()
    for i in range(2):
        assert run(G.review("intraday", parent(f"x{i}"), rp, FakeAdapter(), asker("take"), NOW))["decision"] == "take"
    d = run(G.review("intraday", parent("x2"), rp, FakeAdapter(), asker("take"), NOW))
    assert d["decision"] == "not_reviewed" and "daily cap" in d["why"] and len(rp.pos) == 2


def test_closes_follow_the_parent():
    rp = MemoryRepo()
    run(G.review("intraday", parent("p1"), rp, FakeAdapter(), asker("take"), NOW))
    run(G.review("intraday", parent("p2"), rp, FakeAdapter(), asker("take"), NOW))
    closed_at = NOW + timedelta(hours=2)
    ad = FakeAdapter({"p1": {"status": "CLOSED", "exit_price": 1427.4, "exit_reason": "target", "closed_at": closed_at,
                             "pnl": 9876.5, "currency": "INR"},
                      "p2": {"status": "MISSING"}})
    assert run(G.sync_closes("intraday", rp, ad, NOW + timedelta(hours=2))) == 1
    a1, a2 = rp.pos["AI-INT-20261110-0001"], rp.pos["AI-INT-20261110-0002"]
    assert a1["status"] == "CLOSED" and a1["pnl"] == 9876.5 and a1["closed_at"] == closed_at and a1["exit_reason"] == "target"
    assert a1["move_pct"] == round((1427.4 / 1412.75 - 1) * 100, 4)
    assert a2["status"] == "OPEN" and a2["missing_since"] == NOW + timedelta(hours=2)
    run(G.sync_closes("intraday", rp, ad, NOW + timedelta(hours=2, seconds=G.VOID_AFTER_S + 1)))
    assert rp.pos["AI-INT-20261110-0002"]["status"] == "VOID"


def test_interrupted_reviews_expire():
    rp = MemoryRepo()
    run(rp.claim({"_id": "intraday|z", "module": "intraday", "decision": "pending", "seen_at": NOW, "d": "2026-11-10"}))
    assert run(rp.expire_pending(NOW + timedelta(minutes=11))) == 1
    assert rp.dec["intraday|z"]["decision"] == "not_reviewed"


def test_ids_and_costs():
    assert G.ai_position_id("premium", "2026-11-10", 42) == "AI-PRM-20261110-0042"
    assert G.ai_position_id("gold", "2026-01-02", 1) == "AI-GLD-20260102-0001"
    assert G.cost_usd({"input_tokens": 1_000_000, "output_tokens": 100_000}) == 3.0
