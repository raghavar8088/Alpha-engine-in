"""Writes frontend/app/youtube-live/liveData.ts (the YouTube Live Streaming page's data) from the survey files.

    python -I export_live.py

Reads, next to this file: summary.json (pass 1), summary2.json (pass 2), recount.json (survey.py --recount),
raw/streams_*.json (handles), raw/video_*.json (stream descriptions -> brokers linked), and channels.py (which
channels, which table, a note, account shown). Marks channels the app's YouTube study already covers by reading
frontend/app/premium-strategies/ytChannelsData.ts at origin/main (the working tree's copy if git is unavailable).
"""
import json, re, subprocess, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))  # only this folder's own scripts
from channels import CHANNELS, ROBOT_CHANNELS, TV_CHANNELS, PROBE, MARKETS_SEEN  # noqa: E402
from survey import slug  # noqa: E402

OUT = REPO / "frontend" / "app" / "youtube-live" / "liveData.ts"
STUDY = "frontend/app/premium-strategies/ytChannelsData.ts"
IST = timezone(timedelta(hours=5, minutes=30))

# Matched against each link in a stream's description (lower case). Shorteners hide some (bit.ly), so this is a floor.
BROKERS = [("delta.exchange", "Delta Exchange"), ("zuperior", "Zuperior"), ("exness", "Exness"), ("vigco.co", "Vantage"),
           ("vantage", "Vantage"), ("affs.click", "XM"), ("xm.com", "XM"), ("elefin", "Elefin"),
           ("coinswitch", "CoinSwitch"), ("coindcx", "CoinDCX"), ("sharkexchange", "Shark Exchange"),
           ("sharkapp", "Shark Exchange"), ("suncrypto", "SunCrypto"), ("dhan.co", "Dhan"), ("indstocks", "INDstocks"),
           ("bingx", "BingX"), ("bitget", "Bitget"), ("bitunix", "Bitunix"), ("blofin", "BloFin"), ("bitbase", "BitBase"),
           ("bybit", "Bybit"), ("toobit", "Toobit"), ("btcc.com", "BTCC"), ("weex", "WEEX"), ("binance", "Binance"),
           ("mexc", "MEXC"), ("primexbt", "PrimeXBT"), ("pepperstone", "Pepperstone"), ("risenfx", "RisenFX"),
           ("ninjatrader", "NinjaTrader")]
ROBOT_RE = re.compile(r"24/7|24x7|\bAI\b|signals?\b|\balgo\b|educational|dashboard|indicator|bookmap|heatmap|"
                      r"liquidation watch|robot|expert advisor|auto trading|notifications|market monitor|analy[sz]er|"
                      r"live chart|\bm(1|5|15)\b[^|]*chart", re.I)


def load(name):
    p = HERE / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def study_text():
    try:
        return subprocess.run(["git", "show", f"origin/main:{STUDY}"], cwd=REPO, capture_output=True, text=True,
                              encoding="utf-8", check=True).stdout
    except Exception:
        return (REPO / STUDY).read_text(encoding="utf-8")


def study_of(text, cid):
    i = text.find(f'"id":"{cid}"')
    if i < 0:
        return "", []
    j = text.find('{"id":"UC', i + 10)
    seg = text[i: j if j > 0 else i + 4000]
    m = re.search(r'"studies":\[([^\]]*)\]', seg)
    if m:
        return "studied", re.findall(r'"([^"]+)"', m.group(1))
    return ("listed", []) if '"reason":' in seg else ("", [])


def descriptions_by_channel():
    """Newest stream description per channel id (the survey read one stream's metadata per channel)."""
    best = {}
    for p in (HERE / "raw").glob("video_*.json"):
        d = json.loads(p.read_text(encoding="utf-8") or "{}") or {}
        cid = d.get("channel_id")
        if cid and (cid not in best or (d.get("release_timestamp") or 0) > (best[cid].get("release_timestamp") or 0)):
            best[cid] = d
    return {cid: d.get("description") or "" for cid, d in best.items()}


