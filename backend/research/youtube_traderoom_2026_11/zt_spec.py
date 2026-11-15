"""The Trade Room (Mayank Raj, @thetraderoomsss) study of 15 Nov 2026, as data: every video read, every strategy found
with its rules (E = stated in the video, I = inferred from his words, A = our assumption so the rule can run), the
quote and the video time of each stated rule, what the videos leave missing or ambiguous, and what was not coded and
why. zt_quotes.py checks every quote against the saved transcripts; zt_export.py turns this file into the app's tab
data and analyses/thetraderoomsss.md. Quotes are the romanized Hindi captions as saved (untrusted source text).

A time is (video id, "HH:MM:SS"): the caption where the quoted words start.
"""

from __future__ import annotations

CHANNEL = "The Trade Room (Mayank Raj)"
HANDLE = "@thetraderoomsss"
BUILT = "2026-11-15"

EP1, EP2, EP3, PSY = "TU88i946Bgw", "VmOVGTeIrdI", "iCbM5VL5zMg", "UuIC8EiVfWI"
L10N, L03N, L20O = "egPhH9jaylo", "qh6iEy8G3MU", "FOmPI8AcReM"
SCALP915, BTC15 = "RMwUsnJB40c", "slUuTYS7RUQ"

# every video read: (id, kind, what it gave). Titles, dates and lengths come from the Lab's evidence.
VIDEOS = [
    (EP1, "teaching", "TR-02: the daily EMA 9 side, 5-minute supply and demand boxes, three entry candles, candle stop, 1:2, three trades a day"),
    (EP2, "teaching", "risk: 2% of capital a trade, a 1:2 or 1:3 risk-reward (sizing; used by TR-02 and TR-03)"),
    (EP3, "teaching", "TR-07 (not coded): 15-minute structure, then a 5-minute or 1-minute entry, no stop or target"),
    (PSY, "teaching", "trading psychology: no trading rule"),
    (SCALP915, "teaching", "TR-01 (already in the app since 9 Nov, 11-channel study): the EMA 9/15 scalp; TR-04 runs its rules on Delta"),
    ("CeHFDebhZwA", "teaching", "Master Scalping: live option scalps on the EMA 9/15 and trend lines (repeats TR-01)"),
    ("XurmC12Wp08", "teaching", "Master Scalping EP-2: live index option scalps (repeats TR-01)"),
    ("Vw1zn3GkCxs", "teaching", "Master Scalping: accept your loss (live scalps with a one-candle stop; repeats TR-01)"),
    ("aXxxaJlTO1A", "teaching", "Master Scalping: recovering a big loss (live scalps at the EMA and trend lines; repeats TR-01)"),
    ("zpFH6GhsBR8", "teaching", "Master Scalping: risk-reward (live scalps; no new rule)"),
    ("DsZ0mYyQXec", "teaching", "Master Scalping: small stops (a candle-low stop; no new rule)"),
    ("C-DuAT2WvuQ", "teaching", "Master Scalping: trading on a phone (chart layout only)"),
    (L10N, "live", "TR-03: the momentum candle's 50% entry with the stop beyond the candle (gold after the CPI candle, bitcoin on 15 minutes)"),
    (L03N, "live", "TR-03: a candle closing across the 9 EMA and the momentum's 50% zone"),
    (L20O, "live", "TR-04: 'two EMAs, 9 and 15' on gold and bitcoin; gold's 15-minute EMA rejection"),
    ("uGowTGk-0ro", "live", "TR-06 (not coded): the 50% area of a sell-off as the line between pullback and reversal"),
    ("JSetkeDxS1g", "live", "discretionary zone and trend-line trades (TR-05, not coded)"),
    ("8MHoWYIX1f4", "live", "TR-06 (not coded): an impulsive move's 50% as the pullback entry"),
    ("lljuElLY0FU", "live", "'nothing but the EMA on my chart'; discretionary zone trades (TR-05)"),
    ("5OZvGm5j4qU", "live", "EMA talk (9, 15, 21, 50: 'all of them work'); discretionary trades (TR-05)"),
    ("6FsqMIBY6V4", "live", "discretionary trades (TR-05)"),
    ("RhoAvjhWa9A", "live", "discretionary trades (TR-05)"),
    ("byPdIG6fjy0", "live", "TR-06 (not coded): the Fibonacci 50% as the ideal pullback, the stop near 70%"),
    ("XrGsQxthK3k", "live", "TR-06 (not coded): an impulsive move's 50% zone; trailing the stop to the candle high"),
    ("rOAeBCXc1PA", "live", "1-2-minute micro-zone scalps with a same-candle-high stop (TR-05)"),
    ("Jta4qVH7Vfs", "live", "candle closes below a trend line and a grey zone (TR-05)"),
    ("nLn3_C361j8", "live", "'50% zone trading' at a candle close (Arabic auto-dub captions; TR-06)"),
    ("drS8GY1Bnsg", "live", "a close below a zone as confirmation (Arabic auto-dub captions; TR-05)"),
    ("MyPiQGYR4t8", "live", "a 5-minute candle low break as a sell trigger, a 38-pip stop for a 100-pip target (TR-05)"),
    ("Pq3bUnMR5jI", "live", "market commentary"),
    ("zkLEJopG0WQ", "live", "buy and sell zones with 5-minute closes (TR-05)"),
    ("8ofoNNQ5Ur0", "live", "breakout candles (TR-05)"),
    (BTC15, "short", "TR-04: a pin bar on bitcoin's 15-minute chart, the stop at the candle's low"),
    ("u7Npiub4iAA", "short", "an index option scalp with a resting order (repeats TR-01)"),
    ("xMuD2ueoN-8", "short", "'Power of 9/15 EMA': a rejection at the EMA (repeats TR-01)"),
    ("L_M-gx36imE", "short", "a failed trend-line breakout (TR-05)"),
    ("TSJKiefX1p0", "short", "a clip of a live trade"),
    ("hizNnGf_Ggw", "short", "a bitcoin long with a candle-low stop (repeats TR-01)"),
    ("ipIhRL_1Xl8", "short", "a clip of a live trade"),
    ("BDZ0qTE-8cc", "short", "a clip of a live trade"),
    ("3mlOntKaiz0", "short", "a bitcoin sell with the same-candle-high stop (repeats TR-01)"),
    ("d1ZyL70nOuM", "short", "no speech in the captions"),
    ("1qvDjEFpHiE", "short", "a Bank Nifty buy with the same-candle-low stop (repeats TR-01)"),
    ("rJfeQZ-_buA", "short", "a clip of a live trade"),
    ("CdmzQ_vkuG4", "short", "an overnight (BTST) Nifty buy for a gap-up: one discretionary call"),
    ("h-cAk7QcJ44", "short", "a 3 PM 'hero or zero' option trade after a trend-line breakdown: one discretionary call"),
    ("ukGI37IiAAM", "short", "a clip of a live trade"),
    ("iqgN0p7Ah1g", "short", "a big-bar buy in a running candle (repeats TR-01)"),
    ("JkwJlm48YfU", "short", "a breakout from an area bought several times (TR-05)"),
    ("lD8D87-RoCY", "short", "several reasons at once: a level break, a trend line and the EMA (TR-05)"),
    ("oGKBkkHo3FE", "short", "a stop-hunting sell-off bought (TR-05)"),
]
SKIPPED = [
    ("x6tIwjKKjdk", "his trading-desk tour: no trading content"),
    ("f36ki-zqJak", "option Greeks explained: no strategy"),
    ("GfntazObfqo", "a Bank Nifty expiry-day forecast"),
    ("ossE9V3Lh0M", "a Bank Nifty and Nifty forecast"),
]


