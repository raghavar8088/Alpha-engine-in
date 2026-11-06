"""Data audit: sessions on disk, cleaning counts, and whether each PDF trade's entry price is where the
minute data says the index was at the PDF's marked candle (checks the transcription and the clock)."""

import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I leaves the script's folder off sys.path
from ls_common import HERE, Market, OPEN_MIN, load_minutes  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

days = load_minutes()
mk = Market(days)
print("quality:", json.dumps(days.quality))
print("sessions:", len(mk.dates), mk.dates[0], "->", mk.dates[-1])

rows = list(csv.DictReader(open(HERE / "pdf_examples.csv", encoding="utf-8")))
out = []
for r in rows:
    d = date.fromisoformat(r["date"])
    hh, mm = map(int, r["time"].split(":"))
    m = hh * 60 + mm - OPEN_MIN
    if d not in mk.index:
        print(f"#{r['id']:>2} {d} NOT IN DATA")
        out.append({"id": r["id"], "in_data": False})
        continue
    i = mk.index[d]
    tf = int(r["tf"])
    entry = float(r["entry"])
    # prices around the marker: close of the candle before it, open of the marker candle
    prev_close = float(mk.c[i, m - 1]) if m >= 1 else float("nan")
    lo = float(mk.l[i, max(0, m - tf):min(375, m + tf)].min())
    hi = float(mk.h[i, max(0, m - tf):min(375, m + tf)].max())
    inside = lo - 1 <= entry <= hi + 1
    out.append({"id": r["id"], "in_data": True, "prev_close": prev_close, "lo": lo, "hi": hi,
                "entry_within_marker_candles": inside})
    print(f"#{r['id']:>2} {d} {r['time']} {r['tf']}m {r['side']:5} entry {entry:9.2f} | data before marker "
          f"{prev_close:9.2f} (diff {entry - prev_close:+7.2f}) range[{lo:.2f}, {hi:.2f}] {'OK' if inside else 'OUTSIDE'}")

json.dump(out, open(HERE / "results" / "pdf_datacheck.json", "w"), indent=1, default=str)