def brokers_of(desc):
    links = " ".join(re.findall(r"https?://\S+", desc or "")).lower()
    names = []
    for key, name in BROKERS:
        if key in links and name not in names:
            names.append(name)
    return names


MARKETS = [("Gold", r"gold|\bxau|paxg|xaut"), ("Silver", r"silver|\bxag"), ("BTC", r"\bbtc|bitcoin"),
           ("ETH", r"\beth\b|ethereum"), ("Altcoins", r"altcoin|\bxrp\b|\bsol\b|solana|\bdoge|\bhype\b"),
           ("Forex", r"forex|\bfx\b|eurusd|gbpusd|usdjpy|currenc"),
           ("US indices", r"nasdaq|\bnq\b|s&p|\bspx\b|\bqqq\b|\bspy\b|\bdow\b|\bus30\b|\bus100\b"),
           ("DAX/FTSE", r"\bdax\b|ftse"), ("Crude/gas", r"crude|natural ?gas|naturalgas"),
           ("NIFTY", r"nifty|sensex")]
# what the newest stream's description sells or links to (phrases like "no courses, no call tips" removed first)
SELLS = [("VIP group", r"\bvip\b"), ("Course", r"course|masterclass|mentorship|live classes|university"),
         ("Signals", r"signal"), ("Robot", r"trading robot|my robot|\brobot\b|expert advisor"),
         ("Indicator", r"indicator|setup access")]
NEGATED = re.compile(r"no (paid )?(courses?|call tips|paid services|signals?)", re.I)
GAP_MIN = 60  # start times further apart than this on the clock are separate daily slots
MIN_STREAM_S = 600  # a broadcast shorter than 10 minutes is an aborted start, not a stream


def ist(ts):
    return datetime.fromtimestamp(ts, IST)


def circ_mean(mins):
    import math
    if not mins:
        return None, None
    a = [m / 1440 * 2 * math.pi for m in mins]
    s, c = sum(math.sin(x) for x in a) / len(a), sum(math.cos(x) for x in a) / len(a)
    r = max(min(math.hypot(s, c), 1.0), 1e-9)
    mean = (math.atan2(s, c) / (2 * math.pi) * 1440) % 1440
    spread = math.sqrt(-2 * math.log(r)) / (2 * math.pi) * 1440
    return mean, spread


