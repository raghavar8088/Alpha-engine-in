"""Pre-entry checks for the All Time High desk.

WHY THESE CHECKS AND NOT OTHERS. The desk exits at +20% or −20% and nothing else. That
symmetry is unusual and it decides everything here. On a ₹1,00,000 position the real Angel
delivery schedule costs ₹314 to reach the target and ₹273 to reach the stop, so break-even
is a 50.7% hit rate. Most breakout advice optimises for a different payoff — a tight stop
and a long tail, where being right 35% of the time is fine. That advice does not transfer.
Every check below therefore has to earn its place by raising the HIT RATE, not by finding
better-looking breakouts.

THE STOP IS AN ASSUMPTION, NOT A GUARANTEE. The single largest risk the desk ran unchecked
was the price band. A stock in a 2% circuit band cannot fall 20% in fewer than ten
sessions, and on each of them it is locked limit-down with no bid — WELINV, in the desk's
own book, is exactly this. The stop was never going to fire at −20%; it was going to fire
at whatever price existed after a week of no exit. That is not a stop.

OBSERVE BEFORE ENFORCE. The gate defaults to `observe`: it scores every signal, stamps the
verdict on the position, and lets the trade through. This is deliberate. A gate in enforce
mode destroys the evidence that would show whether it helps — the blocked trades have no
outcome, so "the filter works" can never be more than an assertion. Run it in observe until
there are enough closed trades to compare passers against failers, THEN switch. Flip with
`ATH_GATE_MODE=enforce` or `POST /api/ath/gate/mode`.

UNKNOWN IS NOT A PASS. Every check returns one of pass / warn / fail / unknown, and the
four stay distinct all the way to the UI. NSE is the flakiest feed here; an outage must
read as "we could not check", never as a clean bill of health.
"""

from __future__ import annotations

import logging
import os
import statistics
from dataclasses import dataclass, field

from app.services import nse_surveillance as SURV

logger = logging.getLogger("ath.gate")

MODE_DEFAULT = os.getenv("ATH_GATE_MODE", "observe").lower()
MODES = ("observe", "enforce", "off")

# ── thresholds ──────────────────────────────────────────────────────────────────
# A position should not be a meaningful share of a day's turnover. At 1% you are a
# rounding error on the tape; above ~3% your own exit moves the price against you, which
# is precisely when you least want it to — a −20% stop is a forced sale.
POSITION_PCT_OF_TURNOVER_WARN = 1.0
POSITION_PCT_OF_TURNOVER_FAIL = 3.0

# The stop is 20% away. A band narrower than this cannot deliver the stop in one session;
# the stock locks and there is no bid. 10% needs two clean sessions, which is survivable.
# Below that the exit stops being a price and becomes a queue.
BAND_FAIL_BELOW = 6.0    # 2% and 5% bands
BAND_WARN_BELOW = 15.0   # 10% bands

# Delivery against the stock's OWN habit, never absolute — see the bhavcopy docstring.
# Below 0.7x its own average on a breakout day, the volume is churn rather than ownership.
DELIVERY_FAIL_BELOW = 0.5
DELIVERY_WARN_BELOW = 0.8

# How far past the all-time high we are buying. A stock already well through the level is
# not a breakout, it is a chase — and it puts the stop far below the price that mattered.
EXTENSION_WARN_PCT = 4.0
EXTENSION_FAIL_PCT = 10.0

REGIME_MA = 200

# ── buy conviction ──────────────────────────────────────────────────────────────
# What the checks are worth when the question is "should real money go into this?".
# Not equal, and deliberately not a flat average: the band decides whether the stop is
# executable at all, while the regime is identical for every position on any given day and
# so tells you nothing about which of them is better.
WEIGHTS = {
    "band": 25,
    "surveillance": 20,
    "liquidity": 20,
    "delivery": 15,
    "extension": 12,
    "regime": 8,
}

# Failing any of these is not a demerit to be averaged away — it is a reason the rule
# cannot be executed on this stock. Five passes must not drown out one of these.
STRUCTURAL = ("band", "surveillance", "liquidity")
STRUCTURAL_CAP = 30
STRUCTURAL_CAP_MULTI = 15

