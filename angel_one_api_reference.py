# =============================================================================
# ANGEL ONE SMARTAPI — COMPLETE API REFERENCE
# Base URL : https://apiconnect.angelone.in
# Login URL: https://smartapi.angelone.in/publisher-login
# Docs     : https://smartapi.angelone.in/docs/User
# Library  : pip install smartapi-python pyotp
# =============================================================================

# -----------------------------------------------------------------------------
# QUICK START — LOGIN
# -----------------------------------------------------------------------------
# from SmartApi import SmartConnect
# import pyotp
#
# obj = SmartConnect(api_key="YOUR_API_KEY")
# totp = pyotp.TOTP("YOUR_TOTP_SECRET").now()
# data = obj.generateSession("CLIENT_ID", "PASSWORD", totp)
# refresh_token = data['data']['refreshToken']
# feed_token    = obj.getfeedToken()


# =============================================================================
# 1. AUTHENTICATION
# =============================================================================

AUTH_ENDPOINTS = {
    "login":          "POST /rest/auth/angelbroking/user/v1/loginByPassword",
    "generate_token": "POST /rest/auth/angelbroking/jwt/v1/generateTokens",
    "logout":         "POST /rest/secure/angelbroking/user/v1/logout",
    "get_profile":    "GET  /rest/secure/angelbroking/user/v1/getProfile",
}

LOGIN_REQUEST = {
    "clientcode": "YOUR_CLIENT_ID",   # Angel One login ID (e.g. A123456)
    "password":   "YOUR_PIN",          # 4-digit PIN / password
    "totp":       "123456",            # 6-digit TOTP from authenticator app
}

LOGIN_RESPONSE = {
    "status": True,
    "message": "SUCCESS",
    "data": {
        "jwtToken":     "<JWT — use as Bearer token in Authorization header>",
        "refreshToken": "<use to renew JWT before expiry>",
        "feedToken":    "<use for WebSocket market data>",
    }
}

# Required headers for all authenticated requests
REQUEST_HEADERS = {
    "Content-Type":    "application/json",
    "Accept":          "application/json",
    "X-PrivateKey":    "YOUR_API_KEY",
    "X-UserType":      "USER",
    "X-SourceID":      "WEB",
    "X-ClientLocalIP": "127.0.0.1",
    "X-ClientPublicIP":"<your public IP>",
    "X-MACAddress":    "<your MAC address>",
    "Authorization":   "Bearer <jwtToken>",   # after login
}


# =============================================================================
# 2. ORDERS
# =============================================================================

ORDER_ENDPOINTS = {
    "place_order":     "POST /rest/secure/angelbroking/order/v1/placeOrder",
    "modify_order":    "POST /rest/secure/angelbroking/order/v1/modifyOrder",
    "cancel_order":    "POST /rest/secure/angelbroking/order/v1/cancelOrder",
    "order_book":      "GET  /rest/secure/angelbroking/order/v1/getOrderBook",
    "trade_book":      "GET  /rest/secure/angelbroking/order/v1/getTradeBook",
    "order_details":   "GET  /rest/secure/angelbroking/order/v1/details/<orderid>",
    "ltp_data":        "POST /rest/secure/angelbroking/order/v1/getLtpData",
    "search_scrip":    "POST /rest/secure/angelbroking/order/v1/searchScrip",
}

# --- Place Order ---
PLACE_ORDER_PARAMS = {
    "variety":         "NORMAL",       # NORMAL | STOPLOSS | AMO | ROBO
    "tradingsymbol":   "SBIN-EQ",      # Symbol name (e.g. SBIN-EQ, RELIANCE-EQ)
    "symboltoken":     "3045",         # Unique token — get via searchScrip()
    "transactiontype": "BUY",          # BUY | SELL
    "exchange":        "NSE",          # NSE | BSE | NFO | BFO | MCX | CDS
    "ordertype":       "LIMIT",        # MARKET | LIMIT | STOPLOSS_LIMIT | STOPLOSS_MARKET
    "producttype":     "INTRADAY",     # DELIVERY | INTRADAY | MARGIN | BO | CO | ROBO
    "duration":        "DAY",          # DAY | IOC
    "price":           "500.00",       # Required for LIMIT orders; "0" for MARKET
    "squareoff":       "0",            # For BO orders only
    "stoploss":        "0",            # For BO/CO orders only
    "quantity":        "1",
    # Optional
    "triggerprice":    "0",            # Required for STOPLOSS orders
    "disclosedquantity": "0",
}

