"""Build a runnable local copy of the tournament's backtest from a git commit.

The production modules (rules, store, fills, fees, backtest, portfolio) are written out exactly
as committed at `commit` — never the working copy, which may hold another session's uncommitted
edits. The database and the live services are replaced by small stand-ins that serve the
read-only exports in DATA (see export_box.py); nothing here can write to any database.

    from stubpkg import build, activate
    pkg = build("HEAD")          # -> DATA/pkg/<sha>/
    activate(pkg)                # sys.path + env, before importing any `app.` module
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
DATA = pathlib.Path(os.getenv("INTRADAY_AI_DATA", r"D:/intraday_ai_data"))

REAL = [  # (path in the repo, path in the package)
    ("backend/app/services/intraday_v2_backtest.py", "app/services/intraday_v2_backtest.py"),
    ("backend/app/services/intraday_v2_strategies.py", "app/services/intraday_v2_strategies.py"),
    ("backend/app/services/intraday_v2_portfolio.py", "app/services/intraday_v2_portfolio.py"),
    ("backend/app/services/intraday_store.py", "app/services/intraday_store.py"),
    ("backend/app/services/intraday_fills.py", "app/services/intraday_fills.py"),
    ("backend/app/services/angel_fees.py", "app/services/angel_fees.py"),
    ("backend/app/services/nifty_scalp_strategies.py", "app/services/nifty_scalp_strategies.py"),
    ("shared/tradingai_shared/__init__.py", "tradingai_shared/__init__.py"),
    ("shared/tradingai_shared/option_fees.py", "tradingai_shared/option_fees.py"),
]

STUBS = {
    "app/__init__.py": "",
    "app/core/__init__.py": "",
    "app/services/__init__.py": "",
    "app/services/angel_stream.py": '"""Stand-in: the backtest never reads the live tick stream."""\nstream = None\n',
    "app/services/call_engine.py": '"""Stand-in: call_engine.INDICES."""\nINDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]\n',
    "app/services/intraday_v2_engine.py": (
        '"""Stand-in: the backtest takes only these two names from the live engine."""\n'
        "import os\n"
        "from app.services.intraday_fills import slippage_bp  # noqa: F401\n"
        'MAX_STRATEGIES_PER_SYMBOL = int(os.getenv("INTRADAY_LAB_MAX_STRATEGIES_PER_SYMBOL", "2"))\n'),
    "app/services/intraday_universe.py": (
        '"""Stand-in: today\'s stored universe from the export (members: symbol, cas, turnover_cr)."""\n'
        "import json, os\n"
        '_DOC = json.load(open(os.path.join(os.environ["IVBT_DATA"], "export1.json"), encoding="utf-8"))\n\n\n'
        "async def members():\n"
        '    return list(_DOC["members"])\n'),
    "app/core/db.py": '''"""Stand-in for app.core.db: serves read-only exports; any other access raises."""
import json
import os
from datetime import datetime, timezone

DATA = os.environ["IVBT_DATA"]


class _Cursor:
    def __init__(self, docs):
        self._it = iter(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Bars:
    """1d bars from bars1d.tsv (symbol, epoch, close, volume) — the backtest's PIT universe query."""
    def __init__(self):
        self.rows = []
        with open(os.path.join(DATA, "bars1d.tsv"), encoding="utf-8") as f:
            for line in f:
                s, t, c, v = line.rstrip("\\n").split("\\t")
                self.rows.append((s, int(t), float(c), float(v)))
        self.lo = min(r[1] for r in self.rows)
        self.hi = max(r[1] for r in self.rows)

    def find(self, q, proj=None):
        assert set(q) == {"timeframe", "ts"} and q["timeframe"] == "1d", q
        a, b = q["ts"]["$gte"].timestamp(), q["ts"]["$lt"].timestamp()
        assert a >= self.lo - 86400 * 7 and b <= self.hi + 86400 * 7, ("outside the export", a, b, self.lo, self.hi)
        return _Cursor([{"symbol": s, "ts": datetime.fromtimestamp(t, timezone.utc), "close": c, "volume": v}
                        for s, t, c, v in self.rows if a <= t < b])


class _Instruments:
    def __init__(self):
        self.docs = json.load(open(os.path.join(DATA, "export1.json"), encoding="utf-8"))["instruments"]

    def find(self, q, proj=None):
        want = set(q["symbol"]["$in"])
        return _Cursor([dict(d) for d in self.docs if d["symbol"] in want])


class _NoDB:
    def __getitem__(self, name):
        raise RuntimeError(f"no database in the research harness (asked for {name!r})")


bars_collection = _Bars()
instruments_collection = _Instruments()
db = _NoDB()
''',
}


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True).stdout


def build(commit: str = "HEAD") -> pathlib.Path:
    """Write the package for `commit` (resolved to its sha) under DATA/pkg/<sha>; reuse if present."""
    sha = _git("rev-parse", "--short=12", commit).decode().strip()
    root = DATA / "pkg" / sha
    if (root / ".complete").exists():
        return root
    for repo_path, pkg_path in REAL:
        out = root / pkg_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_git("show", f"{sha}:{repo_path}").replace(b"\r\n", b"\n"))
    for pkg_path, text in STUBS.items():
        out = root / pkg_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    (root / ".complete").write_text(sha)
    return root


def activate(pkg: pathlib.Path, data: pathlib.Path | None = None) -> None:
    """Put the package first on sys.path (dropping any cached app / tradingai_shared modules —
    the local venv ships a stale tradingai_shared) and point the store at DATA/intraday."""
    data = data or DATA
    sys.path.insert(0, str(pkg))
    for name in [m for m in list(sys.modules)
                 if m in ("app", "tradingai_shared") or m.startswith(("app.", "tradingai_shared."))]:
        del sys.modules[name]
    os.environ["INTRADAY_DATA_DIR"] = str(data / "intraday")
    os.environ["IVBT_DATA"] = str(data / "exports")
    os.environ["V2BT_TMP"] = str(data / "tmp")
    (data / "tmp").mkdir(parents=True, exist_ok=True)
    for k in ("INTRADAY_V2_SLOT_NOTIONAL", "INTRADAY_V2_NIFTY_ALIGN"):   # the box sets neither
        os.environ.pop(k, None)
