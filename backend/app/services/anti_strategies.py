"""ANTI variants of the option-BUYING library.

An ANTI strategy is the exact reverse of its base: wherever the base reads bullish and
would buy a CE, the ANTI buys the PE, and vice versa. Flat stays flat. Because every
strategy in `options_buying` expresses itself through a single `direction(ctx)` returning
+1/-1/0/None, the reverse is a one-line negation applied to that read — the ANTI inherits
the base's entire indicator/state machine, so the two can never drift apart.

Why have them at all: this is a SELECTION desk. A strategy that loses consistently is as
informative as one that wins, provided the reverse is actually tradable — and on the
equity desks the reverse of a losing intraday strategy has already been the better side
(the ₹80k Live Intraday shortlist is six ANTIs out of eight). Registering the mirror as a
first-class strategy means its forward record is measured on its own terms rather than
inferred by flipping the sign on the base's P&L, which is not the same thing once fees,
slippage and stop placement are involved.

Registration is idempotent and never overwrites: if an `anti_*` id already exists (the
selling library ships its own mirrors), the existing one wins.
"""

import logging

from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext, StrategyMetadata

logger = logging.getLogger("anti_strategies")

ANTI_PREFIX = "anti_"


def _make_anti(base_cls: type) -> type:
    """Subclass `base_cls`, negating its direction read and relabelling its metadata."""
    base_meta: StrategyMetadata = base_cls.metadata
    anti_id = f"{ANTI_PREFIX}{base_meta.strategy_id}"

    class _Anti(base_cls):  # type: ignore[misc, valid-type]
        metadata = StrategyMetadata(
            strategy_id=anti_id,
            name=f"ANTI {base_meta.name}",
            category=base_meta.category,
            description=(
                f"Reverse of '{base_meta.name}' — buys the PE where the base buys the CE "
                f"and vice versa. Base logic: {base_meta.description}"
            ),
            timeframes=list(base_meta.timeframes),
            asset_classes=list(base_meta.asset_classes),
            suitable_market=base_meta.suitable_market,
        )

        def direction(self, ctx: StrategyContext) -> int | None:
            d = super().direction(ctx)
            # None means "hold whatever you had" — reversing that would invent a signal the
            # base never gave, so hysteresis is passed through untouched. 0 (flat) has no
            # opposite side either.
            if d is None or d == 0:
                return d
            return -d

    _Anti.__name__ = f"Anti{base_cls.__name__}"
    _Anti.__qualname__ = _Anti.__name__
    return _Anti


def register_anti_buying() -> dict:
    """Create and register an ANTI for every registered option-buying strategy.

    Safe to call repeatedly: already-registered ids are left alone. Returns a summary so
    callers can log how big the tradable library actually became."""
    try:
        import strategy_service.strategies.options_buying  # noqa: F401 — registers the base library
    except Exception as exc:  # pragma: no cover
        logger.warning("anti: could not import options_buying (%s)", exc)
        return {"created": 0, "skipped": 0, "base": 0}

    bases = [
        (sid, cls) for sid, cls in list(STRATEGY_REGISTRY.items())
        if "options_buying" in (getattr(cls, "__module__", "") or "")
        and not sid.startswith(ANTI_PREFIX)
    ]
    created = skipped = 0
    for sid, cls in bases:
        anti_id = f"{ANTI_PREFIX}{sid}"
        if anti_id in STRATEGY_REGISTRY:
            skipped += 1
            continue
        try:
            STRATEGY_REGISTRY[anti_id] = _make_anti(cls)
            created += 1
        except Exception as exc:  # a malformed base must not take the whole library down
            logger.warning("anti: could not mirror %s (%s)", sid, exc)
            skipped += 1

    logger.info("ANTI buying strategies: %s created, %s skipped (from %s bases)",
                created, skipped, len(bases))
    return {"created": created, "skipped": skipped, "base": len(bases)}
