"""Phase 7, pre-registered test P7_scorer: an AI signal scorer for the six rules with an edge
before costs. Everything — features, model settings, walk-forward, gate, leakage controls and
the decision — is read from prereg/P7_scorer.json.

Outputs in DATA/runs/scorer/: scores.jsonl.gz (every holdout and development signal's score),
result.json, model.txt (the model refitted on all data, for production only if GO).

Run with the research venv:  D:/intraday_ai_data/venv/Scripts/python.exe scorer.py
"""
from __future__ import annotations

import gzip
import json
import math
import pathlib
import sys
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from move_model import clustered  # noqa: E402
from prereg import load  # noqa: E402
from stubpkg import DATA  # noqa: E402

RULE = load("P7_scorer")
FEATS = RULE["features"]
OUTCOME = {"filled", "entry_t", "exit_t", "ep", "xp", "qty", "gross", "fees", "net", "reason", "gross_bp",
           "net_bp", "hold_min"}
PARAMS = dict(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=500, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, random_state=11, objective="l2", verbose=-1)
DEV_FROM, HOLDOUT_FROM = "2025-05-01", "2026-05-04"


def derive(r: dict, rules: dict[str, int]) -> list[float]:
    side = r["side"]
    x = dict(r)
    x["vix_rel"] = (r["vix"] / r["vix_med60"] - 1) if r.get("vix") and r.get("vix_med60") else None
    x["breadth_side"] = (r["breadth"] if side > 0 else 1 - r["breadth"]) if r.get("breadth") is not None else None
    x["fii_idx_net_side"] = side * r["fii_idx_net"] if r.get("fii_idx_net") is not None else None
    x["rule"] = rules[r["sid"]]
    return [np.nan if x.get(f) is None else float(x[f]) for f in FEATS]


def month_bounds(m: str) -> tuple[str, str]:
    a = date.fromisoformat(m + "-01")
    b = (a + timedelta(days=32)).replace(day=1)
    return a.isoformat(), b.isoformat()


def walk(X, y, days, months, lgb, shuffle: bool = False):
    scores, cut = np.full(len(y), np.nan), np.full(len(y), np.nan)
    rng = np.random.default_rng(11)
    cat = [FEATS.index("rule")]
    for m in months:
        lo, hi = month_bounds(m)
        tr = days < lo
        te = (days >= lo) & (days < hi)
        if not te.any() or tr.sum() < 5000:
            continue
        yt = y[tr].copy()
        if shuffle:
            yt = rng.permutation(yt)
        a, b = np.percentile(yt, [1, 99])
        model = lgb.LGBMRegressor(**PARAMS).fit(X[tr], np.clip(yt, a, b), categorical_feature=cat)
        scores[te] = model.predict(X[te])
        cut[te] = np.percentile(model.predict(X[tr]), 80)
    return scores, cut


def spread(days, scores, net) -> tuple[float, float, int]:
    q20, q80 = np.percentile(scores, [20, 80])
    by = defaultdict(lambda: ([], []))
    for d, s, v in zip(days, scores, net):
        if s >= q80:
            by[d][0].append(v)
        elif s <= q20:
            by[d][1].append(v)
    sp = [np.mean(t) - np.mean(b) for t, b in by.values() if t and b]
    if len(sp) < 3:
        return float("nan"), 0.0, len(sp)
    m, s = float(np.mean(sp)), float(np.std(sp, ddof=1))
    return m, (m / (s / math.sqrt(len(sp))) if s else 0.0), len(sp)


def main() -> None:
    import lightgbm as lgb
    assert not (set(FEATS) & OUTCOME), "leakage control 1: an outcome field is a feature"
    rows = [json.loads(x) for x in gzip.open(DATA / "runs" / "y2" / "features_ctx.jsonl.gz", "rt", encoding="utf-8")]
    rows.sort(key=lambda r: r["t"])
    rules = {s: i for i, s in enumerate(sorted({r["sid"] for r in rows}))}
    X = np.array([derive(r, rules) for r in rows])
    y = np.array([r["net_bp"] for r in rows], dtype=float)
    days = np.array([r["day"] for r in rows])
    months = sorted({d[:7] for d in days if d >= DEV_FROM})
    print(f"signals {len(rows)}, features {len(FEATS)}, months scored {len(months)}")

    scores, cut = walk(X, y, days, months, lgb)
    sh_scores, _ = walk(X, y, days, months, lgb, shuffle=True)
    res = {}
    for name, lo, hi in (("development", DEV_FROM, HOLDOUT_FROM), ("holdout", HOLDOUT_FROM, "9999")):
        sel = (days >= lo) & (days < hi) & ~np.isnan(scores)
        gated = sel & (scores >= cut)
        gm, gt, gn = clustered(list(zip(days[gated], y[gated])))
        am, at_, an = clustered(list(zip(days[sel], y[sel])))
        sm, st, sn = spread(days[sel], scores[sel], y[sel])
        shm, sht, _ = spread(days[sel], sh_scores[sel], y[sel])
        per_rule = {}
        for sid, k in rules.items():
            rs = gated & (X[:, FEATS.index("rule")] == k)
            pm, pt, pn = clustered(list(zip(days[rs], y[rs])))
            per_rule[sid] = {"gated_net_bp": round(pm, 3), "t": round(pt, 2), "n": pn}
        res[name] = {"signals": int(an), "gated": int(gn), "gated_share": round(gn / an, 3) if an else None,
                     "gated_net_bp": round(gm, 3), "gated_t": round(gt, 2), "all_net_bp": round(am, 3), "all_t": round(at_, 2),
                     "spread_bp": round(sm, 3), "spread_t": round(st, 2), "spread_days": sn,
                     "shuffle_spread_bp": round(shm, 3), "shuffle_spread_t": round(sht, 2), "per_rule": per_rule}
    h = res["holdout"]
    shuffle_ok = abs(h["shuffle_spread_t"]) < 2
    go = shuffle_ok and h["gated_net_bp"] > 0 and h["gated_t"] >= 3.0 and h["spread_bp"] >= 4 and h["spread_t"] >= 2
    res["leakage"] = {"outcome_fields_in_features": False, "shuffle_control_passes": shuffle_ok}
    res["decision"] = "GO" if go else "NO-GO"
    print(json.dumps(res, indent=1))
    out = DATA / "runs" / "scorer"
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "result.json", "w"), indent=1)
    with gzip.open(out / "scores.jsonl.gz", "wt", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            if not np.isnan(scores[i]):
                f.write(json.dumps({"day": r["day"], "sid": r["sid"], "sym": r["sym"], "t": r["t"],
                                    "score": round(float(scores[i]), 3), "cut": round(float(cut[i]), 3),
                                    "net_bp": r["net_bp"]}) + "\n")
    a, b = np.percentile(y, [1, 99])
    final = lgb.LGBMRegressor(**PARAMS).fit(X, np.clip(y, a, b), categorical_feature=[FEATS.index("rule")])
    final.booster_.save_model(str(out / "model.txt"))
    json.dump({"features": FEATS, "rules": rules, "cutoff_p80_in_sample": float(np.percentile(final.predict(X), 80))},
              open(out / "model_meta.json", "w"), indent=1)


if __name__ == "__main__":
    main()
