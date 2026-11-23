"""Write premium-intraday-service/pis/data/live_config.json from the frozen research results.

  strategies   each new strategy at its PRIMARY level with the frozen target per side (one instance per distinct
               target, carrying only its sides)
  eligible     strategies with status Portfolio Eligible (none on 22 Nov 2026: the portfolio places no trade)
  imported     the Top 25 followed forward in observation books: Stock Momentum rules (run from morning.py) and
               tournament rules (re-filled from its decision ledger)
"""
import hashlib
import json

from common import HERE, SERVICE

pre = json.loads((HERE / "prereg.json").read_text())
new = json.loads((HERE / "results" / "new_strategies.json").read_text())
top = json.loads((HERE / "results" / "imported_top25.json").read_text())

strategies = []
for sid, s in new["strategies"].items():
    lv = s["primary_level"]
    by_target = {}
    for side, sgn in (("LONG", 1), ("SHORT", -1)):
        tr = pre["frozen_final_targets"].get(f"{sid}|{lv}|{sgn}", 2.0)
        by_target.setdefault(tr, []).append(sgn)
    for tr, sides in sorted(by_target.items()):
        strategies.append({"sid": sid, "name": s["name"], "level": lv, "target_R": tr, "sides": sides,
                           "status": {("LONG" if x > 0 else "SHORT"): s["LONG" if x > 0 else "SHORT"]["status"] for x in sides},
                           "reason": {("LONG" if x > 0 else "SHORT"): s["LONG" if x > 0 else "SHORT"]["reason"] for x in sides}})
eligible = {}
for x in strategies:
    for side, st in x["status"].items():
        if st == "Portfolio Eligible":
            eligible[f"{x['sid']}|R{x['target_R']:g}|{x['level']}"] = {"mean_R": None, "conditions": {}}
imp = [r["id"] for r in top["top25"]]
cfg = {"prereg_sha256": hashlib.sha256((HERE / "prereg.json").read_bytes()).hexdigest(),
       "generated": "2026-11-22", "strategies": strategies, "eligible": eligible,
       "imported": {"morning_rules": [i[3:] for i in imp if i.startswith("SM:")],
                    "tournament": [i for i in imp if not i.startswith("SM:")],
                    "status": {r["id"]: {"status": r["status"], "reason": r["reason"]} for r in top["top25"]}}}
out = SERVICE / "pis" / "data" / "live_config.json"
out.write_text(json.dumps(cfg, indent=1))
print(out, len(strategies), "instances;", "eligible", len(eligible), "; imported", len(imp))
