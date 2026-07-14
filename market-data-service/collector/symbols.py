# Index quotes come from Dhan (see collector/dhan_index_client.py), not NSE's public
# niftyindices.com feed used through Phase 1 — that feed was found frozen months in the
# past (its own payload carried a January timestamp while checked live in July), so
# every index on it was silently wrong, not just occasionally stale. Dhan is already
# the authoritative price source everywhere else on this platform.
#
# These are the 5 indices Dhan lists as tradeable instruments (matches the
# `instruments` collection / options-chain universe). NSE's old list also included
# "NIFTY IT" / "NIFTY 100" / "NIFTY MIDCAP 100" sub-indices Dhan has no equivalent
# for — dropped rather than left on the broken feed with no replacement.
INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"]

EQUITY_SYMBOLS: list[str] = []

WATCHLIST = INDEX_SYMBOLS + EQUITY_SYMBOLS
