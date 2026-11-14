"""Builds the study's structured strategy records (STEP 3-7) from the evidence and the results.

Inputs: registry/freqtrade_inventory.json (static inventory), the freqtrade clone (rule lines are read from the code,
never run here), ws_cards.py (hand-written parts), results/freqtrade_backtests.json, results/qc_backtests.json,
results/freqtrade_bias.json, results/qc_truncation.json and the QuantConnect extract (D:/Strategy-Web-Sources).
Outputs: registry/candidates.json (every record), registry/INVENTORY.md, evidence/<SID>.md (cited lines and quotes).

Statuses: DISCOVERED, NEEDS_CLARIFICATION, READY_FOR_IMPLEMENTATION, READY_FOR_BACKTEST, BACKTESTED,
PAPER_TRADING_CANDIDATE, REJECTED, BLOCKED (a test cannot run; the blocker is recorded). Nothing here is "validated".
The paper-trading gate (GATE) was written before the records were built and is applied mechanically.

    python -I ws_records.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ws_cards as K  # noqa: E402
import ws_engine as E  # noqa: E402

CLONE = Path(r"D:\Strategy-Web-Sources\freqtrade\freqtrade-strategies")
QCX = Path(r"D:\Strategy-Web-Sources\quantconnect\extract.json")
ART = Path(r"D:\Strategy-Web-Sources\articles")
RETRIEVED = "2026-11-13"
INV = json.loads((HERE / "registry" / "freqtrade_inventory.json").read_text(encoding="utf-8"))
FTB = json.loads((HERE / "results" / "freqtrade_backtests.json").read_text(encoding="utf-8"))
QCB = json.loads((HERE / "results" / "qc_backtests.json").read_text(encoding="utf-8"))
BIAS = json.loads((HERE / "results" / "freqtrade_bias.json").read_text(encoding="utf-8"))
TRUNC = json.loads((HERE / "results" / "qc_truncation.json").read_text(encoding="utf-8"))
COMMIT = INV["commit"]
BATCH_FT = ["BinHV45", "Low_BB", "Scalp", "SmoothScalp", "CCIStrategy", "ClucMay72018", "CombinedBinHAndCluc", "BinHV27",
            "CofiBitStrategy", "EMASkipPump", "MACDStrategy", "MultiRSI", "Quickie", "SmoothOperator", "Strategy005",
            "UniversalMACD", "CMCWinner", "Bandtastic", "FAdxSmaStrategy", "FReinforcedStrategy"]
VARIATIONS = ["MACDStrategy_crossed", "ReinforcedQuickie", "ReinforcedSmoothScalp"]
NOT_STRATEGIES = {"DoesNothingStrategy": "does nothing (a test fixture)", "Freqtrade_backtest_validation_freqtrade1": "a backtest validation fixture",
                  "TechnicalExampleStrategy": "an example of the technical library", "FSampleStrategy": "freqtrade's sample strategy",
                  "InformativeSample": "an example of informative pairs", "BreakEven": "a template for a break-even custom stop",
                  "FixedRiskRewardLoss": "a template for a fixed risk-reward custom stop", "CustomStoplossWithPSAR": "an example of a custom stop",
                  "AlmgrenChrissStrategy": "an execution algorithm (Almgren-Chriss) with position adjustment, not a signal strategy",
                  "TWAPStrategy": "an execution algorithm (TWAP) with position adjustment", "multi_tf": "an example of multiple timeframes"}
# ── the paper-trading gate (all must hold) ─────────────────────────────────────────────────────────────────
GATE = ["implemented as published on the original market or its nearest data", "no look-ahead found (freqtrade lookahead-analysis or our truncation test)",
        "net positive in the development window", "net positive out of sample", "net positive out of sample at twice the costs",
        "at least 30 out-of-sample trades", "out-of-sample mean-trade t-stat >= 2.0",
        "net positive out of sample on the second pair (crypto) or the other window (gold)",
        "out-of-sample return above buy-and-hold scaled by the time in the market"]


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────────
def ts(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").timestamp())


def buy_hold(m: E.Minutes, a: int, b: int) -> float | None:
    i, j = m.at(a), min(m.at(b) - 1, m.n - 1)
    return None if j <= i else float((m.c[j] / m.o[i] - 1) * 100)


def method_lines(path: Path, cls: str) -> tuple[list[str], dict]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tree = ast.parse("\n".join(lines))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    out = {}
    for st in node.body:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[st.name] = (st.lineno, st.end_lineno)
    return lines, out


def code_span(lines: list[str], a: int, b: int, skip_defs: bool = True) -> str:
    keep = []
    for i in range(a, b + 1):
        t = lines[i - 1].strip()
        if not t or t.startswith(("#", '"""', "'''")) or (skip_defs and t.startswith("def ")) or t in ("return dataframe",):
            continue
        keep.append(t)
    return " ".join(keep)


