"""The ranking function — pure, additive, and able to explain itself.

WHY RANKING IS THE WHOLE PROBLEM
---------------------------------
The old search had none: Mongo returned natural order, so measured on production
`reliance` put RPOWER above RELIANCE, `tata` never reached TATAMOTORS at all, and `bank`
missed HDFCBANK and ICICIBANK. Finding the matches was never the hard part — ordering them
is.

EVERY COMPONENT IS INSPECTABLE
-------------------------------
`score()` returns the number AND the list of reasons that produced it, in the same spirit
as the desk's rejection ledger: a result that ranks oddly can be asked why rather than
guessed at. The API exposes the reasons behind a debug flag.

DEMOTION IS A SEPARATE AXIS FROM SCORE, AND THAT MATTERS
---------------------------------------------------------
2,457 symbols are searchable but only ~500 carry enough turnover for the desk's liquidity
pillar to pass them, and only ~508 have daily bars at all. Such a name must rank BELOW a
tradable one — but it must still be findable, because "this stock exists and here is why
the desk will not touch it" is the answer you need.

The first implementation expressed that as a large negative score, and it was wrong: a
penalty big enough to reliably demote is also big enough to drive the total below zero,
at which point the result is dropped entirely. Measured on the fixture, `balkrishna paper`
returned NOTHING — the match scored 476, then -300 for no bars and -250 for illiquidity
took it to -74 and it vanished. That is the silent failure this whole upgrade exists to
remove, reintroduced one layer down.

So demotion is now its own integer tier and results sort on `(demotion, -score)`. Ordering
within a tier is preserved, blocked names always fall below tradable ones, and nothing is
ever deleted by arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .aliases import dice, normalise, squash, tokens

# Match tiers. The gaps are deliberately wide so a weaker tier can never overtake a
# stronger one through boosts alone — an exact ticker always wins.
S_EXACT_SYMBOL = 1000.0
S_ALIAS_EXACT = 900.0
S_SQUASHED_NAME_EXACT = 850.0
S_SYMBOL_PREFIX = 700.0
S_NAME_WORD_PREFIX = 500.0
S_SYMBOL_CONTAINS = 380.0
S_NAME_CONTAINS = 300.0
S_FUZZY_MAX = 220.0

# Boosts. Small relative to the tier gaps: they order results WITHIN a tier.
B_NIFTY50 = 90.0
B_NIFTY100 = 55.0
B_NIFTY500 = 25.0
B_TRENDING = 60.0          # in today's screener top 50 by 1-month return
B_FULL_COVERAGE = 30.0
B_HAS_UNIVERSE_NAME = 15.0

# Demotion tiers — NOT scores. Higher means "sorts below everything less demoted".
D_CLEAN = 0
D_ILLIQUID = 1        # tradable, but the liquidity pillar would veto every signal
D_NO_BARS = 2         # nothing can be computed until a backfill runs
D_NOT_TRADABLE = 3    # no broker token: it can never be priced

FUZZY_FLOOR = 0.34         # below this a trigram match is noise, not a typo


@dataclass
class Hit:
    symbol: str
    score: float
    reasons: list[str] = field(default_factory=list)
    matched_on: str = ""
    # Sorted on BEFORE score. See the module docstring: expressing this as a negative
    # score deleted legitimate matches instead of demoting them.
    demotion: int = D_CLEAN


def _prefix_penalty(query: str, target: str) -> float:
    """A prefix match on a short ticker beats the same prefix on a long one.

    Typing `REL` should favour RELIANCE over RELIGAREBROKING: the shorter the remaining
    tail, the more likely that is the word you meant."""
    return min(80.0, 4.0 * max(0, len(target) - len(query)))


def score(rec, q_norm: str, q_squash: str, q_tokens: list[str],
          alias_symbol: str | None = None, trending_top: frozenset[str] = frozenset(),
          ) -> Hit:
    """Score one instrument against one query. Pure — no I/O, no globals."""
    hit = Hit(symbol=rec.symbol, score=0.0)
    if not q_squash:
        return hit

    sym_sq = rec.symbol_squashed
    name_sq = rec.name_squashed

    # ---- tier -------------------------------------------------------------------
    if sym_sq == q_squash:
        hit.score = S_EXACT_SYMBOL
        hit.matched_on = "symbol"
        hit.reasons.append(f"exact ticker {rec.symbol}")
    elif alias_symbol and alias_symbol == rec.symbol:
        hit.score = S_ALIAS_EXACT
        hit.matched_on = "alias"
        hit.reasons.append(f"known alias for {rec.symbol}")
    elif name_sq and name_sq == q_squash:
        hit.score = S_SQUASHED_NAME_EXACT
        hit.matched_on = "name"
        hit.reasons.append("full company name")
    elif sym_sq.startswith(q_squash):
        hit.score = S_SYMBOL_PREFIX - _prefix_penalty(q_squash, sym_sq)
        hit.matched_on = "symbol"
        hit.reasons.append(f"ticker starts with {q_squash}")
    elif _any_word_prefix(rec.name_tokens, q_tokens):
        hit.score = S_NAME_WORD_PREFIX - _prefix_penalty(q_squash, name_sq or q_squash)
        hit.matched_on = "name"
        hit.reasons.append("company name starts with what you typed")
    elif q_squash in sym_sq:
        hit.score = S_SYMBOL_CONTAINS
        hit.matched_on = "symbol"
        hit.reasons.append(f"ticker contains {q_squash}")
    elif name_sq and q_squash in name_sq:
        hit.score = S_NAME_CONTAINS
        hit.matched_on = "name"
        hit.reasons.append("company name contains what you typed")
    else:
        return hit                                   # fuzzy is scored by the caller

    _apply_context(hit, rec, trending_top)
    return hit


def score_fuzzy(rec, q_trigrams: set[str], trending_top: frozenset[str] = frozenset()) -> Hit:
    """Trigram similarity, used only when nothing matched literally.

    This is what turns `RELINCE` into RELIANCE. It is deliberately the lowest tier: a
    typo-corrected guess must never outrank something the user actually typed correctly."""
    hit = Hit(symbol=rec.symbol, score=0.0)
    sim = max(dice(q_trigrams, rec.symbol_trigrams), dice(q_trigrams, rec.name_trigrams))
    if sim < FUZZY_FLOOR:
        return hit
    hit.score = S_FUZZY_MAX * sim
    hit.matched_on = "fuzzy"
    hit.reasons.append(f"closest match ({sim:.0%} similar) — did you mean {rec.symbol}?")
    _apply_context(hit, rec, trending_top)
    return hit


def _any_word_prefix(name_tokens: list[str], q_tokens: list[str]) -> bool:
    """Does every typed word prefix some word of the name, in order?

    `hdfc ba` -> HDFC BANK. Requiring ALL typed words to land is what stops a single
    common word (`bank`) from dragging in every unrelated company."""
    if not q_tokens or not name_tokens:
        return False
    pos = 0
    for qt in q_tokens:
        found = False
        while pos < len(name_tokens):
            if name_tokens[pos].startswith(qt):
                found = True
                pos += 1
                break
            pos += 1
        if not found:
            return False
    return True


def _apply_context(hit: Hit, rec, trending_top: frozenset[str]) -> None:
    """Boosts and penalties — what orders results within a tier."""
    if "nifty50" in rec.indices:
        hit.score += B_NIFTY50
        hit.reasons.append("Nifty 50")
    elif "nifty100" in rec.indices:
        hit.score += B_NIFTY100
        hit.reasons.append("Nifty 100")
    elif "nifty500" in rec.indices:
        hit.score += B_NIFTY500
        hit.reasons.append("Nifty 500")

    if rec.symbol in trending_top:
        hit.score += B_TRENDING
        hit.reasons.append("among today's strongest movers")

    if rec.clean_name:
        hit.score += B_HAS_UNIVERSE_NAME

    if rec.illiquid:
        hit.demotion = max(hit.demotion, D_ILLIQUID)
        hit.reasons.append("below the turnover floor")
    if rec.no_bars:
        hit.demotion = max(hit.demotion, D_NO_BARS)
        hit.reasons.append("no daily bars")
    if not rec.tradable:
        hit.demotion = max(hit.demotion, D_NOT_TRADABLE)
        hit.reasons.append("no broker token — the desk cannot price it")


__all__ = ["Hit", "score", "score_fuzzy", "FUZZY_FLOOR",
           "S_EXACT_SYMBOL", "S_ALIAS_EXACT", "S_SYMBOL_PREFIX", "S_NAME_WORD_PREFIX",
           "D_CLEAN", "D_ILLIQUID", "D_NO_BARS", "D_NOT_TRADABLE"]
