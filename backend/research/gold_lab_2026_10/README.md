# Gold Strategy Lab (2026-10)

The search for new gold strategies behind the Gold Desk's **Gold Lab** book. Findings are in
[`GOLD_STRATEGY_LAB_2026_10.md`](../../../GOLD_STRATEGY_LAB_2026_10.md). The live rules are in
`backend/app/services/gold_lab_rules.py`, held to these scripts by
`backend/tests/gold_desk/verify_gold_lab.py`.

| Script | What it does |
|---|---|
| `gl_fetch.py` | Yahoo daily history into `data/`: gold (GLD, IAU, GC=F), metals, and the drivers (dollar, TIPS, Treasuries, cash rate, GVZ, VIX, S&P 500, oil, INR, miners) |
| `gl_data.py` | Loaders. Drivers that print after gold's close are lagged a day. |
| `gl_engine.py` | Next-open execution, excess returns, costs, metrics, deflated Sharpe, PBO |
| `gl_families.py` | Every strategy family with its reason and its fixed grid per round (`ROUND1` … `ROUND5`) |
| `gl_round.py N` | Runs round N on selection and validation **only**, and appends every variant to `data/registry.csv` |
| `gl_final.py stage3` | Luck correction against all registered trials, robustness, Tier A / Tier B |
| `gl_final.py holdout` | Opens 2020–2026 **once** for the Tier A + B candidates (locked by `data/holdout_opened.json`) |

Periods, all fixed before round 1:
- selection 2004-11-18 → 2014-12-31;
- validation 2015 → 2019;
- holdout 2020-01 → 2026-10.

Result: 157 variants in 38 families. Tier A (proven better than holding gold): **0**. Tier B (profitable in every period, unproven): **7**, three independent ideas.
