"""Read-only exports from the box into DATA/exports and DATA/intraday, for the research harness.

Database exports run in a THROWAWAY container of the backend image on the box, with the box's
own .env: the database credential never leaves the box, and the running backend's memory is
untouched. Bar files are streamed as a tar straight to this machine (nothing written on the
box, whose disk is nearly full). Nothing here writes to any database.

    set BOX_HOST=ubuntu@<box address>   BOX_SSH_KEY=<path to the .pem>
    python export_box.py bars1d 2024-08-01 2026-11-05
    python export_box.py universe 2026-10-01 2026-11-05
    python export_box.py members            # today's universe + CAS flags (export1.json)
    python export_box.py live 2026-10-01    # tournament positions
    python export_box.py h1                 # H1 order-book samples + daily turnover
    python export_box.py files 15m | 5m | nse
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from stubpkg import DATA

HOST = os.getenv("BOX_HOST", "")
KEY = os.getenv("BOX_SSH_KEY", "")
VOLUME = "/var/lib/docker/volumes/alpha-engine_intraday_data/_data"
CONTAINER = ("docker run --rm -i --memory 250m --env-file /home/ubuntu/alpha-engine/.env "
             "-w /app/backend alpha-engine-backend python -")

HEAD = '''import json, os, sys
from datetime import datetime, timezone
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=30000)[os.environ.get("MONGO_DB_NAME", "tradingai")]
'''

SCRIPTS = {
    # 1d bars via the (symbol, timeframe, ts) index: the backtest's point-in-time universe input
    "bars1d": HEAD + '''
lo, hi = [datetime.fromisoformat(x).replace(tzinfo=timezone.utc) for x in sys.argv[1:3]]
syms = db["bars"].distinct("symbol")
n = 0
for b in db["bars"].find({"symbol": {"$in": syms}, "timeframe": "1d", "ts": {"$gte": lo, "$lt": hi}},
                         {"symbol": 1, "ts": 1, "close": 1, "volume": 1, "_id": 0}).batch_size(5000):
    ts = b.get("ts")
    if not isinstance(ts, datetime) or b.get("close") is None or b.get("volume") is None:
        continue
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    sys.stdout.write(f"{b['symbol']}\\t{int(ts.timestamp())}\\t{float(b['close'])!r}\\t{float(b['volume'])!r}\\n")
    n += 1
print(f"rows {n}", file=sys.stderr)
''',
    "universe": HEAD + '''
out = [{"_id": d["_id"], "members": [m.get("symbol") for m in d.get("members", [])],
        "turnover": {m.get("symbol"): m.get("turnover_cr") for m in d.get("members", [])}}
       for d in db["intraday_universe"].find({"_id": {"$gte": sys.argv[1], "$lte": sys.argv[2]}}).sort("_id", 1)]
json.dump(out, sys.stdout)
print(f"days {len(out)}", file=sys.stderr)
''',
    "members": HEAD + '''
files = json.loads(sys.argv[1])
uni = db["intraday_universe"].find_one({}, sort=[("_id", -1)])
out = {"universe_id": uni and uni["_id"], "members": list(uni["members"]) if uni else [],
       "instruments": list(db["instruments"].find({"asset_class": "EQUITY", "symbol": {"$in": files}},
                                                  {"symbol": 1, "is_cas_enabled": 1, "_id": 0}))}
json.dump(out, sys.stdout, default=str)
''',
    "live": HEAD + '''
F = ["strategy_id", "symbol", "side", "status", "signal_bar_close", "opened_at", "closed_at", "entry_price",
     "signal_price", "exit_price", "exit_reason", "qty", "capital_deployed", "slippage_bp", "gross_pnl", "fees",
     "realized_pnl", "stoploss", "target", "rule_version", "gate_version", "cost_model"]
since = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=timezone.utc)
for d in db["intraday_lab_positions"].find({"engine": "v2", "opened_at": {"$gte": since}}, {k: 1 for k in F} | {"_id": 0}):
    for k in ("signal_bar_close", "opened_at", "closed_at"):
        v = d.get(k)
        if isinstance(v, datetime):
            d[k] = int((v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp())
    sys.stdout.write(json.dumps(d, default=str) + "\\n")
''',
    # results-day reactions (the expected-move model's "results" feature): {symbol: [reaction days]}
    "results": HEAD + '''
out = {}
for d in db["results_calendar"].find({"kind": "filed"}, {"symbol": 1, "reaction_day": 1, "_id": 0}):
    if d.get("symbol") and d.get("reaction_day"):
        out.setdefault(d["symbol"], []).append(str(d["reaction_day"])[:10])
json.dump(out, sys.stdout)
print(f"symbols {len(out)}", file=sys.stderr)
''',
    # NSE industry label per symbol (fundamental_universe_symbols), for sector context
    "sectors": HEAD + '''
out = {d["_id"]: d.get("sector") for d in db["fundamental_universe_symbols"].find({}, {"sector": 1})}
json.dump(out, sys.stdout)
print(f"symbols {len(out)}", file=sys.stderr)
''',
    "h1": HEAD + '''
U = {d["_id"]: {m["symbol"]: m.get("turnover_cr") for m in d.get("members", [])}
     for d in db["intraday_universe"].find({"_id": {"$gte": "2026-10-01"}}, {"members.symbol": 1, "members.turnover_cr": 1})}
F = ["strategy_id", "symbol", "phase", "side", "signal_at", "cost_bp_vs_ltp", "cost_bp_vs_mid", "half_spread_bp",
     "insufficient_depth", "measurable", "depth_covered_pct", "shares", "ltp", "lag_s"]
json.dump({"universe": U, "samples": list(db["intraday_h1_samples"].find({}, {k: 1 for k in F} | {"_id": 0}))},
          sys.stdout, default=str)
''',
}


def _ssh(command: str, stdin: bytes | None, out_path: pathlib.Path) -> None:
    assert HOST and KEY, "set BOX_HOST and BOX_SSH_KEY"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as out:
        r = subprocess.run(["ssh", "-i", KEY, HOST, command], input=stdin, stdout=out, stderr=subprocess.PIPE)
    err = r.stderr.decode("utf-8", "replace").strip().splitlines()
    print(f"{out_path.name}: {out_path.stat().st_size:,} bytes; {err[-1] if err else ''}")
    if r.returncode != 0:
        raise SystemExit(f"export failed ({r.returncode}): {err[-5:]}")


def container(kind: str, args: list[str], out_name: str) -> None:
    quoted = " ".join("'" + a.replace("'", "'\\''") + "'" for a in args)
    _ssh(f"{CONTAINER} {quoted}", SCRIPTS[kind].encode(), DATA / "exports" / out_name)


def files(tf: str) -> None:
    """Stream the box's bar files (or NSE archives) as a tar, unpacked under DATA/intraday."""
    tgz = DATA / "exports" / f"{tf}.tgz"
    _ssh(f"sudo tar -C {VOLUME} -czf - {tf}", None, tgz)
    unpack(tf)


def unpack(tf: str) -> None:
    """Python's tarfile with the 'data' filter (Windows tar reads 'D:' as a remote host)."""
    import tarfile
    dest = DATA / "intraday"
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(DATA / "exports" / f"{tf}.tgz", "r:gz") as t:
        t.extractall(dest, filter="data")
    print(f"unpacked {tf}: {len(list((dest / tf).iterdir()))} entries")


def main() -> None:
    kind, args = sys.argv[1], sys.argv[2:]
    if kind == "files":
        files(args[0])
    elif kind == "bars1d":
        container("bars1d", args, "bars1d.tsv")
    elif kind == "universe":
        container("universe", args, "universe_days.json")
    elif kind == "members":
        syms = sorted(p.stem for p in (DATA / "intraday" / "15m").glob("*.ibar") if p.stem != "NIFTY")
        import json
        container("members", [json.dumps(syms)], "export1.json")
    elif kind == "live":
        container("live", args, "live_v2.jsonl")
    elif kind == "h1":
        container("h1", [], "h1_cal.json")
    elif kind == "results":
        container("results", [], "results_reactions.json")
    elif kind == "sectors":
        container("sectors", [], "sectors.json")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    main()
