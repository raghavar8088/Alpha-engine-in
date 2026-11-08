"""Delta Exchange order flow: the aggressor side of every BTCUSD trade, from Delta's public trade feed, summed per minute.

Delta's 1-minute candles carry total volume only. The order-flow strategies (CP-14, CP-15) need to know who was
aggressive, so this thread subscribes to `all_trades` and writes, for each finished minute, the contracts bought and
sold by takers: /data/premium/flow/BTCUSD/<UTC date>.jsonl, one line [minute start, taker buy, taker sell, trades].

A minute is written only if the connection was up for the whole of it; a minute with no trades is written as zeros.
Minutes missed during a reconnect or a restart are simply absent, and the strategies treat their candles' delta as
unknown, so they never trade on a delta they did not see. Started by main.py; paper only, reads public data.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from settings import DATA

log = logging.getLogger("premium.flow")
URL = "wss://socket.india.delta.exchange"
SYMBOL = "BTCUSD"
OUT = DATA / "flow" / SYMBOL
GRACE_S = 3            # a minute is written this long after it ends, for late messages
SILENCE_S = 35         # no message (Delta sends heartbeats every few seconds) for this long: reconnect


class Recorder:
    def __init__(self, out: Path = OUT):
        self.out = out
        self.cur: dict[int, list] = {}
        self.covered_from: int | None = None
        self.written_to: int | None = None

    def connected(self, now: float) -> None:
        """Coverage starts at the first minute that begins after the subscription is confirmed."""
        self.cur = {}
        self.covered_from = (int(now) // 60 + 1) * 60

    def lost(self) -> None:
        self.cur = {}
        self.covered_from = None

    def trade(self, ts_us: int, size: float, buyer_taker: bool) -> None:
        if self.covered_from is None:
            return
        t = int(ts_us // 1_000_000)
        m = t - t % 60
        if m < self.covered_from or (self.written_to is not None and m <= self.written_to):
            return
        x = self.cur.setdefault(m, [0.0, 0.0, 0])
        x[0 if buyer_taker else 1] += float(size)
        x[2] += 1

    def flush(self, now: float) -> int:
        """Write every covered minute that ended at least GRACE_S ago."""
        if self.covered_from is None:
            return 0
        end = (int(now - GRACE_S) // 60) * 60               # minutes starting before `end` are complete
        start = self.covered_from if self.written_to is None else max(self.covered_from, self.written_to + 60)
        rows = []
        t = start
        while t < end:
            b, s, n = self.cur.pop(t, [0.0, 0.0, 0])
            rows.append([t, round(b, 6), round(s, 6), n])
            t += 60
        if not rows:
            return 0
        self.out.mkdir(parents=True, exist_ok=True)
        by_day: dict[str, list] = {}
        for r in rows:
            by_day.setdefault(time.strftime("%Y-%m-%d", time.gmtime(r[0])), []).append(r)
        for day, rr in by_day.items():
            with open(self.out / f"{day}.jsonl", "a", encoding="utf-8") as fh:
                fh.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rr))
        self.written_to = rows[-1][0]
        return len(rows)


def _status(rec: "Recorder", connected: bool, last_msg: float | None, error: str | None = None) -> None:
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT.parent / "status.json.tmp"
        tmp.write_text(json.dumps({"connected": connected, "since": rec.covered_from, "last_msg_t": int(last_msg) if last_msg else None,
                                   "written_to": rec.written_to, "error": error, "at": int(time.time())}))
        tmp.replace(OUT.parent / "status.json")
    except Exception:  # noqa: BLE001
        pass


def run_forever() -> None:
    import websocket          # websocket-client

    rec = Recorder()
    if OUT.exists():
        last = sorted(OUT.glob("*.jsonl"))
        if last:
            try:
                rec.written_to = json.loads(last[-1].read_text().strip().splitlines()[-1])[0]
            except Exception:  # noqa: BLE001
                pass
    while True:
        ws = None
        try:
            ws = websocket.create_connection(URL, timeout=20)
            ws.settimeout(SILENCE_S)
            ws.send(json.dumps({"type": "enable_heartbeat"}))
            ws.send(json.dumps({"type": "subscribe", "payload": {"channels": [{"name": "all_trades", "symbols": [SYMBOL]}]}}))
            last_status = 0.0
            while True:
                msg = json.loads(ws.recv())
                now = time.time()
                kind = msg.get("type")
                if now - last_status >= 20:
                    _status(rec, rec.covered_from is not None, now)
                    last_status = now
                if kind == "subscriptions" and rec.covered_from is None:
                    rec.connected(now)
                    _status(rec, True, now)
                    last_status = now
                    log.info("delta trade feed connected; minutes recorded from %s", time.strftime("%H:%M:%S", time.gmtime(rec.covered_from)))
                elif kind == "all_trades" and msg.get("symbol") == SYMBOL:
                    buyer = msg.get("buyer_role") == "taker"
                    seller = msg.get("seller_role") == "taker"
                    if buyer != seller:
                        rec.trade(int(msg["timestamp"]), float(msg.get("size") or 0), buyer)
                rec.flush(now)
        except Exception as exc:  # noqa: BLE001 - any failure: drop the partial minute, reconnect
            log.warning("delta trade feed: %s; reconnecting", str(exc)[:200])
            _status(rec, False, None, str(exc)[:200])
        finally:
            rec.lost()
            try:
                if ws is not None:
                    ws.close()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(5)


def read(since_t: int) -> dict[int, tuple[float, float]]:
    """{minute start: (taker buy, taker sell)} for every recorded minute from since_t."""
    out: dict[int, tuple[float, float]] = {}
    if not OUT.exists():
        return out
    first = time.strftime("%Y-%m-%d", time.gmtime(since_t))
    for f in sorted(OUT.glob("*.jsonl")):
        if f.stem < first:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                t, b, s, _n = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if t >= since_t:
                out[int(t)] = (float(b), float(s))
    return out