# An unknown is not half a pass. It scores at 0.6 AND lowers the stated confidence, so a
# row built mostly on missing data cannot present itself as a strong buy.
POINTS = {"pass": 1.0, "warn": 0.45, "unknown": 0.6, "fail": 0.0}

BANDS = [
    (80, "Strong", "Everything that decides execution is clean."),
    (65, "Good", "Tradable, with something to keep an eye on."),
    (50, "Fair", "Workable but compromised — size down or skip."),
    (30, "Weak", "The rule does not sit well on this stock."),
    (0, "Avoid", "Something here breaks the +-20% rule outright."),
]


@dataclass
class Check:
    key: str
    label: str
    verdict: str           # pass | warn | fail | unknown
    detail: str
    value: float | None = None
    # How comfortably it passed, 0..1, where the check has a continuous measure behind it.
    # Without this a verdict is a cliff: delivery at 0.81x its own average and delivery at
    # 1.4x both "pass" and both earn full marks, so every clean position ties at exactly
    # 100 and the number ranks nothing. The verdict still decides pass/fail; quality
    # decides how much credit passing earns.
    quality: float | None = None


def _grade(value: float, best: float, worst: float) -> float:
    """Linear 0..1 between two anchors, clamped. Works in either direction."""
    if best == worst:
        return 1.0
    return max(0.0, min(1.0, (value - worst) / (best - worst)))


@dataclass
class Verdict:
    symbol: str
    checks: list[Check] = field(default_factory=list)
    mode: str = "observe"
    conviction: dict | None = None

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.verdict == "fail"]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.verdict == "warn"]

    @property
    def unknowns(self) -> list[Check]:
        return [c for c in self.checks if c.verdict == "unknown"]

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def score(self) -> int:
        """0-100. A blunt summary for sorting, never for deciding — the reasons decide."""
        if not self.checks:
            return 0
        w = {"pass": 1.0, "warn": 0.5, "unknown": 0.5, "fail": 0.0}
        return round(sum(w[c.verdict] for c in self.checks) / len(self.checks) * 100)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "passed": self.passed,
            "score": self.score,
            "mode": self.mode,
            "blocked": self.mode == "enforce" and not self.passed,
            "fail_count": len(self.failures),
            "warn_count": len(self.warnings),
            "unknown_count": len(self.unknowns),
            "summary": self.summary(),
            "conviction": self.conviction,
            "checks": [vars(c) for c in self.checks],
        }

    def summary(self) -> str:
        if self.failures:
            return "; ".join(c.detail for c in self.failures)
        if self.warnings:
            return "Passed, with caution: " + "; ".join(c.detail for c in self.warnings)
        if self.unknowns:
            return ("Passed on what could be checked; "
                    + ", ".join(c.label.lower() for c in self.unknowns) + " unknown")
        return "Every check passed."


# ── individual checks ───────────────────────────────────────────────────────────

def _check_band(s: dict) -> Check:
    if not s.get("known"):
        return Check("band", "Price band", "unknown",
                     "NSE's band list did not have this symbol, so the stop's reachability "
                     "could not be checked.")
    band = s.get("band_pct")
    if band is None:
        # "No Band" is an F&O security: no fixed circuit, only a dynamic operating range.
        # This is the BEST case for a wide stop, not the absence of information.
        return Check("band", "Price band", "pass",
                     "No fixed circuit band (an F&O security), so a 20% stop can fill.",
                     None, quality=1.0)
    if band < BAND_FAIL_BELOW:
        need = int(20 / band) + 1
        return Check("band", "Price band", "fail",
                     f"{band:g}% circuit band — a 20% fall takes at least {need} sessions, "
                     f"each one locked limit-down with no bid. The stop cannot fire at "
                     f"−20%; it fires at whatever price exists once the lock clears.",
                     band, quality=0.0)
    if band < BAND_WARN_BELOW:
        return Check("band", "Price band", "warn",
                     f"{band:g}% circuit band — the stop needs two clean sessions to fill, "
                     f"so expect to exit below −20%.", band,
                     quality=_grade(band, best=20, worst=6))
    return Check("band", "Price band", "pass",
                 f"{band:g}% band — the stop can fill inside one session.", band,
                 quality=_grade(band, best=20, worst=10))


