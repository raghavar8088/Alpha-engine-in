"""Angel One's own reports, imported into Angel One Commodity Live Trading Data (2026-10-19).

Angel's API returns TODAY's session only, so anything older comes from reports the owner
downloads from Angel One. Two kinds are understood, from .xlsx or .csv:

  P&L report      (Angel One -> Reports -> P&L; sheets "Equity P&L" and "F&O P&L") - one row
                  per closed position over a DATE RANGE: quantity, average buy / sell, gross P&L
                  and Angel's ACTUAL charges by component, and the net. It has NO trade dates,
                  so it is kept as a PERIOD record: it counts in lifetime totals and its closed
                  positions are listed with Angel's exact charges, but it is never spread over
                  individual days (that would be inventing a daily split) and it carries no
                  capital, so no ROI. It does not say which side opened a position either - a
                  long bought at 21 and sold at 210 and a short sold at 210 and bought back at 21
                  read the same - so no long / short split is made from it.
  trade history   one row per trade with its date - handed to angel_commodity_ledger's import,
                  which places each trade on its day.

Only commodity rows are kept (MCX instruments: OPTFUT / FUTCOM / OPTCOM, or a known MCX
underlying); NSE equity and F&O rows in the same report are ignored. The client's name, id and
PAN in the report header are never stored.

A report is counted in the lifetime total only when no day inside its period is already
recorded one by one (captured live or imported from a trade history) and it does not overlap a
report already counted - an undated total cannot be netted against dated days.

.xlsx is read with the standard library (it is zipped XML), so no spreadsheet package is needed.
"""

from __future__ import annotations

import base64
import csv
import io
import re
import statistics
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from app.core.db import db

statements = db["acl_statements"]

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
_DATE_FMT_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47}
COMMODITY_TYPES = {"OPTFUT", "FUTCOM", "OPTCOM"}
# Angel's column -> this page's charge component ("STT" on a commodity row is CTT; "Turnover
# Tax" and "Exchange Service Tax" are the exchange's transaction charge)
CHARGE_COLS = {"brokerage": "brokerage", "gst": "gst", "exchange service tax": "exchange", "turnover tax": "exchange",
               "sebi charges": "sebi", "stamp duty": "stamp", "stt": "ctt", "ctt": "ctt", "other charges": "other",
               "ipft charges": "ipft"}
CHARGE_KEYS = ("brokerage", "exchange", "ctt", "stamp", "sebi", "gst", "other", "ipft")


# ── reading .xlsx without third-party packages ──────────────────────────────────


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(data: bytes) -> dict[str, list[list[str | None]]]:
    """{sheet name: rows of cell text}. Date-formatted numbers come back as YYYY-MM-DD HH:MM:SS."""
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    date_styles: set[int] = set()
    if "xl/styles.xml" in names:
        st = ET.fromstring(z.read("xl/styles.xml"))
        fmts = st.find("m:numFmts", NS)
        custom = {int(f.get("numFmtId")): (f.get("formatCode") or "").lower()
                  for f in (fmts.findall("m:numFmt", NS) if fmts is not None else [])}
        xfs = st.find("m:cellXfs", NS)
        for i, xf in enumerate(xfs.findall("m:xf", NS) if xfs is not None else []):
            fid = int(xf.get("numFmtId") or 0)
            code = custom.get(fid, "")
            if fid in _DATE_FMT_IDS or (code and any(c in code for c in ("yy", "dd", "mmm"))):
                date_styles.add(i)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", NS)}
    out: dict[str, list[list[str | None]]] = {}
    for sh in wb.find("m:sheets", NS).findall("m:sheet", NS):
        t = target[sh.get(f"{{{NS['r']}}}id")].lstrip("/")
        path = t if t.startswith("xl/") else f"xl/{t}"
        rows: list[list[str | None]] = []
        for row in ET.fromstring(z.read(path)).iter(f"{{{NS['m']}}}row"):
            vals: dict[int, str | None] = {}
            for c in row.findall("m:c", NS):
                typ, style = c.get("t"), int(c.get("s") or 0)
                v = c.find("m:v", NS)
                if typ == "s" and v is not None:
                    text = shared[int(v.text)]
                elif typ == "inlineStr":
                    text = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                elif v is not None:
                    text = v.text
                    if typ not in ("str", "b", "e") and style in date_styles:
                        try:
                            text = (datetime(1899, 12, 30) + timedelta(days=float(text))).strftime("%Y-%m-%d %H:%M:%S")
                        except (TypeError, ValueError):
                            pass
                else:
                    text = None
                vals[_col(c.get("r"))] = text
            if vals:
                rows.append([vals.get(i) for i in range(max(vals) + 1)])
        out[sh.get("name")] = rows
    return out


