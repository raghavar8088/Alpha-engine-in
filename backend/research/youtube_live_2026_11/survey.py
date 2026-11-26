"""Survey of YouTube trading live streamers, pass 1 (metadata only: no video or audio is downloaded).

1. Live now: YouTube search with the "Live" filter for trading queries (who is live, how many watching).
2. Channel check: each candidate's /streams tab (newest 60, approximate dates): subscribers, streams in the
   last 7/30 days, last stream, typical length, average views of the last 10, recent titles.
Writes raw/*.json and summary.json next to this file (both git-ignored). See README.md for the full run.

    python -I survey.py                      # pass 1
    python -I survey.py --print              # re-print summary.json
    python -I survey.py --recount @handle    # re-count one channel over its newest 200 streams -> recount.json
"""
import json, subprocess, sys, time, statistics, re
import concurrent.futures as cf
from pathlib import Path
from datetime import datetime, timezone, timedelta

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
RAW.mkdir(exist_ok=True)
NOW = time.time()
IST = timezone(timedelta(hours=5, minutes=30))
LIVE_SP = "EgJAAQ%3D%3D"  # YouTube search filter: Live

QUERIES = [
    "gold live trading", "xauusd live trading", "gold scalping live", "forex live trading",
    "bitcoin live trading", "crypto live trading", "btc live trading", "day trading live",
    "live trading hindi", "gold live trading hindi", "crypto live trading hindi", "forex live trading hindi",
]

CHANNELS = {
    # crypto, global
    "@CryptoBanterGroup": "crypto", "@TheMoonCarl": "crypto", "@CryptoFace": "crypto",
    "@TraderXO": "crypto", "@CryptoKirby": "crypto", "@KrownsCryptoCave": "crypto",
    "@ToneVays": "crypto", "@MMCrypto": "crypto", "@CryptoRover": "crypto",
    "@CryptoCapitalVenture": "crypto", "@TheWolfOfAllStreets": "crypto", "@CryptoMichNL": "crypto",
    "@JacobCryptoBury": "crypto", "@CryptoJebb": "crypto", "@TheChartGuys": "crypto",
    "@PaulBarronNetwork": "crypto",
    # gold / forex, global
    "@TJRTrades": "fx", "@InnerCircleTrader": "fx", "@TraderNick": "fx", "@Wysetrade": "fx",
    "@SimplyForex": "fx", "@TomHougaard": "fx", "@CasperSMC": "fx", "@mentfx": "fx",
    "@Pepperstone": "fx", "@KojoForex": "fx", "@TRADEPROAcademy": "fx", "@fxalexg": "fx",
    "@RileyColeman": "fx",
    # India / Hindi
    "@BoomingBulls": "india", "@TradersParadise": "india", "@YTVTraders": "india",
    "@IITianTrader": "india", "@GhanshyamTech": "india", "@MarketGurukul": "india",
    "@DeltaExchangeIndia": "india",
}


