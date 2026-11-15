"""Point-in-time panels for the Fundamental Rank validation (rules: PLAN.md).

    python study.py <screener.jsonl.gz> <rows.jsonl.gz> <nsehist dir> <out dir>

Inputs are the app's own caches: the screener.in pages (one JSON document per line), the NSE Stock Ratings rows,
and the 5-year NSE daily price download (prices/YYYY-MM-DD.json.gz, ca_5y.json, symbolchange.csv). Every as-of
page is scored by the module's own code. Writes <out>/panel.csv (one row per as-of date and stock) and
<out>/selfcheck.csv (the reconstruction at each page's fetch date beside the live row's components)."""
from __future__ import annotations

import bisect
import calendar
import csv
import gzip
import json
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
from app.services import fundamental_rating as FR  # noqa: E402
from app.services import nse_ratings_logic as L  # noqa: E402
from app.services import pnl_strength as PS  # noqa: E402
from app.services import results_strength as RS  # noqa: E402

ASOF = [date(2021, 10, 1), date(2022, 10, 1), date(2023, 10, 1), date(2024, 10, 1), date(2025, 10, 1)]
ANNUAL_LAG, HALF_LAG, Q_LAG, Q4_LAG, SH_LAG = 67, 52, 52, 67, 28
KEEP_SERIES = ("EQ", "BE", "BZ")
BREAK = 0.40                 # nse_market.BREAK
STALE = 5                    # sessions a close may be away from the date it stands for
MIN_SECTOR_PEERS = 8         # nse_ratings.MIN_SECTOR_PEERS
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
COMPONENTS = ("quality", "growth", "valuation", "strength", "quarter")
PILLAR_KEYS = tuple(FR.PILLARS)


def period_end(label) -> date | None:
    m = re.match(r"\s*([A-Za-z]{3})[a-z]*\s+(\d{4})\s*$", str(label or ""))
    if not m or m.group(1).lower() not in MONTHS:
        return None
    y, mo = int(m.group(2)), MONTHS[m.group(1).lower()]
    return date(y, mo, calendar.monthrange(y, mo)[1])


# -- prices -----------------------------------------------------------------------------------------------------------


def load_prices(nh: Path):
    renames: dict[str, tuple[str, date]] = {}
    with open(nh / "symbolchange.csv", encoding="utf-8", errors="replace", newline="") as fh:
        for raw in csv.DictReader(fh):
            x = {(k or "").strip().upper(): (v or "").strip() for k, v in raw.items() if isinstance(k, str)}
            old, new = x.get("OLD SYMBOL", "").upper(), x.get("NEW SYMBOL", "").upper()
            eff = L.parse_nse_date(x.get("EFFECTIVE DATE"))
            if old and new and eff and old != new and (old not in renames or renames[old][1] < eff):
                renames[old] = (new, eff)

    def canon(sym: str, d: date) -> str:
        for _ in range(5):
            hit = renames.get(sym)
            if not hit or d >= hit[1]:
                return sym
            sym = hit[0]
        return sym

    files = sorted((nh / "prices").glob("*.json.gz"))
    days = [date.fromisoformat(p.name[:10]) for p in files]
    loaded = []
    symset: set[str] = set()
    for d, p in zip(days, files):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            day = json.load(fh)
        loaded.append(day)
        symset.update(canon(s, d) for s in day)
    syms = sorted(symset)
    col = {s: i for i, s in enumerate(syms)}
    T, N = len(days), len(syms)
    C = np.full((T, N), np.nan)
    for t, (d, day) in enumerate(zip(days, loaded)):
        for s, v in day.items():
            if v and v[0]:
                C[t, col[canon(s, d)]] = v[0]
    del loaded

    actions = json.loads((nh / "ca_5y.json").read_text(encoding="utf-8"))
    unadj = np.zeros((T, N), dtype=bool)
    n_adj = 0
    for it in actions if isinstance(actions, list) else actions.get("data", []):
        if not isinstance(it, dict) or (it.get("series") or "EQ") not in KEEP_SERIES:
            continue
        act = L.parse_action(it.get("subject") or "")
        ex = L.parse_nse_date(it.get("exDate"))
        sym = (it.get("symbol") or "").strip().upper()
        if not (act and ex and sym):
            continue
        j = col.get(canon(sym, ex))
        if j is None or ex <= days[0] or ex > days[-1]:
            continue
        t_ex = bisect.bisect_left(days, ex)
        if act.get("factor"):
            C[:t_ex, j] *= act["factor"]
            n_adj += 1
        if act.get("unadjusted"):
            unadj[t_ex, j] = True

    # unexplained one-day jumps (the module's breaks), between consecutive traded closes
    jump = np.zeros((T, N), dtype=bool)
    last = np.full(N, np.nan)
    for t in range(T):
        ok = ~np.isnan(C[t])
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.log(C[t] / last)
        jump[t] = ok & ~np.isnan(r) & (np.abs(r) > BREAK)
        last = np.where(ok, C[t], last)
    print(f"prices: {T} sessions {days[0]}..{days[-1]}, {N} symbols, {n_adj} adjustments applied", file=sys.stderr)
    return days, col, C, unadj | jump


