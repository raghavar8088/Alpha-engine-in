"""Phase 8: choose the LLM provider by testing, not preference.

    python llm_eval.py sample          -> DATA/llm_eval/label_me.csv: 300 announcements of
                                          universe stocks, stratified by subject, label columns
                                          empty — for the owner to fill in (category, materiality,
                                          direction, using event_classifier's definitions)
    python llm_eval.py run <provider>  -> classifies the labelled file with `anthropic` or `openai`
                                          (keys from the environment) twice, and reports agreement
                                          with the labels, consistency between the two runs, and
                                          latency. Uses event_classifier's exact prompt and schema.

Nothing is sent anywhere until `run` is called with a key set; only public announcement text
is sent.
"""
from __future__ import annotations

import asyncio
import csv
import gzip
import json
import os
import pathlib
import random
import re
import sys
import time

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from stubpkg import DATA  # noqa: E402

OUT = DATA / "llm_eval"
FIELDS = ["id", "symbol", "time", "subject", "text", "label_category", "label_materiality", "label_direction"]


def _prompt_and_schema():
    """event_classifier's SYSTEM, SCHEMA and prompt builder, read from the committed module."""
    src = (REPO / "backend" / "app" / "services" / "event_classifier.py").read_text(encoding="utf-8")
    ns: dict = {}
    for name in ("SYSTEM", "SCHEMA"):
        m = re.search(rf"^{name} = (.+?)\n(?=[A-Z_]+ = |\n)", src, re.S | re.M)
        ns[name] = eval(m.group(1), {})                      # literal text and dict, from our own file
    return ns["SYSTEM"], ns["SCHEMA"]


def sample(n: int = 300) -> None:
    stocks = {p.stem for p in (DATA / "intraday" / "15m").glob("*.ibar") if not p.stem.startswith("NIFTY")}
    pool = []
    for p in sorted((DATA / "intraday" / "nse_events" / "ann").glob("*.json.gz")):
        for r in json.load(gzip.open(p, "rt", encoding="utf-8"))["rows"]:
            if r.get("symbol") in stocks and r.get("t"):
                pool.append(r)
    rng = random.Random(7)
    by_subject: dict[str, list] = {}
    for r in pool:
        by_subject.setdefault((r.get("desc") or "other").strip().lower(), []).append(r)
    picked = []
    subjects = sorted(by_subject, key=lambda k: -len(by_subject[k]))
    while len(picked) < n and subjects:                      # round-robin over subjects
        for k in list(subjects):
            if by_subject[k]:
                picked.append(by_subject[k].pop(rng.randrange(len(by_subject[k]))))
                if len(picked) >= n:
                    break
            else:
                subjects.remove(k)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "label_me.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in picked:
            w.writerow({"id": f"{r['symbol']}:{r.get('seq_id')}", "symbol": r["symbol"], "time": r["t"],
                        "subject": r.get("desc"), "text": (r.get("attchmntText") or "")[:600],
                        "label_category": "", "label_materiality": "", "label_direction": ""})
    print(f"wrote {len(picked)} announcements ({len(set(r.get('desc') for r in picked))} subjects) to {OUT / 'label_me.csv'}")


async def run(provider_name: str, path: pathlib.Path) -> None:
    sys.path.insert(0, str(REPO / "ai-service"))
    sys.path.insert(0, str(REPO / "shared"))
    os.environ["AI_PROVIDER"] = provider_name
    from ai_service.provider import ProviderError, get_provider
    p = get_provider()
    assert p.configured, f"{provider_name} is not configured (set its key{' and OPENAI_MODEL' if provider_name == 'openai' else ''})"
    system, schema = _prompt_and_schema()
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if r["label_materiality"]]
    out = []
    for r in rows:
        prompt = f"Company: {r['symbol']} (NSE: {r['symbol']})\nSubject: {r['subject']}\nFiled at: {r['time']}\n\nText:\n{r['text']}"
        answers, ms = [], []
        for _ in range(2):
            t0 = time.monotonic()
            try:
                answers.append(json.loads(await p.complete(system, prompt, max_tokens=4000, json_schema=schema)))
            except (ProviderError, ValueError) as exc:
                answers.append({"error": str(exc)})
            ms.append(time.monotonic() - t0)
        out.append({"label": r, "answers": answers, "seconds": ms})
    ok = [o for o in out if "error" not in o["answers"][0]]
    acc = {f: sum(o["answers"][0].get(f) == o["label"][f"label_{f}"] for o in ok) / len(ok) if ok else None
           for f in ("category", "materiality", "direction")}
    same = sum(o["answers"][0] == o["answers"][1] for o in ok) / len(ok) if ok else None
    hi = [o for o in ok if o["label"]["label_materiality"] == "high"]
    rep = {"provider": provider_name, "model": getattr(p, "model", None), "labelled": len(rows), "answered": len(ok),
           "accuracy": acc, "high_materiality_recall": (sum(o["answers"][0].get("materiality") == "high" for o in hi) / len(hi)) if hi else None,
           "same_answer_twice": same, "median_seconds": sorted(s for o in out for s in o["seconds"])[len(out)] if out else None}
    json.dump({"report": rep, "rows": out}, open(OUT / f"result_{provider_name}.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "sample":
        sample()
    else:
        asyncio.run(run(sys.argv[2], OUT / (sys.argv[3] if len(sys.argv) > 3 else "label_me.csv")))