def ft_rules(cls: str) -> list[dict]:
    rec = next(r for r in INV["strategies"] if r.get("class") == cls)
    path = CLONE / rec["file"]
    lines, meth = method_lines(path, cls)
    S = rec["settings"]
    R = []

    def add(kind, tag, text, loc, quote=""):
        R.append({"kind": kind, "tag": tag, "text": text, "loc": loc, "quote": quote[:420]})

    if "timeframe" in S:
        add("timeframe", "E", f"Candle timeframe {S['timeframe']['value']}", f"L{S['timeframe']['line']}", lines[S['timeframe']['line'] - 1].strip())
    for k in ("minimal_roi",):
        if k in S:
            a = S[k]["line"]
            add("target", "E", f"ROI table (minutes since entry: net profit ratio) {json.dumps(S[k]['value'])}", f"L{a}",
                code_span(lines, a, a + 8, False).split("}")[0] + "}")
    if "stoploss" in S:
        add("stop", "E", f"Stop-loss {S['stoploss']['value']} (price level from the entry)", f"L{S['stoploss']['line']}", lines[S['stoploss']['line'] - 1].strip())
    tr = [k for k in ("trailing_stop", "trailing_stop_positive", "trailing_stop_positive_offset", "trailing_only_offset_is_reached") if k in S]
    if tr:
        add("management", "E", "Trailing: " + ", ".join(f"{k} = {S[k]['value']}" for k in tr), "L" + ",".join(str(S[k]["line"]) for k in tr),
            " / ".join(lines[S[k]["line"] - 1].strip() for k in tr))
    for k in ("use_exit_signal", "use_sell_signal", "exit_profit_only", "sell_profit_only", "ignore_roi_if_entry_signal", "can_short",
              "startup_candle_count", "process_only_new_candles"):
        if k in S:
            add("management" if k != "startup_candle_count" else "data", "E", f"{k} = {S[k]['value']}", f"L{S[k]['line']}", lines[S[k]["line"] - 1].strip())
    # shipped parameter values (hyperopt dictionaries and Parameter defaults)
    cl = next(n for n in ast.parse("\n".join(lines)).body if isinstance(n, ast.ClassDef) and n.name == cls)
    params = [st for st in cl.body if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name)
              and (st.targets[0].id.endswith("_params") or "Parameter(" in ast.unparse(st.value))]
    if params:
        add("indicator", "E", "Shipped parameter values (hyperopt dictionaries override Parameter defaults)",
            "L" + ",".join(str(p.lineno) for p in params), " | ".join(ast.unparse(p)[:120] for p in params))
    if "populate_indicators" in meth:
        a, b = meth["populate_indicators"]
        add("indicator", "E", "Indicators as computed in populate_indicators", f"L{a}-{b}", code_span(lines, a, b))
    for name, kind in (("populate_entry_trend", "entry"), ("populate_buy_trend", "entry"), ("populate_exit_trend", "exit"),
                       ("populate_sell_trend", "exit")):
        if name in meth:
            a, b = meth[name]
            add(kind, "E", f"{'Entry' if kind == 'entry' else 'Exit'} signal conditions ({name})", f"L{a}-{b}", code_span(lines, a, b))
    for name in ("custom_stoploss", "custom_exit", "informative_pairs", "adjust_trade_position", "leverage"):
        if name in meth:
            a, b = meth[name]
            add("management", "E", f"Callback {name}", f"L{a}-{b}", code_span(lines, a, b))
    # what the code leaves to freqtrade / the bot's configuration (interpretation, not the source's words)
    add("timing", "I", "Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open", "-")
    add("order", "I", "No order types set in the strategy: the bot configuration decides (limit or market)", "-")
    add("sizing", "I", "Stake size and max open trades are not in the strategy: they come from the bot configuration", "-")
    add("management", "I", "No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit", "-")
    add("session", "I", "No session or time filter: trades around the clock", "-")
    add("market", "A", "Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute "
        "data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars", "-")
    add("market", "A", "Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance "
        "USDT-M funding, 2020-2026; spot prices stand in for the perpetual", "-")
    return R


