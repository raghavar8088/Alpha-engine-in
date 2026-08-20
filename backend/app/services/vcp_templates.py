"""VCP / Minervini templates for the Intraday Stocks pattern desk.

Adapts vcp_core to that desk's contract: fn(Series, profile) -> +1 long / -1 short / 0.

ALL EIGHT ARE LONG-ONLY, and that is deliberate rather than an omission. A VCP is a story
about supply drying up under accumulation before a breakout; there is no symmetric short
version of "volume dried up while weak holders finished selling". Returning -1 on a mirror
of the geometry would be inventing a pattern Minervini never described and attaching his
name to it.
"""

from app.services import vcp_core as V
from app.services.nifty_scalp_strategies import Series, sma


def _cols(s: Series):
    return s.h, s.l, s.c, s.v


def t_vcp_breakout(s: Series, p: dict) -> int:
    """The canonical trade: a tightening base, then a close through the pivot."""
    h, l, c, v = _cols(s)
    r = V.vcp(h, l, c, v, pivot_k=p.get("pivot", 3), min_contractions=2)
    return 1 if r["ok"] and r["pivot"] and V.broke_out(c, r["pivot"]) else 0


def t_vcp_3_contractions(s: Series, p: dict) -> int:
    """The textbook 3T: three shrinking pullbacks, which is what the screener labels
    '3 shrinking'. Stricter than the 2-contraction version and fires far less often."""
    h, l, c, v = _cols(s)
    r = V.vcp(h, l, c, v, pivot_k=p.get("pivot", 3), min_contractions=3,
              max_last_pullback=0.10)
    return 1 if r["ok"] and r["pivot"] and V.broke_out(c, r["pivot"]) else 0


def t_vcp_tight(s: Series, p: dict) -> int:
    """A very tight final contraction (under 6%) — the highest-quality setups, rarest."""
    h, l, c, v = _cols(s)
    r = V.vcp(h, l, c, v, pivot_k=p.get("pivot", 3), min_contractions=2,
              max_last_pullback=0.06, dryup_frac=0.65)
    return 1 if r["ok"] and r["pivot"] and V.broke_out(c, r["pivot"]) else 0


def t_vcp_volume_dryup(s: Series, p: dict) -> int:
    """Leads on the volume leg: an extreme dry-up (under half the base average) with a
    tightening base, then the break."""
    h, l, c, v = _cols(s)
    r = V.vcp(h, l, c, v, pivot_k=p.get("pivot", 3), min_contractions=2,
              dryup_frac=0.50, dryup_bars=7)
    return 1 if r["ok"] and r["pivot"] and V.broke_out(c, r["pivot"]) else 0


def t_vcp_pivot_reclaim(s: Series, p: dict) -> int:
    """The second chance: a qualified base whose breakout failed back under the pivot, then
    reclaimed it. Minervini's own 'undercut and rally' idea, applied to the pivot."""
    h, l, c, v = _cols(s)
    r = V.vcp(h, l, c, v, pivot_k=p.get("pivot", 3), min_contractions=2)
    if not (r["ok"] and r["pivot"]) or len(c) < 6:
        return 0
    piv = r["pivot"]
    was_above = any(x > piv for x in c[-6:-2])
    return 1 if was_above and V.broke_out(c, piv) else 0


def t_minervini_trend(s: Series, p: dict) -> int:
    """The trend template on its own: the 50/150/200 stack, a rising 200, and position
    within the 52-week range. Fires on the bar the last failing check turns true."""
    c = s.c
    now = V.trend_template(c, sma_fn=sma)
    if not now["ok"] or len(c) < 211:
        return 0
    prev = V.trend_template(c[:-1], sma_fn=sma)
    return 1 if not prev["ok"] else 0


def t_trend_plus_vcp(s: Series, p: dict) -> int:
    """Both legs: a stock that already passes the trend template AND breaks out of a
    tightening base. The combination is the actual Minervini entry."""
    h, l, c, v = _cols(s)
    if not V.trend_template(c, sma_fn=sma)["ok"]:
        return 0
    r = V.vcp(h, l, c, v, pivot_k=p.get("pivot", 3), min_contractions=2)
    return 1 if r["ok"] and r["pivot"] and V.broke_out(c, r["pivot"]) else 0


def t_pocket_pivot(s: Series, p: dict) -> int:
    """Accumulation showing up inside the base, before the breakout is obvious."""
    return 1 if V.pocket_pivot(s.c, s.v) else 0


def t_high_tight_flag(s: Series, p: dict) -> int:
    """Power play: a near-doubling, then a shallow tight flag, then the break of it."""
    h, l, c, v = _cols(s)
    if not V.high_tight_flag(c):
        return 0
    flag_hi = max(h[-12:-1]) if len(h) > 12 else None
    return 1 if flag_hi and V.broke_out(c, flag_hi) else 0


# (display name, family, fn) — matching the pattern desk's template shape.
VCP_TEMPLATES = [
    ("VCP Breakout", "vcp", t_vcp_breakout),
    ("VCP 3-Contraction", "vcp", t_vcp_3_contractions),
    ("VCP Tight Base", "vcp", t_vcp_tight),
    ("VCP Volume Dry-Up", "vcp", t_vcp_volume_dryup),
    ("VCP Pivot Reclaim", "vcp", t_vcp_pivot_reclaim),
    ("Minervini Trend Template", "vcp", t_minervini_trend),
    ("Trend Template + VCP", "vcp", t_trend_plus_vcp),
    ("Pocket Pivot", "vcp", t_pocket_pivot),
    ("High Tight Flag", "vcp", t_high_tight_flag),
]
