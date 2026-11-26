"""Hand-made part of the YouTube Live Streaming page: which channels it lists, in which table, and what the
survey cannot work out by itself (a short note, and whether the stream shows the trader's own account).

Every number on the page comes from the survey files instead (summary*.json, recount.json, raw/*.json).
Key = the target the survey used for the channel: an @handle (pass 1) or a channel id (passes 1-2).
shows: "seen"   = a real broker account was read off the stream's screen (Booming Bulls, 26 Nov 2026);
       "titles" = the stream titles name the trader's own positions; not checked on screen.
"""

HINDI, CRYPTO, FX, GONE = "hindi", "crypto", "fx", "gone"

CHANNELS = {
    # --- Indian channels: crypto and gold together, evenings (IST); Hindi or Hinglish ---------------------------
    "UC9zh516XCUhN1EVIdblTXXQ": (HINDI, "", "Mayank Raj. \"Live Crypto & Gold Analysis\"; says it sells no courses or call tips."),
    "@BoomingBulls": (HINDI, "seen", "On 26 Nov 2026 the stream showed a real Zuperior account: an XAUUSD short of 15 lots."),
    "UCJrAfJ39rplnIFssSedUQOQ": (HINDI, "", "Bitcoin and altcoins. The most-watched stream at 23:56 IST (4,254 watching)."),
    "UC5Pug1yQPkk3FG9ii04kVCg": (HINDI, "", "Gold and crypto, about 3½ hours a stream; promotes a paid VIP group."),
    "UC2zdAZeihqvLsUsNx3et8gQ": (HINDI, "", "Gold and crypto; often two streams a day."),
    "UCvkKjDe2XGRYv3dn0_ahdug": (HINDI, "", "Crypto and gold, about 3 hours a stream."),
    "UC6VsKH_O59Kdc_yYATRGc_A": (HINDI, "", "Akhand Pratap Singh. Crypto and gold analysis."),
    "UCXf5JQF72XZe_U10HF3SS6A": (HINDI, "", "Crypto and gold; sells an \"MT30 setup\"."),
    "UCq5uGxe_EkZNqj9le3OXnKQ": (HINDI, "", "Gold, BTC, forex. Same description word for word as Trade Like Malika: likely one team."),
    "UCUMAP6ENB2EIq04ZKMw4EqA": (HINDI, "", "Gold and crypto, US session."),
    "UCJsIlba0RSbBo7_zBC8b6Ig": (HINDI, "", "Gold, BTC, forex. 1,327 watching at 23:56 IST. Bullish Master FX is its second channel."),
    "UCqAp2ZBo9pWZAUODe0OiJCw": (HINDI, "", "Second channel of Bullish Bull Master (its titles tag both)."),
    "UCRem0cxZp0CNrJaFGRB2Tpw": (HINDI, "", "Gold, Bitcoin and Ethereum; titles name Delta Exchange."),
    "UCpqij6wlWog84oKHLAQY-NA": (HINDI, "", "Bitcoin and gold, about 4 hours a stream."),
    "UCj7cny5FsrDD2AdLntePeiQ": (HINDI, "", "BTC and gold; says it has no paid services."),
    "UC8tnMSzCEcVn_9YGCF4V68w": (HINDI, "", "Gold and Bitcoin; calls it \"Live Trap Trading\"."),
    "UCaw-1cUd74wvEatvZna0TzQ": (HINDI, "", "Delta Exchange's own channel: BTC, ETH, the XAUT gold token, options."),
    "UCf6LtAmwVDvzq1myGwCRRmA": (HINDI, "", "Gold, BTC, forex. Same description word for word as Mehak Trades."),
    "UClXLcpCUVoQT6E61QXG_wYg": (HINDI, "", "Gold and BTC."),
    "UCBz5NCFRfIfNbXmwH1_qmww": (HINDI, "", "Gold, London and New York sessions; sells a VIP group."),
    "UCtBjlVRuHjIQPws7tRe1IXg": (HINDI, "", "Bitcoin and gold scalping."),
    "UC_LOYp7JhNmfgOvyQ1vRmFw": (HINDI, "", "Gold scalping, in Hinglish."),
    "UCpoy0NO215QBKaQ28GMuS0g": (HINDI, "", "Crypto and gold, in Hindi; rarely live lately."),
    "@IITianTrader": (HINDI, "", "Crypto; streams a few times a month."),
    # --- crypto, English ---------------------------------------------------------------------------------------
    "@CryptoBanterGroup": (CRYPTO, "", "A studio show: several hosts trade altcoins live, two or three streams a day."),
    "UCc4Rz_T9Sb1w5rqqo9pL1Og": (CRYPTO, "", "Carl Runefelt's show. Bitcoin outlook."),
    "@CryptoCapitalVenture": (CRYPTO, "", "Dan Gambardello. Analysis."),
    "@CryptoJebb": (CRYPTO, "", "Bitcoin analysis."),
    "@CryptoFace": (CRYPTO, "titles", "Titles like \"Live - $3,000,000 Trade\": his own positions."),
    "UCnwxzpFzZNtLH8NgTeAROFA": (CRYPTO, "", "Analysis of stocks and BTC, with his own BTC trades."),
    "UCxIU1RFIdDpvA8VOITswQ1A": (CRYPTO, "", "Scott Melker. News and guests, not trades."),
    "UCEOlty1_FP0B_x3Kedg2r0Q": (CRYPTO, "", "Bitcoin live trading almost every day, about 3 hours."),
    "UC7FkshE7oKhI1uoQBq9cuaA": (CRYPTO, "titles", "Titles like \"$8,400,000+ LONG TRADES\": his own positions."),
    "@TraderXO": (CRYPTO, "", "Occasional Bitcoin market reviews."),
    "@ToneVays": (CRYPTO, "", "Occasional."),
    "UCnqZ2hx679DqRi6khRUNw2g": (CRYPTO, "", "Short Bitcoin streams."),
    "@PaulBarronNetwork": (CRYPTO, "", "Big channel, rarely live (news events)."),
    # --- gold and forex, English -------------------------------------------------------------------------------
    "@TraderNick": (FX, "", "\"LIVE Trading Gold, Nasdaq, Forex | A1 Trading Show\", about 4 hours."),
    "@RileyColeman": (FX, "titles", "Titles state the open trade (\"Long 404 QQQ shares at 625 avg\"); mostly US index trades now."),
    "UC04-HvUvHG4hpMnQx07ObYQ": (FX, "", "Forex, gold and Nasdaq; sells signals and a trading robot."),
    "UC7QFqtxMMFsPUO2rxZsBKEA": (FX, "", "Gold, New York session; sells VIP signals and classes."),
    "UC4C43bjs7bwwasNPecJm8bw": (FX, "", "Tom Hougaard; mostly DAX and FTSE index trading."),
    "UCFEgynfV4t075rh5WowawDw": (FX, "", "Gold and Nasdaq futures, volume and order flow."),
    "@SimplyForex": (FX, "", "Short pre-market streams on currencies and gold."),
    # --- famous, but no longer live on YouTube -----------------------------------------------------------------
    "@TJRTrades": (GONE, "", "Last YouTube live about two years ago."),
    "@InnerCircleTrader": (GONE, "", "ICT. The last streams were NQ futures reviews (May 2026)."),
    "UCBkGMys0mYl3Myxh3CTsASA": (GONE, "", "Used to stream big Bitcoin moves live, with his trades."),
    "@KojoForex": (GONE, "", "Gold and forex; used to hold mid-week live trading sessions."),
    "@CryptoRover": (GONE, "", "The last lives were on big Bitcoin moves."),
    "@GhanshyamTech": (GONE, "", "Hindi; the last live was about a year ago."),
    "@JacobCryptoBury": (GONE, "", "Crypto news."),
    "@TRADEPROAcademy": (GONE, "", "Futures."),
    "UCtvdzJWoDKL1LOewU5ADJIQ": (GONE, "", "Michaël van de Poppe: videos only, the channel has no live streams."),
}

