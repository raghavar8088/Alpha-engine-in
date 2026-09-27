"""Fundamentals for an Indian listed company, read from screener.in.

WHY SCRAPE, AND WHY THIS SOURCE
screener.in publishes the numbers an Indian equity actually gets judged on — ROCE,
promoter holding and its trend, borrowings against reserves, cash from operations
against reported profit, and 10-year compounded sales/profit growth. The Yahoo feed
this app already has (app.services.stock_fundamentals) carries none of that with any
reliability for NSE names, which is why this is a second source rather than a
replacement: Yahoo backs the Bullish Stocks screen, this backs the rating.

There is no public API, so the company page is fetched and parsed. Two things make
that defensible rather than reckless:
  * robots.txt allows /company/<SYMBOL>/ — only /user/*, the sort/page/search query
    forms and /company/source/quarter/* are disallowed, and none are touched here.
  * The numbers are quarterly-reported, so they are cached for a day and a repeat
    ask costs nothing. Requests are paced and run at most two at a time.

PARSING WITHOUT A DEPENDENCY
backend/requirements.txt has httpx and no HTML parser, and adding one would mean a
rebuilt image before this module could run at all. The page is regular enough not to
need one: the ratio list is <li><span class="name">..</span><span class="number">..
</span></li>, and every statement is a plain <table> inside a <section> with a known
id. So it is parsed with stdlib re + html.unescape.

That makes the parser the fragile part, by construction. Every field is therefore
optional, parse_company never raises on a missing block, and what could not be read
is reported to the caller as `missing` rather than defaulted to zero — a zero here
would read as "this company earns nothing", which is a different and much worse
claim than "screener did not give us this".
"""

import asyncio
import html as _html
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.core.db import screener_fundamentals_collection

logger = logging.getLogger("screener_in")

BASE = "https://www.screener.in"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
CACHE_HOURS = 24          # the underlying numbers move once a quarter
PACE_SECONDS = 1.2        # between live fetches, so a 30-symbol paste stays polite
MAX_CONCURRENCY = 2

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class ScreenerError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


# ── symbol handling ──────────────────────────────────────────────────────────────


def normalise_symbol(raw: str) -> str:
    """'nse:reliance ', 'RELIANCE.NS', ' reliance' -> 'RELIANCE'.

    screener.in keys its company URLs on the NSE symbol for listed names (and on the
    BSE scrip code for BSE-only ones, which a user pasting a code still reaches).
    """
    s = (raw or "").strip().upper()
    s = re.sub(r"^(NSE|BSE|NSE_EQ|BSE_EQ)[:\-]", "", s)
    s = re.sub(r"\.(NS|BO)$", "", s)
    return re.sub(r"[^A-Z0-9&-]", "", s)


def split_symbols(text: str) -> list[str]:
    """Accept whatever the user pasted: commas, newlines, tabs, spaces, or a mix."""
    out: list[str] = []
    seen: set[str] = set()
    for tok in re.split(r"[,\n\r\t;|]+| +", text or ""):
        sym = normalise_symbol(tok)
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


