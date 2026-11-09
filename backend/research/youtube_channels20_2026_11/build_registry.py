"""The registry of channels and videos already covered by earlier work, so the new research cycle never repeats it.
    python -I build_registry.py      -> registry/covered.json and registry/COVERED.md

Sources: the YouTube top-20 study's catalogue, the Booming Bulls study, the crypto-playlist / sniper / liquidity-sweep
work, the 11-channel study, the Stock Force extraction (July 2026), and the Trading Video Lab's channel lists and
evidence folders (captions already saved)."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = ROOT / "backend" / "research"
LAB = ROOT / "youtube-video-explainer-reviewed"
VID = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{11}(?![A-Za-z0-9_-])")


def is_vid(tok: str) -> bool:
    return any(ch.isdigit() or ch in "-_" for ch in tok) or (tok.lower() != tok and tok.upper() != tok)


def ids_in(text: str) -> set:
    return {t for t in VID.findall(text) if is_vid(t)}


channels: dict = {}
videos: dict = {}


def chan(cid, handle, title, study, status, note=""):
    c = channels.setdefault(cid or handle, {"id": cid, "handle": handle, "title": title, "studies": [], "status": status, "note": note})
    if study not in c["studies"]:
        c["studies"].append(study)
    rank = {"analyzed": 3, "partial": 2, "listed": 1}
    if rank.get(status, 0) > rank.get(c["status"], 0):
        c["status"] = status
    if note and note not in c["note"]:
        c["note"] = (c["note"] + "; " + note).strip("; ")


def vid(v, study, kind):
    e = videos.setdefault(v, {"studies": [], "kinds": []})
    if study not in e["studies"]:
        e["studies"].append(study)
    if kind not in e["kinds"]:
        e["kinds"].append(kind)


# 1. YouTube top-20 study: 20 channels analyzed; its picked / analysed videos
top = R / "youtube_top20_2026_11"
seen_top = {}
with open(top / "catalogue" / "catalogue.csv", encoding="utf-8-sig", newline="") as fh:
    for r in csv.DictReader(fh):
        seen_top[r["channel_id"]] = r["channel"]
        if r.get("picked") == "true" or r.get("analysis"):
            vid(r["id"], "youtube_top20", "analyzed" if r.get("analysis") else "picked")
for cid, name in seen_top.items():
    chan(cid, None, name, "youtube_top20", "analyzed")
for f in (top / "analyses").glob("*.md"):
    for v in ids_in(f.read_text(encoding="utf-8")):
        vid(v, "youtube_top20", "cited")
# the top-20 study's candidate pool: listed (subscribers, uploads) but not analyzed unless in the top 20
for name in ("candidates.json", "candidates2.json"):
    p = top / "data" / name
    if p.exists():
        for c in json.loads(p.read_text(encoding="utf-8")).get("candidates", []):
            if c.get("channel_id"):
                chan(c["channel_id"], c.get("handle"), c.get("channel") or c.get("name"), "youtube_top20_pool", "listed",
                     "candidate pool of the top-20 study")

# 2. Booming Bulls (whole channel), its playlist, sniper, liquidity sweep
chan("UC2sIhf108S02F0Qlb2a88eQ", "@BoomingBulls", "Booming Bulls", "booming_bulls", "analyzed")
for sub in ("booming_bulls_2026_11/analyses", "crypto_playlist_2026_11/specs", "sniper_headshot_2026_11", "liquidity_sweep_2026_11"):
    p = R / sub
    for f in list(p.glob("*.md")) if p.exists() else []:
        for v in ids_in(f.read_text(encoding="utf-8")):
            vid(v, sub.split("/")[0], "cited")

# 3. the 11-channel study
yc = R / "youtube_channels11_2026_11"
for f in (yc / "catalogue" / "selection").glob("*.tsv"):
    for line in f.read_text(encoding="utf-8").splitlines()[1:]:
        if line.strip():
            vid(line.split("\t")[0], "youtube_channels11", "selected")
for f in (yc / "analyses").glob("*.md"):
    for v in ids_in(f.read_text(encoding="utf-8")):
        vid(v, "youtube_channels11", "cited")
for f in (yc / "catalogue" / "raw").glob("*.json"):
    c = json.loads(f.read_text(encoding="utf-8"))["channel"]
    chan(c["id"], c.get("handle"), c.get("title"), "youtube_channels11", "analyzed")

# 4. Stock Force (July 2026, Nifty option strategies; 35 of 70 transcripts)
sf = ROOT / "STOCKFORCE_NIFTY_OPTION_STRATEGIES.md"
if sf.exists():
    chan(None, "@stockforceofficial", "Stock Force", "stockforce_2026_07", "partial", "35 of 70 transcripts; YouTube rate limit")
    for v in ids_in(sf.read_text(encoding="utf-8")):
        vid(v, "stockforce_2026_07", "cited")

# 5. the Trading Video Lab: channel lists and saved evidence
for f in (LAB / "data" / "channels").glob("*.json"):
    c = json.loads(f.read_text(encoding="utf-8"))
    ch = c.get("channel") or {}
    if ch.get("id"):
        chan(ch["id"], ch.get("handle"), ch.get("title"), "video_lab_list", "listed")
for d in (LAB / "evidence").iterdir():
    m = re.match(r"^([A-Za-z0-9_-]{11})-", d.name)
    if m:
        vid(m.group(1), "video_lab_evidence", "evidence")

# a channel is "analyzed" only when a study extracted its strategies; a Video Lab list alone is "listed"
out = {"built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
       "channels": sorted(channels.values(), key=lambda c: (-{"analyzed": 3, "partial": 2, "listed": 1}[c["status"]], c["title"] or "")),
       "videos": dict(sorted(videos.items()))}
(HERE / "registry").mkdir(exist_ok=True)
(HERE / "registry" / "covered.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
lines = ["# Channels and videos covered before this cycle", "",
         f"Built {out['built']} by build_registry.py. A channel is **analyzed** when a study extracted its strategies, **partial**",
         "when only some of its videos were read, and **listed** when only its uploads were catalogued. Listed channels may",
         "be selected now; analyzed and partial ones are skipped.", "",
         "| Status | Channel | Handle | Channel id | Studies |", "|---|---|---|---|---|"]
for c in out["channels"]:
    lines.append(f"| {c['status']} | {c['title'] or ''} | {c['handle'] or ''} | `{c['id'] or ''}` | {', '.join(c['studies'])} |")
n_an = sum(1 for c in out["channels"] if c["status"] in ("analyzed", "partial"))
lines += ["", f"Channels analyzed or partial: {n_an}; listed only: {len(out['channels']) - n_an}. Videos covered: {len(videos)}."]
(HERE / "registry" / "COVERED.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("channels", len(out["channels"]), "analyzed/partial", n_an, "videos", len(videos))
