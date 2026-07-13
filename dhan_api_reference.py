# =============================================================================
# DHAN HQ — COMPLETE API REFERENCE  (v2.2.0)
# Base URL : https://api.dhan.co/v2/
# Docs     : https://dhanhq.co/docs/v2/
# Library  : pip install dhanhq
# GitHub   : https://github.com/dhan-oss/DhanHQ-py
# =============================================================================

# -----------------------------------------------------------------------------
# QUICK START
# -----------------------------------------------------------------------------
# from dhanhq import DhanContext, dhanhq
#
# dhan_context = DhanContext("CLIENT_ID", "ACCESS_TOKEN")
# dhan = dhanhq(dhan_context)


# =============================================================================
# 1. AUTHENTICATION
# =============================================================================
# Two methods to get access token:

# --- Method 1: PIN + TOTP (simplest for algo trading) ---
# from dhanhq import DhanLogin
# dhan_login = DhanLogin("YOUR_CLIENT_ID")
# access_token_data = dhan_login.generate_token("YOUR_PIN", "YOUR_TOTP")

# --- Method 2: OAuth Flow ---
# consent_id = dhan_login.generate_login_session(app_id, app_secret)
# access_token = dhan_login.consume_token_id(token_id, app_id, app_secret)

# --- Renew Token ---
# dhan_login.renew_token(access_token)

# --- User Profile / Validate Token ---
# user_info = dhan_login.user_profile(access_token)

# --- IP Whitelisting (manage via code) ---
# dhan_login.set_ip(access_token, "157.50.183.241", "PRIMARY")
# dhan_login.modify_ip(access_token, "157.50.183.241", "SECONDARY")
# dhan_login.get_ip(access_token)


# =============================================================================
# 2. EXCHANGE SEGMENTS
# =============================================================================

EXCHANGE_SEGMENTS = {
    "NSE_EQ":       "NSE Equity Cash         — dhan.NSE",
    "BSE_EQ":       "BSE Equity Cash         — dhan.BSE",
    "NSE_FNO":      "NSE Futures & Options   — dhan.NSE_FNO / dhan.FNO",
    "BSE_FNO":      "BSE Futures & Options   — dhan.BSE_FNO",
    "NSE_CURRENCY": "NSE Currency Derivatives— dhan.CUR",
    "MCX_COMM":     "MCX Commodity           — dhan.MCX",
    "IDX_I":        "Index (for option chain)— dhan.INDEX",
}


# =============================================================================
# 3. ENUMS / CONSTANTS
# =============================================================================

TRANSACTION_TYPES = {"BUY": "dhan.BUY", "SELL": "dhan.SELL"}

PRODUCT_TYPES = {
    "CNC":       "Cash & Carry — delivery equity",
    "INTRADAY":  "Intraday MIS — square off by EOD  (dhan.INTRA)",
    "MARGIN":    "Margin product                     (dhan.MARGIN)",
    "CO":        "Cover Order                        (dhan.CO)",
    "BO":        "Bracket Order                      (dhan.BO)",
    "MTF":       "Margin Trade Funding               (dhan.MTF)",
}

ORDER_TYPES = {
    "MARKET":           "Execute at best available price  (dhan.MARKET)",
    "LIMIT":            "Execute at specified price       (dhan.LIMIT)",
    "STOP_LOSS":        "SL Limit order                   (dhan.SL)",
    "STOP_LOSS_MARKET": "SL Market order                  (dhan.SLM)",
}

VALIDITY = {"DAY": "dhan.DAY", "IOC": "dhan.IOC"}

MARKET_FEED_MODES = {
    "Ticker": "MarketFeed.Ticker  — LTP only",
    "Quote":  "MarketFeed.Quote   — LTP + OHLC + volume",
    "Full":   "MarketFeed.Full    — Full packet with market depth",
}

WEBSOCKET_EXCHANGE_TYPES = {
    1:  "NSE_EQ  (NSE Cash)",
    2:  "NSE_FNO (NSE F&O)",
    3:  "BSE_EQ  (BSE Cash)",
    4:  "BSE_FNO (BSE F&O)",
    5:  "MCX_COMM (Commodity)",
}


