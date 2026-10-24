# Amendment A8.1: a clarification registered before any A8 backtest (2026-10-24)

**The problem.** A8's strategy 16 (ORB-US-1h) names "the 18:30 hourly bar". The stored hourly
bars start on the hour (09:00, 10:00, …, 23:00), so no 18:30 bar exists.

**The fix.** ORB-US-1h uses the **18:00 hourly bar** (18:00–19:00), which contains the 18:30
NYMEX open:
- the range is that bar's high and low;
- the first breakout is taken **from the 19:00 bar on**;
- the stop is at the other side;
- the exit is at the close.

**Two readings that A8's wording left open, fixed now:**
- **EMA-X-1h and BB-BREAK:** EMA-X-1h computes its EMAs on the chosen contract's continuous hourly
  closes. BB-BREAK computes its bands within the day (from the 20th fifteen-minute bar on). In
  both, positions remain intraday only.
- **"Both halves" in the verdict** split each strategy's window at its middle session.

Nothing else changes.
