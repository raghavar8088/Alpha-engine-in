"""Candidate videos for the channel-shortlist study, from the Trading Video Lab's catalogue of each channel (titles,
durations, views and the Lab's title classifier; nothing is watched here).
    python -I ze_select.py      -> registry/candidates.json, registry/CANDIDATES.md

A candidate is a public video or live stream (no Shorts) of 5-120 minutes whose title the Lab's classifier marks P1
(a strategy word plus a setup family) or P2 with a setup word, that is not a re-upload, not a market call, and not
covered by an earlier study (selected, cited or analysed - captions saved without a reading do not count).
Candidates are ranked by a title score fixed BEFORE any video is read:
  +2 a named indicator or level (RSI, EMA, VWAP, Supertrend, CPR, pivots, ...)   +2 a clock or session anchor
  +2 intraday / scalping / opening range / VWAP family                          +1 a timeframe in minutes
  +1 a setup word (breakout, pullback, reversal, gap, retest, trap, sweep)      +1 tested / backtest / win rate
  -3 live trading, recap, prediction, outlook, psychology, mindset, motivation, Q&A, news
  + log10(views + 10)                                                           +1 published in the last 2 years
The final pick per channel is made by reading the ranked titles (registry/SELECTION.md records the pick and why)."""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[2] / "youtube-video-explainer-reviewed"

IND = re.compile(r"\b(rsi|ema|sma|macd|vwap|super ?trend|bollinger|adx|atr|stoch|stochastic|cpr|pivot|ichimoku|fib|fibonacci|"
                 r"heikin|moving average|\d+ ?ema|\d+ ?sma|keltner|donchian|parabolic|sar|obv|mfi|cci|williams|ttm|squeeze|"
                 r"volume profile|vwma|hull|alligator|camarilla|vpoc|poc|order block|fvg|fair value gap|previous day high)\b", re.I)
CLOCK = re.compile(r"\b(9[:.]?1[05]|9[:.]?20|9[:.]?30|10[:.]?00|opening range|orb|first (5|15|30|five|fifteen|thirty)[ -]?min|"
                   r"first (hour|candle)|london (open|session)|new york (open|session)|ny (open|session)|asian (range|session)|"
                   r"market open|opening bell|power hour|closing)\b", re.I)
TF = re.compile(r"\b\d+[ -]?(min|minute|minutes|m)\b|\b(1|5|15|30)m\b|\bhourly\b|\b4h\b|\b1h\b", re.I)
SETUP = re.compile(r"\b(breakout|break ?out|pullback|pull ?back|reversal|gap|retest|trap|sweep|range|scalp|scalping|momentum|"
                   r"trend|crossover|cross ?over|divergence|engulfing|inside bar|pin ?bar|rejection|liquidity)\b", re.I)
TEST = re.compile(r"\b(backtest|back ?tested|tested|win ?rate|100 times|results?|statistics|stats|proven|data)\b", re.I)
BAD = re.compile(r"\b(live trading|live trade|recap|prediction|outlook|psychology|mindset|motivation|q ?& ?a|news|vlog|"
                 r"podcast|giveaway|budget|ipo|mutual fund|tax|interview with|market update|weekly analysis|"
                 r"tomorrow|kal ka|aaj ka)\b", re.I)
INTRA = {"Scalping and intraday", "Opening range", "VWAP", "Previous-day high/low", "Gap trading"}
TODAY = date(2026, 11, 13)


def strict_covered() -> set:
    cov = json.loads((HERE / "registry" / "covered.json").read_text(encoding="utf-8"))
    return {v for v, e in cov["videos"].items() if set(e["kinds"]) & {"selected", "cited", "analyzed"}}


def score(e: dict) -> float:
    t = e["title"]
    s = 0.0
    s += 2 if IND.search(t) else 0
    s += 2 if CLOCK.search(t) else 0
    s += 2 if (set(e.get("families") or []) & INTRA or re.search(r"intraday|scalp|day ?trad", t, re.I)) else 0
    s += 1 if TF.search(t) else 0
    s += 1 if SETUP.search(t) else 0
    s += 1 if TEST.search(t) else 0
    s -= 3 if BAD.search(t) else 0
    s += math.log10((e.get("views") or 0) + 10)
    if e.get("published"):
        try:
            if (TODAY - date.fromisoformat(e["published"])).days <= 730:
                s += 1
        except ValueError:
            pass
    return round(s, 2)


def main() -> None:
    reg = json.loads((HERE / "registry" / "channels.json").read_text(encoding="utf-8"))
    covered = strict_covered()
    out, md = {}, ["# Candidate videos per channel (ranked by title score; nothing watched yet)", "",
                   "Columns: score | video id | minutes | views | published | title. `cov` = videos of this channel already",
                   "covered by an earlier study.", ""]
    for key, r in reg.items():
        ids = [r["pick"]] + [x["id"] for x in r.get("extra", [])] if r.get("pick") else []
        entries, titles = [], []
        for cid in ids:
            f = LAB / "data" / "channels" / f"{cid}.json"
            if f.exists():
                cat = json.loads(f.read_text(encoding="utf-8"))
                entries += cat["entries"]
                titles.append(cat["channel"]["title"])
        if not entries:
            out[key] = {"key": key, "name": r["name"], "listed": False}
            md += [f"## {key} - {r['name']}: NOT LISTED", ""]
            continue
        vids = [e for e in entries if e["kind"] in ("video", "stream")]
        p1 = [e for e in vids if e.get("priority") == "P1" and not e.get("dup_of")]
        cov = [e["id"] for e in vids if e["id"] in covered]
        cand = []
        for e in vids:
            if e.get("dup_of") or e.get("calls") or e["id"] in covered:
                continue
            if not (300 <= (e.get("duration") or 0) <= 7200):
                continue
            if e.get("priority") == "P1" or (e.get("priority") == "P2" and SETUP.search(e["title"])):
                cand.append({**{k: e.get(k) for k in ("id", "title", "duration", "views", "published", "priority", "families", "market")},
                             "score": score(e)})
        cand.sort(key=lambda c: -c["score"])
        out[key] = {"key": key, "name": r["name"], "titles": titles, "star": r["star"], "group": r["group"], "earlier": r["earlier"],
                    "listed": True, "videos": len(vids), "p1": len(p1), "covered": cov, "candidates": cand[:25]}
        md += [f"## {key} - {r['name']} ({' + '.join(titles)}) {'*' if r['star'] else ''} [{r['group']}] "
               f"{('earlier: ' + r['earlier']) if r['earlier'] else ''}",
               f"videos {len(vids)}, P1 {len(p1)} ({100 * len(p1) / max(1, len(vids)):.0f}%), candidates {len(cand)}, cov {len(cov)}"]
        for c in cand[:8]:
            md.append(f"- {c['score']:5.2f} | {c['id']} | {round((c['duration'] or 0) / 60)}m | {c['views'] or 0} | "
                      f"{c['published'] or '-'} | {c['title'][:110]}")
        md.append("")
    (HERE / "registry" / "candidates.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    (HERE / "registry" / "CANDIDATES.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    listed = [v for v in out.values() if v.get("listed")]
    print("channels listed", len(listed), "of", len(out), "| candidates", sum(len(v["candidates"]) for v in listed))


if __name__ == "__main__":
    main()