def ft_source(cls: str) -> dict:
    rec = next(r for r in INV["strategies"] if r.get("class") == cls)
    a, b = rec["lines"]
    return {"platform": "GitHub · freqtrade/freqtrade-strategies", "url": f"{K.FT_REPO}/blob/{COMMIT}/{rec['file']}#L{a}-L{b}",
            "file": rec["file"], "author": K.FT.get(cls, {}).get("author", "see file"), "retrieved": RETRIEVED,
            "licence": "GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository",
            "version": f"commit {COMMIT}", "file_sha256": rec["sha256_file"]}


def market_class(cls: str) -> str:
    rec = next(r for r in INV["strategies"] if r.get("class") == cls)
    return "crypto_perp" if "/futures/" in rec["file"] else "crypto_spot"


def summarize(s: dict | None) -> dict | None:
    if not s or not s.get("trades"):
        return {"trades": 0} if s is not None else None
    keys = ["trades", "net", "ret_pct", "win_rate", "pf", "max_dd_pct", "exp_usd", "exp_pct", "gross_pct", "funding_pct",
            "avg_hold_min", "exposure_pct", "t_stat", "ruined_on", "by_reason"]
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items() if k in keys}


def gate(c: dict) -> list[tuple[str, bool | None]]:
    """Each GATE item with True / False (None = not applicable)."""
    r = c.get("results") or {}
    d, o, ox, o2 = r.get("dev"), r.get("oos"), r.get("oos_x2"), r.get("oos_second")
    bh, ex = r.get("oos_buy_hold_pct"), (o or {}).get("exposure_pct")
    ok = [True, not c.get("lookahead"),
          bool(d and d.get("trades") and d["net"] > 0), bool(o and o.get("trades") and o["net"] > 0),
          bool(ox and ox.get("trades") and ox["net"] > 0), bool(o and o.get("trades", 0) >= 30),
          bool(o and (o.get("t_stat") or 0) >= 2.0),
          (None if o2 is None else bool(o2.get("trades") and o2["net"] > 0)),
          (None if bh is None or not o or not o.get("trades") else bool(o["ret_pct"] > bh * min(ex or 0, 100) / 100))]
    return list(zip(GATE, ok))