def close_on_or_before(days, C, j, d):
    t = bisect.bisect_right(days, d) - 1
    for k in range(t, max(t - STALE, -1), -1):
        if k >= 0 and not math.isnan(C[k, j]):
            return k, C[k, j]
    return None, None


def close_on_or_after(days, C, j, d):
    t = bisect.bisect_left(days, d)
    for k in range(t, min(t + STALE, len(days))):
        if not math.isnan(C[k, j]):
            return k, C[k, j]
    return None, None


# -- the page as it stood on an as-of date ----------------------------------------------------------------------------


def _keep(periods, d: date, lag_of) -> list[int]:
    out = []
    for i, label in enumerate(periods or []):
        e = period_end(label)
        if e is not None and e + timedelta(days=lag_of(e, i, periods)) <= d:
            out.append(i)
    return out


def _cut(table, idx):
    return {k: ([v[i] if i < len(v) else None for i in idx] if isinstance(v, list) else v)
            for k, v in (table or {}).items()}


def _annual_lag(e, i, periods):
    return ANNUAL_LAG


def _bs_lag(e, i, periods):
    # a trailing column whose month differs from the year-end month is a half-year balance sheet
    ends = [period_end(p) for p in periods]
    months = [x.month for x in ends if x]
    fy_month = max(set(months), key=months.count) if months else 3
    return HALF_LAG if (e.month != fy_month and i == len(periods) - 1) else ANNUAL_LAG


def _q_lag(e, i, periods):
    return Q4_LAG if e.month == 3 else Q_LAG


def _sh_lag(e, i, periods):
    return SH_LAG


def _row(table, *names):
    for n in names:
        v = (table or {}).get(n)
        if isinstance(v, list) and any(x is not None for x in v):
            return v
    return []


def _last(vals):
    for v in reversed(vals or []):
        if v is not None:
            return v
    return None


def _cagr(vals, years):
    if len(vals) < years + 1:
        return None
    a, b = vals[-1 - years], vals[-1]
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return round(((b / a) ** (1 / years) - 1) * 100, 1)