def r(kind, tag, cites, text, quote=""):
    return {"kind": kind, "tag": tag, "cites": list(cites), "text": text, "quote": quote}


# ═════════════════════════════════════════ coded strategies ═════════════════════════════════════════════════

TR02 = {
    "id": "TR-02", "status": "coded", "readiness": "assumptions", "video": EP1,
    "name": "Daily EMA 9 side, a 5-minute supply or demand box, one of his three entry candles, the candle's extreme as "
            "the stop, 1:2, three trades a day (Nifty, Bank Nifty)",
    "markets": ["NIFTY", "BANKNIFTY"], "timeframes": ["1D", "5m"],
    "summary": "His beginner strategy. Before the day, look at yesterday's daily candle against the 9 EMA: closed above it "
               "means only buys today, below it only sells. On the 5-minute chart mark where two to four candles could not "
               "break out of a range and extend that as a box: a demand box to buy from, a supply box to sell from. When "
               "the price comes back to the box, take one of his three entry candles (a pin bar, a big bar, or a big "
               "candle with its longer wick on the losing side), stop at that candle's low (high for a sell), target at "
               "least 1:2, and no more than three trades a day.",
    "rules": [
        r("market", "E", [(EP1, "00:43:07")], "He sets it up on the NIFTY 50 chart.",
          "ye pooraa kanpleet chaart hai ye niphtee 50 kaa chaart hai"),
        r("market", "I", [(EP1, "00:55:15")], "He says the same setup turns up every day in some stock; the desk runs it on "
          "the two index charts only.", "itanaa saaraa stok hai naa har"),
        r("timeframe", "E", [(EP1, "00:42:19")], "Two timeframes: the daily chart ...",
          "ham do taaim phrem yooj karane vaale gaais theek hai ek pahalaa van de kaa chaart"),
        r("timeframe", "E", [(EP1, "00:42:52"), (EP1, "00:25:45")], "... and the 5-minute chart for the entry.",
          "aur usake baad 5"),
        r("indicator", "E", [(EP1, "00:43:34")], "The 9 EMA on the daily chart, left at its default.",
          "baay dipholt kitanaa hai 9 eem men lagaa huaa hai"),
        r("setup", "E", [(EP1, "00:45:14")], "Before trading a day, look at the previous day's daily candle: did it close "
          "above or below the EMA?", "1 janavaree kaa delee chaart dekhoge ki ye eee se"),
        r("setup", "E", [(EP1, "00:47:57"), (EP1, "00:46:00")], "Closed below it: only sells that day, every buy is "
          "ignored; closed above it: only buys, from demand zones.",
          "delee kaindal eee se neeche kloj kiyaa hai to baaing"),
        r("setup", "E", [(EP1, "00:45:27"), (EP1, "00:45:34")], "Then, on the 5-minute chart, find the supply and demand "
          "zones (support and resistance areas).", "saplaaee end dimaand jon phaaind aaut karanaa hai"),
        r("setup", "E", [(EP1, "00:57:09")], "A zone: wherever two, three or four candles or more cannot break out of a "
          "range, a support (demand) zone has formed ...", "agar do yaa do kaindal yaa"),
        r("setup", "E", [(EP1, "00:57:26")], "... extend it into a box; whenever the price comes back to the box area, look "
          "for a good entry candle.", "to aap isako aise eksatend kar lo samajh men aa rahaa hai ye ek boks ban gayaa"),
        r("entry", "E", [(EP1, "00:30:23")], "Entry candle 1: a pin bar (hammer) ...",
          "isako pin baar kaindal bolate hain haimar kaindal bolate hain"),
        r("entry", "E", [(EP1, "00:31:01"), (EP1, "00:31:14")], "... the market opened, went down, could not stay down, and "
          "closed at its high.", "maarket yahaan pe opan huaa thaa aur neeche gayaa lekin neeche sasten naheen huaa"),
        r("entry", "E", [(EP1, "00:31:33"), (EP1, "00:31:41")], "Entry candle 2: a complete candle of its colour, a small "
          "wick allowed: a 'big bar'.", "ekadam kanpleet green kaindal agar aapake"),
        r("entry", "E", [(EP1, "00:31:58")], "Entry candle 3: a big candle with a little more wick below than above (the other "
          "way round for sells).", "aur thard kaindal hotaa hai ki maan lete hain ki"),
        r("entry", "E", [(EP1, "00:32:25"), (EP1, "00:33:28")], "Sells take the mirror candles: an inverted pin bar, a red "
          "big bar, a big red candle with more wick above.", "cheej honaa chaahie jaise yah pin baar kaindal hai naa in v varted pin baar kaindal"),
        r("no_trade", "E", [(EP1, "00:33:41"), (EP1, "00:35:11")], "A candle with big wicks on both sides is indecision: no "
          "buy or sell order on it.", "lekin baraa viks naheen rahanaa"),
        r("entry", "I", [(EP1, "00:53:44"), (EP1, "00:57:31")], "He takes the trade as the entry candle closes (his "
          "risk-reward tool starts there).", "to yahaan pe ye kaindal banaa aap idhar short kie"),
        r("stop", "E", [(EP1, "00:50:43"), (EP1, "00:53:49")], "Stop at the entry candle's high for a sell ...",
          "sem kaindal haaee kaa stop los hotaa hai"),
        r("stop", "E", [(EP1, "00:57:40")], "... and at its low for a buy.", "aap kaindal lo ke stop los ke saath"),
        r("target", "E", [(EP1, "00:51:08"), (EP1, "00:58:01")], "At least 1:2, and do not get out before it.",
          "1:2 kaa etaleest aapake paas risk rivord"),
        r("management", "E", [(EP1, "00:51:02")], "At most three trades a day as a beginner: after a loss take the second, "
          "after a second loss the third.", "teen tred aap kar sakate ho ej e biganar usase jyaadaa mat karanaa"),
        r("sizing", "E", [(EP2, "00:08:45")], "Risk 2% of the capital on a trade (episode 2).", "2% kaa risk lenaa chaahie"),
        r("market", "A", [], "The desk trades the NIFTY and BANKNIFTY index minutes it records from Angel One (his chart is the "
          "index itself); stocks are left out."),
        r("setup", "A", [], "Daily candles are the desk's own sessions (a session's close is its last minute); the side is the "
          "previous session's close against the EMA 9 of the session closes (a close exactly on it: no trades that day)."),
        r("setup", "A", [], "A base is a 5-minute candle and at least two next candles of the same session whose closes stay "
          "inside its high-low range; the box is the base's lowest low to highest high. The first close outside that "
          "range shows how the market left: up makes a demand box, down a supply box. A box lives through its session "
          "and the next one, a close through its far side ends it, and each box gives one trade at most."),
        r("entry", "A", [], "'At the box': a candle reaching into it (for a buy, its low at or below the box top) without "
          "closing beyond its far side. Pin bar: the wick on the losing side at least twice the body and the other wick at "
          "most a quarter of the range. Big bar: the side's colour, a body of at least 70% of the range and at least the "
          "average body of the 20 candles before it. Candle 3: the side's colour, a body of at least half the range and at "
          "least that average, the longer wick on the losing side."),
        r("entry", "A", [], "A market order at the next minute's open; no new entries from 15:00 IST; the desk closes what is "
          "still open at its session end."),
        r("sizing", "A", [], "The desk sizes every account at 1% of equity a trade (the module's rule for all its books, so "
          "they compare), not his 2%."),
    ],
    "vague": [
        {"term": "touches the EMA and makes a green candle", "at": (EP1, "00:44:35"),
         "why": "he first describes the daily candle as touching the EMA and closing green, then reduces it to a close above "
                "or below the EMA (45:14)", "coded": "the close against the EMA alone"},
        {"term": "a trend line works like a supply or demand zone", "at": (EP1, "00:48:18"),
         "why": "trend lines are drawn by eye through two or three touches", "coded": "horizontal base boxes only"},
        {"term": "book at the previous support zone", "at": (EP1, "00:53:52"),
         "why": "his first example books profit at the previous day's support zone (1:3.67) instead of 1:2",
         "coded": "the fixed 1:2 he gives as the minimum"},
        {"term": "hold it longer while above the EMA", "at": (EP1, "00:58:08"),
         "why": "he shows the trade running further but gives no exit for it", "coded": "not used: out at 1:2"},
        {"term": "the zone the market fell from", "at": (EP1, "00:52:52"),
         "why": "his 22 Oct example sells from an area the market had fallen from earlier, not a fresh base",
         "coded": "boxes from the same session or the previous one"},
    ],
    "unclear": ["How old may a zone be, and may one zone give a second trade?",
                "Is 'big' a size against recent candles or against the day's range? He never gives a number."],
    "claims": [{"at": (EP1, "00:54:14"), "value": "1:3.67 on his first example trade, booked at the support zone", "period": "one example"},
               {"at": (EP1, "00:58:54"), "value": "he says he uses this single strategy for all his trading", "period": ""}],
    "examples": [
        {"at": (EP1, "00:53:22"), "date": "22 Oct (the year is not said)", "instrument": "NIFTY", "direction": "short",
         "setup": "the previous day closed red below the 9 EMA; a big red bar at a supply zone", "entry": "the candle's close",
         "stop": "the candle's high", "target": "the previous support zone", "outcome": "1:3.67 as he shows it"},
        {"at": (EP1, "00:57:31"), "date": "25 Jun 2024", "instrument": "NIFTY", "direction": "long",
         "setup": "24 Jun closed green at the 9 EMA; a morning base box, a green entry candle at the box",
         "entry": "the candle's close", "stop": "the candle's low", "target": "1:2", "outcome": "target hit, he says"},
    ],
    "duplicate_check": "Not in the library: SB-03 (9 EMA rejection scalp, NIFTY) has no daily side and no boxes; BG-05 (gold "
                       "supply/demand zone) needs an EMA 8 cross and an engulfing on gold; SJ-01 takes its side from two "
                       "daily closes and trades a 9:40 range retest.",
}