# =============================================================================
# 4. ORDER MANAGEMENT
# =============================================================================

ORDER_ENDPOINTS = {
    "place_order":    "POST   /v2/orders",
    "modify_order":   "PUT    /v2/orders/{order_id}",
    "cancel_order":   "DELETE /v2/orders/{order_id}",
    "get_order_list": "GET    /v2/orders",
    "get_order_by_id":"GET    /v2/orders/{order_id}",
    "get_by_corr_id": "GET    /v2/orders/external/{correlation_id}",
    "trade_book":     "GET    /v2/trades",
    "trade_history":  "GET    /v2/trades/{from_date}/{to_date}/{page}",
}

# --- Place Order (Equity) ---
# dhan.place_order(
#     security_id      = "1333",          # HDFC Bank security ID
#     exchange_segment = dhan.NSE,        # NSE_EQ
#     transaction_type = dhan.BUY,
#     quantity         = 10,
#     order_type       = dhan.MARKET,     # MARKET | LIMIT | SL | SLM
#     product_type     = dhan.INTRA,      # INTRADAY | CNC | MARGIN | CO | BO
#     price            = 0,               # 0 for MARKET orders
#     trigger_price    = 0,               # required for SL orders
#     disclosed_quantity = 0,
#     after_market_order = False,
#     validity         = dhan.DAY,        # DAY | IOC
#     correlation_id   = "",              # optional custom order tag
# )

# --- Place F&O Order ---
# dhan.place_order(
#     security_id      = "52175",         # Nifty PE token
#     exchange_segment = dhan.NSE_FNO,
#     transaction_type = dhan.BUY,
#     quantity         = 550,
#     order_type       = dhan.MARKET,
#     product_type     = dhan.INTRA,
#     price            = 0,
# )

# --- Modify Order ---
# dhan.modify_order(
#     order_id          = "order_id",
#     order_type        = dhan.LIMIT,
#     leg_name          = "ENTRY_LEG",    # for BO/CO
#     quantity          = 10,
#     price             = 1950.0,
#     trigger_price     = 0,
#     disclosed_quantity= 0,
#     validity          = dhan.DAY,
# )

# --- Cancel Order ---
# dhan.cancel_order(order_id)

# --- Get Order by Correlation ID ---
# dhan.get_order_by_correlationID(correlationID)


# =============================================================================
# 5. SUPER ORDERS (Smart Risk Management)
# =============================================================================
# Super Orders allow setting target, stop loss, and trailing SL in one order.

SUPER_ORDER_ENDPOINTS = {
    "place":  "POST   /v2/super/orders",
    "modify": "PUT    /v2/super/orders/{order_id}",
    "cancel": "DELETE /v2/super/orders/{order_id}",
}

# dhan.place_super_order(
#     security_id      = "1333",
#     exchange_segment = dhan.NSE,
#     transaction_type = dhan.BUY,
#     quantity         = 10,
#     price            = 1900.0,
#     product_type     = dhan.CNC,
#     target_price     = 2000.0,
#     stop_loss_price  = 1850.0,
#     trailing_jump    = 5.0,           # trailing stop loss step
# )


# =============================================================================
# 6. FOREVER ORDERS (GTT — Good Till Triggered)
# =============================================================================

FOREVER_ORDER_ENDPOINTS = {
    "place":  "POST   /v2/forever/orders",
    "modify": "PUT    /v2/forever/orders/{order_id}",
    "cancel": "DELETE /v2/forever/orders/{order_id}",
    "get_all":"GET    /v2/forever/orders",
}

# --- Single Forever Order ---
# dhan.place_forever(
#     security_id      = "1333",
#     exchange_segment = dhan.NSE,
#     transaction_type = dhan.BUY,
#     order_type       = dhan.LIMIT,
#     product_type     = dhan.CNC,
#     quantity         = 10,
#     price            = 1900.0,
#     trigger_Price    = 1950.0,
# )

