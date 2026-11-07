"""The NSE daily seed panel for the desk: the last 560 calendar days of the study's bhavcopy panel (data/nse_daily.npz, in
the research folder and not in git). Copied to the box's premium volume once; the desk extends it from NSE every evening.
    python -I make_seed.py <output.npz>"""

import sys
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[1] / "backend" / "research" / "youtube_top20_2026_11" / "data" / "nse_daily.npz"
KEEP_DAYS = 560


def write_seed(out: Path) -> dict:
    with np.load(SRC, allow_pickle=False) as zf:
        z = {k: zf[k] for k in zf.files}
    keep = z["date"] >= z["date"].max() - np.timedelta64(KEEP_DAYS, "D")
    used, code = np.unique(z["code"][keep], return_inverse=True)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, code=code.astype(np.int32), names=z["names"][used], date=z["date"][keep],
                        **{k: z[k][keep].astype(np.float64) for k in ("o", "h", "l", "c", "value")})
    return {"rows": int(keep.sum()), "symbols": int(len(used)), "first": str(z["date"][keep].min()), "last": str(z["date"].max()),
            "mb": round(out.stat().st_size / 1e6, 1)}


if __name__ == "__main__":
    print(write_seed(Path(sys.argv[1])))