def asof_page(doc: dict, d: date, mcap_d: float | None, price_d: float | None) -> dict | None:
    """The cached page cut to what was public on `d`, with today's snapshot fields rebuilt from those years."""
    f = {k: v for k, v in doc.items() if k not in ("ratios", "ranges")}
    keep = {}
    for tbl, lag in (("profit_loss", _annual_lag), ("cash_flow", _annual_lag), ("ratios_table", _annual_lag),
                     ("balance_sheet", _bs_lag), ("quarters", _q_lag), ("shareholding", _sh_lag)):
        periods = doc.get(f"{tbl}_periods") or []
        idx = _keep(periods, d, lag)
        keep[tbl] = idx
        f[tbl] = _cut(doc.get(tbl), idx)
        f[f"{tbl}_periods"] = [periods[i] for i in idx]
    years = f["profit_loss_periods"]
    if len(years) < 3:
        return None
    pl, bs, rt = f["profit_loss"], f["balance_sheet"], f["ratios_table"]
    sales = _row(pl, "Sales", "Revenue")
    profit = _row(pl, "Net Profit")
    # net worth per year-end, matched to the P&L's years by label
    bs_lab = f["balance_sheet_periods"]
    eqc, res = _row(bs, "Equity Capital"), _row(bs, "Reserves")
    nw = {}
    for i, lab in enumerate(bs_lab):
        a = eqc[i] if i < len(eqc) else None
        b = res[i] if i < len(res) else None
        if a is not None and b is not None:
            nw[lab] = a + b
    roes = []
    for i, lab in enumerate(years):
        npf = profit[i] if i < len(profit) else None
        prev = years[i - 1] if i > 0 else None
        base = [x for x in (nw.get(lab), nw.get(prev)) if x is not None]
        if npf is not None and base and sum(base) / len(base) > 0:
            roes.append(npf / (sum(base) / len(base)) * 100)
        else:
            roes.append(None)
    roe_now = roes[-1] if roes else None
    roe3 = [x for x in roes[-3:] if x is not None]
    roce = _last(_row(rt, "ROCE %"))
    np_last = _last(profit)
    pe = (mcap_d / np_last) if (mcap_d and np_last and np_last > 0) else None
    f["ratios"] = {"Market Cap": round(mcap_d, 1) if mcap_d else None, "Current Price": price_d,
                   "Stock P/E": round(pe, 1) if pe else None, "ROCE": roce,
                   "ROE": round(roe_now, 1) if roe_now is not None else None}
    f["ranges"] = {
        "Compounded Sales Growth": {"3 Years": _cagr(sales, 3), "5 Years": _cagr(sales, 5), "TTM": None},
        "Compounded Profit Growth": {"3 Years": _cagr(profit, 3), "5 Years": _cagr(profit, 5), "TTM": None},
        "Return on Equity": {"3 Years": round(sum(roe3) / len(roe3), 1) if len(roe3) == 3 else None},
    }
    f["_years_kept"] = len(years)
    return f


def score_page(f: dict, series: str | None) -> dict:
    r = FR.rate(f)
    try:
        q = RS.analyse(f)
    except Exception:  # noqa: BLE001
        q = {"rated": False, "score": None}
    try:
        p = PS.analyse(f)
    except Exception:  # noqa: BLE001
        p = {"rated": False, "score": None}
    row = L.static_row(f, r, q, p, series=series)
    row["_fund"] = r.get("score")
    return row


def add_val_rel(rows: list[dict], sector_of) -> None:
    """nse_ratings.valuation_cross_section, across one date's stocks."""
    by: dict[str, list[dict]] = {}
    for x in rows:
        sec = sector_of(x["_sym"])
        x["val_rel_score"] = None
        if x.get("pe") and x["pe"] > 0 and sec and sec != "Unclassified":
            by.setdefault(sec, []).append(x)
    for sec, items in by.items():
        if len(items) < MIN_SECTOR_PEERS:
            continue
        pes = sorted(x["pe"] for x in items)
        n = len(pes)
        for x in items:
            below = bisect.bisect_left(pes, x["pe"])
            equal = bisect.bisect_right(pes, x["pe"]) - below
            x["val_rel_score"] = round(10 * (1 - (below + 0.5 * equal) / n), 1)


def data_ok(row: dict) -> bool:
    n = row.get("pillars_n") or 0
    cov = row.get("coverage")
    return n >= L.MIN_PILLARS and (cov is None or cov >= L.MIN_APPLICABLE_COVERAGE)