# ── tiny HTML helpers ────────────────────────────────────────────────────────────


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _num(raw) -> float | None:
    """'16,59,089' -> 1659089.0 ; '-11%' -> -11.0 ; '' -> None.

    Indian digit grouping means a comma is never a decimal separator here.
    """
    if raw is None:
        return None
    s = _html.unescape(str(raw)).replace(",", "").replace("%", "")
    s = s.replace("₹", "").replace("Cr.", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _rows(table_html: str) -> list[list[str]]:
    return [[_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S)]


def _section_table(page: str, section_id: str) -> list[list[str]]:
    m = re.search(rf'<section[^>]*id="{section_id}".*?<table[^>]*>(.*?)</table>', page, re.S)
    return _rows(m.group(1)) if m else []


def _labelled(rows: list[list[str]]) -> dict[str, list]:
    """A screener statement table -> {'Sales': [...], 'Net Profit': [...]}.

    The label carries a trailing '+' where the row expands; it is stripped so callers
    can look a row up by the name a person would use.
    """
    out: dict[str, list] = {}
    for r in rows[1:]:
        if len(r) < 2:
            continue
        key = re.sub(r"\s*\+$", "", r[0]).strip()
        if key:
            out[key] = [_num(c) for c in r[1:]]
    return out


def _periods(rows: list[list[str]]) -> list[str]:
    return list(rows[0][1:]) if rows and rows[0] else []


# ── parsing ──────────────────────────────────────────────────────────────────────


def parse_company(page: str) -> dict:
    """Everything the rating needs, with `missing` naming what could not be read."""
    data: dict = {"missing": []}

    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    data["name"] = _text(m.group(1)) if m else None

    m = re.search(r'<div class="sub show-more-box about">(.*?)</div>', page, re.S)
    data["about"] = _text(m.group(1))[:600] if m else None

    # Sector/industry come from the /market/ breadcrumb links, each tagged by a title
    # attribute. They are kept because the rating needs them: a bank's balance sheet
    # and cash flow mean something entirely different from a manufacturer's.
    taxonomy = {t: _text(v) for t, v in re.findall(
        r'<a href="/market/[^"]*"[^>]*title="([^"]+)"[^>]*>(.*?)</a>', page, re.S)}
    data["sector"] = taxonomy.get("Sector") or taxonomy.get("Broad Sector")
    data["industry"] = taxonomy.get("Industry") or taxonomy.get("Broad Industry")

    # ── headline ratios ──────────────────────────────────────────────────────────
    ratios: dict[str, float | None] = {}
    m = re.search(r'<ul[^>]*id="top-ratios".*?</ul>', page, re.S)
    if m:
        for li in re.findall(r"<li[^>]*>(.*?)</li>", m.group(0), re.S):
            name = re.search(r'<span class="name">(.*?)</span>', li, re.S)
            nums = re.findall(r'<span class="number">(.*?)</span>', li, re.S)
            if not name or not nums:
                continue
            key = _text(name.group(1))
            if key == "High / Low" and len(nums) >= 2:
                ratios["High"], ratios["Low"] = _num(nums[0]), _num(nums[1])
            else:
                ratios[key] = _num(nums[0])
    else:
        data["missing"].append("headline ratios")
    data["ratios"] = ratios

    # ── compounded growth / ROE range tables ─────────────────────────────────────
    ranges: dict[str, dict] = {}
    for t in re.findall(r'<table class="ranges-table">(.*?)</table>', page, re.S):
        rows = _rows(t)
        if not rows or not rows[0]:
            continue
        ranges[rows[0][0]] = {r[0].rstrip(":"): _num(r[1]) for r in rows[1:] if len(r) >= 2}
    if not ranges:
        data["missing"].append("compounded growth")
    data["ranges"] = ranges

    # ── statements ───────────────────────────────────────────────────────────────
    for key, sec in (("profit_loss", "profit-loss"), ("balance_sheet", "balance-sheet"),
                     ("cash_flow", "cash-flow"), ("ratios_table", "ratios"),
                     ("quarters", "quarters")):
        rows = _section_table(page, sec)
        data[key] = _labelled(rows)
        data[f"{key}_periods"] = _periods(rows)
        if not rows:
            data["missing"].append(sec.replace("-", " "))

    # ── shareholding (quarterly trend) ───────────────────────────────────────────
    m = re.search(r'<div id="quarterly-shp".*?<table[^>]*>(.*?)</table>', page, re.S)
    if m:
        rows = _rows(m.group(1))
        data["shareholding"] = _labelled(rows)
        data["shareholding_periods"] = _periods(rows)
    else:
        data["shareholding"], data["shareholding_periods"] = {}, []
        data["missing"].append("shareholding")

    # ── screener's own machine-generated pros/cons ───────────────────────────────
    def bullets(cls: str) -> list[str]:
        mm = re.search(rf'<div class="{cls}"[^>]*>(.*?)</div>', page, re.S)
        if not mm:
            return []
        return [_text(li) for li in re.findall(r"<li[^>]*>(.*?)</li>", mm.group(1), re.S) if _text(li)]

    data["pros"] = bullets("pros")
    data["cons"] = bullets("cons")
    return data


# ── fetching ─────────────────────────────────────────────────────────────────────


async def _get(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url)
    except httpx.HTTPError as exc:
        raise ScreenerError(f"screener.in unreachable: {exc}") from exc
    if r.status_code == 404:
        return None
    if r.status_code == 429:
        raise ScreenerError("screener.in is rate-limiting this IP — try again in a minute")
    if r.status_code >= 400:
        raise ScreenerError(f"screener.in returned HTTP {r.status_code}")
    return r.text


async def fetch_company(symbol: str, client: httpx.AsyncClient | None = None) -> dict:
    """Consolidated numbers where the company reports them, else standalone.

    Consolidated is the right default — it is the whole group including subsidiaries —
    but a company without subsidiaries has no consolidated page at all, so standalone
    is the fallback rather than an error. Which basis was used is recorded, because
    the two are not comparable.
    """
    own = client is None
    c = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                    headers=BROWSER_HEADERS)
    try:
        basis = "consolidated"
        page = await _get(c, f"{BASE}/company/{symbol}/consolidated/")
        if page is None:
            basis = "standalone"
            page = await _get(c, f"{BASE}/company/{symbol}/")
        if page is None:
            raise ScreenerError(f"no company page on screener.in for '{symbol}'")

        parsed = parse_company(page)
        # A consolidated URL can exist yet carry no statements; standalone then has them.
        if basis == "consolidated" and not parsed.get("profit_loss"):
            alt = await _get(c, f"{BASE}/company/{symbol}/")
            if alt:
                alt_parsed = parse_company(alt)
                if alt_parsed.get("profit_loss"):
                    basis, parsed = "standalone", alt_parsed

        parsed["basis"] = basis
        parsed["symbol"] = symbol
        parsed["source_url"] = f"{BASE}/company/{symbol}/" + ("consolidated/" if basis == "consolidated" else "")
        parsed["fetched_at"] = datetime.now(timezone.utc)
        return parsed
    finally:
        if own:
            await c.aclose()


