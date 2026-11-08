"""Writes frontend/app/premium-strategies/library.ts: every strategy of the two YouTube studies, with its rules (from the
pre-registrations), the variant the paper desk trades, and its hold-out result (from results/summary.json).
    python -I build_library.py"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
R = ROOT / "backend" / "research"
sys.path.insert(0, str(HERE))
from catalog import ACCOUNTS, BB, LABEL, YT  # noqa: E402

BBD, YTD = R / "booming_bulls_2026_11", R / "youtube_top20_2026_11"
VIDEOS = {}
sys.path.insert(0, str(YTD))
sys.path.insert(0, str(BBD))
import bb_strategies as BS  # noqa: E402
import yt_strategies as YS  # noqa: E402

for k, s in BS.STRATEGIES.items():
    VIDEOS[k] = list(s.videos)
for k, s in YS.STRATEGIES.items():
    VIDEOS[k] = list(s.videos)
VIDEOS["BB-15"] = ["T_VlPXyqj0U"]

summary = {}
for d in (BBD, YTD):
    for r in json.loads((d / "results" / "summary.json").read_text())["rows"]:
        if r.get("chosen"):
            summary[(r["strategy"], r["market"])] = r


def tidy(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("**", "").replace("`", "")).strip()


def parse_block(lines: list[str]) -> tuple[list[dict], dict]:
    """(rules as label/text pairs, variant tag -> change)."""
    rules: list[dict] = []
    variants: dict = {}
    for ln in lines:
        s = ln.rstrip()
        if not s.strip() or set(s.strip()) <= set("|-: "):
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] != "Variant":
                variants[cells[0]] = tidy(cells[1])
            continue
        m = re.match(r"^(\s*)[-*] \*\*(.+?)\*\*:?\s*(.*)$", s)
        if m and not m.group(1):
            rules.append({"label": tidy(m.group(2)).rstrip(":"), "text": tidy(m.group(3))})
            continue
        m = re.match(r"^(\s*)[-*] (.*)$", s)
        if m:
            text = tidy(m.group(2))
            if m.group(1) and rules:
                rules[-1]["text"] = (rules[-1]["text"] + " " + text).strip()
            else:
                rules.append({"label": "", "text": text})
            continue
        m = re.match(r"^\*\*(.+?)\*\*:?\s*(.*)$", s)
        if m:
            if m.group(2).strip():
                rules.append({"label": tidy(m.group(1)).rstrip(":"), "text": tidy(m.group(2))})
            continue                                   # a bare bold line is only a sub-heading
        rules.append({"label": "", "text": tidy(s)})
    return [r for r in rules if r["text"]], variants


def bb_sections() -> dict:
    txt = (BBD / "specs" / "PREREGISTRATION.md").read_text(encoding="utf-8").splitlines()
    out, cur = {}, None
    for ln in txt:
        m = re.match(r"^### (BB-\d+)\b", ln)
        if m:
            cur = m.group(1)
            out[cur] = []
            continue
        if re.match(r"^##+ ", ln):
            cur = None
        elif cur:
            out[cur].append(ln)
    return out


def yt_sections() -> dict:
    txt = (YTD / "specs" / "PREREGISTRATION.md").read_text(encoding="utf-8").splitlines()
    out, cur = {}, None
    for ln in txt:
        m = re.match(r"^\*\*(YT-\d+[ab]?)\b(.*)$", ln)
        if m:
            cur = m.group(1)
            out[cur] = []
            continue
        if re.match(r"^##+ ", ln):
            cur = None
        elif cur:
            out[cur].append(ln)
    return out


secs = {**bb_sections(), **yt_sections()}
VERDICT = {"not supported": "Not supported", "needs more evidence": "Needs more evidence", "unable to evaluate": "Too few trades to judge"}
ORDER = {"Needs more evidence": 0, "Too few trades to judge": 1, "Not supported": 2}
out = []
missing = []
for a in ACCOUNTS:
    if a.source not in (BB, YT):
        continue
    lines = secs.get(a.id)
    if lines is None:
        missing.append(a.id)
        lines = []
    rules, variants = parse_block(lines)
    books = []
    for market, v in a.books:
        r = summary.get((a.id, market))
        h = (r or {}).get("hold") or {}
        books.append({"market": LABEL[market], "variant": v, "change": variants.get(v, ""),
                      "cls": VERDICT.get((r or {}).get("class"), "Not tested"), "n": h.get("n"),
                      "meanR": h.get("mean_r"), "grossR": h.get("mean_r_gross"),
                      "winRate": None if h.get("win_rate") is None else round(100 * h["win_rate"], 1)})
    vs = {b["cls"] for b in books}
    verdict = "Not tested" if "Not tested" in vs else min(vs, key=lambda x: ORDER[x])
    out.append({"id": a.id, "source": a.source, "name": a.name, "channel": a.channel, "videos": VIDEOS.get(a.id, []),
                "verdict": verdict, "books": books, "rules": rules})
# The Crypto Trading playlist (backend/research/crypto_playlist_2026_11): rules from specs/RULES.md, no backtest.
CPD = R / "crypto_playlist_2026_11"
cp_secs, cp_vids, cur = {}, {}, None
for ln in (CPD / "specs" / "RULES.md").read_text(encoding="utf-8").splitlines():
    mm = re.match(r"^### (CP-\d+) (.+?) \(([^)]*)\)\s*$", ln)
    if mm:
        cur = mm.group(1)
        cp_secs[cur] = []
        cp_vids[cur] = re.findall(r"[A-Za-z0-9_-]{11}", mm.group(3))
        continue
    if re.match(r"^##+ ", ln):
        cur = None
    elif cur:
        cp_secs[cur].append(ln)
for a in ACCOUNTS:
    if a.source != "crypto_playlist":
        continue
    rules, _ = parse_block(cp_secs.get(a.id, []))
    if a.id not in cp_secs:
        missing.append(a.id)
    out.append({"id": a.id, "source": a.source, "name": a.name, "channel": a.channel, "videos": cp_vids.get(a.id, []),
                "verdict": "Paper test only", "books": [{"market": LABEL[mk], "variant": v, "change": "", "cls": "Paper test only",
                                                          "n": None, "meanR": None, "grossR": None, "winRate": None} for mk, v in a.books],
                "rules": rules})
# The liquidity-sweep study (backend/research/liquidity_sweep_2026_11): the app's strategy D9 and its versions. The
# change per version comes from PREREGISTRATION_VERSIONS.md and the numbers from results/versions/summary.json. The
# "hold-out" columns show the last test period, 24 Sep 2025 to 23 Oct 2026 (the PDF's own period).
LSD = R / "liquidity_sweep_2026_11"
ls_change: dict = {}
for ln in (LSD / "PREREGISTRATION_VERSIONS.md").read_text(encoding="utf-8").splitlines():
    mm = re.match(r"^\| (v\d\d|r\d) \| (.+?) \| (.+?) \|\s*$", ln)
    if mm:
        vid, col2, col3 = mm.groups()
        ls_change[vid] = tidy(col3 if vid.startswith("v") else col2)
ls_runs = json.loads((LSD / "results" / "versions" / "summary.json").read_text(encoding="utf-8"))["versions"]


def _r(x) -> str:
    return "—" if x is None else f"{x:+.2f}R"


LS_RULES = [
    {"label": "Levels", "text": "Previous day's high, low and close; equal highs or lows (two swings within 0.04%); 1-hour swing "
                               "highs and lows. Levels that the open gaps through are dropped, and each level is used once."},
    {"label": "Sweep", "text": "A 5-minute candle trades beyond a level."},
    {"label": "Confirmation", "text": "A candle closes back inside within 30 minutes. If it does not, the break was accepted: a "
                                     "breakout, which is never traded."},
    {"label": "Entry", "text": "At that close: short after a high is swept, long after a low is swept."},
    {"label": "Stop and target", "text": "Stop 0.02% beyond the sweep's extreme, target 2R. The trade is skipped unless the risk "
                                        "is 0.05-0.35% of price."},
    {"label": "Day", "text": "Entries 09:20-14:45, one trade at a time, at most 2 a day, out at 15:15."},
]
for a in ACCOUNTS:
    if a.source != "liquidity_sweep":
        continue
    market, vid = a.books[0]
    run = ls_runs[vid]
    per = run["periods"]
    s, v, p = per["S"], per["V"], per["P"]
    rules = list(LS_RULES) + [
        {"label": "This version", "text": "None: this is the original." if vid == "v00" else ls_change.get(vid, "")},
        {"label": "Backtest", "text": f"Net of costs: 2016-22 {_r(s.get('mean_r_net'))}, 2023 to Sep 2025 {_r(v.get('mean_r_net'))}, "
                                     f"24 Sep 2025 to 23 Oct 2026 {_r(p.get('mean_r_net'))} a trade ({p.get('trades', 0)} trades). Before "
                                     f"costs {_r(s.get('mean_r_gross'))}, {_r(v.get('mean_r_gross'))}, {_r(p.get('mean_r_gross'))}. "
                                     "Verdict: no edge."},
        {"label": "Costs", "text": "One futures lot: Angel One's charges on the trade date plus 1 index point of slippage a fill."},
    ]
    if vid not in ls_change:
        missing.append(a.id)
    out.append({"id": a.id, "source": a.source, "name": a.name, "channel": a.channel, "videos": ["iTWMIaqYLJg"],
                "verdict": "Not supported",
                "books": [{"market": LABEL[market], "variant": vid, "change": ls_change.get(vid, ""), "cls": "Not supported",
                           "n": p.get("trades"), "meanR": p.get("mean_r_net"), "grossR": p.get("mean_r_gross"),
                           "winRate": p.get("win_rate_net")}],
                "rules": rules})
print("strategies", len(out), "without rule text:", missing)
head = '''// GENERATED by premium-paper-service/build_library.py - do not edit by hand.
// The strategies of the Booming Bulls and YouTube top-20 studies: rules from their pre-registrations, results from their
// saved hold-out tests. The paper desk trades exactly the variant named on each market.

export type LibRule = { label: string; text: string };
export type LibBook = { market: string; variant: string; change: string; cls: string; n: number | null; meanR: number | null;
  grossR: number | null; winRate: number | null };
export type LibStrategy = { id: string; source: "booming_bulls" | "youtube_top20" | "crypto_playlist" | "liquidity_sweep"; name: string; channel: string; videos: string[];
  verdict: string; books: LibBook[]; rules: LibRule[] };

export const LIBRARY: LibStrategy[] = '''
(ROOT / "frontend" / "app" / "premium-strategies" / "library.ts").write_text(head + json.dumps(out, indent=1, ensure_ascii=False) + ";\n", encoding="utf-8", newline="\n")