def hhmm(m):
    m = int(round(m)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def slots_of(rows):
    """Cluster start times on the 24-hour clock; return the daily slots that hold at least a fifth of the streams."""
    pts = sorted(((ist(r["start"]).hour * 60 + ist(r["start"]).minute, r) for r in rows), key=lambda p: p[0])
    if not pts:
        return []
    n = len(pts)
    gaps = [((pts[(i + 1) % n][0] - pts[i][0]) % 1440 or (1440 if n == 1 else 0)) for i in range(n)]
    cut = max(range(n), key=lambda i: gaps[i])  # the largest gap separates the last slot from the first
    order = [pts[(cut + 1 + k) % n] for k in range(n)]
    groups, cur = [], [order[0]]
    for a, b in zip(order, order[1:]):
        if (b[0] - a[0]) % 1440 > GAP_MIN:
            groups.append(cur)
            cur = []
        cur.append(b)
    groups.append(cur)
    out = []
    for g in sorted(groups, key=len, reverse=True):
        if len(g) < max(2, 0.2 * n) and out:
            continue  # an odd one-off start; the slots that repeat are what a viewer can plan around
        starts = [m for m, _ in g]
        ends = [(m + (r["duration"] or 0) / 60) % 1440 for m, r in g if r.get("duration")]
        ms, sp = circ_mean(starts)
        me, _ = circ_mean(ends)
        out.append({"start": hhmm(ms), "end": hhmm(me) if me is not None else None, "startMin": round(ms),
                    "endMin": round(me) if me is not None else None, "n": len(g), "share": round(len(g) / n, 2),
                    "spreadMin": round(sp)})
    return sorted(out[:3], key=lambda s: s["startMin"])


def schedule_of(rows, read_at):
    rows = [r for r in rows if r.get("start") and (r.get("duration") or 0) >= MIN_STREAM_S]
    if not rows:
        return None
    end_day = ist(read_at).date() - timedelta(days=1)  # the survey ran just after midnight: count whole days
    days = [end_day - timedelta(days=k) for k in range(14)]
    first = min(ist(r["start"]).date() for r in rows)
    capped = len(rows) >= 30
    covered = [d for d in days if not capped or d >= first]
    live_days = {ist(r["start"]).date() for r in rows}
    hit = [d for d in covered if d in live_days]
    wk = [d for d in covered if d.weekday() < 5]
    we = [d for d in covered if d.weekday() >= 5]
    wk_hit = sum(1 for d in wk if d in live_days)
    we_hit = sum(1 for d in we if d in live_days)
    in_window = [r for r in rows if ist(r["start"]).date() in set(covered)]
    ratio = len(hit) / len(covered) if covered else 0
    if ratio >= 0.9:
        label = "Every day"
    elif wk and wk_hit == len(wk):
        label = "Every weekday"
    elif wk and wk_hit / len(wk) >= 0.8 and we_hit <= 1:
        label = "Weekdays"
    elif ratio >= 0.6:
        label = "Most days"
    elif ratio >= 0.25:
        label = "Some days"
    elif hit:
        label = "Rarely"
    else:
        label = "Not in 14 days"
    per_day = len(in_window) / len(hit) if hit else 0
    durs = sorted(r["duration"] for r in rows if r.get("duration"))
    last = max(rows, key=lambda r: r["start"])
    recent = sorted(rows, key=lambda r: r["start"], reverse=True)[:6]
    return {"daysLive": len(hit), "daysCovered": len(covered), "weekdaysLive": wk_hit, "weekdays": len(wk),
            "weekendLive": we_hit, "weekendDays": len(we), "pattern": label, "perDay": round(per_day, 1),
            "slots": slots_of(rows), "streamsRead": len(rows),
            "medianHours": round(durs[len(durs) // 2] / 3600, 1) if durs else None,
            "latest": ist(last["start"]).strftime("%Y-%m-%d %H:%M"),
            "recent": [f"{ist(r['start']).strftime('%a %d %b %H:%M')}–{ist(r['start'] + r['duration']).strftime('%H:%M')}"
                       for r in recent]}


def markets_of(titles, extra=()):
    found = list(extra)
    ts = [t.lower() for t in titles if t]
    for name, rx in MARKETS:
        k = sum(1 for t in ts if re.search(rx, t))
        if ts and k / len(ts) >= 0.2 and name not in found:
            found.append(name)
    return found


def sells_of(desc):
    d = NEGATED.sub(" ", desc or "").lower()
    out = [name for name, rx in SELLS if re.search(rx, d)]
    if "t.me/" in d or "telegram" in d:
        out.append("Telegram")
    if "whatsapp" in d:
        out.append("WhatsApp")
    return out


def kind(row):
    ch = row.get("channel") or ""
    if ch in TV_CHANNELS:
        return "tv"
    if ch in ROBOT_CHANNELS or ROBOT_RE.search(row.get("title") or ""):
        return "robot"
    return "person"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    s1, s2, recount = load("summary.json"), load("summary2.json"), load("recount.json")
    checks = {}
    for c in s1.get("channels", []) + s1.get("discovered", []) + s2.get("checks", []):
        checks[c["target"]] = c
        if c.get("channel_id"):
            checks[c["channel_id"]] = c
    for cid, c in recount.items():  # a fuller count for a channel at pass 1's 60-stream cap
        base = checks.get(cid) or {}
        merged = {**base, **{k: v for k, v in c.items() if v is not None}}
        checks[cid] = merged
        if base.get("target"):
            checks[base["target"]] = merged
    found = {}
    for _name, hits in s2.get("found", []):
        for h in hits:
            if h.get("channel_id"):
                found.setdefault(h["channel_id"], h)
    descs = descriptions_by_channel()
    sched_file = load("schedule.json")
    sched_rows, read_at = sched_file.get("streams", {}), sched_file.get("read_at") or 0
    text = study_text()

    out = []
    for target, (group, shows, note) in CHANNELS.items():
        c = checks.get(target, {"target": target, "error": "not surveyed"})
        raw_p = HERE / "raw" / f"streams_{slug(target)}.json"
        raw = (json.loads(raw_p.read_text(encoding="utf-8") or "{}") or {}) if raw_p.exists() else {}
        cid = c.get("channel_id") or raw.get("channel_id") or (target if target.startswith("UC") else None)
        hit = found.get(cid or "", {})
        handle = raw.get("uploader_id") or (target if target.startswith("@") else None)
        name = c.get("name") or raw.get("channel") or hit.get("title") or target
        subs = c.get("subs") if c.get("subs") is not None else hit.get("subs")
        page = f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{cid}"
        desc = descs.get(cid or "", "")
        bro = brokers_of(desc)
        if any("delta exchange" in (t or "").lower() for t in c.get("titles", [])) and "Delta Exchange" not in bro:
            bro.append("Delta Exchange")
        entries = raw.get("entries") or []
        titles30 = [e.get("title") for e in entries if e.get("live_status") in ("was_live", "is_live")
                    and (not e.get("timestamp") or (time.time() - e["timestamp"]) / 86400 <= 31)]
        markets = markets_of(titles30 or (c.get("titles") or []), MARKETS_SEEN.get(target, ()))
        sched = schedule_of(sched_rows.get(target, []), read_at) if group != "gone" else None
        study, studies = study_of(text, cid) if cid else ("", [])
        last = c.get("last_stream_days")
        no_tab = "does not have a streams tab" in (c.get("error") or "")
        out.append({
            "id": cid, "name": name.strip(), "handle": handle, "url": page + ("/streams" if not no_tab else ""),
            "group": group, "subs": subs, "lives30": 0 if no_tab else c.get("n30"), "lives7": 0 if no_tab else c.get("n7"),
            "lastDays": last, "monthsSince": round(last / 30.44) if last is not None else None, "never": no_tab,
            "hours": (sched or {}).get("medianHours") or c.get("median_len_h"), "avgViews": c.get("avg_views_last10"),
            "brokers": bro, "shows": shows, "note": note, "titles": [t for t in (c.get("titles") or [])[:3] if t],
            "study": study, "studies": studies, "markets": markets, "sells": sells_of(desc) if desc else None,
            "sched": sched,
        })
        if c.get("error") and not no_tab:
            print(f"WARN {target}: {c['error']}")
    order = {"hindi": 0, "crypto": 1, "fx": 2, "gone": 3}
    out.sort(key=lambda r: (order[r["group"]], -(r["avgViews"] or 0)))

    live = []
    for r in s1.get("live_now", []):
        live.append({"watching": r.get("watching") or 0, "channel": (r.get("channel") or "").strip() or None,
                     "handle": r.get("handle"), "title": re.sub(r"\s+", " ", r.get("title") or "").strip(),
                     "kind": kind(r), "url": f"https://www.youtube.com/watch?v={r['id']}"})
    live.sort(key=lambda r: -r["watching"])

    stamps = [p.stat().st_mtime for p in (HERE / n for n in ("summary.json", "summary2.json", "summary3.json",
                                                              "recount.json", "schedule.json")) if p.exists()]
    run_at = s1.get("run_at_ist", "")
    survey = {
        "snapshotAt": run_at[:16].replace("T", " ") + " IST",
        "readUntil": datetime.fromtimestamp(max(stamps), IST).strftime("%Y-%m-%d %H:%M IST") if stamps else "",
        "queries": [q for q in ("gold live trading", "xauusd live trading", "gold scalping live", "forex live trading",
                                "bitcoin live trading", "crypto live trading", "btc live trading", "day trading live",
                                "live trading hindi", "gold live trading hindi", "crypto live trading hindi",
                                "forex live trading hindi")],
        "liveStreams": len(live), "livePeople": sum(1 for r in live if r["kind"] == "person"),
        "liveRobots": sum(1 for r in live if r["kind"] == "robot"), "liveTv": sum(1 for r in live if r["kind"] == "tv"),
    }

    def arr(rows):
        return "[\n" + "".join("  " + json.dumps(r, ensure_ascii=False) + ",\n" for r in rows) + "]"

    ts = f"""// GENERATED by backend/research/youtube_live_2026_11/export_live.py - do not edit by hand; re-run the survey and
// the export instead (see that folder's README). Public YouTube metadata only: no video or audio was downloaded.
export type Group = "hindi" | "crypto" | "fx" | "gone";
export type Shows = "seen" | "titles" | "";
export type Channel = {{
  id: string | null; name: string; handle: string | null; url: string; group: Group; subs: number | null;
  lives30: number | null; lives7: number | null; lastDays: number | null; monthsSince: number | null; never: boolean;
  hours: number | null; avgViews: number | null; brokers: string[]; shows: Shows; note: string; titles: string[];
  study: "studied" | "listed" | ""; studies: string[]; markets: string[]; sells: string[] | null; sched: Sched | null;
}};
/** A daily slot: the average start and end on the IST clock of a cluster of streams that start close together. */
export type Slot = {{ start: string; end: string | null; startMin: number; endMin: number | null; n: number;
  share: number; spreadMin: number }};
/** From the exact start and length of each stream of about the last three weeks (newest 30 at most). */
export type Sched = {{ daysLive: number; daysCovered: number; weekdaysLive: number; weekdays: number;
  weekendLive: number; weekendDays: number; pattern: string; perDay: number; slots: Slot[]; streamsRead: number;
  medianHours: number | null; latest: string; recent: string[] }};
export type LiveRow = {{ watching: number; channel: string | null; handle: string | null; title: string;
  kind: "person" | "robot" | "tv"; url: string }};
export type ProbeEntry = {{ lots: number; entry: number; stop: number; stop_approx: boolean; target: number | null;
  when: string }};

export const SURVEY = {json.dumps(survey, ensure_ascii=False)};

export const CHANNELS: Channel[] = {arr(out)};

export const LIVE_NOW: LiveRow[] = {arr(live)};

export const PROBE = {json.dumps(PROBE, ensure_ascii=False)} as {{ channel: string; video: string; date: string;
  time: string; terminal: string; symbol: string; side: string; lots: number; avg_entry: number; balance: number;
  notional_usd: number; risk_usd: number; entries: ProbeEntry[]; pnl_swing: number[]; pnl_last: number; speech: string }};
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".ts.tmp")
    tmp.write_text(ts, encoding="utf-8", newline="\n")
    tmp.replace(OUT)
    groups = {g: sum(1 for r in out if r["group"] == g) for g in order}
    print(f"wrote {OUT.relative_to(REPO)}: {len(out)} channels {groups}, {len(live)} live rows "
          f"({survey['livePeople']} people, {survey['liveRobots']} robots, {survey['liveTv']} TV)")
    for r in out:
        s = r["sched"] or {}
        slots = " / ".join(f"{x['start']}-{x['end']} ({x['n']}, ±{x['spreadMin']}m)" for x in s.get("slots", []))
        print(f"  {r['group']:<6} {r['name'][:24]:<24} l30={r['lives30']} days={s.get('daysLive')}/{s.get('daysCovered')} "
              f"wk={s.get('weekdaysLive')}/{s.get('weekdays')} we={s.get('weekendLive')}/{s.get('weekendDays')} "
              f"{s.get('pattern', '-'):<13} x{s.get('perDay')} {slots} h={r['hours']} mk={','.join(r['markets'])} "
              f"sells={','.join(r['sells'] or [])}")


if __name__ == "__main__":
    main()