TR03 = {
    "id": "TR-03", "status": "coded", "readiness": "assumptions", "video": L10N,
    "name": "Momentum candle through the EMA 9 and 15: a limit at its 50%, the stop beyond the candle, 1:2 (Delta gold "
            "and bitcoin, 15 minutes)",
    "markets": ["BTCUSD", "XAUUSD"], "timeframes": ["15m"],
    "summary": "What he does in his live gold and bitcoin sessions after a strong candle. He does not chase it: he waits for "
               "the price to come back to about half of that candle and enters there, with the stop just beyond the "
               "candle's far end, so the stop is half the size it would be in the running candle. A candle closing across "
               "the 9 EMA is his sign of momentum; his standing minimum reward is twice the risk.",
    "rules": [
        r("market", "I", [(L10N, "00:06:35"), (L10N, "01:10:58")], "He trades it live on gold (the CPI candle, in pips) and "
          "on bitcoin (the instruments are on screen).", "vaise to ye paraphekt entree kaindal hai"),
        r("timeframe", "E", [(L10N, "01:10:25")], "His bitcoin example is a 15-minute candle.",
          "15 minat kaa kaindal chaar minat men kloj karane vaalaa hai"),
        r("indicator", "E", [(L20O, "00:59:27")], "Two EMAs, 9 and 15 (asked for his EMA settings).", "9 end 15 do eeemae"),
        r("setup", "E", [(L03N, "00:09:04")], "A candle closing across the 9 EMA is momentum; while the price stays beyond "
          "the momentum candle's 50%, do not trade against it.", "kaaphee achchhaa 9 eeemae ko kros karake kloj kiyaa hai"),
        r("setup", "E", [(L03N, "00:07:06")], "A candle that closes through the zone, crossing the EMA, is the trade.",
          "kar detaa hai naa eeemae ko kros karake"),
        r("entry", "E", [(L10N, "01:09:16")], "No entry before the candle has closed.", "binaa kaindal klojing ke entree naheen karenge"),
        r("entry", "E", [(L10N, "00:06:35")], "Then wait for the price to come back to around the candle's 50% ...",
          "thoraa agar is kaindal kaa 50% ke ke"),
        r("entry", "E", [(L10N, "01:10:58")], "... 'if this candle's 50% comes, I enter with this candle's high as the stop'.",
          "et leest is kaindal kaa agar 50% aataa hai to phir main is kaindal ke haaee kaa stop los rakh ke yahaan pe entar karoongaa"),
        r("entry", "E", [(L10N, "01:10:40")], "Entering in the running candle would need a far bigger stop (500 points on "
          "bitcoin).", "agar yahaan pe raning kaindal men entar karenge to et leest stop los 500 point kaa"),
        r("stop", "E", [(L10N, "00:06:49")], "The stop just beyond the candle.", "stop los jast is kaindal ke oopar rahegaa"),
        r("target", "I", [(EP2, "00:14:20"), (EP1, "00:51:08")], "His standing risk-reward is 1:2 (or 1:3).",
          "kyonki meraa risk rivord 1:2 hotaa hai"),
        r("management", "I", [(EP1, "00:51:02")], "At most three trades a day (his rule for beginners in episode 1).",
          "teen tred aap kar sakate ho ej e biganar"),
        r("market", "A", [], "Delta Exchange's BTCUSD and XAUTUSD perpetuals, from the desk's real-time Delta minutes (he "
          "trades spot gold and bitcoin with a CFD broker)."),
        r("timeframe", "A", [], "15-minute candles for both (his bitcoin example; the size of the gold candle is not said)."),
        r("setup", "A", [], "A momentum candle: a body of at least 60% of its range and at least 1.5 times the average body of "
          "the 20 candles before it, opening on one side of both EMAs (9 and 15) and closing on the other side."),
        r("entry", "A", [], "A limit order at the midpoint of the candle's high and low, alive for the next three candles; "
          "not filled means no trade."),
        r("stop", "A", [], "The stop exactly at the candle's far end; the target twice the risk from the fill; at most three "
          "trades a day; one position at a time; intraday (bitcoin out by 23:55 UTC, gold at its 17:00 New York roll)."),
    ],
    "vague": [
        {"term": "a momentum (entry) candle", "at": (L10N, "00:06:35"),
         "why": "he never says how big; his examples are a news candle and a breakdown below every zone",
         "coded": "body at least 60% of the range and 1.5 times the recent average, across both EMAs"},
        {"term": "this candle's 50%", "at": (L10N, "01:10:58"),
         "why": "it could be half of the whole candle or half of its body", "coded": "half of the high-low range"},
        {"term": "the CPI candle", "at": (L10N, "00:06:54"),
         "why": "his gold example is the candle of a US inflation release; the desk has no news calendar",
         "coded": "any candle that qualifies, news or not"},
        {"term": "100-150 pips target", "at": (L10N, "00:09:26"),
         "why": "live targets are pips or the next zone, never a fixed multiple", "coded": "his 1:2 minimum"},
        {"term": "below all the zones", "at": (L10N, "01:10:25"),
         "why": "the bitcoin example's zones are drawn by eye", "coded": "the EMA 9 and 15 in place of the zones"},
    ],
    "unclear": ["How long does he wait for the 50% before giving up?",
                "Does he still take it when the candle is against the higher-timeframe trend?"],
    "claims": [],
    "examples": [
        {"at": (L10N, "00:06:35"), "date": "10 Nov 2026", "instrument": "gold (spot, XM)", "direction": "short",
         "setup": "the CPI release candle, a 300-pip fall in a minute", "entry": "around the candle's 50%, two lots at a time",
         "stop": "just above the candle", "target": "100-150 pips", "outcome": "not said"},
        {"at": (L10N, "01:10:58"), "date": "10 Nov 2026", "instrument": "bitcoin", "direction": "short",
         "setup": "a 15-minute breakdown below every zone after a 1,600-point fall", "entry": "at the candle's 50%",
         "stop": "the candle's high", "target": "not said", "outcome": "not taken while live (too extended)"},
    ],
    "duplicate_check": "Not in the library: NJ-30 limits at half of a fair value gap, BB-17 and CP-18 at half of an order "
                       "block (the last opposite candle before a move); none uses a momentum candle across the EMA 9/15.",
}