def ytdlp(args, timeout=150):
    try:
        p = subprocess.run(["yt-dlp", "--no-warnings", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def slug(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:60]


def search(q):
    url = "https://www.youtube.com/results?search_query=" + q.replace(" ", "+") + "&sp=" + LIVE_SP
    rc, out, err = ytdlp(["--flat-playlist", "-J", "--playlist-end", "20", url])
    (RAW / f"search_{slug(q)}.json").write_text(out or "{}", encoding="utf-8")
    if rc != 0 or not out.strip():
        return q, [], err.strip()[-300:]
    d = json.loads(out)
    rows = []
    for e in d.get("entries") or []:
        if e.get("live_status") != "is_live":
            continue
        rows.append({"q": q, "title": e.get("title"), "channel": e.get("channel"),
                     "channel_id": e.get("channel_id"), "handle": e.get("uploader_id"),
                     "watching": e.get("concurrent_view_count") or 0, "id": e.get("id")})
    return q, rows, ""


def streams(target, limit=60):
    url = (f"https://www.youtube.com/{target}/streams" if target.startswith("@")
           else f"https://www.youtube.com/channel/{target}/streams")
    rc, out, err = ytdlp(["--flat-playlist", "-J", "--playlist-end", str(limit),
                          "--extractor-args", "youtubetab:approximate_date", url])
    (RAW / f"streams_{slug(target)}.json").write_text(out or "{}", encoding="utf-8")
    if rc != 0 or not out.strip():
        return {"target": target, "error": (err.strip().splitlines() or ["?"])[-1][:200]}
    d = json.loads(out)
    ents = d.get("entries") or []
    past = [e for e in ents if e.get("live_status") in ("was_live", None) and e.get("timestamp")]
    live_now = [e for e in ents if e.get("live_status") == "is_live"]
    upcoming = [e for e in ents if e.get("live_status") == "is_upcoming"]
    age_d = lambda e: (NOW - e["timestamp"]) / 86400
    n7 = sum(1 for e in past if age_d(e) <= 7) + len(live_now)
    n30 = sum(1 for e in past if age_d(e) <= 30) + len(live_now)
    durs = [e["duration"] for e in past if e.get("duration") and age_d(e) <= 30]
    views = [e["view_count"] for e in past[:10] if e.get("view_count")]
    last = max((e["timestamp"] for e in past), default=None)
    return {
        "target": target, "name": d.get("channel") or d.get("uploader") or d.get("title"),
        "channel_id": d.get("channel_id"), "subs": d.get("channel_follower_count"),
        "listed": len(ents), "live_now": [(e.get("title"), e.get("concurrent_view_count")) for e in live_now],
        "upcoming": len(upcoming), "n7": n7, "n30": n30,
        "last_stream_days": round((NOW - last) / 86400, 1) if last else None,
        "median_len_h": round(statistics.median(durs) / 3600, 1) if durs else None,
        "avg_views_last10": int(statistics.mean(views)) if views else None,
        "titles": [e.get("title") for e in (live_now + past)[:4]],
    }


def report(summary, took=0.0):
    live_rows, checks, extra_checks = summary["live_now"], summary["channels"], summary["discovered"]
    print(f"run at {summary['run_at_ist']}  ({took:.0f}s)")
    print(f"\n== LIVE NOW ({len(live_rows)} streams) ==")
    for r in live_rows[:45]:
        print(f"{r['watching']:>7}  {str(r['channel'])[:32]:<32} {r['handle'] or '':<26} {str(r['title'])[:90]}")
    for label, rows in (("LISTED CHANNELS", checks), ("DISCOVERED (live now, 150+ watching)", extra_checks)):
        print(f"\n== {label} ==")
        for c in rows:
            if c.get("error"):
                print(f"  {c['target']:<26} ERROR {c['error']}")
                continue
            print(f"  {c['target'][:26]:<26} {str(c['name'])[:30]:<30} subs={c['subs']} n7={c['n7']} n30={c['n30']} "
                  f"last={c['last_stream_days']}d len={c['median_len_h']}h views10={c['avg_views_last10']} "
                  f"live={len(c['live_now'])} up={c['upcoming']}")
            for t in c["titles"][:3]:
                print(f"      - {str(t)[:110]}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--print" in sys.argv:
        report(json.loads((HERE / "summary.json").read_text(encoding="utf-8")))
        return
    if "--recount" in sys.argv:
        # A channel at the 60-stream cap (n30 == 60) streams more often than pass 1 can count.
        target = sys.argv[sys.argv.index("--recount") + 1]
        c = streams(target, 200)
        p = HERE / "recount.json"
        done = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        done[c.get("channel_id") or target] = c
        p.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print({k: c.get(k) for k in ("name", "subs", "listed", "n7", "n30", "median_len_h", "error")})
        return
    t0 = time.time()
    live = []
    with cf.ThreadPoolExecutor(4) as ex:
        for q, rows, err in ex.map(search, QUERIES):
            if err:
                print(f"[search fail] {q}: {err}")
            live.extend(rows)
    # one row per live video, keep the max viewer figure
    by_vid = {}
    for r in live:
        if r["id"] not in by_vid or r["watching"] > by_vid[r["id"]]["watching"]:
            by_vid[r["id"]] = r
    live_rows = sorted(by_vid.values(), key=lambda r: -r["watching"])

    known_ids = set()
    targets = list(CHANNELS)
    with cf.ThreadPoolExecutor(4) as ex:
        checks = list(ex.map(streams, targets))
    for c in checks:
        if c.get("channel_id"):
            known_ids.add(c["channel_id"])
    # channels found live with real audiences that we did not list
    extra = []
    for r in live_rows:
        if r["watching"] >= 150 and r["channel_id"] and r["channel_id"] not in known_ids:
            known_ids.add(r["channel_id"])
            extra.append(r["channel_id"])
    with cf.ThreadPoolExecutor(4) as ex:
        extra_checks = list(ex.map(streams, extra))

    summary = {"run_at_ist": datetime.now(IST).isoformat(timespec="seconds"),
               "live_now": live_rows, "channels": checks, "discovered": extra_checks}
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"run at {summary['run_at_ist']}  ({time.time() - t0:.0f}s)")
    print(f"\n== LIVE NOW ({len(live_rows)} streams) ==")
    for r in live_rows[:45]:
        print(f"{r['watching']:>7}  {r['channel'][:32]:<32} {r['handle'] or '':<26} {r['title'][:90]}")
    for label, rows in (("LISTED CHANNELS", checks), ("DISCOVERED (live now, 150+ watching)", extra_checks)):
        print(f"\n== {label} ==")
        for c in rows:
            if c.get("error"):
                print(f"  {c['target']:<26} ERROR {c['error']}")
                continue
            print(f"  {c['target'][:26]:<26} {str(c['name'])[:30]:<30} subs={c['subs']} n7={c['n7']} n30={c['n30']} "
                  f"last={c['last_stream_days']}d len={c['median_len_h']}h views10={c['avg_views_last10']} "
                  f"live={len(c['live_now'])} up={c['upcoming']}")
            for t in c["titles"][:3]:
                print(f"      - {str(t)[:110]}")


if __name__ == "__main__":
    main()
