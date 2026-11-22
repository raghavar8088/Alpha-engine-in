"""NSE corporate announcements as catalysts, with the exchange's own dissemination time.

Source: the app's nse_events collector writes NSE's announcement feed to
/data/intraday/nse_events/ann/YYYY-MM-DD.json.gz (rows: symbol, desc, an_dt, exchdisstime, t = dissemination time in
IST). The desk only READS those files. Local history: 1 Nov 2025 - 3 Nov 2026 (368 days), so any rule that needs
news can be tested historically only from November 2025; earlier days are "announcements unavailable".

MATERIAL is fixed in advance (pis/prereg.json): results and board outcomes, orders, deals, ratings, regulatory and
legal actions, takeover/stake disclosures and senior management changes. Routine filings (newspaper copies, trading
window notices, analyst-meet schedules, certificates, AGM notices, ESOP allotments) are never catalysts.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime

from .timeutil import IST

MATERIAL = {
    "Outcome of Board Meeting", "Integrated Filing- Financial", "Financial Result Updates", "Financial Results",
    "Clarification - Financial Results", "Reply to Clarification- Financial results", "Press Release",
    "Investor Presentation", "Bagging/Receiving of orders/contracts", "Acquisition", "Amalgamation/Merger",
    "Scheme of Arrangement", "Buyback", "Credit Rating", "Credit Rating- Revision", "Credit Rating- New",
    "Action(s) taken or orders passed", "Action(s) initiated or orders passed",
    "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company", "Disclosure of material issue",
    "Agreements", "Disclosure under SEBI Takeover Regulations", "Change in Management", "Resignation",
    "Resignation of Director/KMP/SMP", "Fraud/Default/Arrest", "Restructuring", "Delisting", "Open Offer",
    "Qualified Institutional Placement", "Preferential Issue", "Rights Issue", "Sale or disposal", "Joint Venture",
    "Corporate Insolvency Resolution Process",
}
# NOT catalysts: "Spurt in Volume", "Price movement", "News Verification" are the EXCHANGE asking a company about a
# move that already happened; counting them as news would reverse cause and effect.
KEYWORDS = ("financial result", "acquisition", "merger", "order", "rating", "buyback", "fund raising")
ROUTINE = ("newspaper", "trading window", "analysts/institutional", "certificate", "shareholders meeting",
           "record date", "esop", "allotment", "structural digital", "monitoring agency")


def is_material(desc: str | None) -> bool:
    d = (desc or "").strip()
    if d in MATERIAL:
        return True
    low = d.lower()
    if any(r in low for r in ROUTINE):
        return False
    return any(kw in low for kw in KEYWORDS)


def parse_rows(rows: list, symbols: set | None = None) -> list[dict]:
    out = []
    for r in rows:
        sym = r.get("symbol")
        if not sym or (symbols is not None and sym not in symbols):
            continue
        t = r.get("t")
        try:
            dt = datetime.fromisoformat(t) if t else None
        except ValueError:
            dt = None
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        out.append({"symbol": sym, "desc": r.get("desc"), "ts": dt.timestamp(), "at": dt.astimezone(IST).isoformat(),
                    "material": is_material(r.get("desc")), "seq": r.get("seq_id")})
    return out


def read_day(root: str, day) -> list | None:
    """Rows of one calendar day's file, or None if the file does not exist (= unavailable, not 'no news')."""
    p = os.path.join(root, "nse_events", "ann", f"{day.isoformat()}.json.gz")
    if not os.path.exists(p):
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            x = json.load(f)
    except (OSError, ValueError):
        return None
    return x.get("rows", []) if isinstance(x, dict) else x
