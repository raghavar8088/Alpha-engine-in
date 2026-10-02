# Pre-Live (NIFTY option buying) audit and research — 2026-10-02

Scripts behind the audit and the U0-U6 upgrade. Run order and what each settled:

| Script | Settles |
|---|---|
| `prelive_audit.py`, `prelive_audit2.py` | (run in the backend image, read-only) the desk's real record: 6,038 trades, net -Rs27.2 lakh, direction hit 47%, 0/148 strategies t>2, six missing daily records, lot 75 vs 65; exports `nifty_bars.json` / `prelive_trades.json` |
| `pl_calib2.py` | each trade's TRUE expiry (the instrument master was stale: monthlies and a December contract were traded as "weekly"); BS-at-VIX underprices expiry-day options ~52% |
| `pl_calib3.py`, `pl_calib4.py` | the variance clock (trading minutes + 0.2 session a night) and IV/VIX ratios that re-price real exits within +-1.5% (1-80 days); out of sample the model is good to ~+-5-8% only -> `calib_clock.json`, `calib_surface.json` |
| `pl_replay.py`, `pl_analyse.py` | two-year replay of all 167 strategies with the live desk's rules (validated: trade counts per strategy correlate 0.95 with live); no direction edge (47.8-48.4%), best DSR 0.12 |
| `pl_vol.py`, `pl_checks.py` | realized/implied variance is predictable at 09:45 (corr 0.40 / 0.37 held out); NIFTY's own ORB has no edge; vol-gating does not rescue directional signals; the leaderboard's ANTI winners lose as real sellers |
| `pl_h1.py`, `pl_h1b.py`, `pl_freeze.py` | H1 (intraday straddle) is negative under the calibrated model; H1b (overnight) positive in both periods but model-extrapolated; both frozen -> `h1_frozen.json` |
| `pl_h3.py` | H3 (event days: RBI, US CPI, FOMC) rejected on history |

The data files are not committed (`nifty_bars.json` is exported by `prelive_audit2.py`). Paths in
`pl_replay.py` point at the local checkout; adjust `sys.path` to run elsewhere.