# ── build ────────────────────────────────────────────────────────────────────────────────────────────────────
def main() -> None:
    mins = {"BTC/USDT": E.Minutes("BTC/USDT"), "ETH/USDT": E.Minutes("ETH/USDT")}
    gold = E.GoldMinutes()
    W = FTB["windows"]
    bh = {"BTC_oos": buy_hold(mins["BTC/USDT"], ts(W["BTC/USDT"]["oos"][0]), ts(W["BTC/USDT"]["oos"][1])),
          "BTC_dev": buy_hold(mins["BTC/USDT"], ts(W["BTC/USDT"]["dev"][0]), ts(W["BTC/USDT"]["dev"][1])),
          "ETH_oos": buy_hold(mins["ETH/USDT"], ts(W["ETH/USDT"]["oos"][0]), ts(W["ETH/USDT"]["oos"][1])),
          "GOLD_5079_oos": buy_hold(gold, ts("2018-01-01"), ts("2026-10-31")), "GOLD_5079_dev": buy_hold(gold, ts("2010-01-01"), ts("2018-01-01")),
          "GOLD_pre": buy_hold(gold, ts("2010-01-01"), ts("2021-01-01")), "GOLD_author": buy_hold(gold, ts("2021-01-01"), ts("2026-06-01"))}
    qcx = json.loads(QCX.read_text(encoding="utf-8"))
    cands: list[dict] = []

    # freqtrade batch + variations
    for cls in BATCH_FT + VARIATIONS:
        note = K.FT.get(cls, {})
        res = FTB["results"].get(cls)
        la = (BIAS["lookahead"].get(cls) or {}).get("result") or {}
        rc = BIAS["recursive"].get(cls) or {}
        c = {"sid": f"FT-{cls}", "name": cls, "group": "crypto", "batch": cls in BATCH_FT,
             "variation_of": (f"FT-{note['variation_of']}" if note.get("variation_of") else None),
             "kind": "specified (code)", "source": ft_source(cls),
             "market": {"class": market_class(cls), "original": "crypto perpetual futures (freqtrade futures mode, long and short)" if market_class(cls) == "crypto_perp"
                        else "crypto spot (freqtrade, exchange-agnostic; the repository's era used Binance pairs)",
                        "timeframe": (res or {}).get("settings", {}).get("timeframe") or next(r for r in INV["strategies"] if r.get("class") == cls)["settings"].get("timeframe", {}).get("value"),
                        "tested_on": "Binance BTC/USDT and ETH/USDT spot 1-minute data (repository), resampled; perpetual adaptation on BTC"},
             "hypothesis": {"tag": "I", "text": note.get("hyp", "")}, "rules": ft_rules(cls), "missing": [],
             "claims": [{"tag": "author-reported", "text": t} for t in note.get("claims", [])],
             "risks": [], "dedupe": {"verdict": (note.get("dedupe") or ("new", ""))[0], "note": (note.get("dedupe") or ("new", "No exact duplicate in the Premium library (408 names), the antigravity scalper registry (545 names) or the gold/crypto studies; families noted where close."))[1]}}
        c["risks"] += [{"check": "code review", "finding": t} for t in note.get("risks", [])]
        if la:
            c["risks"].append({"check": "freqtrade lookahead-analysis", "finding": f"has_bias = {la.get('has_bias')}; signals checked {la.get('total_signals')}; biased entry {la.get('biased_entry_signals')}, exit {la.get('biased_exit_signals')}; indicators: {la.get('biased_indicators') or 'none'} (window {BIAS['lookahead'][cls]['timerange']})"})
            c["lookahead"] = str(la.get("has_bias")).lower() in ("true", "yes")
        elif cls in BIAS["lookahead"]:
            c["risks"].append({"check": "freqtrade lookahead-analysis", "finding": "did not complete: " + str(BIAS["lookahead"][cls].get("error"))[:200]})
        if rc:
            rows = [x for x in rc.get("table", []) if x.strip().startswith("|") and "%" in x]
            worst = 0.0
            for x in rows:
                for cell in x.split("|")[2:]:
                    cell = cell.strip().rstrip("%")
                    try:
                        worst = max(worst, abs(float(cell)))
                    except ValueError:
                        pass
            c["risks"].append({"check": "freqtrade recursive-analysis", "finding": (f"startup_candle_count {rc.get('strategy_startup_candle_count')} "
                               f"({rc.get('analysis_override') or 'as shipped'}); largest indicator difference across 199-1999 startup candles: {worst:.3f}%")})
        c["risks"].append({"check": "unsafe code", "finding": "static review: no network, process or file access in the strategy file"})
        if note.get("blocked"):
            c["status"], c["status_reason"], c["blocker"] = "BLOCKED", note["blocked"], note["blocked"]
        elif res:
            b, e = res["btc_spot"], res.get("eth_spot", {})
            c["results"] = {"market": "BTC/USDT spot (original market type)", "dev": summarize(b["dev"]), "oos": summarize(b["oos"]),
                            "oos_x2": summarize(res.get("btc_spot_x2_oos")), "oos_second": summarize(e.get("oos")) if e and "oos" in e else None,
                            "eth_dev": summarize(e.get("dev")) if e else None, "yearly": b.get("yearly"),
                            "perp_adaptation": {"dev": summarize(res["btc_perp_adaptation"]["dev"]), "oos": summarize(res["btc_perp_adaptation"]["oos"])},
                            "sensitivity": res.get("sensitivity_btc_spot"), "oos_buy_hold_pct": bh["BTC_oos"], "dev_buy_hold_pct": bh["BTC_dev"],
                            "eth_oos_buy_hold_pct": bh["ETH_oos"], "windows": W, "costs": FTB.get("costs")}
        cands.append(c)

    # QuantConnect
    for q in K.QC_CARDS:
        sid = q["sid"]
        key = sid.replace("QC-R", "r").replace("QC-", "")
        disc = qcx.get(key, {})
        post = disc.get("opening") if q["file"][0] == "opening" else (disc.get("comments") or [])[int(q["file"][0])]
        f = next((x for x in (post or {}).get("files", []) if x["name"] == q["file"][1]), None)
        c = {"sid": sid, "name": q["name"], "group": q["group"], "batch": q.get("batch", True), "kind": "specified (code)",
             "source": {"platform": "QuantConnect " + ("research" if "/research/" in q["url"] else "forum"), "url": q["url"], "author": q["author"],
                        "retrieved": RETRIEVED, "licence": "unknown (QuantConnect terms of service govern community posts; no licence stated in the post)",
                        "version": f"page sha256 {disc.get('page_sha256', '?')[:16]}…; {q['file'][1]} sha256 {(f or {}).get('sha256', '?')}",
                        "post_published": (post or {}).get("published")},
             "market": {"class": q["class"], "original": q["original"], "timeframe": q["tf"]},
             "hypothesis": {"tag": "I", "text": q["hyp"]},
             "rules": [{"kind": k, "tag": t, "text": txt, "loc": loc, "quote": qq} for (k, t, txt, loc, qq) in q["rules"]],
             "missing": [], "claims": [{"tag": "author-reported", "text": t} for t in q.get("claims", [])],
             "risks": [{"check": "code review", "finding": t} for t in q.get("risks", [])],
             "dedupe": {"verdict": (q.get("dedupe") or ("new", ""))[0], "note": (q.get("dedupe") or ("new", "No exact duplicate found in the existing libraries and studies."))[1]},
             "sources_more": q.get("sources_more", [])}
        if q.get("status"):
            c["status"], c["status_reason"], c["blocker"] = q["status"], q.get("blocked", ""), q.get("blocked", "")
        res = QCB.get(sid)
        tkeys = [k for k in TRUNC if k.startswith(sid + " ")]
        if tkeys:
            diffs = sum(TRUNC[k]["differences"] for k in tkeys)
            c["risks"].append({"check": "truncation test (our implementation)", "finding": f"{diffs} differences over {sum(TRUNC[k]['rows_compared'] for k in tkeys):,} signal rows at {sum(TRUNC[k]['cuts'] for k in tkeys)} random cuts"})
            c["lookahead"] = diffs > 0
        if res and sid in ("QC-20960", "QC-5079"):
            g = res["XAUUSD"]
            if sid == "QC-20960":
                c["results"] = {"market": "XAUUSD mid (Dukascopy via HistData), adaptation of OANDA XAUUSD CFD data", "dev": summarize(g["author"]),
                                "oos": summarize(g["pre"]), "post": summarize(g["post"]), "oos_x2": summarize(res["XAUUSD_x2"]["pre"]),
                                "oos_second": summarize(g["post"]) if (g["post"] or {}).get("trades") else None,
                                "labels": {"dev": "the author's own window 2021-01 .. 2026-05 (in sample for the author)", "oos": "2010-01 .. 2020-12 (not shown by the author)", "post": "2026-06 .. 2026-10 (after the post)"},
                                "yearly": g.get("yearly"), "oos_buy_hold_pct": bh["GOLD_pre"], "dev_buy_hold_pct": bh["GOLD_author"], "costs": QCB["_meta"]["costs"]["gold"]}
            else:
                c["results"] = {"market": "XAUUSD mid at 15:58 New York (ADAPTATION of GLD)", "dev": summarize(g["dev"]), "oos": summarize(g["oos"]),
                                "oos_x2": summarize(res["XAUUSD_x2"]["oos"]), "oos_second": None, "yearly": g.get("yearly"),
                                "oos_buy_hold_pct": bh["GOLD_5079_oos"], "dev_buy_hold_pct": bh["GOLD_5079_dev"], "costs": QCB["_meta"]["costs"]["gold"]}
        elif res:
            b, e = res["BTC_USDT_spot"], res.get("ETH_USDT_spot", {})
            primary_eth = sid == "QC-15987"                 # its original market is ETH
            P, S = (e, b) if primary_eth else (b, e)
            c["results"] = {"market": ("ETH/USDT spot (original market ETHUSD)" if primary_eth else "BTC/USDT spot"),
                            "dev": summarize(P.get("dev")), "oos": summarize(P.get("oos")),
                            "oos_x2": summarize(res.get("BTC_USDT_spot_x2_oos")) if not primary_eth else None,
                            "oos_second": summarize(S.get("oos")), "second_market": "BTC/USDT" if primary_eth else "ETH/USDT",
                            "yearly": P.get("yearly"), "perp_adaptation": {"oos": summarize(res.get("BTC_perp_adaptation_oos"))} if res.get("BTC_perp_adaptation_oos") else None,
                            "oos_buy_hold_pct": bh["ETH_oos"] if primary_eth else bh["BTC_oos"], "costs": QCB["_meta"]["costs"]}
        cands.append(c)

    # articles and education
    for a in K.ARTICLE_CARDS:
        src = a["src"]
        page = ART / ("capital_gold.html" if src is K.CAP else "pepperstone_gold.html")
        c = {"sid": a["sid"], "name": a["name"], "group": "gold", "batch": True, "kind": "educational idea",
             "source": {"platform": src["platform"], "url": src["url"], "author": src["author"], "retrieved": RETRIEVED,
                        "licence": src["licence"], "version": "page sha256 " + hashlib.sha256(page.read_bytes()).hexdigest()},
             "market": {"class": src["class"], "original": "spot gold / gold CFDs (broker guide)", "timeframe": "not stated"},
             "hypothesis": {"tag": "I", "text": a["name"]},
             "rules": [{"kind": "setup", "tag": "E", "text": a["quote"], "loc": "§ " + a["sec"], "quote": a["quote"]}],
             "missing": a["missing"], "claims": [], "risks": [{"check": "specification", "finding": "Educational description: entry, exit and stop are not fully defined; not implemented (would require invented rules)."}],
             "dedupe": {"verdict": (a.get("dedupe") or ("new", ""))[0], "note": (a.get("dedupe") or ("new", "No exact duplicate; general ideas of this family exist across the library."))[1]},
             "sources_more": a.get("more", []), "status": "NEEDS_CLARIFICATION", "status_reason": "Missing: " + "; ".join(a["missing"])}
        cands.append(c)
    for a in K.TRADECIETY_READ:
        page = ART / f"tradeciety_{a['page']}.html"
        url = f"https://tradeciety.com/{a['page']}"
        cands.append({"sid": a["sid"], "name": a["name"], "group": "general", "batch": False, "kind": "educational idea",
                      "source": {"platform": K.TRADECIETY["platform"], "url": url, "author": "Tradeciety", "retrieved": RETRIEVED,
                                 "licence": K.TRADECIETY["licence"], "version": "page sha256 " + hashlib.sha256(page.read_bytes()).hexdigest()},
                      "market": {"class": "general_forex", "original": "general / forex (examples on EUR/USD and other FX)", "timeframe": "by example"},
                      "hypothesis": {"tag": "I", "text": a["name"]},
                      "rules": [{"kind": "setup", "tag": "E", "text": a["quote"], "loc": "§ " + a["sec"], "quote": a["quote"]}],
                      "missing": a["missing"], "claims": [], "risks": [{"check": "transfer", "finding": "Written for forex and markets in general: any gold or crypto version would be a labelled adaptation."}],
                      "dedupe": {"verdict": "new", "note": "Generic family (breakouts, sessions, zones, pullbacks) present across the library."},
                      "status": "NEEDS_CLARIFICATION", "status_reason": "Missing: " + "; ".join(a["missing"])})
    k = 0
    for page, names in K.TRADECIETY_DISCOVERED:
        for nm in names:
            k += 1
            cands.append({"sid": f"TC-D{k:02d}", "name": nm, "group": "general", "batch": False, "kind": "named setup (headings only)",
                          "source": {"platform": K.TRADECIETY["platform"], "url": f"https://tradeciety.com/{page}", "author": "Tradeciety", "retrieved": RETRIEVED,
                                     "licence": K.TRADECIETY["licence"], "version": "page sha256 " + hashlib.sha256((ART / f"tradeciety_{page}.html").read_bytes()).hexdigest()},
                          "market": {"class": "general_forex", "original": "general / forex", "timeframe": "-"}, "rules": [], "missing": ["not extracted in this batch"],
                          "status": "DISCOVERED", "status_reason": "Seen as a section heading; rules not extracted in this batch (generic forex education)."})
    # freqtrade classes outside the batch
    for r in INV["strategies"]:
        cls = r.get("class")
        if not cls or cls in BATCH_FT or cls in VARIATIONS:
            continue
        if cls in NOT_STRATEGIES:
            st, why = "REJECTED", "Not a trading strategy: " + NOT_STRATEGIES[cls]
        elif "/lookahead_bias/" in r["file"]:
            st, why = "REJECTED", "Published in the repository's lookahead_bias folder as an example of look-ahead bias" + (" (whole-column min/max normalisation, e.g. Zeus L102-104)" if cls == "Zeus" else "")
        else:
            st, why = "DISCOVERED", "Not selected for this batch (intraday-first selection; most are 1h+ swing or hyperopted templates)"
        cands.append({"sid": f"FT-{cls}", "name": cls, "group": "crypto", "batch": False, "kind": "code", "source": ft_source(cls),
                      "market": {"class": market_class(cls), "original": "crypto (freqtrade)", "timeframe": r["settings"].get("timeframe", {}).get("value")},
                      "rules": [], "status": st, "status_reason": why})
    for tid, nm in K.QC_DISCOVERED:
        cands.append({"sid": f"QC-{tid}", "name": nm, "group": "crypto", "batch": False, "kind": "code",
                      "source": {"platform": "QuantConnect forum", "url": f"{K.QC}/forum/discussion/{tid}/", "retrieved": RETRIEVED,
                                 "licence": "unknown (QuantConnect terms)"},
                      "market": {"class": "crypto_spot", "original": "crypto (QuantConnect)", "timeframe": "-"}, "rules": [],
                      "status": "DISCOVERED", "status_reason": "Strategy thread with code; not taken into this batch."})

    # statuses for the tested ones, then the gate
    for c in cands:
        if c.get("status"):
            continue
        r = c.get("results")
        if not r:
            c["status"], c["status_reason"] = "READY_FOR_BACKTEST", "Rules complete; not run in this batch."
            continue
        g = gate(c)
        c["gate"] = [{"check": a, "pass": b} for a, b in g]
        o = r.get("oos") or {}
        if c.get("lookahead"):
            c["status"], c["status_reason"] = "REJECTED", "Look-ahead bias in the source (see risks)."
        elif all(b is not False for _, b in g):
            c["status"], c["status_reason"] = "PAPER_TRADING_CANDIDATE", "Passed every gate check (still not validated)."
        elif o.get("ruined_on") or (o.get("trades") and o["net"] <= 0):
            both = (r.get("dev") or {}).get("net", 0) <= 0
            c["status"], c["status_reason"] = "REJECTED", (("Loses in both windows after costs" if both else "Loses out of sample after costs (the development window does not carry over)")
                                                           + (f"; a $10,000 account is empty by {o['ruined_on']}" if o.get("ruined_on") else "") + ".")
        else:
            fails = [a for a, b in g if b is False]
            c["status"], c["status_reason"] = "BACKTESTED", "Fails: " + "; ".join(fails) + "."

    # ranking for further research: evidence first, then out-of-sample strength, sample size and drawdown
    tier = {"PAPER_TRADING_CANDIDATE": 0, "BACKTESTED": 1, "READY_FOR_BACKTEST": 2, "READY_FOR_IMPLEMENTATION": 3, "BLOCKED": 4,
            "NEEDS_CLARIFICATION": 5, "REJECTED": 6, "DISCOVERED": 7}

    def key(c):
        g = sum(1 for x in c.get("gate", []) if x["pass"] is True)
        o = (c.get("results") or {}).get("oos") or {}
        return (tier[c["status"]], 0 if c.get("batch") else 1, -g, -(o.get("t_stat") or -99), -(o.get("trades") or 0), -(o.get("max_dd_pct") or -100))

    cands.sort(key=key)
    for i, c in enumerate(cands, start=1):
        c["rank"] = i
    out = {"study": "web_sources_2026_11", "built": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "retrieved": RETRIEVED,
           "freqtrade_commit": COMMIT, "gate": GATE, "buy_hold": bh, "candidates": cands,
           "screened": K.SCREENED, "counts": {}}
    batch = [c for c in cands if c.get("batch")]
    out["counts"] = {"crypto_batch": sum(1 for c in batch if c["group"] == "crypto"), "gold_batch": sum(1 for c in batch if c["group"] == "gold"),
                     "general_read": len(K.TRADECIETY_READ), "variations": len(VARIATIONS), "total_records": len(cands),
                     "by_status": {s: sum(1 for c in cands if c["status"] == s) for s in tier},
                     "batch_by_status": {s: sum(1 for c in batch if c["status"] == s) for s in tier}}
    (HERE / "registry" / "candidates.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    write_md(out)
    write_evidence(out)
    print(json.dumps(out["counts"], indent=1))


def fmt(v, d=0, pct=False):
    if v is None:
        return "–"
    return f"{v:,.{d}f}{'%' if pct else ''}"


def write_md(out: dict) -> None:
    L = ["# Web-sourced crypto and gold strategies — inventory (generated by ws_records.py; do not edit by hand)", "",
         f"Built {out['built']}; sources retrieved {out['retrieved']}; freqtrade-strategies commit `{out['freqtrade_commit']}`.", "",
         "Batch: " + ", ".join(f"{k} {v}" for k, v in out["counts"]["batch_by_status"].items() if v) + ".", "",
         "| Rank | ID | Strategy | Market | Status | OOS trades | OOS net $ | OOS t | Why |", "|---|---|---|---|---|---|---|---|---|"]
    for c in out["candidates"]:
        if not c.get("batch") and c["status"] in ("DISCOVERED",):
            continue
        o = (c.get("results") or {}).get("oos") or {}
        L.append(f"| {c['rank']} | {c['sid']} | {c['name']} | {c['market']['class']} | {c['status']} | {o.get('trades', '–')} | "
                 f"{fmt(o.get('net'))} | {fmt(o.get('t_stat'), 2)} | {c.get('status_reason', '')[:140]} |")
    L += ["", "## Sources screened without a strategy", ""] + [f"- **{s['source']}** — {s['result']}: {s['why']}" for s in out["screened"]]
    L += ["", "## Paper-trading gate (all must hold)", ""] + [f"{i + 1}. {g}" for i, g in enumerate(out["gate"])]
    (HERE / "registry" / "INVENTORY.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def write_evidence(out: dict) -> None:
    ev = HERE / "evidence"
    ev.mkdir(exist_ok=True)
    for c in out["candidates"]:
        if not c.get("rules"):
            continue
        s = c["source"]
        L = [f"# {c['sid']} — {c['name']}", "", f"- Source: {s.get('platform')} — {s.get('url')}", f"- Author: {s.get('author', '–')}",
             f"- Retrieved: {s.get('retrieved')}", f"- Licence / attribution: {s.get('licence')}", f"- Version: {s.get('version')}"
             + (f"; file sha256 {s['file_sha256']}" if s.get("file_sha256") else ""), "",
             "| Kind | Tag | Rule | Where | Excerpt |", "|---|---|---|---|---|"]
        for r in c["rules"]:
            q = (r.get("quote") or "").replace("|", "\\|")
            L.append(f"| {r['kind']} | {r['tag']} | {r['text'].replace('|', '/')} | {r['loc']} | `{q[:300]}` |" if q else
                     f"| {r['kind']} | {r['tag']} | {r['text'].replace('|', '/')} | {r['loc']} | |")
        (ev / f"{c['sid']}.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