def _check_surveillance(s: dict) -> Check:
    if not s.get("known"):
        return Check("surveillance", "Surveillance", "unknown",
                     "Could not reach NSE's ASM/GSM lists.")
    gsm, asm, t2t = s.get("gsm"), s.get("asm"), s.get("t2t")
    if gsm:
        stage = gsm.get("stage") if isinstance(gsm, dict) else gsm
        return Check("surveillance", "Surveillance", "fail",
                     f"Under GSM ({stage}). GSM stages impose trade-for-trade settlement "
                     f"and up to 100% margin; price discovery is not normal here.")
    if asm:
        return Check("surveillance", "Surveillance", "fail",
                     f"Under ASM ({asm.get('horizon', '')} {asm.get('stage', '')}). "
                     f"Margins go to 100% and the band usually tightens, which changes the "
                     f"stop out from under the position.")
    if t2t:
        return Check("surveillance", "Surveillance", "warn",
                     f"Trade-to-Trade series ({s.get('series')}). Delivery only, and the "
                     f"series itself is usually a surveillance step.", quality=0.4)
    return Check("surveillance", "Surveillance", "pass",
                 f"Not under ASM or GSM; series {s.get('series') or 'EQ'}.", quality=1.0)


def _check_liquidity(d: dict | None, per_position: float) -> Check:
    if not d or d.get("median_turnover") is None:
        return Check("liquidity", "Liquidity", "unknown",
                     "No stored bhavcopy turnover for this symbol.")
    turnover = d["median_turnover"]          # rupees, median over the stored window
    if turnover <= 0:
        return Check("liquidity", "Liquidity", "fail", "No traded value on record.", 0.0)
    pct = per_position / turnover * 100
    if pct >= POSITION_PCT_OF_TURNOVER_FAIL:
        return Check("liquidity", "Liquidity", "fail",
                     f"₹{per_position:,.0f} is {pct:.1f}% of a median day's turnover "
                     f"(₹{turnover/1e5:,.0f}L). Your own exit would move the price, and a "
                     f"stop is a forced sale.", pct)
    if pct >= POSITION_PCT_OF_TURNOVER_WARN:
        return Check("liquidity", "Liquidity", "warn",
                     f"₹{per_position:,.0f} is {pct:.1f}% of a median day's turnover "
                     f"(₹{turnover/1e5:,.0f}L) — thin enough to slip on the way out.",
                     pct, quality=_grade(pct, best=1.0, worst=3.0))
    return Check("liquidity", "Liquidity", "pass",
                 f"{pct:.2f}% of a median day's turnover (₹{turnover/1e5:,.0f}L).", pct,
                 quality=_grade(pct, best=0.05, worst=1.0))


def _check_delivery(d: dict | None) -> Check:
    if not d or d.get("delivery_ratio") is None:
        return Check("delivery", "Delivery", "unknown",
                     "No delivery history stored for this symbol yet.")
    ratio = d["delivery_ratio"]
    pct, avg = d.get("delivery_pct"), d.get("delivery_avg")
    where = f"{pct:.0f}% delivered vs its own {avg:.0f}% average"
    if ratio < DELIVERY_FAIL_BELOW:
        return Check("delivery", "Delivery", "fail",
                     f"{where} — {ratio:.2f}x. A breakout on this little delivery is "
                     f"intraday churn, not someone taking ownership.", ratio)
    if ratio < DELIVERY_WARN_BELOW:
        return Check("delivery", "Delivery", "warn",
                     f"{where} — {ratio:.2f}x, below its own habit on the day it broke out.",
                     ratio, quality=_grade(ratio, best=0.8, worst=0.5))
    return Check("delivery", "Delivery", "pass",
                 f"{where} — {ratio:.2f}x.", ratio,
                 quality=_grade(ratio, best=1.3, worst=0.8))


