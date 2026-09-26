"""Is the Chartink catalogue shippable — and, with --live, is it still true?

Two modes, because the two failures are different.

OFFLINE (the default) checks the things that make a chip render at all: a slug the adapter
would actually accept, a group the panel knows how to draw, a label and a `why`. Those are
pure-data mistakes, they are silent — a chip in an unknown group simply never appears —
and they need no network.

LIVE (`--live`) fetches every screener and runs it. Chartink is somebody else's site: a
public screener can be made private, deleted, or quietly rewritten by its author, and any
of those turns a chip into a dead end. This is not a CI test; it is the thing to run when
a chip starts misbehaving, or before adding new ones.

Run: python -m tests.screener.verify_chartink_catalog
     python -m tests.screener.verify_chartink_catalog --live
"""
import asyncio
import re
import sys

from app.services.screener.chartink import (
    GROUP_ORDER,
    NAMED,
    PRESETS,
    _SLUG_RE,
    parse_slug,
)

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  - ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def check_slugs() -> None:
    print("every slug is one the adapter would accept")
    bad = [k for k in NAMED if not _SLUG_RE.match(k)]
    check("all slugs match the adapter's own pattern", not bad, str(bad))
    # parse_slug is what the endpoint actually runs on user input. A catalogue slug that
    # does not survive it would be unreachable from the very panel that lists it.
    broken = [k for k in NAMED if parse_slug(k) != k]
    check("all slugs survive parse_slug unchanged", not broken, str(broken))
    full = [k for k in NAMED if parse_slug(f"https://chartink.com/screener/{k}") != k]
    check("and survive being pasted as a full URL", not full, str(full))


def check_groups() -> None:
    print("\nevery entry lands in a group the panel draws")
    groups = {v.get("group", "Other") for v in NAMED.values()}
    orphans = sorted(groups - set(GROUP_ORDER))
    # The panel iterates GROUP_ORDER and filters the catalogue into each one. An entry
    # whose group is not in that list is never iterated over, so it renders NOWHERE while
    # looking perfectly fine in the payload.
    check("no entry sits in a group missing from GROUP_ORDER", not orphans, str(orphans))
    check("GROUP_ORDER has no duplicates", len(GROUP_ORDER) == len(set(GROUP_ORDER)))
    empty = [g for g in GROUP_ORDER if not any(v.get("group") == g for v in NAMED.values())]
    check("and no group in the order is empty", not empty, str(empty))


def check_copy() -> None:
    print("\nevery chip carries a label and an explanation")
    no_label = [k for k, v in NAMED.items() if not (v.get("label") or "").strip()]
    check("all have a label", not no_label, str(no_label))
    no_why = [k for k, v in NAMED.items() if not (v.get("why") or "").strip()]
    # `why` is the chip's tooltip AND the only place a misleading Chartink title gets
    # corrected. An entry without one is a chip nobody can evaluate.
    check("all have a why", not no_why, str(no_why))
    # Catching a placeholder, not enforcing a word count. "At the highest point of the
    # last year." is 38 characters and says everything there is to say about that clause;
    # a bar set above it would push padding into good copy. Anything under ~25 is "TODO".
    short = [k for k, v in NAMED.items() if len((v.get("why") or "").strip()) < 25]
    check("no why is a placeholder", not short, str(short))

    labels = [v["label"] for v in NAMED.values()]
    dupes = sorted({x for x in labels if labels.count(x) > 1})
    # Two chips with the same face and different clauses is a trap, not a convenience.
    check("no two chips share a label", not dupes, str(dupes))


def check_rejects_documented() -> None:
    print("\nthe rejected screeners stay documented")
    import app.services.screener.chartink as CK

    src = (CK.__doc__ or "") + open(CK.__file__, encoding="utf-8").read()
    for slug in ("rounding-bottom", "descending-triangle", "200-ema-crossover",
                 "all-time-high", "near-all-time-high"):
        # Each of these was probed and rejected for a specific reason. Without the note,
        # the next person re-probes them and re-adds the broken ones.
        listed = slug in NAMED
        noted = re.search(rf"^#\s+{re.escape(slug)}\s", src, re.M) is not None
        check(f"{slug} is left out and the reason is written down",
              (not listed) and noted,
              "still in the catalogue" if listed else ("no note" if not noted else ""))


def check_presets_untouched() -> None:
    print("\nthe computed presets are still separate from the named screeners")
    overlap = set(PRESETS) & set(NAMED)
    check("no key appears in both PRESETS and NAMED", not overlap, str(overlap))
    check("PRESETS still carry runnable clauses",
          all(p.get("clause") for p in PRESETS.values()))


async def check_live() -> None:
    print("\nLIVE - fetching and running every screener in the catalogue")
    from app.services.screener import chartink as CK

    dead, empty, ok = [], [], 0
    for slug in NAMED:
        res = await CK.named(slug, fresh=True)
        if not res.get("ok"):
            dead.append((slug, (res.get("error") or "")[:70]))
        else:
            ok += 1
            if not res.get("rows"):
                empty.append(slug)
        await asyncio.sleep(1.2)  # somebody else's site; do not hammer it

    print(f"\n  {ok}/{len(NAMED)} ran, {len(empty)} returned no rows")
    for slug, err in dead:
        print(f"    DEAD  {slug}: {err}")
    if empty:
        print(f"    empty right now (fine for rare patterns, and for intraday scans out "
              f"of hours): {', '.join(empty)}")
    check("every catalogued screener still runs", not dead,
          f"{len(dead)} dead" if dead else "")


def main() -> int:
    check_slugs()
    check_groups()
    check_copy()
    check_rejects_documented()
    check_presets_untouched()
    if "--live" in sys.argv:
        asyncio.run(check_live())
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        return 1
    print(f"All checks passed - {len(NAMED)} screeners across {len(GROUP_ORDER)} groups.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
