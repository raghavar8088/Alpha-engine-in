"""Pass 4: exact start time and length of each listed channel's recent live streams (metadata only).

The /streams tab gives only "Streamed 3 days ago" style dates, so for every channel in channels.py that still
streams, this reads each stream of about the last three weeks (newest 30 at most) one by one:
release_timestamp = the moment the broadcast started, duration = its length, so end = start + duration.
Writes schedule.json next to this file (git-ignored). Run after survey.py / survey2.py; export_live.py uses it.

    python -I survey4.py
"""
import json, subprocess, sys, time
import concurrent.futures as cf
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # only this folder's own scripts
from channels import CHANNELS  # noqa: E402
from survey import RAW, slug  # noqa: E402

MAX_PER_CHANNEL = 30
MAX_AGE_D = 21  # by the tab's approximate date; "3 weeks ago" covers 21-27 days
NOW = time.time()


def recent_ids(target):
    p = RAW / f"streams_{slug(target)}.json"
    d = (json.loads(p.read_text(encoding="utf-8") or "{}") or {}) if p.exists() else {}
    ids = []
    for e in d.get("entries") or []:
        if e.get("live_status") != "was_live":
            continue
        ts = e.get("timestamp")
        if ts and (NOW - ts) / 86400 > MAX_AGE_D:
            continue
        ids.append(e["id"])
        if len(ids) >= MAX_PER_CHANNEL:
            break
    return ids


def read(target):
    ids = recent_ids(target)
    if not ids:
        return target, []
    lst = HERE / "raw" / f"ids_{slug(target)}.txt"
    lst.write_text("\n".join(f"https://www.youtube.com/watch?v={i}" for i in ids), encoding="utf-8")
    try:
        p = subprocess.run(["yt-dlp", "--no-warnings", "--ignore-errors", "--extractor-args", "youtube:player_skip=js",
                            "--print", "%(id)s|%(release_timestamp)s|%(timestamp)s|%(duration)s|%(live_status)s",
                            "-a", str(lst)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=600)
        out = p.stdout
    except subprocess.TimeoutExpired:
        out = ""
    rows = []
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 5:
            continue
        vid, rel, ts, dur, status = parts
        num = lambda s: int(float(s)) if s not in ("NA", "None", "") else None
        rows.append({"id": vid, "start": num(rel) or num(ts), "duration": num(dur), "status": status})
    return target, rows


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    targets = [t for t, (group, _s, _n) in CHANNELS.items() if group != "gone"]
    t0 = time.time()
    with cf.ThreadPoolExecutor(6) as ex:
        res = dict(ex.map(read, targets))
    (HERE / "schedule.json").write_text(json.dumps({"read_at": int(time.time()), "streams": res}, indent=1),
                                        encoding="utf-8")
    total = sum(len(v) for v in res.values())
    print(f"{total} streams read for {len(targets)} channels in {time.time() - t0:.0f}s")
    for t, rows in res.items():
        print(f"  {t:<28} {len(rows)}")


if __name__ == "__main__":
    main()