def main() -> None:
    scr, rws, nh, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(scr, "rt", encoding="utf-8") as fh:
        pages = {d["_id"]: d for d in map(json.loads, fh)}
    with gzip.open(rws, "rt", encoding="utf-8") as fh:
        live = {d["_id"]: d for d in map(json.loads, fh)}
    days, col, C, brk = load_prices(nh)
    sector_of = lambda s: (live.get(s) or {}).get("sector") or "Unclassified"  # noqa: E731
    print(f"pages {len(pages)}, live rows {len(live)}", file=sys.stderr)

    def mcap_at(sym, doc, d):
        j = col.get(sym)
        mc_now = L.num((doc.get("ratios") or {}).get("Market Cap"))
        fetched = L.as_date(doc.get("fetched_at"))
        if j is None or not mc_now or not fetched:
            return None, None, None
        t0, p0 = close_on_or_before(days, C, j, d)
        tf, pf = close_on_or_before(days, C, j, fetched)
        if p0 is None or pf is None:
            return None, None, None
        return mc_now * p0 / pf, p0, t0

    fields = (["asof", "symbol", "sector", "series", "lender", "mcap", "years", "data_ok", "fund", "pnl",
               "val_rel"] + [f"p_{k}" for k in PILLAR_KEYS] + [f"c_{k}" for k in COMPONENTS]
              + ["ret12", "brk12", "ret6", "brk6"])
    with open(out / "panel.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for d in ASOF:
            rows = []
            for sym, doc in pages.items():
                lv = live.get(sym) or {}
                if lv.get("series") not in KEEP_SERIES:
                    continue
                mc, p0, t0 = mcap_at(sym, doc, d)
                if t0 is None:
                    continue
                f = asof_page(doc, d, mc, p0)
                if f is None:
                    continue
                try:
                    row = score_page(f, lv.get("series"))
                except Exception as e:  # noqa: BLE001
                    print(f"  {d} {sym}: scoring failed: {e}", file=sys.stderr)
                    continue
                row["_sym"], row["_mcap"], row["_t0"], row["_p0"] = sym, mc, t0, p0
                row["_years"] = f["_years_kept"]
                rows.append(row)
            add_val_rel(rows, sector_of)
            n_ok = 0
            for row in rows:
                sym, j = row["_sym"], col[row["_sym"]]
                comps = L.rating_components(row)
                rets = {}
                for h, days_ahead in (("12", 365), ("6", 182)):
                    t1, p1 = close_on_or_after(days, C, j, d + timedelta(days=days_ahead))
                    if t1 is None:
                        rets[h] = (None, None)
                    else:
                        rets[h] = (p1 / row["_p0"] - 1, bool(brk[row["_t0"] + 1:t1 + 1, j].any()))
                ok = data_ok(row) and comps.get("quality") is not None
                n_ok += ok
                ps = row.get("pillar_scores") or {}
                w.writerow([d.isoformat(), sym, sector_of(sym), (live.get(sym) or {}).get("series"),
                            int(bool(row.get("is_lender"))), round(row["_mcap"], 1) if row["_mcap"] else None,
                            row["_years"], int(ok), row.get("_fund"), row.get("pnl"), row.get("val_rel_score")]
                           + [ps.get(k) for k in PILLAR_KEYS] + [comps.get(k) for k in COMPONENTS]
                           + [rets["12"][0], rets["12"][1], rets["6"][0], rets["6"][1]])
            print(f"{d}: {len(rows)} scored, {n_ok} pass the data rule", file=sys.stderr)

    # self-check: the reconstruction at each page's fetch date against the live row
    recon = []
    for sym, doc in pages.items():
        lv = live.get(sym) or {}
        fetched = L.as_date(doc.get("fetched_at"))
        if lv.get("series") not in KEEP_SERIES or not fetched:
            continue
        mc = L.num((doc.get("ratios") or {}).get("Market Cap"))
        f = asof_page(doc, fetched + timedelta(days=1), mc, None)
        if f is None:
            continue
        try:
            row = score_page(f, lv.get("series"))
        except Exception:  # noqa: BLE001
            continue
        row["_sym"] = sym
        recon.append(row)
    add_val_rel(recon, sector_of)
    with open(out / "selfcheck.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol"] + [f"mine_{k}" for k in COMPONENTS[:4]] + [f"live_{k}" for k in COMPONENTS[:4]]
                   + ["mine_fund", "live_fund"])
        for row in recon:
            lv = live[row["_sym"]]
            mine = L.rating_components(row)
            lp = lv.get("rating_parts") or L.rating_components(lv)
            w.writerow([row["_sym"]] + [mine.get(k) for k in COMPONENTS[:4]] + [lp.get(k) for k in COMPONENTS[:4]]
                       + [row.get("_fund"), lv.get("fund")])
    print(f"self-check rows: {len(recon)}", file=sys.stderr)


if __name__ == "__main__":
    main()
