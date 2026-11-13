"""Videos and strategies covered before this study, so the channel-shortlist study never re-reads a video or adds a
strategy the library already holds.
    python -I ze_covered.py      -> registry/covered.json, registry/COVERED.md, registry/library_names.tsv

Sources:
- the four-topic intraday study's registry (youtube_intraday4_2026_11/registry/covered.json, 12 Nov 2026), which already
  merges every earlier study (top-20, Booming Bulls, crypto playlist, sniper, liquidity sweep, 11 and 20 channels,
  Stock Force) and the Trading Video Lab's evidence as it was then;
- that study's own selections and cards (its 16 backups were queued, never read: they stay selectable);
- the Trading Video Lab's evidence folders and cards as they are now.
A video counts as covered when any study selected it, cited it, or saved its captions in the Lab."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = ROOT / "backend" / "research"
LAB = ROOT / "youtube-video-explainer-reviewed"
ZD = R / "youtube_intraday4_2026_11"


def main() -> None:
    prev = json.loads((ZD / "registry" / "covered.json").read_text(encoding="utf-8"))
    videos: dict = {k: {"studies": list(v["studies"]), "kinds": list(v["kinds"])} for k, v in prev["videos"].items()}

    def add(v: str, study: str, kind: str) -> None:
        e = videos.setdefault(v, {"studies": [], "kinds": []})
        if study not in e["studies"]:
            e["studies"].append(study)
        if kind not in e["kinds"]:
            e["kinds"].append(kind)

    for v in prev.get("queued_only", []):
        add(v, "earlier_queue", "queued")
    for f in (ZD / "catalogue" / "selection").glob("*.tsv"):
        for line in f.read_text(encoding="utf-8").splitlines()[1:]:
            if line.strip():
                vid, role = line.split("\t")[:2]
                add(vid, "youtube_intraday4", "selected" if role == "primary" else "queued")
    for f in (ZD / "cards").glob("*.txt"):
        add(f.stem, "youtube_intraday4", "analyzed")
    for d in (LAB / "evidence").iterdir():
        m = re.match(r"^([A-Za-z0-9_-]{11})-", d.name)
        if m:
            add(m.group(1), "video_lab_evidence", "evidence")
            if (d / "card.json").exists():
                add(m.group(1), "video_lab_card", "analyzed")
    covered = {k: v for k, v in videos.items() if set(v["kinds"]) - {"queued"}}
    out = {"built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "channels": prev.get("channels", {}),
           "videos": dict(sorted(covered.items())), "queued_only": sorted(set(videos) - set(covered))}
    (HERE / "registry").mkdir(exist_ok=True)
    (HERE / "registry" / "covered.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    # strategy names in the library: the earlier list plus the four-topic study's own strategies
    rows = (ZD / "registry" / "library_names.tsv").read_text(encoding="utf-8").splitlines()[1:]
    for f in sorted((ZD / "cards").glob("*.txt")):
        for m in re.finditer(r"^= ([A-Z]{2}-\d{2}) \| (.+)$", f.read_text(encoding="utf-8"), re.M):
            rows.append(f"youtube_intraday4\t{m.group(1)}\t{m.group(2).strip()}")
    seen, uniq = set(), []
    for r in rows:
        if r and r not in seen:
            seen.add(r)
            uniq.append(r)
    (HERE / "registry" / "library_names.tsv").write_text("study\tid\tname\n" + "\n".join(uniq) + "\n", encoding="utf-8")

    by: dict = {}
    for v in covered.values():
        for s in v["studies"]:
            by[s] = by.get(s, 0) + 1
    lines = ["# Videos covered before the channel-shortlist study", "",
             f"Built {out['built']} by ze_covered.py. Videos covered: {len(covered)} (selected or cited by a study, or with",
             f"captions saved in the Trading Video Lab). Queued but never read: {len(out['queued_only'])} (selectable).",
             f"Library strategy names for the duplicate check: {len(uniq)} (registry/library_names.tsv).", "",
             "| Study | Videos |", "|---|---|"] + [f"| {s} | {n} |" for s, n in sorted(by.items(), key=lambda x: -x[1])]
    (HERE / "registry" / "COVERED.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("covered", len(covered), "queued_only", len(out["queued_only"]), "library names", len(uniq))


if __name__ == "__main__":
    main()