def rows_to_csv(rows: list[list[str | None]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(["" if x is None else x for x in r])
    return buf.getvalue()


# ── Angel's P&L report ──────────────────────────────────────────────────────────


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _ddmmyyyy(v) -> str | None:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(v or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


SCRIP_RE = re.compile(r"^(OPTFUT|FUTCOM|OPTCOM|FUTIDX|OPTIDX|OPTSTK|FUTSTK)\s+([A-Z0-9&]+)\s+(\d{4}-\d{2}-\d{2})(?:\s+([\d.]+)\s+(CE|PE))?",
                      re.IGNORECASE)


def parse_scrip(s: str) -> dict:
    """'OPTFUT CRUDEOILM 2026-10-15 8650.00 PE' -> instrument, underlying, expiry, strike, type."""
    m = SCRIP_RE.match((s or "").strip())
    if not m:
        return {"instrument": None, "underlying": (s or "").split(" ")[0].upper(), "expiry": None, "strike": None, "kind": None}
    inst, und, exp, strike, kind = m.groups()
    return {"instrument": inst.upper(), "underlying": und.upper(), "expiry": exp,
            "strike": float(strike) if strike else None, "kind": (kind or "FUT").upper()}


def _is_commodity(p: dict) -> bool:
    if p["instrument"] in COMMODITY_TYPES:
        return True
    if p["instrument"] in ("FUTIDX", "OPTIDX", "OPTSTK", "FUTSTK"):
        return False
    try:
        from app.services.commodity_positions import CONTRACT_SPEC, SCAN_FAMILY
        return p["underlying"] in CONTRACT_SPEC or p["underlying"] in SCAN_FAMILY
    except Exception:  # noqa: BLE001
        return False


def _lots(underlying: str, qty: float) -> float | None:
    try:
        from app.services.commodity_positions import broker_order_qty
        lot = broker_order_qty(underlying)
    except Exception:  # noqa: BLE001
        lot = None
    return round(qty / lot, 2) if lot else None


SUMMARY_KEYS = {"total gross pnl": "gross", "net pnl": "net", **{f"total {k}": v for k, v in CHARGE_COLS.items()}}


def parse_pnl_report(sheets: dict[str, list[list]]) -> dict | None:
    """The commodity rows of Angel's P&L report, or None if this is not one.

    Totals are Angel's own summary lines when every position on that sheet is a commodity
    (they are exact; the per-row charges are rounded to the paisa), else the commodity rows'
    sums."""
    period_from = period_to = downloaded = None
    rows_out: list[dict] = []
    found = False
    totals = {"gross": 0.0, "net": 0.0, **{k: 0.0 for k in CHARGE_KEYS}}
    sources: list[str] = []
    skipped = 0
    for name, rows in sheets.items():
        header = None
        summary: dict[str, float] = {}
        sheet_rows: list[dict] = []
        sheet_skipped = 0
        for r in rows:
            cells = ["" if x is None else str(x).strip() for x in r]
            if not any(cells):
                continue
            key = cells[0].lower()
            second = cells[1] if len(cells) > 1 else ""
            if key == "from date":
                period_from = period_from or _ddmmyyyy(second)
            elif key == "to date":
                period_to = period_to or _ddmmyyyy(second)
            elif key == "date of download":
                downloaded = downloaded or _ddmmyyyy(second)
            elif key in SUMMARY_KEYS and header is None and second:
                comp = SUMMARY_KEYS[key]
                summary[comp] = round(summary.get(comp, 0.0) + _num(second), 2)
            if key == "scrip symbol":
                cols = [c.lower() for c in cells]
                header = cols if any(c in cols for c in ("gross pnl", "net pnl", "intraday pnl")) else None
                found = found or header is not None
                continue
            if key == "total" and header:
                header = None
                continue
            if header and key not in ("", "disclaimer"):
                rec = dict(zip(header, cells))
                p = parse_scrip(rec.get("scrip symbol", ""))
                if not _is_commodity(p):
                    sheet_skipped += 1
                    continue
                charges: dict[str, float] = {}
                for col, comp in CHARGE_COLS.items():
                    if col in rec:
                        charges[comp] = round(charges.get(comp, 0.0) + _num(rec[col]), 2)
                gross = _num(rec.get("gross pnl"))
                net_key = next((k for k in ("net pnl", "intraday pnl") if k in rec), None)
                avg_buy, avg_sell = _num(rec.get("avg buy price")), _num(rec.get("avg sell price"))
                qty = _num(rec.get("quantity"))
                sheet_rows.append({
                    "scrip": rec.get("scrip symbol"), **p, "qty": qty, "lots": _lots(p["underlying"], qty),
                    "avg_buy": avg_buy, "buy_value": _num(rec.get("buy price") or rec.get("buy value")),
                    "avg_sell": avg_sell, "sell_value": _num(rec.get("sell price") or rec.get("sell value")),
                    "points": round(avg_sell - avg_buy, 2), "gross": gross, "charges": charges,
                    "charges_total": round(sum(charges.values()), 2),
                    "net": _num(rec.get(net_key)) if net_key else round(gross - sum(charges.values()), 2),
                    "sheet": name, "seq": len(rows_out) + len(sheet_rows)})
        skipped += sheet_skipped
        rows_out.extend(sheet_rows)
        if not sheet_rows:
            continue
        if summary and not sheet_skipped and "net" in summary:
            for k in totals:
                totals[k] += summary.get(k, 0.0)
            sources.append("angel-summary")
        else:
            totals["gross"] += sum(x["gross"] for x in sheet_rows)
            totals["net"] += sum(x["net"] for x in sheet_rows)
            for x in sheet_rows:
                for k, v in x["charges"].items():
                    totals[k] = totals.get(k, 0.0) + v
            sources.append("row-sums")
    if not found:
        return None
    charges = {k: round(totals.get(k, 0.0), 2) for k in CHARGE_KEYS}
    return {"kind": "pnl-report", "from": period_from, "to": period_to, "downloaded": downloaded,
            "rows": rows_out, "positions": len(rows_out),
            "gross": round(totals["gross"], 2), "charges": charges, "charges_total": round(sum(charges.values()), 2),
            "net": round(totals["net"], 2), "wins": sum(1 for r in rows_out if r["net"] > 0),
            "totals_source": "angel-summary" if sources and all(s == "angel-summary" for s in sources) else "row-sums",
            "rows_net": round(sum(r["net"] for r in rows_out), 2), "non_commodity_rows_ignored": skipped}


# ── what a report shows ─────────────────────────────────────────────────────────


def mcx_sessions(start: str | None, end: str | None) -> int | None:
    """MCX trading days from start to end, both included (the shared MCX calendar)."""
    if not (start and end):
        return None
    try:
        from tradingai_shared import mcx_calendar as mcal
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        return mcal.trading_days_between(a - timedelta(days=1), b)
    except Exception:  # noqa: BLE001
        return None


def _group(rows: list[dict], key) -> list[dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        g[str(key(r))].append(r)
    out = []
    for k, rs in g.items():
        out.append({"key": k, "positions": len(rs), "wins": sum(1 for r in rs if r["net"] > 0),
                    "gross": round(sum(r["gross"] for r in rs), 2), "charges": round(sum(r["charges_total"] for r in rs), 2),
                    "net": round(sum(r["net"] for r in rs), 2)})
    return sorted(out, key=lambda x: x["key"])


def row_stats(doc: dict) -> dict:
    rows = doc.get("rows") or []
    nets = [r["net"] for r in rows]
    if not nets:
        return {"positions": 0}
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x < 0]
    won, lost = sum(wins), -sum(losses)
    avg_win = statistics.mean(wins) if wins else None
    avg_loss = statistics.mean(losses) if losses else None
    gross = doc.get("gross") or 0.0
    sessions = mcx_sessions(doc.get("from"), doc.get("to"))
    net = doc.get("net") or 0.0
    return {
        "positions": len(rows), "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / len(rows),
        "avg_win": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 2) if avg_loss is not None else None,
        "payoff": round(avg_win / -avg_loss, 2) if avg_win is not None and avg_loss else None,
        "profit_factor": round(won / lost, 2) if lost else None,
        "expectancy": round(statistics.mean(nets), 2), "median": round(statistics.median(nets), 2),
        "largest_win": max(nets), "largest_loss": min(nets),
        "charges_share_of_gross": (doc.get("charges_total") or 0.0) / gross if gross > 0 else None,
        "charges_per_position": round((doc.get("charges_total") or 0.0) / len(rows), 2),
        "lots": round(sum(r.get("lots") or 0 for r in rows), 2) if all(r.get("lots") for r in rows) else None,
        "buy_value": round(sum(r["buy_value"] for r in rows), 2), "sell_value": round(sum(r["sell_value"] for r in rows), 2),
        "sessions": sessions, "net_per_session": round(net / sessions, 2) if sessions else None,
        "by_type": _group(rows, lambda r: r.get("kind") or "?"),
        "by_expiry": _group(rows, lambda r: r.get("expiry") or "?"),
        "by_underlying": _group(rows, lambda r: r.get("underlying") or "?"),
    }


def rate_card_check(doc: dict) -> dict | None:
    """This page's rate card (the one that prices the live days) applied to the report's own
    positions - one buy order and one sell order each, as Angel's report charges them - beside
    Angel's actual charges. Shows how far the live days' estimate can be trusted."""
    from app.services import angel_commodity_ledger as L
    try:
        on = date.fromisoformat(doc.get("to") or doc.get("from"))
    except (TypeError, ValueError):
        on = date.today()
    est = {k: 0.0 for k in L.COMPONENTS}
    try:
        for r in doc.get("rows") or []:
            fn = L._option_order_breakdown if r.get("kind") in ("CE", "PE") else L._future_order_breakdown
            for value, sell in ((r["buy_value"], False), (r["sell_value"], True)):
                if value:
                    b = fn(value, sell, on)
                    for k in L.COMPONENTS:
                        est[k] += b.get(k, 0.0)
    except Exception:  # noqa: BLE001 - a missing fee schedule leaves the check out, never the report
        return None
    actual = doc.get("charges") or {}
    est = {k: round(v, 2) for k, v in est.items()}
    total_est, total_act = round(sum(est.values()), 2), round(doc.get("charges_total") or 0.0, 2)
    return {"estimate": total_est, "actual": total_act, "difference": round(total_act - total_est, 2),
            "by_component": [{"key": k, "actual": round(actual.get(k, 0.0), 2), "estimate": est.get(k, 0.0)}
                             for k in CHARGE_KEYS if actual.get(k) or est.get(k)]}


# ── one entry point for any Angel file ──────────────────────────────────────────


async def import_file(filename: str, content_b64: str, apply: bool = False) -> dict:
    """Detect what the file is and preview (default) or apply its import."""
    from app.services import angel_commodity_ledger as L
    data = base64.b64decode(content_b64)
    if data[:4] == b"PK\x03\x04":
        sheets = read_xlsx(data)
        rep = parse_pnl_report(sheets)
        if rep is not None:
            return await _apply_report(rep, filename, apply)
        # a trade history saved as Excel: from its header row on, as CSV
        first = next((rows for rows in sheets.values() if rows), [])
        start = next((i for i, r in enumerate(first)
                      if sum(1 for x in r if x and str(x).strip()) >= 4
                      and any(str(x or "").strip().lower() in ("qty", "quantity", "trade qty", "price", "trade price") for x in r)), 0)
        text = rows_to_csv(first[start:])
    else:
        text = data.decode("utf-8-sig", errors="replace")
        if "scrip symbol" in text[:20000].lower():
            rep = parse_pnl_report({"csv": list(csv.reader(io.StringIO(text)))})
            if rep is not None:
                return await _apply_report(rep, filename, apply)
    res = await L.import_tradebook(text, apply=apply)
    return {"kind": "trade-history", **res}


async def _apply_report(rep: dict, filename: str, apply: bool) -> dict:
    if not (rep.get("from") and rep.get("to")):
        raise ValueError("the report's From Date / To Date were not found")
    if not rep["rows"]:
        raise ValueError(f"the report for {rep['from']} - {rep['to']} has no closed commodity (MCX) positions")
    from app.services import angel_commodity_ledger as L
    recorded = sorted([d["_id"] async for d in L.days.find({"active": True}, {"_id": 1})])
    inside = [d for d in recorded if rep["from"] <= d <= rep["to"]]
    others = [s async for s in statements.find({"_id": {"$ne": _sid(rep)}}, {"from": 1, "to": 1})]
    clash = [f"{s['from']} - {s['to']}" for s in others if s.get("from") and s.get("to")
             and not (s["to"] < rep["from"] or s["from"] > rep["to"])]
    exists = await statements.find_one({"_id": _sid(rep)}, {"_id": 1}) is not None
    preview = {**rep, "filename": filename, "recorded_days_inside": inside, "overlaps_reports": clash,
               "replaces_existing": exists, "stats": row_stats(rep), "rate_card": rate_card_check(rep)}
    if not apply:
        return {**preview, "applied": False}
    doc = {**rep, "filename": (filename or "")[:200], "imported_at": datetime.now(timezone.utc)}
    await statements.update_one({"_id": _sid(rep)}, {"$set": doc}, upsert=True)
    return {**preview, "applied": True}


def _sid(rep: dict) -> str:
    return f"pnl-report|{rep['from']}|{rep['to']}"


async def listing() -> list[dict]:
    out = []
    async for s in statements.find({}).sort("from", -1):
        s["id"] = s.pop("_id")
        if isinstance(s.get("imported_at"), datetime):
            s["imported_at"] = (s["imported_at"] if s["imported_at"].tzinfo else s["imported_at"].replace(tzinfo=timezone.utc)).isoformat()
        s["stats"] = row_stats(s)
        s["rate_card"] = rate_card_check(s)
        out.append(s)
    return out


def select(stmts: list[dict], day_rows: list[dict]) -> list[dict]:
    """Mark each report counted or not (with the reason) and return the counted ones. Longer
    periods first, then the latest import."""
    dates = sorted(r["date"] for r in day_rows if r.get("date"))
    chosen: list[dict] = []
    for s in sorted(stmts, key=lambda s: (_span(s), s.get("imported_at") or ""), reverse=True):
        inside = [d for d in dates if s.get("from") and s.get("to") and s["from"] <= d <= s["to"]]
        clash = next((c for c in chosen if not (c["to"] < s["from"] or c["from"] > s["to"])), None)
        if inside:
            s["counted"], s["reason"] = False, (
                f"{len(inside)} day(s) inside this period are already recorded one by one ({inside[0]}"
                f"{' to ' + inside[-1] if len(inside) > 1 else ''}); an undated total cannot be split around them")
        elif clash:
            s["counted"], s["reason"] = False, f"overlaps the report for {clash['from']} to {clash['to']}, which is counted"
        else:
            s["counted"], s["reason"] = True, None
            chosen.append(s)
    return chosen


def _span(s: dict) -> int:
    try:
        return (date.fromisoformat(s["to"]) - date.fromisoformat(s["from"])).days
    except (KeyError, TypeError, ValueError):
        return -1


def lifetime(day_rows: list[dict], stmts: list[dict]) -> dict:
    """Everything known: the daily records plus the counted P&L-report periods."""
    used = select(stmts, day_rows)
    d_net = sum(r.get("net_pnl") or 0.0 for r in day_rows)
    d_gross = sum((r.get("gross_pnl") if r.get("basis") == "angel-api" else r.get("realised_fifo")) or 0.0 for r in day_rows)
    d_chg = sum(r.get("charges") or 0.0 for r in day_rows)
    s_net = sum(s.get("net") or 0.0 for s in used)
    s_gross = sum(s.get("gross") or 0.0 for s in used)
    s_chg = sum(s.get("charges_total") or 0.0 for s in used)
    starts = [x for x in [min((r["date"] for r in day_rows), default=None), *(s.get("from") for s in used)] if x]
    ends = [x for x in [max((r["date"] for r in day_rows), default=None), *(s.get("to") for s in used)] if x]
    return {"net": round(d_net + s_net, 2), "gross": round(d_gross + s_gross, 2), "charges": round(d_chg + s_chg, 2),
            "charges_actual": round(s_chg, 2), "charges_estimated": round(d_chg, 2),
            "from": min(starts) if starts else None, "to": max(ends) if ends else None,
            "days": len(day_rows), "days_net": round(d_net, 2),
            "statement_periods": len(used), "statements_net": round(s_net, 2),
            "statements_left_out": len(stmts) - len(used),
            "closed_positions_in_statements": sum(s.get("positions") or 0 for s in used),
            "wins_in_statements": sum(s.get("wins") or 0 for s in used)}
