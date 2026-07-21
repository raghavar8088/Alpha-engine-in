"""Mirror the option-BUYING library into the SELLING desk.

THE IDEA
--------
Every buying strategy is a direction detector: `direction(ctx)` returns +1 (bullish,
would buy a call), -1 (bearish, would buy a put), 0 (flat), or None (hold). This module
wraps each one so the SAME directional read drives a CREDIT structure on the selling desk
instead of a debit on the buying desk:

    buying bullish  (long CE)  ->  SELL a bull put spread   (SELL PE / BUY further PE)
    buying bearish  (long PE)  ->  SELL a bear call spread  (SELL CE / BUY further CE)

So "when the buying signal fires, the selling desk opens a position" — achieved in one
process, with the selling daemon running these wrapped strategies itself. There is no
cross-desk coupling: the selling desk does not depend on the buying desk being up, it
just re-runs the same signal logic.

TWO DELIBERATE DESIGN CHOICES, EACH FROM A LESSON ALREADY PAID FOR
-----------------------------------------------------------------
1. DEFINED RISK ONLY. Every mirror is a two-leg credit SPREAD, never a naked short. The
   buying signals are noisy (the buying desk itself is down ~9% over two sessions), and
   expressing a noisy signal as a naked short is how a selling book gets a tail event.
   The long wing caps the loss on every trade, structurally.

2. HELD TO WEEKLY EXPIRY, NOT SQUARED OFF. The buying strategies are mostly intraday
   scalps. We already proved that selling on an intraday, square-off-at-EOD cadence
   destroys the edge — theta is a sliver over a few hours and round-trip charges eat it
   (sell_dead_tape_condor: PF 0.66 intraday vs 2.16 held to expiry). So every mirror is
   an `options_sell_swing` strategy: its intraday signal chooses the ENTRY, but the
   position is then held to the weekly expiry where theta actually accrues.

WHAT THIS DOES NOT DO
---------------------
It does not put 215 ungated strategies onto the live desk. These register like any other
selling strategy and go through the SAME sweep -> tail-aware gate -> out-of-sample split
-> overlap dedup funnel. Only the mirrors that actually work as sellers reach the live
basket. Mirroring is the mechanism; the gate is still the judge. Trading a buying signal
as a seller because it was a good BUYING signal is exactly the "flip the sign" fallacy
the whole desk was built to reject — so a mirror earns its place on selling evidence or
not at all.
"""

from strategy_service.strategies.options_buying._base import OptionBuyStrategy
from strategy_service.strategies.options_selling._base import (
    LegSpec,
    OptionSellStrategy,
    sell_meta,
)
from tradingai_shared.contracts import STRATEGY_REGISTRY, register_strategy
from tradingai_shared.domain import Timeframe

# Short strike delta and wing width for the mirrored spreads. 0.20-delta short leg is a
# conventional credit-spread strike (roughly one standard deviation out on a weekly),
# and the wing is 1.5% of spot — wide enough to collect real credit, tight enough to
# keep the defined max loss modest. Fixed values, not tuned to any result.
_SHORT_DELTA = 0.20
_WING_PCT = 0.015

# Mirrors read the buying strategy's native timeframe but hold to the weekly expiry, so
# they all live in the swing style. Intraday/scalp signals thus become weekly-held credit
# spreads triggered intraday.
_MIRROR_CATEGORY = "options_sell_swing"


def _make_mirror(buy_id: str, buy_cls: type[OptionBuyStrategy]) -> type[OptionSellStrategy]:
    """Build a registered selling strategy that mirrors one buying strategy's direction."""

    @register_strategy
    class _Mirror(OptionSellStrategy):
        metadata = sell_meta(
            f"mirror_{buy_id}",
            f"Mirror: {buy_cls.metadata.name}",
            _MIRROR_CATEGORY,
            f"Sells the credit spread implied by the '{buy_cls.metadata.name}' buying "
            f"signal — bullish reads sell a bull put spread, bearish reads sell a bear "
            f"call spread, held to the weekly expiry. Defined risk on both sides.",
            Timeframe.M15,
            buy_cls.metadata.suitable_market,
        )
        # The optimizer/params surface of the underlying buying strategy is not exposed;
        # mirrors run the buying strategy at its defaults.
        Params = OptionSellStrategy.Params

        def __init__(self, params: dict | None = None):
            super().__init__(params)
            self._buy = buy_cls()
            self._entry_dir = 0

        @property
        def warmup(self) -> int:
            # Enough for the buying strategy's own indicators plus the selling engine's
            # vol-rank window; take the larger.
            return max(self._buy.warmup, 90)

        def _direction(self, ctx) -> int:
            """The buying strategy's regime read, with its hold-hysteresis applied exactly
            as its own on_bar would (None = keep the previous direction)."""
            nd = self._buy.direction(ctx)
            if nd is None:
                nd = getattr(self._buy, "_dir", 0)
            self._buy._dir = nd
            return nd

        def want_open(self, ctx) -> bool:
            d = self._direction(ctx)
            if d in (1, -1):
                self._entry_dir = d
                side = "bull put (bullish)" if d > 0 else "bear call (bearish)"
                self.why = f"mirror {buy_id}: {side}"
                return True
            return False

        def legs(self, ctx) -> list[LegSpec]:
            if self._entry_dir > 0:  # bullish -> bull put spread
                return [
                    LegSpec("PE", sell=True, target_delta=_SHORT_DELTA),
                    LegSpec("PE", sell=False, wing_pct=_WING_PCT),
                ]
            # bearish -> bear call spread
            return [
                LegSpec("CE", sell=True, target_delta=_SHORT_DELTA),
                LegSpec("CE", sell=False, wing_pct=_WING_PCT),
            ]

        def force_close(self, ctx) -> bool:
            """Close early if the buying regime goes flat or flips against the spread —
            the directional thesis the spread was opened on no longer holds."""
            d = self._direction(ctx)
            if d == 0:
                return True
            return d != 0 and self._entry_dir != 0 and d != self._entry_dir

    _Mirror.__name__ = f"Mirror_{buy_id}"
    _Mirror.__qualname__ = _Mirror.__name__
    return _Mirror


def register_mirrors() -> int:
    """Wrap every registered OptionBuyStrategy as a mirror seller. Idempotent: skips any
    mirror id already registered (so re-import is safe)."""
    # Snapshot first — registering mirrors mutates the registry we are iterating.
    buying = [
        (sid, cls) for sid, cls in list(STRATEGY_REGISTRY.items())
        if isinstance(cls, type) and issubclass(cls, OptionBuyStrategy)
        and not sid.startswith("mirror_")
    ]
    made = 0
    for sid, cls in buying:
        if f"mirror_{sid}" in STRATEGY_REGISTRY:
            continue
        _make_mirror(sid, cls)
        made += 1
    return made
