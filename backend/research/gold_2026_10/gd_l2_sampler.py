"""Sample Delta's gold perp order books: what does a Gold Desk slot really pay to cross?

Standard library only (runs on the AWS host's python3 without the app):

    nohup python3 gd_l2_sampler.py 72 60 /tmp/gd_l2.jsonl > /tmp/gd_l2.log 2>&1 &

args: hours to run, seconds between samples, output file. Each line: per symbol, the best
bid/ask, the quoted spread, the mark, and the cost in bp (vs mid) of a market order of
$1,666.67 (one slot of the $10k book over 6 slots) and of $10,000 walked through the book.
Public endpoint, two requests a sample. Exits by itself when the hours are up.
"""

import json
import sys
import time
import urllib.request

BASE = "https://api.india.delta.exchange"
SYMS = ("XAUTUSD", "PAXGUSD")
CONTRACT_OZ = 0.001
SIZES_USD = (1666.67, 10000.0)


def get(path: str) -> dict:
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json",
                                                        "User-Agent": "gold-desk-research/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def walk(levels: list[tuple[float, float]], usd: float) -> tuple[float | None, float]:
    """VWAP of filling `usd` of notional through `levels` [(price, contracts)], best first.
    Returns (vwap, fraction filled)."""
    need = usd
    cost = got = 0.0
    for px, size in levels:
        avail = px * size * CONTRACT_OZ
        take = min(avail, need)
        if take <= 0:
            break
        cost += take
        got += take / px
        need -= take
        if need <= 1e-9:
            break
    if got <= 0:
        return None, 0.0
    return cost / got, (usd - need) / usd


def sample() -> dict:
    out = {"ts": int(time.time())}
    for s in SYMS:
        try:
            ob = get(f"/v2/l2orderbook/{s}?depth=50")["result"]
            tk = get(f"/v2/tickers/{s}")["result"]
        except Exception as exc:  # noqa: BLE001
            out[s] = {"error": str(exc)[:120]}
            continue
        bids = [(float(x["price"]), float(x["size"])) for x in ob.get("buy", [])]
        asks = [(float(x["price"]), float(x["size"])) for x in ob.get("sell", [])]
        if not bids or not asks:
            out[s] = {"error": "one-sided"}
            continue
        bb, ba = bids[0][0], asks[0][0]
        mid = (bb + ba) / 2
        row = {"bid": bb, "ask": ba, "bid_size": bids[0][1], "ask_size": asks[0][1],
               "spread_bp": (ba - bb) / mid * 1e4, "mark": float(tk.get("mark_price") or 0),
               "funding": tk.get("funding_rate"), "levels": [len(bids), len(asks)]}
        for usd in SIZES_USD:
            vb, fb = walk(asks, usd)
            vs, fs = walk(bids, usd)
            row[f"buy_{int(usd)}_bp"] = (vb - mid) / mid * 1e4 if vb else None
            row[f"sell_{int(usd)}_bp"] = (mid - vs) / mid * 1e4 if vs else None
            row[f"fill_{int(usd)}"] = min(fb, fs)
        out[s] = row
    return out


def main() -> None:
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    every = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    path = sys.argv[3] if len(sys.argv) > 3 else "gd_l2.jsonl"
    stop = time.time() + hours * 3600
    while time.time() < stop:
        t0 = time.time()
        try:
            rec = sample()
            with open(path, "a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception as exc:  # noqa: BLE001
            print("sample failed:", exc, flush=True)
        time.sleep(max(1.0, every - (time.time() - t0)))


if __name__ == "__main__":
    main()