# --- Modify Order ---
MODIFY_ORDER_PARAMS = {
    "variety":         "NORMAL",
    "orderid":         "<order_id>",
    "ordertype":       "LIMIT",
    "producttype":     "INTRADAY",
    "duration":        "DAY",
    "price":           "510.00",
    "quantity":        "1",
    "tradingsymbol":   "SBIN-EQ",
    "symboltoken":     "3045",
    "exchange":        "NSE",
}

# --- Cancel Order ---
CANCEL_ORDER_PARAMS = {
    "variety": "NORMAL",
    "orderid": "<order_id>",
}

# --- LTP (Last Traded Price) ---
LTP_PARAMS = {
    "exchange":      "NSE",
    "tradingsymbol": "SBIN-EQ",
    "symboltoken":   "3045",
}

# --- Search Scrip (get symboltoken) ---
SEARCH_SCRIP_PARAMS = {
    "exchange":    "NSE",       # NSE | BSE | NFO | MCX
    "searchscrip": "SBIN",     # search string
}


# =============================================================================
# 3. PORTFOLIO
# =============================================================================

PORTFOLIO_ENDPOINTS = {
    "holdings":     "GET /rest/secure/angelbroking/portfolio/v1/getHolding",
    "all_holdings": "GET /rest/secure/angelbroking/portfolio/v1/getAllHolding",
    "positions":    "GET /rest/secure/angelbroking/order/v1/getPosition",
    "rms_limit":    "GET /rest/secure/angelbroking/user/v1/getRMS",
}

# --- Convert Position ---
CONVERT_POSITION_PARAMS = {
    "exchange":        "NSE",
    "oldproducttype":  "INTRADAY",
    "newproducttype":  "DELIVERY",
    "tradingsymbol":   "SBIN-EQ",
    "symboltoken":     "3045",
    "transactiontype": "BUY",
    "quantity":        1,
}


# =============================================================================
# 4. GTT — GOOD TILL TRIGGERED
# =============================================================================

GTT_ENDPOINTS = {
    "create": "POST /gtt-service/rest/secure/angelbroking/gtt/v1/createRule",
    "modify": "POST /gtt-service/rest/secure/angelbroking/gtt/v1/modifyRule",
    "cancel": "POST /gtt-service/rest/secure/angelbroking/gtt/v1/cancelRule",
    "details":"POST /rest/secure/angelbroking/gtt/v1/ruleDetails",
    "list":   "POST /rest/secure/angelbroking/gtt/v1/ruleList",
}

GTT_CREATE_PARAMS = {
    "tradingsymbol":  "SBIN-EQ",
    "symboltoken":    "3045",
    "exchange":       "NSE",
    "producttype":    "MARGIN",        # MARGIN | DELIVERY | INTRADAY
    "transactiontype":"BUY",
    "price":          100000,          # Order price (in paise or as float)
    "qty":            10,
    "disclosedqty":   10,
    "triggerprice":   200000,          # Price at which GTT triggers
    "timeperiod":     365,             # Days the rule is valid
}

GTT_LIST_PARAMS = {
    "status": ["FORALL"],  # ["NEW"] | ["CANCELLED"] | ["ACTIVE"] | ["FORALL"]
    "page":   1,
    "count":  10,
}


# =============================================================================
# 5. HISTORICAL / CANDLE DATA
# =============================================================================

HISTORICAL_ENDPOINTS = {
    "candle_data": "POST /rest/secure/angelbroking/historical/v1/getCandleData",
    "oi_data":     "POST /rest/secure/angelbroking/historical/v1/getOIData",
}

CANDLE_DATA_PARAMS = {
    "exchange":    "NSE",
    "symboltoken": "3045",
    "interval":    "ONE_MINUTE",   # ONE_MINUTE | THREE_MINUTE | FIVE_MINUTE |
                                   # TEN_MINUTE | FIFTEEN_MINUTE | THIRTY_MINUTE |
                                   # ONE_HOUR | ONE_DAY | ONE_WEEK | ONE_MONTH
    "fromdate":    "2024-01-01 09:15",   # Format: YYYY-MM-DD HH:MM
    "todate":      "2024-01-01 15:30",
}

# Response: {"status": True, "data": [[timestamp, open, high, low, close, volume], ...]}


# =============================================================================
# 6. MARKET DATA
# =============================================================================

