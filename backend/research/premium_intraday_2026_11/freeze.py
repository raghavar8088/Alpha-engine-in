"""Freeze the pre-registration before the final period is opened.

Writes prereg.json: the protocol, the promotion criteria, the trial count, the frozen walk-forward target choices
(from the development analysis), the development-phase fixes, and a sha256 of every file that decides a trade.
Its own sha256 is printed; run_replay.py refuses to open the final period without it."""
import hashlib
import json
from pathlib import Path

from common import HERE, RUNS, SERVICE
import protocol as P
from pis.strategies import REGISTRY

CODE = sorted((SERVICE / "pis").glob("*.py")) + [SERVICE / "pis" / "data" / "sector_map.json"] + \
    [HERE / "protocol.py", HERE / "run_replay.py", HERE / "analyze.py"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main():
    an = json.loads((RUNS / "dev_x1" / "analysis.json").read_text())
    choices = an["final_choices"]
    doc = {
        "frozen_at": "2026-11-22",
        "module": "Premium Strategies -> Premium Intraday Strategies",
        "periods": {"development": [str(P.DEV_START), str(P.DEV_END)], "final": [str(P.FINAL_START), str(P.FINAL_END)],
                    "post_final": [str(P.POST_START), str(P.POST_END)]},
        "folds": [[str(x) for x in f] for f in P.FOLDS],
        "final_train": [str(x) for x in P.FINAL_TRAIN],
        "walk_forward_parameter": {"name": "target_R", "values": list(P.TARGETS),
                                   "rule": f"best mean net R on the training window with >= {P.MIN_TRAIN_TRADES} trades, else {P.DEFAULT_TARGET}"},
        "strategies": {sid: {"name": cls.name, "primary_level": cls.primary,
                             "allowed_conditions": {"LONG": list(cls.allowed[1]), "SHORT": list(cls.allowed[-1])}}
                       for sid, cls in REGISTRY.items()},
        "frozen_final_targets": choices,
        "trials": {"configurations_replayed": len(REGISTRY) * 2 * len(P.LEVELS) * len(P.TARGETS),
                   "candidate_configurations": len(REGISTRY) * 2 * len(P.TARGETS),
                   "imported_strategies": 62, "K_for_bonferroni": P.K_TRIALS},
        "criteria": P.CRITERIA,
        "costs": {"charges": "Angel One INTRADAY schedule (backend angel_fees.round_trip)",
                  "slippage_bp_per_side_by_turnover": "1.50 / 2.85 / 3.73 / 4.12 (>= Rs 1,000 cr / 300-1,000 / 150-300 / < 150)",
                  "stress": [2.0, 3.0]},
        "development_fixes": [
            {"what": "official previous close used only when on the bars' price basis (within 2% of the last bar)",
             "why": "the broker's bar history is back-adjusted for later splits/bonuses; the bhavcopy is not "
                    "(HDFCBANK June 2025: bars ~Rs 990, bhavcopy Rs 1,978.9): fake -50% gaps"},
            {"what": "a stock opening >15% from its previous close is set aside for the day (probable corporate action)",
             "why": "same price-basis problem on an ex-date in live trading"},
            {"what": "day-clustered t reported only with >= 10 trading days", "why": "two similar days gave t = -897"},
        ],
        "code_sha256": {str(p.relative_to(SERVICE.parent)).replace("\\", "/"): sha(p) for p in CODE},
    }
    out = HERE / "prereg.json"
    out.write_text(json.dumps(doc, indent=1, sort_keys=True))
    print("prereg.json sha256", hashlib.sha256(out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
