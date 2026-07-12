"""Starter NSE sector classification — covers the large-caps most likely to appear in
a retail portfolio (broadly Nifty 50/Next 50 names) so sector exposure limits and
sector-allocation analytics have something to key off today. This is intentionally NOT
exhaustive (NSE lists ~2,000 equities); a real sector master (NSE industry
classification file, ingested once and refreshed periodically) is the Phase 6+
replacement — see research-service. Unknown symbols return None from get_sector(),
and callers must treat that as "exclude from sector-exposure checks/allocation", never
as an error."""

SECTOR_MAP: dict[str, str] = {
    # Banking & Financial Services
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking", "KOTAKBANK": "Banking",
    "AXISBANK": "Banking", "INDUSINDBK": "Banking", "BANKBARODA": "Banking", "PNB": "Banking",
    "IDFCFIRSTB": "Banking", "AUBANK": "Banking", "FEDERALBNK": "Banking",
    "BAJFINANCE": "Financial Services", "BAJAJFINSV": "Financial Services", "HDFCLIFE": "Financial Services",
    "SBILIFE": "Financial Services", "ICICIPRULI": "Financial Services", "ICICIGI": "Financial Services",
    "SHRIRAMFIN": "Financial Services", "CHOLAFIN": "Financial Services", "PFC": "Financial Services",
    "RECLTD": "Financial Services", "MUTHOOTFIN": "Financial Services", "SBICARD": "Financial Services",
    # IT
    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT", "TECHM": "IT", "LTIM": "IT",
    "PERSISTENT": "IT", "COFORGE": "IT", "MPHASIS": "IT",
    # Energy / Oil & Gas
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "IOC": "Energy", "GAIL": "Energy",
    "ADANIGREEN": "Energy", "ADANIENSOL": "Energy", "NTPC": "Power", "POWERGRID": "Power",
    "TATAPOWER": "Power", "COALINDIA": "Energy",
    # Auto
    "MARUTI": "Auto", "TATAMOTORS": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto", "EICHERMOT": "Auto",
    "HEROMOTOCO": "Auto", "TVSMOTOR": "Auto", "ASHOKLEY": "Auto", "BOSCHLTD": "Auto",
    "MOTHERSON": "Auto", "BHARATFORG": "Auto",
    # Pharma & Healthcare
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma", "DIVISLAB": "Pharma",
    "APOLLOHOSP": "Healthcare", "LUPIN": "Pharma", "AUROPHARMA": "Pharma", "TORNTPHARM": "Pharma",
    "ZYDUSLIFE": "Pharma", "ALKEM": "Pharma", "MAXHEALTH": "Healthcare",
    # FMCG
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "TATACONSUM": "FMCG", "DABUR": "FMCG", "GODREJCP": "FMCG", "MARICO": "FMCG",
    "VBL": "FMCG", "COLPAL": "FMCG", "UNITDSPR": "FMCG",
    # Metals & Mining
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals", "VEDL": "Metals",
    "JINDALSTEL": "Metals", "SAIL": "Metals", "NMDC": "Metals", "HINDZINC": "Metals",
    # Cement / Infra / Construction
    "ULTRACEMCO": "Cement", "SHREECEM": "Cement", "AMBUJACEM": "Cement", "ACC": "Cement",
    "LT": "Infra", "ADANIPORTS": "Infra", "GMRINFRA": "Infra", "IRB": "Infra",
    # Telecom
    "BHARTIARTL": "Telecom", "IDEA": "Telecom", "INDUSTOWER": "Telecom",
    # Consumer Durables / Retail
    "TITAN": "Consumer Durables", "ASIANPAINT": "Consumer Durables", "HAVELLS": "Consumer Durables",
    "DIXON": "Consumer Durables", "VOLTAS": "Consumer Durables", "TRENT": "Retail",
    "DMART": "Retail", "NYKAA": "Retail",
    # Realty
    "DLF": "Realty", "GODREJPROP": "Realty", "OBEROIRLTY": "Realty", "LODHA": "Realty",
    # Conglomerate / Diversified
    "ADANIENT": "Diversified", "GRASIM": "Diversified", "SIEMENS": "Capital Goods",
    "ABB": "Capital Goods", "CUMMINSIND": "Capital Goods", "HAL": "Defence", "BEL": "Defence",
    # Indices (not equities, but appear in the universe / portfolios via derivatives)
    "NIFTY": "Index", "BANKNIFTY": "Index", "FINNIFTY": "Index", "MIDCPNIFTY": "Index",
    "SENSEX": "Index",
}


def get_sector(symbol: str) -> str | None:
    """None means unclassified — callers must exclude, not guess."""
    return SECTOR_MAP.get(symbol.upper())