TR04 = {
    "id": "TR-04", "status": "coded", "readiness": "assumptions", "video": SCALP915,
    "name": "TR-01's EMA 9/15 scalp on three entry candles, on Delta gold and bitcoin (15 minutes)",
    "markets": ["BTCUSD", "XAUUSD"], "timeframes": ["15m"],
    "summary": "His best-known video (5.4 million views) teaches a 9 and 15 EMA scalp on Bank Nifty; the app has traded it "
               "as TR-01 on Bank Nifty since 9 Nov. In his live sessions he trades gold and bitcoin with the same two "
               "EMAs, and his bitcoin short shows the pin-bar entry on the 15-minute chart. TR-04 is TR-01's coded rules, "
               "unchanged, on Delta gold and bitcoin 15-minute candles: buy above a pin bar, a big bar or a candle "
               "crossing the EMA at the EMAs while both point up (mirrored for sells), stop at the candle's other end, 1:2.",
    "rules": [
        r("indicator", "E", [(L20O, "00:59:27")], "Live on gold and bitcoin he uses the same two EMAs, 9 and 15.",
          "9 end 15 do eeemae"),
        r("market", "I", [(L20O, "00:16:12")], "Gold on 15 minutes: a rejection at the EMA, his first scalp that session (the "
          "instrument is on screen; his 36-pip stop says gold).", "are yaar 15 minat pe yah eeemae pe rijekshan"),
        r("timeframe", "E", [(BTC15, "00:00:04")], "Bitcoin: a pin bar on the 15-minute chart, bought ...",
          "15 minat ke chaart p pan kaindal banaayaa gayaa"),
        r("stop", "E", [(BTC15, "00:00:22")], "... the stop at that candle's low.", "stopalos is kaindal ke lo"),
        r("setup", "E", [(SCALP915, "00:07:39")], "Trade the way the EMAs point (up for buys).",
          "daayarekshan is tarah se oopar kee taraph rahegaa"),
        r("entry", "E", [(SCALP915, "00:07:25")], "Three entry candles at the EMAs: a pin bar, a full-bodied candle with a light "
          "lower wick, or a big bar ...", "bilkul pee baar"),
        r("entry", "E", [(SCALP915, "00:10:58")], "... the third can also be a candle crossing both EMAs from below and "
          "closing above them.", "se em ko kros karake donon hee em e ko kros karake"),
        r("entry", "E", [(SCALP915, "00:08:33")], "Sells take the three opposite candles.",
          "mainne bataa diyaa seling ke lie jast isakaa apojit teen kaindal aapako phaaind aaut karanaa hai"),
        r("entry", "E", [(SCALP915, "00:07:44")], "Buy at the entry candle's high.", "jab bhee is kaindal"),
        r("stop", "E", [(SCALP915, "00:09:30")], "The stop at the candle's low and a 1:2 target.",
          "banaa lenaa aur kaindal lo kaisal rahegaa aapakaa aur 1:2 kaa aapakaa taaraget hogaa"),
        r("timeframe", "E", [(SCALP915, "00:08:46")], "5-minute candles for a trader of a few months; shorter ones later (the "
          "Bank Nifty version, TR-01).", "kiyaa ho kuchh maheene hue hain aapako treding karate hue to aapako chaat silekt karanaa hai 5"),
        r("market", "A", [], "Delta Exchange's BTCUSD and XAUTUSD perpetuals on 15-minute candles from the desk's real-time "
          "Delta minutes."),
        r("setup", "A", [], "As TR-01: trend up = EMA 9 above EMA 15 and both higher than three candles ago; 'at the EMAs' = "
          "the candle's low at or below the EMA 9 while its close stays above the EMA 15 (mirrored for sells)."),
        r("entry", "A", [], "As TR-01: pin bar = lower wick at least twice the body; big bar = green, a body of at least 60% of "
          "the range and at least the 20-candle average body; cross candle = open below the EMA 9, close above it. A stop "
          "order at the candle's high, alive for the next two candles."),
        r("management", "A", [], "As TR-01: stop at the candle's low, target 2R, up to four trades a day, none after two "
          "stops; intraday (bitcoin out by 23:55 UTC, gold at its 17:00 New York roll)."),
    ],
    "vague": [
        {"term": "enter at the candle's close", "at": (SCALP915, "00:09:25"),
         "why": "here he says to enter at the entry candle's close, where 07:44 says buy at its high",
         "coded": "the stop order at the high, as TR-01"},
        {"term": "which timeframe on gold", "at": (L20O, "00:16:12"),
         "why": "his lives move between 1, 3, 5 and 15-minute charts", "coded": "15 minutes, as his bitcoin short and this gold scalp"},
    ],
    "unclear": ["Does he use the same three-candle rule on gold, or only the EMA rejection?"],
    "claims": [],
    "examples": [
        {"at": (BTC15, "00:00:04"), "date": "10 Aug 2024 (upload)", "instrument": "bitcoin", "direction": "long",
         "setup": "a pin bar on the 15-minute chart", "entry": "market order", "stop": "the candle's low",
         "target": "booked by hand", "outcome": "a $59 profit as he shows it"},
    ],
    "duplicate_check": "TR-01 already trades these rules on Bank Nifty only; TD-02 (9/15 EMA cross with an SMI filter, gold and "
                       "bitcoin) and AB-06 (9/15 cross, Nifty) are crossover systems, not pullback entry candles.",
}