MARKET_DATA_ENDPOINTS = {
    "quote":          "POST /rest/secure/angelbroking/market/v1/quote",
    "option_greek":   "POST /rest/secure/angelbroking/marketData/v1/optionGreek",
    "gainers_losers": "POST /rest/secure/angelbroking/marketData/v1/gainersLosers",
    "put_call_ratio": "GET  /rest/secure/angelbroking/marketData/v1/putCallRatio",
    "oi_buildup":     "POST /rest/secure/angelbroking/marketData/v1/OIBuildup",
    "nse_intraday":   "GET  /rest/secure/angelbroking/marketData/v1/nseIntraday",
    "bse_intraday":   "GET  /rest/secure/angelbroking/marketData/v1/bseIntraday",
}

MARKET_DATA_PARAMS = {
    "mode": "FULL",              # LTP | OHLC | FULL
    "exchangeTokens": {
        "NSE": ["3045", "1594"],
        "BSE": ["500325"],
    }
}

OPTION_GREEK_PARAMS = {
    "name":       "NIFTY",
    "expirydate": "25JAN2024",   # DD-MON-YYYY
}

GAINERS_LOSERS_PARAMS = {
    "datatype":   "PercOIGainers",   # PercOIGainers | PercOILosers | PercPriceGainers | PercPriceLosers
    "expirytype": "NEAR",            # NEAR | NEXT | FAR
}

OI_BUILDUP_PARAMS = {
    "expirytype": "NEAR",
    "datatype":   "Long Built Up",   # Long Built Up | Short Built Up | Short Covering | Long Unwinding
}


# =============================================================================
# 7. MARGIN / CHARGES
# =============================================================================

MARGIN_ENDPOINTS = {
    "margin_api":       "POST /rest/secure/angelbroking/margin/v1/batch",
    "estimate_charges": "POST /rest/secure/angelbroking/brokerage/v1/estimateCharges",
}

ESTIMATE_CHARGES_PARAMS = {
    "orders": [
        {
            "product_type":     "DELIVERY",   # DELIVERY | INTRADAY | MARGIN
            "transaction_type": "BUY",
            "quantity":         "10",
            "price":            "800",
            "exchange":         "NSE",
            "symbol_name":      "SBIN-EQ",
            "token":            "3045",
        }
    ]
}


# =============================================================================
# 8. EDIS (Electronic Delivery Instruction Slip)
# =============================================================================

EDIS_ENDPOINTS = {
    "verify_dis":      "POST /rest/secure/angelbroking/edis/v1/verifyDis",
    "generate_tpin":   "POST /rest/secure/angelbroking/edis/v1/generateTPIN",
    "tran_status":     "POST /rest/secure/angelbroking/edis/v1/getTranStatus",
}

VERIFY_DIS_PARAMS    = {"isin": "INE528G01035", "quantity": "1"}
GENERATE_TPIN_PARAMS = {"dpId": "33200", "ReqId": "235161...", "boid": "120332...", "pan": "ABCDE1234F"}
TRAN_STATUS_PARAMS   = {"ReqId": "235161..."}


# =============================================================================
# 9. WEBSOCKET — MARKET FEED (SmartWebSocketV2)
# =============================================================================
# WebSocket URL: wss://smartapisocket.angelone.com/smart/stream
#
# from SmartApi.smartWebSocketV2 import SmartWebSocketV2
#
# sws = SmartWebSocketV2(
#     auth_token  = "Bearer <jwtToken>",
#     api_key     = "YOUR_API_KEY",
#     client_code = "CLIENT_ID",
#     feed_token  = feed_token,
# )
#
# def on_data(wsapp, message):       print("Tick:", message)
# def on_open(wsapp):                sws.subscribe("1", 1, [{"exchangeType": 1, "tokens": ["3045"]}])
# def on_error(wsapp, error):        print("Error:", error)
# def on_close(wsapp):               print("Closed")
#
# sws.on_open  = on_open
# sws.on_data  = on_data
# sws.on_error = on_error
# sws.on_close = on_close
# sws.connect()

WEBSOCKET_SUBSCRIPTION = {
    "correlationID": "1",
    "action": 1,           # 1 = SUBSCRIBE | 0 = UNSUBSCRIBE
    "params": {
        "mode": 1,         # 1 = LTP | 2 = QUOTE | 3 = SNAP_QUOTE
        "tokenList": [
            {
                "exchangeType": 1,         # 1=NSE_CM | 2=NSE_FO | 3=BSE_CM | 4=BSE_FO | 5=MCX_FO | 7=NCX_FO | 13=CDS_FO
                "tokens": ["3045", "1594"]
            }
        ]
    }
}


