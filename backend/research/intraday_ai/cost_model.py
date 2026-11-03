"""Phase 3, pre-registered test P3_cost_model: does a book-based model predict a Rs 10 lakh market
order's cost better than the turnover-band averages in production?  Judged by prereg.load().

    python cost_model.py        -> report + DATA/runs/cost_model/result.json (coefficients)
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from prereg import load  # noqa: E402
from stubpkg import DATA  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
RULE = load("P3_cost_model")
BANDS = (1000.0, 300.0, 150.0, 0.0)
FEATURES = ["const", "half_spread_bp", "depth_covered_pct", "insufficient_depth", "log10_turnover",
            "mins", "mins2", "buy"]


def _when(s) -> datetime:
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(IST)


def rows() -> list[dict]:
    d = json.load(open(DATA / "exports" / "h1_cal.json", encoding="utf-8"))
    out = []
    for s in d["samples"]:
        if s.get("phase") != "entry" or not s.get("measurable") or s.get("cost_bp_vs_ltp") is None:
            continue
        t = _when(s["signal_at"])
        turn = (d["universe"].get(t.date().isoformat()) or {}).get(s["symbol"])
        if not turn or s.get("half_spread_bp") is None or s.get("depth_covered_pct") is None:
            continue
        mins = t.hour * 60 + t.minute - (9 * 60 + 15)
        out.append({"day": t.date().isoformat(), "y": float(s["cost_bp_vs_ltp"]), "turnover": float(turn),
                    "x": [1.0, float(s["half_spread_bp"]), float(s["depth_covered_pct"]),
                          1.0 if s.get("insufficient_depth") else 0.0, math.log10(float(turn)),
                          mins / 60.0, (mins / 60.0) ** 2, 1.0 if s.get("side") == "BUY" else 0.0]})
    return out


def band(t: float) -> float:
    return next(b for b in BANDS if t >= b)


def tmean(xs: list[float], cut: float = 0.10) -> float:
    xs = sorted(xs)
    k = int(len(xs) * cut)
    xs = xs[k:len(xs) - k] if len(xs) > 2 * k else xs
    return sum(xs) / len(xs)


def main() -> None:
    data = rows()
    train = [r for r in data if r["day"] < "2026-10-27"]
    test = [r for r in data if "2026-10-27" <= r["day"] <= "2026-11-03"]
    y = np.array([r["y"] for r in train])
    lo, hi = np.percentile(y, [1, 99])
    yw = np.clip(y, lo, hi)
    X = np.array([r["x"] for r in train])
    beta, *_ = np.linalg.lstsq(X, yw, rcond=None)
    by_band = {b: tmean([r["y"] for r in train if band(r["turnover"]) == b]) for b in BANDS}
    Xt = np.array([r["x"] for r in test])
    yt = np.array([r["y"] for r in test])
    pred = Xt @ beta
    base = np.array([by_band[band(r["turnover"])] for r in test])
    mae_model, mae_base = float(np.mean(np.abs(pred - yt))), float(np.mean(np.abs(base - yt)))
    adopt = mae_model <= 0.90 * mae_base
    res = {"train_n": len(train), "test_n": len(test), "winsor": [float(lo), float(hi)],
           "coefficients": dict(zip(FEATURES, [round(float(b), 4) for b in beta])),
           "band_baseline_train": {str(int(k)): round(v, 3) for k, v in by_band.items()},
           "test_mae_model": round(mae_model, 3), "test_mae_baseline": round(mae_base, 3),
           "ratio": round(mae_model / mae_base, 3), "decision": "ADOPT" if adopt else "KEEP BAND MODEL",
           "rule": RULE["decision"]}
    out = DATA / "runs" / "cost_model"
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "result.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