async def get_fundamentals(symbol: str, force: bool = False,
                           client: httpx.AsyncClient | None = None) -> dict:
    """Cached for CACHE_HOURS. `force` refetches and overwrites."""
    symbol = normalise_symbol(symbol)
    if not symbol:
        raise ScreenerError("empty symbol")

    if not force:
        doc = await screener_fundamentals_collection.find_one({"_id": symbol})
        if doc and doc.get("fetched_at"):
            at = doc["fetched_at"]
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - at < timedelta(hours=CACHE_HOURS):
                doc["cached"] = True
                return doc

    data = await fetch_company(symbol, client=client)
    data["cached"] = False
    await screener_fundamentals_collection.replace_one(
        {"_id": symbol}, {**data, "_id": symbol}, upsert=True)
    return data


async def get_many(symbols: list[str], force: bool = False) -> dict:
    """Fetch a pasted list, at most MAX_CONCURRENCY live requests at a time.

    A symbol that fails returns its error rather than sinking the batch — one bad
    ticker in a pasted list of thirty must not cost the other twenty-nine.
    """
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    out: dict = {}

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                 headers=BROWSER_HEADERS) as client:
        async def one(sym: str) -> None:
            async with sem:
                try:
                    data = await get_fundamentals(sym, force=force, client=client)
                    out[sym] = data
                    if not data.get("cached"):
                        await asyncio.sleep(PACE_SECONDS)
                except ScreenerError as exc:
                    out[sym] = exc
                except Exception as exc:                      # parser surprise
                    logger.exception("screener parse failed for %s", sym)
                    out[sym] = ScreenerError(f"could not read screener.in page: {exc}")

        await asyncio.gather(*(one(s) for s in symbols))
    return out
