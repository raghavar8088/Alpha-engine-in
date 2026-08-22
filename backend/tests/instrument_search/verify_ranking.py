"""Verify the search ranks correctly — the queries that were measured failing on production.

Run:  python backend/tests/instrument_search/verify_ranking.py

Every case in `MUST_RANK_FIRST` is a query that was probed against the live system before
this upgrade and returned the wrong thing. They are the specification:

    reliance  ->  RPOWER, RELIANCE, RIIL          the company ranked SECOND
    RELI      ->  RELIGARE, RPOWER, ..., RELIANCE ranked FOURTH
    tata      ->  TCS, NPBET, TATAINVEST, ...     TATAMOTORS never appeared
    bank      ->  FEDERALBNK, PNB, ...            HDFCBANK and ICICIBANK never appeared
    RELINCE   ->  (nothing)                       one transposed letter, zero results

No Mongo, no Angel, no network: the index is built from a fixture that reproduces the real
shapes found in production, including the truncated broker names.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()

from app.services.instrument_search.aliases import dice, normalise, squash, tokens, trigrams
from app.services.instrument_search.index import InstrumentIndex, Record
from app.services.instrument_search.scoring import score, score_fuzzy

FAILURES: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ---- fixture: real shapes, including the truncated names the broker actually returns ----
# (symbol, broker_name, clean_name, indices, sector, turnover_cr, has_bars)
FIXTURE = [
    ("RELIANCE", "RELIANCE INDUSTRIES", "Reliance Industries Ltd.", ["nifty50", "nifty100", "nifty500"], "Oil Gas & Consumable Fuels", 840, True),
    ("RPOWER", "RELIANCE POWER LTD", "Reliance Power Ltd.", ["nifty500"], "Power", 120, True),
    ("RIIL", "RELIANCE INDUSTRIAL INFRA", "", [], "Power", 4, True),
    ("RELCHEMQ", "RELIANCE CHEMOTEX INDUST", "", [], "Textiles", 1, True),
    ("RELIGARE", "RELIGARE ENTERPRISES LTD", "", [], "Financial Services", 8, True),
    ("RELIABLE", "RELIABLE DATA SERVICES L", "", [], "IT", 0.4, False),
    ("TCS", "TATA CONSULTANCY SERV LT", "Tata Consultancy Services Ltd.", ["nifty50", "nifty100", "nifty500"], "IT", 620, True),
    ("TATAMOTORS", "TATA MOTORS LIMITED", "Tata Motors Ltd.", ["nifty50", "nifty100", "nifty500"], "Automobile", 710, True),
    ("TATASTEEL", "TATA STEEL LIMITED", "Tata Steel Ltd.", ["nifty50", "nifty100", "nifty500"], "Metals & Mining", 480, True),
    ("TATAPOWER", "TATA POWER CO LTD", "Tata Power Company Ltd.", ["nifty100", "nifty500"], "Power", 310, True),
    ("TATAINVEST", "TATA INVESTMENT CORP LTD", "", ["nifty500"], "Financial Services", 40, True),
    ("TATATECH", "TATA TECHNOLOGIES LTD", "Tata Technologies Ltd.", ["nifty500"], "IT", 55, True),
    ("HDFCBANK", "HDFC BANK LTD", "HDFC Bank Ltd.", ["nifty50", "nifty100", "nifty500"], "Financial Services", 950, True),
    ("ICICIBANK", "ICICI BANK LTD.", "ICICI Bank Ltd.", ["nifty50", "nifty100", "nifty500"], "Financial Services", 880, True),
    ("FEDERALBNK", "FEDERAL BANK LTD", "Federal Bank Ltd.", ["nifty100", "nifty500"], "Financial Services", 90, True),
    ("PNB", "PUNJAB NATIONAL BANK", "Punjab National Bank", ["nifty100", "nifty500"], "Financial Services", 130, True),
    ("UNIONBANK", "UNION BANK OF INDIA", "Union Bank of India", ["nifty500"], "Financial Services", 70, True),
    ("CANBK", "CANARA BANK", "Canara Bank", ["nifty100", "nifty500"], "Financial Services", 95, True),
    ("TMB", "TAMILNAD MERCANTILE BANK", "", [], "Financial Services", 3, True),
    ("ARE&M", "AMARA RAJA ENERGY MOB LTD", "Amara Raja Energy & Mobility Ltd.", ["nifty500"], "Automobile", 60, True),
    ("M&M", "MAHINDRA & MAHINDRA LTD", "Mahindra & Mahindra Ltd.", ["nifty50", "nifty100", "nifty500"], "Automobile", 700, True),
    ("M&MFIN", "M&M FINANCIAL SERVICES", "Mahindra & Mahindra Financial Services Ltd.", ["nifty500"], "Financial Services", 85, True),
    ("LT", "LARSEN & TOUBRO LTD.", "Larsen & Toubro Ltd.", ["nifty50", "nifty100", "nifty500"], "Construction", 760, True),
    ("BALKRISHNA", "BALKRISHNA PAPER MILLS L", "", [], "Paper", 0.3, False),
    ("GODREJCP", "GODREJ CONSUMER PRODUCTS", "Godrej Consumer Products Ltd.", ["nifty100", "nifty500"], "FMCG", 220, True),
    ("SBIN", "STATE BANK OF INDIA", "State Bank of India", ["nifty50", "nifty100", "nifty500"], "Financial Services", 900, True),
    ("HINDUNILVR", "HINDUSTAN UNILEVER LTD", "Hindustan Unilever Ltd.", ["nifty50", "nifty100", "nifty500"], "FMCG", 540, True),
    ("INFY", "INFOSYS LIMITED", "Infosys Ltd.", ["nifty50", "nifty100", "nifty500"], "IT", 800, True),
    ("NOTOKEN", "SOME UNLISTED THING LTD", "", [], "", 0.1, False),
]

MIN_TURNOVER_CR = 5.0


def build() -> InstrumentIndex:
    idx = InstrumentIndex()
    for sym, broker, clean, indices, sector, turn_cr, has_bars in FIXTURE:
        rec = Record(
            symbol=sym, broker_name=broker, clean_name=clean, sector=sector,
            indices=tuple(indices), tightest_index=(indices[0] if indices else ""),
            angel_token=None if sym == "NOTOKEN" else "1234",
            tradable=sym != "NOTOKEN",
            no_bars=not has_bars,
            turnover=turn_cr * 1e7, liquidity_unknown=False,
            illiquid=turn_cr < MIN_TURNOVER_CR,
            timeframes=("1m", "5m", "15m", "1h", "1d") if has_bars else (),
        )
        rec.symbol_squashed = squash(sym)
        name = rec.display_name
        rec.name_squashed = squash(name)
        rec.name_tokens = tokens(name)
        rec.symbol_trigrams = trigrams(sym)
        rec.name_trigrams = trigrams(name)
        idx.records[sym] = rec
        for tri in rec.symbol_trigrams | rec.name_trigrams:
            idx.trigram_postings.setdefault(tri, set()).add(sym)

    from app.services.instrument_search.aliases import CURATED
    idx.aliases = {normalise(k): v for k, v in CURATED.items() if v in idx.records}
    idx.built_at = 1e18                      # never stale during the test
    return idx


IDX = build()


def top(q, n=5, untradable=False):
    return [r.symbol for r, _ in IDX.search(q, limit=n, include_untradable=untradable)]


print("\n== the queries that were measured failing on production ==")
MUST_RANK_FIRST = [
    ("reliance", "RELIANCE", "ranked 2nd behind RPOWER"),
    ("RELI", "RELIANCE", "ranked 4th behind RELIGARE"),
    ("RELIANCE", "RELIANCE", "exact ticker"),
    ("hdfc bank", "HDFCBANK", "worked before, must keep working"),
    ("godrej consumer", "GODREJCP", "worked before, must keep working"),
]
for q, want, was in MUST_RANK_FIRST:
    got = top(q)
    check(f"{q!r} ranks {want} first", got and got[0] == want, f"was: {was} · now: {got}")

print("\n== queries that returned the wrong SET entirely ==")
tata = top("tata", 6)
check("'tata' reaches TATAMOTORS", "TATAMOTORS" in tata, str(tata))
check("'tata' reaches TATASTEEL", "TATASTEEL" in tata, str(tata))
bank = top("bank", 6)
check("'bank' reaches HDFCBANK", "HDFCBANK" in bank, str(bank))
check("'bank' reaches ICICIBANK", "ICICIBANK" in bank, str(bank))
check("'bank' puts a Nifty 50 name first", bank and bank[0] in ("HDFCBANK", "ICICIBANK", "SBIN"),
      str(bank))

print("\n== typo tolerance ==")
for typo, want in (("RELINCE", "RELIANCE"), ("INFOYS", "INFY"), ("HDFC BNK", "HDFCBANK")):
    got = top(typo, 4)
    check(f"{typo!r} still finds {want}", want in got, str(got))

print("\n== aliases: the tickers no rule can reach ==")
for q, want in (("amara raja", "ARE&M"), ("mahindra", "M&M"), ("larsen", "LT"),
                ("L&T", "LT"), ("sbi", "SBIN"), ("hul", "HINDUNILVR"),
                ("infosys", "INFY"), ("state bank", "SBIN")):
    got = top(q, 4)
    check(f"{q!r} -> {want}", got and got[0] == want, str(got))

print("\n== & and 'and' are the same thing ==")
check("'M&M' == 'M AND M'", top("M&M", 3) == top("M AND M", 3), f"{top('M&M',3)} vs {top('M AND M',3)}")
check("'M&MFIN' finds the finance arm", top("M&MFIN")[0] == "M&MFIN", str(top("M&MFIN")))

print("\n== truncated broker names are still searchable ==")
check("'balkrishna paper' finds BALKRISHNA (name cut at 'MILLS L')",
      "BALKRISHNA" in top("balkrishna paper", 4), str(top("balkrishna paper", 4)))

print("\n== untradable and illiquid are ranked down, not hidden by accident ==")
check("a name with no broker token is excluded by default", "NOTOKEN" not in top("some unlisted", 5))
check("...but findable when explicitly asked for",
      "NOTOKEN" in top("some unlisted", 5, untradable=True), str(top("some unlisted", 5, untradable=True)))
reli = top("reli", 8)
check("illiquid RELIABLE ranks below liquid RELIANCE",
      reli.index("RELIANCE") < reli.index("RELIABLE") if "RELIABLE" in reli else True, str(reli))

print("\n== hostile input does not crash or wildcard ==")
for q in ["(", "[", ".*", "a{100000}", "\\", "^$", "?" * 80, ""]:
    try:
        got = IDX.search(q, limit=3)
        wild = len(got) > 0 and q in ("(", "[", ".*", "\\", "^$")
        check(f"{q[:12]!r} handled safely", not wild, f"{len(got)} results")
    except Exception as exc:
        check(f"{q[:12]!r} handled safely", False, f"{type(exc).__name__}: {exc}")

print("\n== the scoring primitives ==")
check("dice is symmetric", dice(trigrams("RELIANCE"), trigrams("RELINCE"))
      == dice(trigrams("RELINCE"), trigrams("RELIANCE")))
check("dice of identical strings is 1.0", dice(trigrams("TCS"), trigrams("TCS")) == 1.0)
check("normalise folds & to AND", normalise("M&M") == "M AND M", normalise("M&M"))
check("squash removes separators", squash("HDFC BANK") == "HDFCBANK", squash("HDFC BANK"))
check("tokens drop corporate noise",
      tokens("RELIANCE INDUSTRIES LIMITED") == ["RELIANCE", "INDUSTRIES"],
      str(tokens("RELIANCE INDUSTRIES LIMITED")))
check("tokens keep a name that is ONLY noise", tokens("LTD") == ["LTD"], str(tokens("LTD")))

print("\n== an exact ticker can never be outranked by boosts ==")
# TATAPOWER is Nifty 100; TCS is Nifty 50 and its name contains "TATA". Typing the exact
# ticker must still win.
check("'TATAPOWER' beats the Nifty-50 name match", top("TATAPOWER")[0] == "TATAPOWER",
      str(top("TATAPOWER")))

print(f"\n{'ALL CHECKS PASSED' if not FAILURES else 'FAILURES: ' + '; '.join(FAILURES)}")
sys.exit(1 if FAILURES else 0)
