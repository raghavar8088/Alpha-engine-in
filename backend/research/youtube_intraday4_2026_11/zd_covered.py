"""Videos and strategies covered before this cycle, so the four-topic intraday study never repeats a video or adds a
strategy the library already holds.
    python -I zd_covered.py      -> registry/covered.json, registry/COVERED.md, registry/library_names.tsv

Sources:
- the 20-channel study's registry (registry/covered.json, built 9 Nov 2026), which already merges the top-20 study,
  Booming Bulls, the crypto playlist, the sniper and liquidity-sweep work, the 11-channel study, Stock Force and the
  Trading Video Lab's evidence folders as they were then;
- the 20-channel study's own selections and analyses (added after that registry was built);
- the Trading Video Lab's evidence folders and cards as they are now.
A video counts as covered when any study selected it, cited it in an analysis, or saved its captions in the Lab."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = ROOT / "backend" / "research"
LAB = ROOT / "youtube-video-explainer-reviewed"
ZC = R / "youtube_channels20_2026_11"
YC = R / "youtube_channels11_2026_11"
VID = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{11}(?![A-Za-z0-9_-])")


def is_vid(tok: str) -> bool:
    return any(ch.isdigit() or ch in "-_" for ch in tok) or (tok.lower() != tok and tok.upper() != tok)


def ids_in(text: str) -> set:
    return {t for t in VID.findall(text) if is_vid(t)}


prev = json.loads((ZC / "registry" / "covered.json").read_text(encoding="utf-8"))
videos: dict = {k: {"studies": list(v["studies"]), "kinds": list(v["kinds"])} for k, v in prev["videos"].items()}
channels = prev["channels"]


def add(v: str, study: str, kind: str) -> None:
    e = videos.setdefault(v, {"studies": [], "kinds": []})
    if study not in e["studies"]:
        e["studies"].append(study)
    if kind not in e["kinds"]:
        e["kinds"].append(kind)


for f in (ZC / "catalogue" / "selection").glob("*.tsv"):
    for line in f.read_text(encoding="utf-8").splitlines()[1:]:
        if line.strip():
            add(line.split("\t")[0], "youtube_channels20", "selected")
for f in list((ZC / "analyses").glob("*.md")) + [ZC / "specs" / "RULES.md", ZC / "REPORT.md"]:
    for v in ids_in(f.read_text(encoding="utf-8")):
        add(v, "youtube_channels20", "cited")
pe = ZC / "registry" / "playlist_entries.json"
if pe.exists():   # queued by the 20-channel study, not analysed: recorded so a later cycle can tell them apart
    for v in ids_in(pe.read_text(encoding="utf-8")):
        videos.setdefault(v, {"studies": [], "kinds": []})
        add(v, "youtube_channels20_queue", "queued")
for d in (LAB / "evidence").iterdir():
    m = re.match(r"^([A-Za-z0-9_-]{11})-", d.name)
    if m:
        add(m.group(1), "video_lab_evidence", "evidence")
        if (d / "card.json").exists():
            add(m.group(1), "video_lab_card", "analyzed")

# a queued-only video was never read: it stays selectable
covered = {k: v for k, v in videos.items() if set(v["kinds"]) - {"queued"}}
out = {"built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "channels": channels,
       "videos": dict(sorted(covered.items())), "queued_only": sorted(set(videos) - set(covered))}
(HERE / "registry").mkdir(exist_ok=True)
(HERE / "registry" / "covered.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

# every strategy name in the library, for the duplicate check (ids and names only)
names: list[tuple[str, str, str]] = []
lib = (ROOT / "frontend" / "app" / "premium-strategies" / "library.ts").read_text(encoding="utf-8")
for m in re.finditer(r'"id":\s*"([A-Z0-9-]+)",\s*"source":\s*"[a-z0-9_]+",\s*"name":\s*"([^"]+)"', lib):
    names.append(("library", m.group(1), m.group(2)))
for f, study in ((YC / "specs" / "RULES.md", "youtube_channels11"), (ZC / "specs" / "RULES.md", "youtube_channels20")):
    for m in re.finditer(r"^#{2,3} ([A-Z]{2}-\d{2}[A-Z]?) (.+?)(?: \([A-Za-z0-9_-]{11}[^)]*\))?$", f.read_text(encoding="utf-8"), re.M):
        names.append((study, m.group(1), m.group(2).strip()))
for sub in ("crypto_playlist_2026_11/specs", "sniper_headshot_2026_11", "liquidity_sweep_2026_11", "booming_bulls_2026_11/specs",
            "youtube_top20_2026_11/specs"):
    p = R / sub
    for f in (list(p.glob("*.md")) if p.exists() else []):
        for m in re.finditer(r"^#{2,3} ([A-Z]{2,3}-\d{2}[A-Z0-9]*)[:\s.-]+(.+?)$", f.read_text(encoding="utf-8"), re.M):
            names.append((sub.split("/")[0], m.group(1), m.group(2).strip()))
seen, rows = set(), []
for study, sid, name in names:
    if (sid, name) not in seen:
        seen.add((sid, name))
        rows.append(f"{study}\t{sid}\t{name}")
(HERE / "registry" / "library_names.tsv").write_text("study\tid\tname\n" + "\n".join(rows) + "\n", encoding="utf-8")

lines = ["# Videos covered before the four-topic intraday cycle", "",
         f"Built {out['built']} by zd_covered.py. Videos covered: {len(covered)} (selected or cited by a study, or with",
         f"captions saved in the Trading Video Lab). Queued but never read: {len(out['queued_only'])} (selectable).",
         f"Library strategy names for the duplicate check: {len(rows)} (registry/library_names.tsv).", ""]
by = {}
for v in covered.values():
    for s in v["studies"]:
        by[s] = by.get(s, 0) + 1
lines += ["| Study | Videos |", "|---|---|"] + [f"| {s} | {n} |" for s, n in sorted(by.items(), key=lambda x: -x[1])]
(HERE / "registry" / "COVERED.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("covered", len(covered), "queued_only", len(out["queued_only"]), "library names", len(rows))