# --- OCO Forever Order (One Cancels Other) ---
# dhan.place_forever(
#     security_id      = "1333",
#     exchange_segment = dhan.NSE,
#     transaction_type = dhan.SELL,
#     order_type       = dhan.LIMIT,
#     product_type     = dhan.CNC,
#     quantity         = 10,
#     price            = 2100.0,         # target
#     trigger_Price    = 2050.0,
#     order_flag       = "OCO",
#     price1           = 1850.0,         # stop loss price
#     trigger_Price1   = 1870.0,
#     quantity1        = 10,
# )


# =============================================================================
# 7. PORTFOLIO
# =============================================================================

PORTFOLIO_ENDPOINTS = {
    "positions": "GET /v2/positions",
    "holdings":  "GET /v2/holdings",
    "convert":   "POST /v2/positions/convert",
}

# dhan.get_positions()
# dhan.get_holdings()
# dhan.convert_position(
#     from_product_type = dhan.INTRA,
#     to_product_type   = dhan.CNC,
#     security_id       = "1333",
#     exchange_segment  = dhan.NSE,
#     transaction_type  = dhan.BUY,
#     quantity          = 10,
# )


# =============================================================================
# 8. FUNDS & MARGIN
# =============================================================================

FUND_ENDPOINTS = {
    "fund_limits":    "GET  /v2/fundlimit",
    "margin_calc":    "POST /v2/margincalculator",
}

# dhan.get_fund_limits()
# Returns: availabelBalance, sodLimit, collateralAmount, receiveableAmount,
#          utilisedAmount, blockedPayoutAmount, withdrawableBalance

# dhan.calculate_margin(
#     exchange_segment = dhan.NSE,
#     transaction_type = dhan.BUY,
#     quantity         = 10,
#     product_type     = dhan.CNC,
#     security_id      = "1333",
#     price            = 1900.0,
# )


# =============================================================================
# 9. MARKET QUOTES (REST — Snapshot)
# =============================================================================

MARKET_QUOTE_ENDPOINTS = {
    "ltp":   "POST /v2/marketfeed/ltp",
    "ohlc":  "POST /v2/marketfeed/ohlc",
    "quote": "POST /v2/marketfeed/quote",
}

# --- LTP ---
# dhan.ticker_data(securities={"NSE_EQ": [1333, 2885]})

# --- OHLC ---
# dhan.ohlc_data(securities={"NSE_EQ": [1333], "NSE_FNO": [52175]})

# --- Full Quote (with depth) ---
# dhan.quote_data(securities={"NSE_EQ": [1333]})


# =============================================================================
# 10. HISTORICAL DATA
# =============================================================================

HISTORICAL_ENDPOINTS = {
    "intraday": "POST /v2/charts/intraday",
    "daily":    "POST /v2/charts/historical",
    "expired":  "POST /v2/charts/expired-options",
}

CANDLE_INTERVALS = ["1", "5", "15", "25", "60"]  # minutes for intraday

# --- Intraday Minute Data ---
# dhan.intraday_minute_data(
#     security_id      = "1333",
#     exchange_segment = "NSE_EQ",
#     instrument_type  = "EQUITY",        # EQUITY | FUTIDX | OPTIDX | FUTSTK | OPTSTK | FUTCOM | OPTFUT | UNDIDX
#     from_date        = "2024-01-01",
#     to_date          = "2024-01-31",
#     interval         = "1",             # 1 | 5 | 15 | 25 | 60 minutes
# )

# --- Historical Daily Data ---
# dhan.historical_daily_data(
#     security_id      = "1333",
#     exchange_segment = "NSE_EQ",
#     instrument_type  = "EQUITY",
#     from_date        = "2023-01-01",
#     to_date          = "2024-01-01",
# )

