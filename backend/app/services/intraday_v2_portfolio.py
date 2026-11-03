"""The live engine's entry rules, for the backtest: every strategy's candidates decided together.

intraday_v2_engine._take decides at each bar close with ALL strategies' signals ranked together
by priority:
  - a strategy holds at most `slots` positions, and never the same stock twice;
  - a stock already held by `max_per_symbol` OTHER strategies is closed to a third
    (pre-registered own-book strategies are neither blocked by nor counted in that cap);
  - the strategy's cash (capital + realised - deployed) must cover the position.
The backtest's own `accept` judges each strategy alone and leaves out the cross-strategy cap.
Measured on 6 Oct - 3 Nov 2026 for the Rank top 10, it reproduced 313 of the tournament's 1,091
live trades; with these rules about 645 (INTRADAY_STOCKS_AI_UPGRADE_PLAN.md, Phase 2). The rest
differ because live exits on minute bars free slots at other moments than 15-minute bars do.

Every position is intraday (flat by the close), so days are independent apart from each
strategy's realised cash, which carries over. Candidates are therefore taken one DAY at a
time: a day of a few thousand candidates in memory, never two years of a million.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Callable, Iterable

# candidate tuple: (strategy_id, symbol, entry_t, exit_t, side, entry_px, exit_px, qty,
#                   gross, fees, net, reason, priority) — intraday_v2_backtest's format
SID, SYM, ET, XT, EP, QTY, NET, PRIO = 0, 1, 2, 3, 5, 7, 10, 12


def accept_live(days: Iterable[list[tuple]], own_book: set[str], capital: float, slots: int = 5,
                max_per_symbol: int = 2, tiebreak: Callable[[tuple], tuple] | None = None,
                skipped: dict | None = None) -> dict[str, list[tuple]]:
    """Take each day's candidates under the live rules. `days` yields one day's candidate
    tuples at a time (any order). Ties at one moment go to the higher priority, then to
    `tiebreak(row)` (the live loop's order: universe order, then catalog order). Counts of
    the reasons candidates were refused go into `skipped`. Returns {strategy: taken rows}."""
    realized: dict[str, float] = defaultdict(float)
    taken: dict[str, list[tuple]] = defaultdict(list)
    for rows in days:
        rows = sorted(rows, key=lambda r: (r[ET], -r[PRIO]) + (tiebreak(r) if tiebreak else ()))
        heap: list = []                       # (exit_t, seq, sid, sym, net, cost) of open positions
        per_s: dict[str, int] = defaultdict(int)
        per_sym: dict[str, set] = defaultdict(set)
        held: set = set()
        deployed: dict[str, float] = defaultdict(float)
        for seq, r in enumerate(rows):
            sid, sym, et = r[SID], r[SYM], r[ET]
            while heap and heap[0][0] <= et:
                _x, _q, s2, y2, net, cost2 = heapq.heappop(heap)
                per_s[s2] -= 1
                held.discard((s2, y2))
                per_sym[y2].discard(s2)
                realized[s2] += net
                deployed[s2] -= cost2
            cost = r[EP] * r[QTY]
            if per_s[sid] >= slots:
                why = "slots full"
            elif (sid, sym) in held:
                why = "already holding"
            elif sid not in own_book and len(per_sym[sym] - {sid}) >= max_per_symbol:
                why = "stock crowded"
            elif capital + realized[sid] - deployed[sid] < cost:
                why = "cash"
            else:
                why = None
            if why is not None:
                if skipped is not None:
                    skipped[why] = skipped.get(why, 0) + 1
                continue
            heapq.heappush(heap, (r[XT], seq, sid, sym, r[NET], cost))
            per_s[sid] += 1
            held.add((sid, sym))
            deployed[sid] += cost
            if sid not in own_book:
                per_sym[sym].add(sid)
            taken[sid].append(r)
        while heap:                           # the day's last exits: book their cash
            _x, _q, s2, _y, net, _c = heapq.heappop(heap)
            realized[s2] += net
    return dict(taken)
