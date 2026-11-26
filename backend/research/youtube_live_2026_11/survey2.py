"""Pass 2: resolve channels by name, find popular past live streams, read live videos' metadata (no media)."""
import json, sys, re
import concurrent.futures as cf
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # only my own scripts live here
from survey import ytdlp, streams, RAW, slug  # noqa: E402

CHANNEL_SP = "EgIQAg%3D%3D"  # search filter: type = channel
NAMES = ["The Moon Carl Runefelt", "Krown's Crypto Cave", "MMCrypto", "Scott Melker Wolf Of All Streets",
         "Michael van de Poppe", "The Chart Guys", "Wysetrade", "Tom Hougaard", "Traders Paradise",
         "YTV Traders", "Market Gurukul", "Delta Exchange India", "TJR live trading"]
QUERIES = ["gold live trading", "xauusd live trading", "forex live trading", "bitcoin live trading",
           "crypto live trading", "live trading hindi gold crypto"]
LIVE_VIDEOS = {  # live right now in pass 1, read metadata only
    "Stock Burner": None, "Bullish Bull Master": None, "ICT ENIGMA": None, "Sameer Singh": None,
    "Sin City Crypto": None, "Nomi trades 2.0": None, "Vishal Analyst": None, "Uday Patel": None,
}


def find_channel(name):
    url = "https://www.youtube.com/results?search_query=" + name.replace(" ", "+") + "&sp=" + CHANNEL_SP
    rc, out, err = ytdlp(["--flat-playlist", "-J", "--playlist-end", "3", url])
    (RAW / f"chsearch_{slug(name)}.json").write_text(out or "{}", encoding="utf-8")
    if rc != 0 or not out.strip():
        return name, []
    d = json.loads(out)
    hits = []
    for e in d.get("entries") or []:
        cid = e.get("channel_id") or (e.get("id") if str(e.get("id", "")).startswith("UC") else None)
        hits.append({"title": e.get("title") or e.get("channel"), "channel_id": cid, "url": e.get("url"),
                     "subs": e.get("channel_follower_count")})
    return name, hits


def popular(q):
    rc, out, err = ytdlp(["--flat-playlist", "-J", f"ytsearch40:{q}"])
    (RAW / f"ytsearch_{slug(q)}.json").write_text(out or "{}", encoding="utf-8")
    if rc != 0 or not out.strip():
        return q, []
    return q, json.loads(out).get("entries") or []


def video_meta(vid):
    rc, out, err = ytdlp(["-J", "--skip-download", f"https://www.youtube.com/watch?v={vid}"], timeout=90)
    if rc != 0 or not out.strip():
        return vid, {"error": (err.strip().splitlines() or ["?"])[-1][:160]}
    d = json.loads(out)
    (RAW / f"video_{vid}.json").write_text(json.dumps({k: d.get(k) for k in (
        "id", "title", "channel", "channel_id", "language", "description", "tags", "concurrent_view_count",
        "channel_follower_count", "live_status", "release_timestamp")}, ensure_ascii=False), encoding="utf-8")
    desc = re.sub(r"\s+", " ", d.get("description") or "")
    links = re.findall(r"https?://[^\s)]+", d.get("description") or "")
    return vid, {"channel": d.get("channel"), "language": d.get("language"), "watching": d.get("concurrent_view_count"),
                 "desc": desc[:420], "links": links[:12]}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    s1 = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
    checked = {c.get("channel_id") for c in s1["channels"] + s1["discovered"] if c.get("channel_id")}

    with cf.ThreadPoolExecutor(4) as ex:
        found = list(ex.map(find_channel, NAMES))
        pops = list(ex.map(popular, QUERIES))
    print("== CHANNELS BY NAME ==")
    resolve = []
    for name, hits in found:
        print(f"  {name}: " + " | ".join(f"{h['title']} {h['channel_id']} subs={h['subs']}" for h in hits[:3]))
        if hits and hits[0]["channel_id"] and hits[0]["channel_id"] not in checked:
            resolve.append(hits[0]["channel_id"])
            checked.add(hits[0]["channel_id"])

    agg = {}
    for q, ents in pops:
        for e in ents:
            cid = e.get("channel_id")
            if not cid:
                continue
            a = agg.setdefault(cid, {"channel": e.get("channel"), "hits": 0, "live_hits": 0, "max_views": 0,
                                     "queries": set(), "top_title": ""})
            a["hits"] += 1
            a["queries"].add(q)
            if e.get("live_status") in ("was_live", "is_live") or "live" in (e.get("title") or "").lower():
                a["live_hits"] += 1
            v = e.get("view_count") or 0
            if v > a["max_views"]:
                a["max_views"], a["top_title"] = v, e.get("title") or ""
    ranked = sorted(agg.items(), key=lambda kv: -kv[1]["max_views"])
    print("\n== MOST-VIEWED IN 'LIVE TRADING' SEARCHES (top 30 channels by best video views) ==")
    for cid, a in ranked[:30]:
        print(f"  {a['max_views']:>9}  {str(a['channel'])[:30]:<30} hits={a['hits']} live_hits={a['live_hits']} "
              f"{cid}  | {a['top_title'][:80]}")
    for cid, a in ranked[:30]:
        if a["live_hits"] and cid not in checked and len(resolve) < 30:
            resolve.append(cid)
            checked.add(cid)

    with cf.ThreadPoolExecutor(4) as ex:
        checks = list(ex.map(streams, resolve))
    print("\n== STREAMS TAB OF RESOLVED + POPULAR CHANNELS ==")
    for c in checks:
        if c.get("error"):
            print(f"  {c['target']:<26} ERROR {c['error']}")
            continue
        print(f"  {c['target'][:26]:<26} {str(c['name'])[:30]:<30} subs={c['subs']} n7={c['n7']} n30={c['n30']} "
              f"last={c['last_stream_days']}d len={c['median_len_h']}h views10={c['avg_views_last10']} "
              f"live={len(c['live_now'])}")
        for t in c["titles"][:3]:
            print(f"      - {str(t)[:110]}")

    vids = {}
    for r in s1["live_now"]:
        if r["channel"] in LIVE_VIDEOS and r["channel"] not in vids:
            vids[r["channel"]] = r["id"]
    with cf.ThreadPoolExecutor(4) as ex:
        metas = dict(ex.map(video_meta, vids.values()))
    print("\n== LIVE VIDEOS' METADATA ==")
    for ch, vid in vids.items():
        m = metas.get(vid, {})
        print(f"  {ch} ({vid}) lang={m.get('language')} watching={m.get('watching')} {m.get('error', '')}")
        print(f"      desc: {m.get('desc', '')[:420]}")
        print(f"      links: {' '.join(m.get('links', [])[:10])}")

    out = {"found": found, "popular": [(cid, {**a, "queries": sorted(a["queries"])}) for cid, a in ranked[:60]],
           "checks": checks, "live_meta": {ch: metas.get(v) for ch, v in vids.items()}}
    (HERE / "summary2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
