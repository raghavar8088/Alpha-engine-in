"""A failed write's leftover "*.tmp.npz" must never break the reads of a minute-bar store.

Run:  python premium-paper-service/test_tmp_files.py

On 22 Nov 2026 at 21:03 UTC the box's disk filled while feeds.py was saving the November files of DELTA_BTCUSD,
DELTA_ETHUSD and DELTA_XAUTUSD. Each save writes "<month>.tmp.npz" and then renames it over "<month>.npz"; the
saves failed between the two, leaving three EMPTY temp files beside intact month files. The readers listed
"*.npz", which matches "2026-11.tmp.npz" too, so every read of those stores raised "EOFError: No data left in
file" and the paper desk made no bitcoin, ether or gold trade for 18 hours. The checks below build such a store in
a temporary folder (no network, no database, no real data) and read it the three ways feeds.py does.
"""
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import resource  # noqa: F401
except ImportError:             # Windows
    sys.modules["resource"] = types.ModuleType("resource")

import feeds  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool, detail="") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILS.append(label)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        feeds.DATA = Path(tmp)
        folder = feeds.DATA / "min1" / "DELTA_TEST"
        folder.mkdir(parents=True)
        t0 = 1793491200                                   # 1 Nov 2026 00:00 UTC
        t = np.arange(t0, t0 + 600 * 60, 60, dtype=np.int64)
        px = 100.0 + np.arange(len(t), dtype=float) * 0.01
        np.savez_compressed(folder / "2026-11.npz", t=t, o=px, h=px + 0.5, l=px - 0.5, c=px, v=np.ones(len(t)))
        (folder / "2026-11.tmp.npz").write_bytes(b"")    # what the full disk left behind
        (folder / "2026-10.tmp.npz").write_bytes(b"PK\x03\x04 truncated")   # and a half-written one

        files = feeds._month_files(folder)
        check("the store lists only real month files", [f.name for f in files] == ["2026-11.npz"], [f.name for f in files])
        try:
            tt, cc = feeds._read_cols("DELTA_TEST", "2026-10", ("t", "c"))
            check("_read_cols reads the month despite the leftovers", len(tt) == 600 and float(cc[-1]) == float(px[-1]), len(tt))
        except Exception as exc:  # noqa: BLE001
            check("_read_cols reads the month despite the leftovers", False, repr(exc))
        try:
            parts = feeds._read_months("DELTA_TEST", "2026-10")
            check("_read_months reads it too (all six columns)", len(parts) == 6 and len(parts[0]) == 600, len(parts[0]))
        except Exception as exc:  # noqa: BLE001
            check("_read_months reads it too (all six columns)", False, repr(exc))
        check("the leftovers are left alone (the next save overwrites its own temp file)",
              (folder / "2026-11.tmp.npz").exists() and (folder / "2026-10.tmp.npz").exists())
        check("an empty or missing store is still just empty", feeds._month_files(feeds.DATA / "min1" / "NOPE") == [])
    print("\n" + (f"{len(FAILS)} FAILED" if FAILS else "all checks passed"))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