# --- Expired Options Data ---
# dhan.expired_options_data(
#     security_id      = 13,              # Nifty
#     exchange_segment = "NSE_FNO",
#     instrument_type  = "INDEX",
#     expiry_flag      = "MONTH",         # MONTH | WEEK
#     expiry_code      = 1,               # 1=near, 2=next, 3=far
#     strike           = "ATM",
#     drv_option_type  = "CALL",          # CALL | PUT
#     required_data    = ["open","high","low","close","volume"],
#     from_date        = "2023-01-01",
#     to_date          = "2023-01-31",
# )


# =============================================================================
# 11. OPTION CHAIN
# =============================================================================

OPTION_CHAIN_ENDPOINT = "POST /v2/optionchain"

# --- Expiry List ---
# dhan.expiry_list(
#     under_security_id      = 13,        # Nifty security ID
#     under_exchange_segment = "IDX_I",
# )

# --- Full Option Chain ---
# dhan.option_chain(
#     under_security_id      = 13,
#     under_exchange_segment = "IDX_I",
#     expiry                 = "2024-10-31",   # YYYY-MM-DD
# )
# Returns: OI, greeks (delta/gamma/theta/vega), volume, bid/ask, LTP for all strikes


# =============================================================================
# 12. SECURITY / INSTRUMENT SEARCH
# =============================================================================

# --- Fetch Full Instrument List ---
# dhan.fetch_security_list("compact")    # "compact" | "detailed"
# Downloads CSV of all tradeable instruments with security_id, symbol, ISIN etc.

# Common Security IDs (NSE):
COMMON_SECURITY_IDS = {
    "NIFTY 50":   "13",
    "BANK NIFTY": "25",
    "FINNIFTY":   "27",
    "SENSEX":     "1",
    "HDFCBANK":   "1333",
    "RELIANCE":   "2885",
    "TCS":        "11536",
    "INFY":       "1594",
    "SBIN":       "3045",
    "ICICIBANK":  "4963",
    "ITC":        "1660",
    "WIPRO":      "3787",
    "AXISBANK":   "5900",
    "KOTAKBANK":  "1922",
    "LT":         "11483",
}


# =============================================================================
# 13. WEBSOCKET — LIVE MARKET FEED
# =============================================================================
# from dhanhq import DhanContext, MarketFeed
#
# dhan_context = DhanContext("CLIENT_ID", "ACCESS_TOKEN")
#
# instruments = [
#     (MarketFeed.NSE, "1333",  MarketFeed.Ticker),   # LTP only
#     (MarketFeed.NSE, "1333",  MarketFeed.Quote),    # LTP + OHLC + volume
#     (MarketFeed.NSE, "1333",  MarketFeed.Full),     # Full depth
#     (MarketFeed.NSE, "11915", MarketFeed.Ticker),
# ]
#
# data = MarketFeed(dhan_context, instruments, version="v2")
# data.run_forever()
#
# while True:
#     response = data.get_data()
#     print(response)
#
# # Subscribe more while running
# data.subscribe_symbols([(MarketFeed.NSE, "14436", MarketFeed.Ticker)])
#
# # Unsubscribe
# data.unsubscribe_symbols([(MarketFeed.NSE, "1333", 16)])
#
# # Close
# data.close_connection()


# =============================================================================
# 14. WEBSOCKET — LIVE ORDER UPDATES
# =============================================================================
# from dhanhq import DhanContext, OrderUpdate
#
# dhan_context = DhanContext("CLIENT_ID", "ACCESS_TOKEN")
#
# def on_order_update(order_data: dict):
#     print(order_data["Data"])
#
# order_client = OrderUpdate(dhan_context)
# order_client.on_update = on_order_update
# order_client.connect_to_dhan_websocket_sync()


# =============================================================================
# 15. FULL MARKET DEPTH (200 Levels)
# =============================================================================
# from dhanhq import DhanContext, FullDepth
#
# dhan_context = DhanContext("CLIENT_ID", "ACCESS_TOKEN")
# instruments = [(1, "1333"), (2, "52175")]   # (exchange_type, security_id)
#
# response = FullDepth(dhan_context, instruments, depth_level=200)  # 20 or 200
# response.run_forever()
#
# while True:
#     response.get_data()


