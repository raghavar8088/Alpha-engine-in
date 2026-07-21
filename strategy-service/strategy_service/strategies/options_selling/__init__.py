"""The option-SELLING library: importing registers all of it.

Three books, split by how the tail is controlled rather than by timeframe, because the
tail is the only thing that matters when you are short premium:

  neutral      — straddles, strangles, condors, butterflies (both sides sold)
  directional  — bull put and bear call credit spreads (defined risk by construction)
  naked        — single-side short calls and puts (tail controlled only by a stop)

Every strategy runs on the UNDERLYING's bars, exactly like the rest of this codebase.
What makes them option strategies is that `options_service.options_selling_backtest`
turns each signal into a real multi-leg credit structure, blocks margin for it, marks it
to market, and owns every exit.

Those three hand-written books are joined by `_matrix`, which generates the structure x
regime grid across the swing and positional styles. See that module's docstring for why
it is a factory rather than seventy hand-written classes, and for the statistical cost a
generated grid carries.

Finally, `_mirror` wraps every option-BUYING strategy as a selling strategy: when a
buying strategy's direction signal fires, the mirror sells the credit spread that
expresses the same view (bullish -> bull put spread, bearish -> bear call spread), held
to the weekly expiry. This is what lets a buying signal drive the selling desk. The
mirrors are registered here but, like everything else, only reach the live desk if they
pass the sweep's tail-aware gate — mirroring is the mechanism, the gate is still the
judge. This import MUST follow the buying library (see strategies/__init__.py order), or
there would be nothing to mirror.
"""

from strategy_service.strategies.options_selling import (  # noqa: F401
    _matrix,
    _mirror,
    directional,
    naked,
    neutral,
)

# Buying strategies are already registered by the time this module imports (the parent
# strategies package imports options_buying before options_selling), so every one can be
# wrapped now.
_mirror.register_mirrors()
