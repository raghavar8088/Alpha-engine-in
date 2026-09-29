"""What a "module" IS, and which HTTP traffic belongs to it.

`desk_switches` already stopped a module's SCHEDULER. That closed one of the two doors work
comes through. This file closes the other: the API. A desk does not only trade from its
background loop - every page also asks for quotes, runs scans on demand, and writes rows on
demand. Switching a module off while its endpoints still answered meant the loop went quiet
and the browser carried straight on pulling broker data and adding documents.

So: one registry, used by both gates, and every module names the API prefixes it owns.

WHAT OFF BLOCKS, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
Blocked, because these spend something:
  * every write method (POST/PUT/PATCH/DELETE) - placing, running, resetting, saving
  * GETs that go and DO work rather than report - a quote, an option chain, a scan

Still served, on purpose:
  * plain read GETs of rows already stored

That last line is the one worth arguing about, and the reason is practical: if OFF blocked
reads too, the module's page would show nothing but an error - you could not see the history
you already paid for, or even confirm the thing is off. Reading a document that already
exists costs one cheap query and fetches no market data. Blocking it would buy nothing and
cost the ability to look.

The consequence to be aware of: an OFF module's page still renders its last known numbers.
They are frozen, not live. Nothing is updating them.

WHY A SEGMENT MATCH AND NOT A SUBSTRING
---------------------------------------
`/api/intraday-lab/runs` READS stored runs; `/api/screener/scan` GOES AND SCANS. A substring
test for "run" blocks both, and blocking `/runs` would hide history for no gain. So a path is
only "work" if one of its SEGMENTS is exactly a work word - "runs" is not "run", and that
distinction is the whole point.

FAIL OPEN, ALWAYS
-----------------
A prefix nobody claimed is ungated, and an unresolvable path is ungated. A control plane that
cannot decide must let traffic through: the alternative is a typo here silently bricking a
page. `/api/main-control` and `/api/modules` are never gated at all, because a switch you
cannot reach to turn back on is not a switch.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    key: str
    label: str
    group: str
    href: str
    api_prefixes: tuple[str, ...] = ()
    # True where OTHER pages depend on this module's API, so OFF reaches further than its own
    # page. Surfaced in the UI as a warning rather than refused - it is the user's call, but
    # it should not be a surprise.
    shared: bool = False
    note: str = ""
    # False for the handful of keys that gate a background loop and own no endpoints.
    has_api: bool = True


def _m(key, label, group, href, prefixes=(), shared=False, note="") -> Module:
    return Module(key=key, label=label, group=group, href=href,
                  api_prefixes=tuple(prefixes), shared=shared, note=note,
                  has_api=bool(prefixes))


# Grouped the way the sidebar groups them, so Main Control reads like the app looks.
_MODULES: list[Module] = [
    # -- Trading ---------------------------------------------------------------------
    _m("market_data", "Market Data", "Trading", "/dashboard", ["/api/market-data"],
       shared=True,
       note="Other pages read quotes through this. OFF stops those quotes app-wide."),
    _m("ath_trading", "All Time High Trading", "Trading", "/all-time-high-trading",
       ["/api/ath"]),
    _m("screener", "Stock Screener", "Trading", "/stock-screener", ["/api/screener"]),
    _m("fundamentals", "Fundamental Rating", "Trading", "/fundamentals",
       ["/api/fundamentals"],
       note="OFF stops new screener.in lookups; ratings already stored still read back."),
    _m("swing_trading", "Swing Trading", "Trading", "/swing-trading",
       ["/api/swing", "/api/swing-signals"]),
    _m("live_trading", "Live Trading (REAL MONEY)", "Trading", "/live-trading",
       ["/api/live-trading"],
       note="Real orders. OFF blocks placing them through the API as well as the loop."),
    _m("paper_broker", "Stock + F&O Paper Trading", "Trading", "/stock-paper-trading",
       ["/api/paper-trading"]),
    _m("chart", "Chart", "Trading", "/chart", ["/api/chart"], shared=True,
       note="Chart data and the live stream. OFF stops charts wherever they appear."),
    _m("momentum_engine", "Momentum", "Trading", "/momentum", ["/api/momentum"]),
    _m("trending_stocks", "Trending Stocks", "Trading", "/trending-stocks",
       ["/api/trending-stocks"]),
    _m("nifty_scalp", "NIFTY 50 Option Scalping", "Trading", "/nifty-scalp",
       ["/api/nifty-scalp"]),
    _m("commodity", "Commodity Trading", "Trading", "/commodity", ["/api/commodity"]),
    _m("commodity_prelive", "Pre-Live Commodity Trading", "Trading", "/commodity-prelive",
       ["/api/commodity-prelive"]),
    _m("natgas_book", "Natural Gas Paper Trading", "Trading", "/commodity-prelive",
       ["/api/natgas-book"],
       note="Rs 2 lakh on two picked NATGASMINI strategies. Independent of the Pre-Live "
            "desk's switch — OFF here stops only this book's new entries."),
    _m("gold_desk", "Gold Desk (MCX + Delta)", "Trading", "/gold-desk", ["/api/gold-desk"],
       note="Two books on the same metal — MCX gold futures in rupees and Delta gold "
            "perpetuals in dollars. OFF stops new entries on BOTH; open positions are "
            "still managed to their target or stop."),
    _m("commodity_positions", "Commodity Positions", "Trading", "/commodity-positions",
       ["/api/commodity-positions"]),
    _m("portfolio", "Portfolio", "Trading", "/portfolio", ["/api/portfolio"]),
    _m("broker_account", "Orders / Positions (broker account)", "Trading", "/orders",
       ["/api/broker"], shared=True,
       note="The broker session itself. OFF stops order and position reads everywhere."),
    _m("stocks_range", "Stocks Range", "Trading", "/stocks-range", ["/api/stocks-range"]),
    _m("bullish_stocks", "Bullish Stocks", "Trading", "/bullish-stocks",
       ["/api/bullish-stocks"]),
    _m("fno_positions", "F&O Positions", "Trading", "/fno-positions",
       ["/api/fno-positions", "/api/manual-positions"]),
    _m("watchlist", "Watchlist", "Trading", "/watchlist", ["/api/watchlist"]),

    # -- Strategy Lab ----------------------------------------------------------------
    _m("strategy_factory", "Strategy Factory", "Strategy Lab", "/strategy-factory",
       ["/api/strategy-factory"]),
    _m("strategies", "Strategies", "Strategy Lab", "/strategies", ["/api/strategies"]),
    _m("zero_hero", "Zero Hero Trades", "Strategy Lab", "/zero-hero", ["/api/zero-hero"]),
    _m("backtesting", "Backtesting", "Strategy Lab", "/backtesting", ["/api/backtest"]),
    _m("stock_research", "Stock Research", "Strategy Lab", "/stock-research",
       ["/api/research"]),
    _m("live_paper", "Live Engine", "Strategy Lab", "/live",
       ["/api/live", "/api/live-paper"]),
    _m("prelive", "Pre-Live Desk - Buying", "Strategy Lab", "/prelive", ["/api/prelive"]),
    _m("prelive_selling", "Pre-Live Desk - Selling", "Strategy Lab", "/prelive-selling",
       ["/api/prelive-selling"]),
    _m("stock_desk", "Stock Pre-Live (buying + selling)", "Strategy Lab",
       "/stock-prelive-buying", ["/api/stock-desk"]),
    _m("stock_books", "Stock Pre-Live - Paper Books (Rs 10L / Rs 2L)", "Strategy Lab",
       "/stock-prelive-buying", ["/api/stock-books"]),
    _m("intraday_lab", "Intraday Stocks - Tournament", "Strategy Lab", "/intraday-stocks",
       ["/api/intraday-lab"]),
    _m("live_intraday", "Intraday Stocks - Live Intraday books", "Strategy Lab",
       "/intraday-stocks", ["/api/live-intraday"]),
    _m("pattern", "Intraday Stocks - Patterns", "Strategy Lab", "/intraday-stocks",
       ["/api/pattern"]),
    _m("pattern_books", "Intraday Stocks - Paper Trade books", "Strategy Lab",
       "/intraday-stocks", ["/api/pattern-books"]),
    _m("long_horizon", "Long-Horizon Desk", "Strategy Lab", "/long-horizon",
       ["/api/long-horizon"]),

    # -- Analytics -------------------------------------------------------------------
    _m("options", "Options", "Analytics", "/options", ["/api/options"]),
    _m("risk", "Risk", "Analytics", "/risk", ["/api/risk"]),
    _m("ai_research", "AI Research", "Analytics", "/ai", ["/api/ai"]),

    # -- Shared services (no page of their own) --------------------------------------
    _m("desk_history", "Desk History (all desks)", "System", "/dashboard",
       ["/api/desk-history"], shared=True,
       note="Aggregates every desk. OFF empties the history strips on many pages."),
    _m("instrument_search", "Instrument Search (Cmd-K)", "System", "/dashboard",
       ["/api/search"], shared=True,
       note="The app-wide search bar. OFF disables it on every page."),
    _m("telegram_signals", "Telegram Signals", "System", "/dashboard",
       ["/api/telegram-signals"]),

    # -- Background loops that own no endpoints --------------------------------------
    _m("morning_momentum", "Morning Momentum (loop)", "System", "/momentum"),
    _m("fno_auto_roll", "F&O NIFTY Auto-Roll (loop)", "System", "/fno-positions"),
    _m("fno_stock_roll", "F&O Stock Auto-Roll (loop)", "System", "/fno-positions"),
]

REGISTRY: dict[str, Module] = {m.key: m for m in _MODULES}

GROUP_ORDER = ("Trading", "Strategy Lab", "Analytics", "System")

# Never gated. The control plane has to stay reachable with everything switched off, and the
# health probe has to answer or the container is declared dead.
UNGATED_PREFIXES: tuple[str, ...] = (
    "/api/main-control", "/api/modules",
    "/api/auth", "/api/users", "/api/settings",
    "/health", "/docs", "/redoc", "/openapi.json",
)

# A path SEGMENT equal to one of these means the request goes and does work: it calls the
# broker, walks the universe, or writes what it finds. Exact segments only - see the module
# docstring on "runs" vs "run".
WORK_SEGMENTS: frozenset[str] = frozenset({
    "run", "scan", "rescan", "refresh", "resync", "sync", "backfill", "seed", "rebuild",
    "reload", "ingest", "warm", "tick", "fetch", "import",
    "quote", "quotes", "ltp", "candle", "candles", "chain", "delivery", "expiry",
})

# Methods that change something. GET and HEAD are the only ones that should not.
WRITE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# prefix -> key, longest first so "/api/live-intraday" wins over "/api/live".
_PREFIX_MAP: list[tuple[str, str]] = sorted(
    ((p, m.key) for m in _MODULES for p in m.api_prefixes),
    key=lambda t: len(t[0]), reverse=True)


def _seg_prefix(path: str, prefix: str) -> bool:
    """True if `path` is `prefix` or a child of it - on a SEGMENT boundary.

    Without the boundary check "/api/live" would claim "/api/live-trading", and Live Trading
    would be switched off by the Live Engine's toggle."""
    return path == prefix or path.startswith(prefix + "/")


def is_ungated(path: str) -> bool:
    return any(_seg_prefix(path, p) for p in UNGATED_PREFIXES)


def resolve(path: str) -> str | None:
    """Which module owns this request path, or None if nobody claims it."""
    if is_ungated(path):
        return None
    for prefix, key in _PREFIX_MAP:
        if _seg_prefix(path, prefix):
            return key
    return None


def is_work(method: str, path: str) -> bool:
    """Would serving this spend a broker call or add/change a document?"""
    if (method or "").upper() in WRITE_METHODS:
        return True
    return any(seg.lower() in WORK_SEGMENTS for seg in path.split("/") if seg)


def owned_prefixes() -> list[str]:
    return [p for p, _ in _PREFIX_MAP]