# =============================================================================
# 16. EDIS — SELL HOLDINGS AUTHORIZATION
# =============================================================================

EDIS_ENDPOINTS = {
    "generate_tpin": "GET  /v2/edis/tpin",
    "form":          "POST /v2/edis/form",
    "inquiry":       "GET  /v2/edis/inquire/{isin}",
}

# dhan.generate_tpin()
# dhan.open_browser_for_tpin(isin="INE00IN01015", qty=1, exchange="NSE")
# dhan.edis_inquiry(isin="INE00IN01015")


# =============================================================================
# 17. STATEMENTS & REPORTS
# =============================================================================

STATEMENT_ENDPOINTS = {
    "ledger":        "GET /v2/ledger?from_date=&to_date=",
    "trade_history": "GET /v2/trades/{from_date}/{to_date}/{page}",
}

# dhan.get_trade_history(from_date="2024-01-01", to_date="2024-01-31", page_number=0)


# =============================================================================
# 18. UTILITY
# =============================================================================

# --- Convert EPOCH to IST datetime ---
# dhan.convert_to_date_time(epoch_value)

# --- Trader Control (kill switch) ---
# dhan.kill_switch(status="ACTIVATE")     # ACTIVATE | DEACTIVATE  — halts all orders


# =============================================================================
# 19. INSTRUMENT TYPES
# =============================================================================

INSTRUMENT_TYPES = {
    "EQUITY":  "Cash equity stocks",
    "FUTIDX":  "Index Futures (Nifty/BankNifty)",
    "OPTIDX":  "Index Options",
    "FUTSTK":  "Stock Futures",
    "OPTSTK":  "Stock Options",
    "FUTCOM":  "Commodity Futures (MCX)",
    "OPTFUT":  "Commodity Options",
    "UNDIDX":  "Underlying Index (for option chain)",
}


# =============================================================================
# 20. RATE LIMITS & TRADING HOURS
# =============================================================================

RATE_LIMITS = {
    "order_api":      "10 requests/second",
    "market_data":    "1 request/second per endpoint",
    "historical_api": "3 requests/second",
    "websocket":      "1 connection, up to 100 instruments",
    "full_depth_ws":  "1 connection, up to 50 instruments",
}

TRADING_HOURS = {
    "NSE_BSE_equity":   "09:15 — 15:30 IST",
    "NSE_BSE_currency": "09:00 — 17:00 IST",
    "MCX_commodity":    "09:00 — 23:30 IST",
    "pre_open":         "09:00 — 09:15 IST",
    "AMO_window":       "After 15:30 till next day 09:08",
}


# =============================================================================
# 21. COMPLETE USAGE EXAMPLE
# =============================================================================

FULL_EXAMPLE = '''
from dhanhq import DhanContext, dhanhq, MarketFeed

# 1. Initialize
dhan_context = DhanContext("CLIENT_ID", "ACCESS_TOKEN")
dhan = dhanhq(dhan_context)

# 2. Check funds
funds = dhan.get_fund_limits()
print("Available Balance:", funds["data"]["availabelBalance"])

# 3. Get Nifty LTP
ltp = dhan.ticker_data(securities={"IDX_I": [13]})
print("Nifty LTP:", ltp)

# 4. Get option chain
chain = dhan.option_chain(under_security_id=13, under_exchange_segment="IDX_I", expiry="2024-10-31")

# 5. Place intraday buy order
order = dhan.place_order(
    security_id="1333",
    exchange_segment=dhan.NSE,
    transaction_type=dhan.BUY,
    quantity=10,
    order_type=dhan.MARKET,
    product_type=dhan.INTRA,
    price=0,
)
print("Order ID:", order["data"]["orderId"])

# 6. Check order status
orders = dhan.get_order_list()

# 7. Get positions
positions = dhan.get_positions()

# 8. Cancel order
dhan.cancel_order(order["data"]["orderId"])
'''