def _check_extension(ltp: float, ath: float) -> Check:
    if not ath or ath <= 0:
        return Check("extension", "Entry vs the high", "unknown", "No stored high.")
    ext = (ltp - ath) / ath * 100
    if ext >= EXTENSION_FAIL_PCT:
        return Check("extension", "Entry vs the high", "fail",
                     f"Already {ext:+.1f}% through the high. This is a chase, and it puts "
                     f"the stop {20 + ext:.0f}% below the level that actually mattered.",
                     ext)
    if ext >= EXTENSION_WARN_PCT:
        return Check("extension", "Entry vs the high", "warn",
                     f"{ext:+.1f}% past the high — later than the break.", ext,
                     quality=_grade(ext, best=4.0, worst=10.0))
    return Check("extension", "Entry vs the high", "pass",
                 f"{ext:+.1f}% from the high — at the break.", ext,
                 quality=_grade(ext, best=0.0, worst=4.0))


def _check_regime(regime: dict | None) -> Check:
    if not regime or regime.get("above") is None:
        return Check("regime", "Market regime", "unknown",
                     "Not enough Nifty history stored to judge the trend.")
    if regime["above"]:
        return Check("regime", "Market regime", "pass",
                     f"Nifty is {regime['distance_pct']:+.1f}% above its {REGIME_MA}-day "
                     f"average.", regime["distance_pct"],
                     quality=_grade(regime["distance_pct"], best=6.0, worst=0.0))
    return Check("regime", "Market regime", "fail",
                 f"Nifty is {regime['distance_pct']:+.1f}% below its {REGIME_MA}-day "
                 f"average. Breakouts fail wholesale in a downtrend, and this desk holds "
                 f"through it with no time exit.", regime["distance_pct"])


# ── context loading ─────────────────────────────────────────────────────────────

_stats_cache: tuple[float, dict] | None = None
STATS_TTL = 1800.0
# Ten sessions is plenty for a median turnover and halves what has to come off the wire.
TURNOVER_WINDOW = 10


async def liquidity_and_delivery(fresh: bool = False) -> dict[str, dict]:
    """Per-symbol median turnover and delivery-vs-own-average, from stored bhavcopy.

    ONE read, THREE economies. Each bhavcopy document holds ~2,860 embedded rows of nine
    fields; pulling twenty of them whole is ~60,000 dicts and reliably times out against
    the M0 cluster at 45s. So: project only the three subfields actually used, take ten
    sessions rather than twenty-one, and compute delivery here instead of also calling
    `bhavcopy.delivery_stats()` — which reads the very same documents a second time.
    """
    global _stats_cache
    import time as _time
    from app.core.db import screener_bhavcopy_collection

    if not fresh and _stats_cache and _time.monotonic() - _stats_cache[0] < STATS_TTL:
        return _stats_cache[1]

    docs = [d async for d in screener_bhavcopy_collection.find(
        {"ok": True},
        {"_id": 0, "date": 1, "rows.symbol": 1, "rows.turnover_lacs": 1,
         "rows.delivery_pct": 1},
    ).sort("date", -1).limit(TURNOVER_WINDOW + 1)]
    if not docs:
        return {}

    turnovers: dict[str, list[float]] = {}
    history: dict[str, list[float]] = {}
    for i, d in enumerate(docs):
        for r in d.get("rows") or []:
            sym = r.get("symbol")
            if not sym:
                continue
            t = r.get("turnover_lacs")
            if t:
                turnovers.setdefault(sym, []).append(float(t) * 1e5)
            # The most recent document is "today"; delivery is judged against the days
            # BEFORE it, never against an average that includes the day being judged.
            if i > 0 and r.get("delivery_pct") is not None:
                history.setdefault(sym, []).append(float(r["delivery_pct"]))

    latest = {r["symbol"]: r for r in (docs[0].get("rows") or []) if r.get("symbol")}
    out: dict[str, dict] = {}
    for sym in set(turnovers) | set(latest):
        vals = turnovers.get(sym) or []
        pct = (latest.get(sym) or {}).get("delivery_pct")
        prior = history.get(sym) or []
        avg = sum(prior) / len(prior) if prior else None
        out[sym] = {
            "median_turnover": statistics.median(vals) if vals else None,
            "turnover_sessions": len(vals),
            "delivery_pct": pct,
            "delivery_avg": round(avg, 2) if avg is not None else None,
            "delivery_ratio": (round(pct / avg, 2)
                               if pct is not None and avg and avg > 0 else None),
            "date": docs[0].get("date"),
        }
    docs.clear()
    _stats_cache = (_time.monotonic(), out)
    return out


