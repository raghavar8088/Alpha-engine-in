"""The 50-strategy option-BUYING library (#51-100): importing registers all of them.

15 scalp (5m) + 20 intraday (15m) + 15 swing (1d), every one a premium buyer — the
options backtest engine turns BUY into a long ATM CE and SELL into a long ATM PE and
manages DTE/premium-stop/EOD square-off per style."""

from strategy_service.strategies.options_buying import (  # noqa: F401
    booming_bulls,
    breakout,
    devansh_umar,
    famous_traders,
    iitian_trader,
    intraday,
    intraday2,
    madras_trader,
    monika_rajput,
    neeraj_joshi,
    pta_aakash,
    pushkar_thakur,
    scalp,
    scalp2,
    stock_learners,
    stockburner2,
    stockforce,
    swing,
    swing2,
    trade_for_sure,
    trade_room,
    wizard_trader,
    youtube_families,
)
