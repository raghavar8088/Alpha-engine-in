"""Build the sector map the Premium Intraday desk ships with (pis/data/sector_map.json).

Sources, both public:
  - niftyindices.com constituent files (downloaded 22 Nov 2026 to D:/premium_intraday_data/raw/niftyindices):
    ind_nifty500list.csv gives NSE's "Industry" for 500 stocks; the sectoral index lists give membership.
  - D:/intraday_ai_data/exports/sectors.json: the app's own symbol -> NSE industry table (stock_universe.sector),
    used for the stocks the Nifty 500 list does not carry.

Why banks are split out: NSE's Industry column puts banks, NBFCs, insurers, AMCs and exchanges together as
"Financial Services". A morning read of "banks are leading" needs the banks on their own, measured against NIFTY BANK.
A stock is a bank if it is in NIFTY BANK, NIFTY PSU BANK or NIFTY PRIVATE BANK, or its name ends in "Bank Ltd."
(small finance banks such as AU, Equitas, Ujjivan are banks too).

Each sector reads against the NSE sectoral index that covers it (the same pairing as the app's
intraday_universe.SECTOR_INDEX, with banks moved to NIFTYBANK). A sector with no index is measured from its
constituents only.

Run:  python build_sector_map.py   (writes ../../../premium-intraday-service/pis/data/sector_map.json)
"""
import csv
import json
import os
from pathlib import Path

RAW = Path("D:/premium_intraday_data/raw/niftyindices")
APP_SECTORS = Path("D:/intraday_ai_data/exports/sectors.json")
OUT = Path(__file__).resolve().parents[3] / "premium-intraday-service" / "pis" / "data" / "sector_map.json"

# NSE industry -> (our sector label, benchmark index or None)
INDUSTRY = {
    "Financial Services": ("Financial Services", "FINNIFTY"),
    "Information Technology": ("IT", "NIFTYIT"),
    "Automobile and Auto Components": ("Auto", "NIFTYAUTO"),
    "Healthcare": ("Healthcare", "NIFTYPHARMA"),
    "Fast Moving Consumer Goods": ("FMCG", "NIFTYFMCG"),
    "Metals & Mining": ("Metals & Mining", "NIFTYMETAL"),
    "Oil Gas & Consumable Fuels": ("Energy & Power", "NIFTYENERGY"),
    "Power": ("Energy & Power", "NIFTYENERGY"),
    "Capital Goods": ("Capital Goods & Infra", "NIFTYINFRA"),
    "Construction": ("Capital Goods & Infra", "NIFTYINFRA"),
    "Services": ("Capital Goods & Infra", "NIFTYINFRA"),
    "Telecommunication": ("Telecom", "NIFTYINFRA"),
    "Construction Materials": ("Chemicals & Materials", "NIFTYCOMMODITIES"),
    "Chemicals": ("Chemicals & Materials", "NIFTYCOMMODITIES"),
    "Consumer Durables": ("Consumer", "NIFTYCONSUMPTION"),
    "Consumer Services": ("Consumer", "NIFTYCONSUMPTION"),
    "Textiles": ("Consumer", "NIFTYCONSUMPTION"),
    "Realty": ("Realty", "NIFTYREALTY"),
    "Media Entertainment & Publication": ("Media", "NIFTYMEDIA"),
    "Diversified": ("Diversified", None),
    "Forest Materials": ("Chemicals & Materials", "NIFTYCOMMODITIES"),
    "Utilities": ("Energy & Power", "NIFTYENERGY"),
}
BANK_LISTS = ("ind_niftybanklist.csv", "ind_niftypsubanklist.csv", "ind_nifty_privatebanklist.csv")


def rows(name):
    with open(RAW / name, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    banks = set()
    for fn in BANK_LISTS:
        banks |= {r["Symbol"].strip() for r in rows(fn)}
    industry, names = {}, {}
    for r in rows("ind_nifty500list.csv"):
        industry[r["Symbol"].strip()] = r["Industry"].strip()
        names[r["Symbol"].strip()] = r["Company Name"].strip()
    app = json.loads(APP_SECTORS.read_text()) if APP_SECTORS.exists() else {}
    for sym, ind in app.items():
        industry.setdefault(sym, ind)
    out, unmapped = {}, []
    for sym, ind in sorted(industry.items()):
        is_bank = sym in banks or names.get(sym, "").lower().endswith("bank ltd.")
        if is_bank:
            out[sym] = {"sector": "Banks", "index": "NIFTYBANK", "industry": ind}
            continue
        sec = INDUSTRY.get(ind)
        if sec is None:
            unmapped.append((sym, ind))
            if ind.lower() != "unclassified":      # unclassified small caps never reach the liquid universe
                out[sym] = {"sector": "Other", "index": None, "industry": ind}
        else:
            out[sym] = {"sector": sec[0], "index": sec[1], "industry": ind}
    index_members = {}
    for fn in sorted(os.listdir(RAW)):
        if fn.endswith(".csv") and fn not in ("ind_nifty500list.csv",):
            index_members[fn[:-4]] = sorted(r["Symbol"].strip() for r in rows(fn))
    doc = {
        "built": "2026-11-22",
        "sources": {
            "niftyindices": "https://www.niftyindices.com/IndexConstituent/<list>.csv (downloaded 2026-11-22)",
            "app_industry_table": "stock_universe.sector export (D:/intraday_ai_data/exports/sectors.json)",
        },
        "rule": "banks = NIFTY BANK / PSU BANK / PRIVATE BANK members or names ending 'Bank Ltd.'; "
                "others by NSE Industry -> sector label and sectoral index",
        "symbols": out,
        "index_members": index_members,
        "unmapped": unmapped,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True))
    from collections import Counter
    print("symbols", len(out), "banks", sum(1 for v in out.values() if v["sector"] == "Banks"),
          "unmapped", len(unmapped), unmapped[:10])
    print(Counter(v["sector"] for v in out.values()).most_common())


if __name__ == "__main__":
    main()