async def market_regime() -> dict:
    """Is the index above its own 200-day average?

    Uses NIFTY 50 from stored daily bars — the same source the rest of the desk marks
    against, so the regime cannot disagree with the prices it is judging.
    """
    from app.core.db import bars_collection

    for sym in ("NIFTY 50", "NIFTY50", "NIFTY"):
        bars = [b async for b in bars_collection.find(
            {"symbol": sym}, {"_id": 0, "close": 1, "ts": 1}
        ).sort("ts", -1).limit(REGIME_MA)]
        if len(bars) >= REGIME_MA:
            closes = [float(b["close"]) for b in bars if b.get("close")]
            if len(closes) < REGIME_MA:
                continue
            ma = sum(closes) / len(closes)
            last = closes[0]
            return {"symbol": sym, "last": round(last, 2), "ma": round(ma, 2),
                    "above": last > ma, "distance_pct": round((last - ma) / ma * 100, 2),
                    "sessions": len(closes)}
    return {"symbol": None, "above": None, "distance_pct": None, "sessions": 0}


class GateContext:
    """Everything the gate needs, loaded once per cycle rather than per symbol."""

    def __init__(self, surv_reader, stats: dict, regime: dict, mode: str,
                 per_position: float):
        self.surv = surv_reader
        self.stats = stats
        self.regime = regime
        self.mode = mode
        self.per_position = per_position

    def evaluate(self, symbol: str, ltp: float, ath: float) -> Verdict:
        sym = (symbol or "").upper()
        d = self.stats.get(sym)
        v = Verdict(symbol=sym, mode=self.mode, checks=[
            _check_band(self.surv(sym)),
            _check_surveillance(self.surv(sym)),
            _check_liquidity(d, self.per_position),
            _check_delivery(d),
            _check_extension(ltp, ath),
            _check_regime(self.regime),
        ])
        v.conviction = conviction(v, d)
        return v


async def build_context(mode: str | None = None,
                        per_position: float = 100000.0) -> GateContext:
    """Load the gate's inputs. Any source that fails degrades to `unknown`, never to a pass."""
    try:
        surv = await SURV.snapshot_reader()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ath gate: surveillance unavailable (%s)", exc)
        surv = lambda sym: {"symbol": sym, "known": False}  # noqa: E731
    try:
        stats = await liquidity_and_delivery()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ath gate: bhavcopy stats unavailable (%s)", exc)
        stats = {}
    try:
        regime = await market_regime()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ath gate: regime unavailable (%s)", exc)
        regime = {"above": None}
    return GateContext(surv, stats, regime, (mode or MODE_DEFAULT), per_position)


def _volume_line(d: dict | None) -> str:
    """One sentence on whether the money behind the move is real."""
    if not d:
        return "No volume or delivery data stored for this stock."
    parts = []
    ratio, pct, avg = d.get("delivery_ratio"), d.get("delivery_pct"), d.get("delivery_avg")
    if ratio is not None:
        word = ("well above" if ratio >= 1.3 else "above" if ratio >= 1.05
                else "in line with" if ratio >= 0.85 else "below" if ratio >= 0.5
                else "far below")
        parts.append(f"{pct:.0f}% of volume was delivered, {word} its own "
                     f"{avg:.0f}% average ({ratio:.2f}x)")
    t = d.get("median_turnover")
    if t:
        amount = f"\u20b9{t/1e7:,.0f}cr" if t >= 1e7 else f"\u20b9{t/1e5:,.0f}L"
        parts.append(f"median turnover {amount} a day")
    if not parts:
        return "No delivery or turnover data stored yet."
    line = "; ".join(parts)
    # Upper-case the FIRST letter only. `.capitalize()` lower-cases everything after it,
    # which is why the turnover was rendering as "rs128 cr" instead of a rupee amount.
    return line[0].upper() + line[1:] + "."