# Markets seen on screen where the titles name none ("Live Trading").
MARKETS_SEEN = {"@BoomingBulls": ["Gold"]}

# Known 24/7 automated chart / signal channels and TV news channels in the live-now snapshot.
ROBOT_CHANNELS = {"Daily Trading Tips", "Forex Education Live", "Million Moves", "Ocs Ai Trader", "Bitcoin LIVE",
                  "ForexLia", "ChartPrime", "Target Hit", "Forex & Crypto Live Signals", "Forex & Crypto Live", "AutoFX",
                  "Sniperiq", "Live Market Pro", "TradeVector Labs", "Yuvi FX Trader", "Tomi Crypto",
                  "EXPERT ADVISOR FOREX TRADING ROBOT", "Crypto Dashboard Live", "Fable Edge View",
                  "René Balke - Fx Bot Trading", "1 Minute Futures Trader"}
TV_CHANNELS = {"CNBC Awaaz.", "Zee Business", "NDTV Profit", "ET Now Swadesh"}

# What one stream showed: Booming Bulls, live 4niO2hOWJ-E, read off the screen frames on 26 Nov 2026 ~21:13 IST.
PROBE = {
    "channel": "Booming Bulls", "video": "4niO2hOWJ-E", "date": "2026-11-26", "time": "21:13 IST",
    "terminal": "Zuperior web terminal, \"Real\" account", "symbol": "XAUUSD", "side": "SHORT", "lots": 15,
    "avg_entry": 3572.42, "balance": 99429.87, "notional_usd": 5360000, "risk_usd": 5385,
    "entries": [
        {"lots": 5, "entry": 3573.30, "stop": 3577.60, "stop_approx": False, "target": 3563.21,
         "when": "19:58, before the stream began"},
        {"lots": 5, "entry": 3572.23, "stop": 3575.26, "stop_approx": True, "target": None,
         "when": "between 21:07 and 21:12"},
        {"lots": 5, "entry": 3571.72, "stop": 3575.16, "stop_approx": True, "target": None, "when": "about 21:12:35"},
    ],
    "pnl_swing": [175, 1405], "pnl_last": 220,
    "speech": "Only \"gold still alive\" and \"gold coming back to its zone\"; the rest was a lucky draw.",
}
