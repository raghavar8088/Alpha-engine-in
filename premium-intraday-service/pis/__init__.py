"""Premium Intraday Strategies (pis): the decision logic of the Premium Strategies -> Premium Intraday Strategies desk.

The same code runs the historical replay (pis.replay) and the forward paper desk (pis.live): every screen, plan,
trigger, fill, risk check and exit is decided by pis.engine.DayEngine from timestamped five-minute bars, so a
replayed day and a live day are decided the same way. Nothing in this package can place a broker order: it has no
broker client, and the live worker is given no broker credentials.
"""

VERSION = "pis-1.0.0"
