"""Writes the study's readable rules from the cards: analyses/<topic>.md (one file per topic, every video and strategy
with its rules grouped the way a trader reads them) and specs/RULES.md (every strategy, compact). Tags: [E] stated in
the video, [I] inferred from its examples, [A] a research assumption we added to make it codeable (never the
creator's). Times are mm:ss into the video and link to that moment.

    python -I zd_rules.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import zd_cardlib as CL  # noqa: E402

TOPICS = [("nifty_option_buying", "NIFTY intraday option buying"), ("stock_intraday", "Indian stock intraday"),
          ("btc_intraday", "Bitcoin intraday"), ("commodity_intraday", "MCX commodity intraday")]
STATUS = {"ready": "every core rule stated", "with_assumptions": "codeable once the [A] rules below fill the gaps",
          "concept_only": "an idea, not rules", "not_testable": "needs data or discretion the desk cannot simulate"}


def _sec(t: str) -> int:
    p = [int(x) for x in t.split(":")]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


def _times(vid, times):
    return ", ".join(f"[{t}](https://youtu.be/{vid}?t={_sec(t)})" for t in times)


def strategy_md(c, s, meta, blocked: dict, level="##") -> list[str]:
    vid = c["video"]
    out = [f"{level} {s['sid']} {s['name']}", ""]
    out.append(f"Video: \"{meta['title']}\" - {meta['channel']}, uploaded {meta['uploaded'] or 'unknown'}, "
               f"{meta['minutes']} min - https://youtu.be/{vid} (transcript: {meta['captions'] or 'n/a'})")
    if s["duplicate"]:
        state = f"Duplicate of {s['duplicate']['of']} - not added again. {s['duplicate']['why']}."
    elif s["sid"] in blocked:
        state = f"Blocked (no paper account): {blocked[s['sid']]}."
    else:
        state = f"Coded as v1 ({STATUS.get(s['status'], s['status'])})."
    out += [f"Status: {state}", ""]
    stated = [r for r in s["rules"] if r["tag"] in "EI"]
    ours = [r for r in s["rules"] if r["tag"] == "A"]
    out.append("Creator's rules ([E] stated, [I] inferred from the examples):")
    for kind in CL.KINDS_ORDER:
        rs = [r for r in stated if r["kind"] == kind]
        if not rs:
            continue
        out.append(f"- **{CL.KIND_LABEL[kind]}**")
        for r in rs:
            tm = f" ({_times(vid, r['times'])})" if r["times"] else ""
            out.append(f"  - [{r['tag']}] {r['text']}{tm}")
    if ours:
        out += ["", "Research assumptions used to code it ([A] - ours, not the creator's):"]
        for r in ours:
            out.append(f"- [A] {r['text']}")
    out += ["", f"Why the status: {'; '.join(s['reasons']) or '-'}", ""]
    return out


def video_extras(c) -> list[str]:
    vid = c["video"]
    out = []
    if c["vague"] or c["unclear"]:
        out.append("Missing or ambiguous in the video:")
        for v in c["vague"]:
            at = f" ({_times(vid, [v['at']])})" if v["at"] else ""
            out.append(f"- \"{v['term']}\"{at}: {v['why']}. Coded as: {v['suggestion']}.")
        for u in c["unclear"]:
            out.append(f"- Open question: {u}")
        out.append("")
    if c["claims"]:
        out.append("Claims (quoted as said; not verified):")
        for k in c["claims"]:
            at = f" ({_times(vid, [k['at']])})" if k["at"] else ""
            out.append(f"- {k['value']} [{k['kind']}, {k['period'] or 'period not stated'}]{at}")
        out.append("")
    if c["examples"]:
        out.append("Example trades shown:")
        for x in c["examples"]:
            at = f" ({_times(vid, [x['at']])})" if x["at"] else ""
            out.append(f"- {x['date'] or 'date not shown'} {x['instrument']} {x['direction']}: {x['setup']}; entry {x['entry'] or '-'}, "
                       f"stop {x['stop'] or '-'}, target {x['target'] or '-'} -> {x['outcome']}{(' - ' + x['note']) if x['note'] else ''}{at}")
        out.append("")
    if c["promotions"]:
        out.append("Promotions: " + "; ".join(f"{p['what']} ({p['from']}-{p['to']})" for p in c["promotions"]))
        out.append("")
    return out


def main():
    sys.path.insert(0, str(HERE))
    import zd_strategies as ZS
    blocked = ZS.BLOCKED
    cards = CL.all_cards()
    (HERE / "analyses").mkdir(exist_ok=True)
    (HERE / "specs").mkdir(exist_ok=True)
    rules_all = ["# The four-topic intraday study: strategy rules", "",
                 "Generated from cards/<video>.txt by zd_rules.py. [E] stated in the video, [I] inferred from its examples, [A] a",
                 "research assumption added to make it codeable. Coded strategies are v1: a changed rule is a new version.", ""]
    for topic, label in TOPICS:
        cs = [c for c in cards if c["topic"] == topic]
        cs.sort(key=lambda c: c["strategies"][0]["sid"])
        lines = [f"# {label}: {len(cs)} videos", "",
                 "Each strategy is written from the video's own words (timestamps link to the moment). The [A] lines are",
                 "ours: the creator did not say them. Duplicates of the library and blocked strategies are listed with the reason.",
                 ""]
        rules_all += [f"## {label}", ""]
        for c in cs:
            meta = CL.video_meta(c["video"])
            for s in c["strategies"]:
                lines += strategy_md(c, s, meta, blocked)
                rules_all += strategy_md(c, s, meta, blocked, "###")
            lines += video_extras(c)
        (HERE / "analyses" / f"{topic}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (HERE / "specs" / "RULES.md").write_text("\n".join(rules_all) + "\n", encoding="utf-8")
    print("analyses", len(TOPICS), "strategies", sum(len(c["strategies"]) for c in cards))


if __name__ == "__main__":
    main()