CODED = [TR02, TR03, TR04]

# ═════════════════════════════════════ not coded: rules incomplete or data missing ═══════════════════════════════

NOT_CODED = [
    {"id": "TR-05", "status": "blocked", "video": L10N, "cites": [(L10N, "01:09:43"), ("Jta4qVH7Vfs", "00:59:56"),
                                                                    ("MyPiQGYR4t8", "00:30:11"), ("zkLEJopG0WQ", "00:56:27")],
     "name": "Trend-line and zone breakdowns confirmed by a candle close (his live sessions)",
     "reason": "the trend lines and zones are drawn by eye, the targets are pips or the next zone, and he "
               "adds lots as the trade moves; no fixed entry, stop and exit to code"},
    {"id": "TR-06", "status": "blocked", "video": "byPdIG6fjy0", "cites": [("byPdIG6fjy0", "00:21:30"), ("XrGsQxthK3k", "00:31:13"),
                                                                             ("8MHoWYIX1f4", "01:30:24"), (L10N, "00:44:21")],
     "name": "An impulsive move's 50-61% pullback as the entry, the stop near 70% (his live sessions)",
     "reason": "which swing is 'the impulsive move' is picked by eye and the target is never fixed; the "
               "candle-sized version of the 50% entry is coded as TR-03"},
    {"id": "TR-07", "status": "blocked", "video": EP3, "cites": [(EP3, "00:06:23")],
     "name": "15-minute buying structure, then a 5-minute (or 1-minute) entry (episode 3)",
     "reason": "'structure' is not defined and there is no stop or target; the 5-minute part repeats TR-02"},
]

DUPLICATES = [
    {"id": "TR-01", "status": "duplicate", "video": SCALP915, "of": "TR-01",
     "name": "EMA 9/15 scalp on three entry candles, 1:2 (Bank Nifty)",
     "why": "the 11-channel study's Rs 10 lakh account has traded it on Bank Nifty since 9 Nov; his Master "
            "Scalping videos and most shorts trade the same method live. Not added again; TR-04 runs the same rules on Delta"},
]