# =============================================================================
# 10. ENUMS / REFERENCE VALUES
# =============================================================================

EXCHANGES = {
    "NSE": "NSE",   # NSE Cash
    "BSE": "BSE",   # BSE Cash
    "NFO": "NFO",   # NSE F&O
    "BFO": "BFO",   # BSE F&O
    "MCX": "MCX",   # Commodity
    "CDS": "CDS",   # Currency derivatives
}

VARIETIES = {
    "NORMAL":    "Regular order",
    "STOPLOSS":  "Stop-loss order",
    "AMO":       "After Market Order",
    "ROBO":      "ROBO (trailing SL bracket)",
}

ORDER_TYPES = {
    "MARKET":          "Execute at current market price",
    "LIMIT":           "Execute at specified price or better",
    "STOPLOSS_LIMIT":  "Trigger SL then place LIMIT order",
    "STOPLOSS_MARKET": "Trigger SL then place MARKET order",
}

PRODUCT_TYPES = {
    "DELIVERY": "CNC — equity delivery (hold overnight)",
    "INTRADAY": "MIS — must square off by EOD",
    "MARGIN":   "Margin product",
    "BO":       "Bracket Order (with target & SL)",
    "CO":       "Cover Order (with SL)",
    "ROBO":     "ROBO trailing SL bracket order",
}

VALIDITY = {
    "DAY": "Valid for the current trading day",
    "IOC": "Immediate or Cancel — fill instantly or cancel",
}

TRANSACTION_TYPES = {
    "BUY":  "Buy / Long",
    "SELL": "Sell / Short",
}

CANDLE_INTERVALS = [
    "ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE", "TEN_MINUTE",
    "FIFTEEN_MINUTE", "THIRTY_MINUTE", "ONE_HOUR",
    "ONE_DAY", "ONE_WEEK", "ONE_MONTH",
]

WEBSOCKET_EXCHANGE_TYPES = {
    1:  "NSE_CM  (NSE Cash)",
    2:  "NSE_FO  (NSE F&O)",
    3:  "BSE_CM  (BSE Cash)",
    4:  "BSE_FO  (BSE F&O)",
    5:  "MCX_FO  (MCX Commodity)",
    7:  "NCX_FO",
    13: "CDS_FO  (Currency Derivatives)",
}

WEBSOCKET_MODES = {
    1: "LTP        — Last Traded Price only",
    2: "QUOTE      — LTP + OHLC + volume",
    3: "SNAP_QUOTE — Full market depth (best 5 bid/ask)",
}


# =============================================================================
# 11. COMMON SYMBOL TOKENS (NSE)
# =============================================================================

COMMON_TOKENS = {
    "NIFTY 50":    "99926000",
    "BANK NIFTY":  "99926009",
    "SENSEX":      "1",
    "RELIANCE":    "2885",
    "TCS":         "11536",
    "INFY":        "1594",
    "HDFCBANK":    "1333",
    "SBIN":        "3045",
    "ITC":         "1660",
    "ICICIBANK":   "4963",
    "WIPRO":       "3787",
    "HINDUNILVR":  "1394",
    "LT":          "11483",
    "AXISBANK":    "5900",
    "KOTAKBANK":   "1922",
}


# =============================================================================
# 12. ERROR CODES
# =============================================================================

ERROR_CODES = {
    "AB1000": "SUCCESS",
    "AB1001": "Invalid Token / Session expired — re-login required",
    "AB1002": "Invalid API Key",
    "AB1003": "Access denied",
    "AB1004": "Session Limit exceeded",
    "AB1005": "Too many requests — rate limit hit",
    "AB1010": "Order rejected",
    "AB1011": "Insufficient margin/funds",
    "AB1012": "Invalid symbol token",
    "AB1013": "Exchange not enabled for this account",
    "AB2000": "Internal server error",
    "AB2001": "Service unavailable",
}


# =============================================================================
# 13. RATE LIMITS & TRADING HOURS
# =============================================================================

RATE_LIMITS = {
    "order_api":       "10 orders/second",
    "market_data_api": "3 requests/second",
    "historical_api":  "3 requests/second",
    "websocket":       "1 connection per session",
}

TRADING_HOURS = {
    "NSE_BSE_equity":   "09:15 — 15:30 IST",
    "NSE_BSE_currency": "09:00 — 17:00 IST",
    "MCX_commodity":    "09:00 — 23:30 IST",
    "pre_open":         "09:00 — 09:15 IST",
    "AMO_window":       "After 15:30 until next day 09:15",
}