def conviction(v: Verdict, d: dict | None = None) -> dict:
    """A single percentage for "should real money go into this stock on this rule?".

    WHAT IT IS NOT: a probability of profit. Nothing here forecasts the trade. It scores
    whether the +-20% rule can actually be executed on this stock and whether the move
    that triggered it was backed by real ownership. A 90% can still lose; it just loses
    for reasons the desk chose to take rather than ones it failed to look at.

    Weighted and CAPPED rather than averaged. A stock whose stop cannot fill is not
    redeemed by passing five other checks, so a structural failure caps the result instead
    of being diluted by it.
    """
    by = {c.key: c for c in v.checks}
    total = sum(WEIGHTS.get(k, 0) for k in by)
    if not total:
        return {"pct": 0, "label": "Unknown", "headline": "Nothing could be checked.",
                "volume": _volume_line(d), "confidence": "none", "capped": False}

    def _points(c: Check) -> float:
        # A passing check earns between a floor and full marks according to how
        # comfortably it passed; a warn earns a fraction of its warn ceiling the same way.
        # Without the graded term every clean position scored exactly 100 and the number
        # could not rank one holding against another, which is the whole point of it.
        if c.verdict == "pass":
            return 0.75 + 0.25 * (1.0 if c.quality is None else c.quality)
        if c.verdict == "warn":
            return POINTS["warn"] * (1.0 if c.quality is None else max(0.2, c.quality))
        return POINTS[c.verdict]

    earned = sum(WEIGHTS.get(k, 0) * _points(c) for k, c in by.items())
    pct = round(earned / total * 100)

    structural_fails = [k for k in STRUCTURAL
                        if k in by and by[k].verdict == "fail"]
    cap = None
    if len(structural_fails) >= 2:
        cap = STRUCTURAL_CAP_MULTI
    elif structural_fails:
        cap = STRUCTURAL_CAP
    capped = cap is not None and pct > cap
    if capped:
        pct = cap

    label, blurb = next((lb, b) for lo, lb, b in BANDS if pct >= lo)

    fails = [c for c in v.checks if c.verdict == "fail"]
    warns = [c for c in v.checks if c.verdict == "warn"]
    if fails:
        headline = fails[0].detail
    elif warns:
        headline = warns[0].detail
    else:
        headline = blurb

    unknowns = sum(1 for c in v.checks if c.verdict == "unknown")
    confidence = ("high" if unknowns == 0 else "medium" if unknowns <= 1 else "low")

    return {
        "pct": pct,
        "label": label,
        "headline": headline,
        "volume": _volume_line(d),
        "confidence": confidence,
        "unknown_checks": unknowns,
        "capped": capped,
        "cap_reason": (f"Capped at {cap}% — "
                       + ", ".join(by[k].label.lower() for k in structural_fails)
                       + " decides whether the rule can be executed at all, so passing "
                         "other checks cannot make up for it.") if capped else None,
    }


def thresholds() -> dict:
    return {
        "mode_default": MODE_DEFAULT,
        "modes": list(MODES),
        "position_pct_of_turnover": {"warn": POSITION_PCT_OF_TURNOVER_WARN,
                                     "fail": POSITION_PCT_OF_TURNOVER_FAIL},
        "band_pct": {"fail_below": BAND_FAIL_BELOW, "warn_below": BAND_WARN_BELOW},
        "delivery_ratio": {"fail_below": DELIVERY_FAIL_BELOW,
                           "warn_below": DELIVERY_WARN_BELOW},
        "extension_pct": {"warn": EXTENSION_WARN_PCT, "fail": EXTENSION_FAIL_PCT},
        "regime_ma": REGIME_MA,
        "note": ("observe = score and record but still trade; enforce = block failures; "
                 "off = do not evaluate. Start in observe — a gate in enforce mode "
                 "destroys the evidence needed to judge whether it helps."),
    }
