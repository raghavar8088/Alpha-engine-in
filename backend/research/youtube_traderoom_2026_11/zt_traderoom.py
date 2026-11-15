"""The Trade Room (Mayank Raj, @thetraderoomsss) study of 15 Nov 2026: the rule sets written from his teaching videos
and live sessions (zt_spec.py has every rule with its tag, quote and video time; analyses/thetraderoomsss.md is the
readable version). Conventions are the 11-channel study's (yc_common): fn(m, B, p, cache) -> signals from completed
bars only; a signal carries its bar's last row, so orders start on the next row; an order's life is counted in rows
from the signal row, never from a later bar (so a live day can never change a signal already seen).

TR-02  Daily EMA 9 side (yesterday's close against its EMA 9), a 5-minute base box (a demand box on a bullish day, a
       supply box on a bearish one), one of his three entry candles back at the box, the candle's extreme as the stop,
       1:2, at most three trades a day (NIFTY, BANKNIFTY; "Beginner To Advance EP-1").
TR-03  A momentum candle through the EMA 9 and EMA 15, a limit order at its 50%, the stop beyond the candle, 1:2
       (Delta gold and bitcoin, 15 minutes; his live sessions).
TR-04  TR-01's EMA 9/15 scalp on three entry candles (the 11-channel study's rules, unchanged) on the markets he
       trades it on live: Delta gold and bitcoin, 15 minutes.
"""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import body, ctx, green, lw, red, rng, sig, uw
from yt_engine import Exits

T1500 = 15 * 60          # no new index entries from 15:00 IST (the desk closes index books at its session end)


# ═══ TR-02 Daily EMA 9 side + 5-minute base box + entry candle, 1:2 (NIFTY, BANKNIFTY) ════════════════════════

def _daily_side(m, cache) -> np.ndarray:
    """Per trading day d: +1 when day d-1 closed above the EMA 9 of the daily closes, -1 when below, 0 for the first day
    (or a close exactly on it). Daily candles are the sessions themselves: a session's close is its last minute."""
    key = ("zt_dside",)
    if key not in cache:
        nd = int(m.n_days)
        side = np.zeros(nd, np.int8)
        if nd > 1:
            dc = np.asarray([float(m.c[int(m.d1[d]) - 1]) for d in range(nd)])
            e9 = I.ema(dc, 9)
            pc, pe = dc[:-1], e9[:-1]
            side[1:] = np.where(pc > pe, 1, np.where(pc < pe, -1, 0))
        cache[key] = side
    return cache[key]


def _bases(b, cache, tf: int, need: int = 2):
    """The 5-minute base boxes, scanned once from left to right. A base starts at a candle q and goes on while the next
    candles close inside q's high-low range (at least `need` of them: "two, three or four candles that cannot break out
    of a range"); the box is the base's lowest low to its highest high. The first close outside q's range, on the same
    day, ends the base and says which way the market left it: up = a demand (support) box, down = a supply
    (resistance) box. Returns rows (x, kind, lo, hi): x = the candle that left the box, known at its close."""
    key = ("zt_bases", tf, need)
    if key in cache:
        return cache[key]
    o, h, l, c, day = b.o, b.h, b.l, b.c, b.day
    n = len(c)
    out = []
    q = 0
    while q < n:
        cnt, lo, hi, x = 0, float(l[q]), float(h[q]), q + 1
        while x < n and day[x] == day[q] and l[q] <= c[x] <= h[q]:
            cnt += 1
            lo, hi = min(lo, float(l[x])), max(hi, float(h[x]))
            x += 1
        if x >= n:
            break                     # still inside q's range at the data's end: how it ends is not known yet
        if cnt >= need and day[x] == day[q]:
            out.append((x, 1 if c[x] > h[q] else -1, lo, hi))
            q = x                     # the candle that left the box may start the next base
        else:
            q += 1
    cache[key] = out
    return out


def entry_candle(b, j, side: int, ba: float) -> str | None:
    """His three entry candles (episode 1, 30:20-32:09), bullish for side +1 (bearish mirrored), or None:
    pin   a pin bar / hammer: the wick on the losing side at least twice the body, the close near the far end
          (the other wick at most a quarter of the range);
    big   a 'big bar': a full candle of the side's colour, body at least 70% of the range and at least the average
          body of the 20 candles before it;
    body  a big candle of the side's colour with the longer wick on the losing side: body at least half the range
          and at least that average body.
    A candle with long wicks on both sides is indecision and never an entry candle."""
    r, bd = rng(b, j), body(b, j)
    if not r > 0 or not np.isfinite(ba):
        return None
    lose, win = (lw(b, j), uw(b, j)) if side > 0 else (uw(b, j), lw(b, j))
    colour = green(b, j) if side > 0 else red(b, j)
    if lose >= 2 * bd and win <= 0.25 * r:
        return "pin"
    if colour and bd >= 0.7 * r and bd >= ba:
        return "big"
    if colour and bd >= 0.5 * r and bd >= ba and lose > win:
        return "body"
    return None


def tr02(m, B, p, cache):
    tf = int(p.get("tf", 5))
    b = B[tf]
    ba = ctx(m, B, tf, cache).body_avg(20)
    dside = _daily_side(m, cache)
    bases = _bases(b, cache, tf)
    n = len(b.c)
    out = []
    zones: list[list] = []                       # [x, kind, lo, hi, used]
    nxt = 0
    for j in range(n):
        while nxt < len(bases) and bases[nxt][0] < j:      # a box exists from the candle after the one that left it
            x, kind, lo, hi = bases[nxt]
            zones.append([x, kind, lo, hi, False])
            nxt += 1
        d = int(b.day[j])
        # boxes live through their own session and the next one; a close through the far side ends a box
        zones = [z for z in zones if d - int(b.day[z[0]]) <= 1]
        side = int(dside[d]) if d < len(dside) else 0
        cj = float(b.c[j])
        hit = None
        for z in zones:
            if z[4]:
                continue
            if (z[1] > 0 and cj < z[2]) or (z[1] < 0 and cj > z[3]):
                z[4] = True                          # broken: no trade from it any more
                continue
            if hit is None and side != 0 and z[1] == side:
                at_box = (float(b.l[j]) <= z[3] and cj >= z[2]) if side > 0 else (float(b.h[j]) >= z[2] and cj <= z[3])
                if at_box:
                    hit = z
        if hit is None or int(b.ist0[j]) >= T1500 or int(b.ist0[j]) < 9 * 60 + 15:
            continue
        kind = entry_candle(b, j, side, float(ba[j]))
        if kind is None:
            continue
        hit[4] = True                                # one trade a box
        if side > 0:
            out.append(sig(b, j, 1, float(b.l[j]), f"TR02_LONG_{kind}", info={"box_lo": hit[2], "box_hi": hit[3]}))
        else:
            out.append(sig(b, j, -1, float(b.h[j]), f"TR02_SHORT_{kind}", info={"box_lo": hit[2], "box_hi": hit[3]}))
    return out


def tr02_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ═══ TR-03 Momentum candle through the EMA 9 and 15, limit at its 50%, stop beyond it, 1:2 (gold, bitcoin) ════════

def tr03(m, B, p, cache):
    tf = int(p.get("tf", 15))
    wait = int(p.get("wait", 3))                 # the limit order lives for the next three candles
    b = B[tf]
    c = ctx(m, B, tf, cache)
    e9, e15, ba = c.ema(9), c.ema(15), c.body_avg(20)
    out = []
    for j in range(20, len(b.c)):
        if not np.isfinite(ba[j]):
            continue
        r, bd = rng(b, j), body(b, j)
        if not (r > 0 and bd >= 0.6 * r and bd >= 1.5 * ba[j]):
            continue
        top, bot = max(e9[j], e15[j]), min(e9[j], e15[j])
        mid = 0.5 * float(b.h[j] + b.l[j])
        exp = int(b.i1[j]) + wait * tf
        if green(b, j) and b.o[j] < bot and b.c[j] > top:
            out.append(sig(b, j, 1, float(b.l[j]), "TR03_LONG", entry_limit=mid, expire_k=exp))
        elif red(b, j) and b.o[j] > top and b.c[j] < bot:
            out.append(sig(b, j, -1, float(b.h[j]), "TR03_SHORT", entry_limit=mid, expire_k=exp))
    return out


def tr03_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ═══ TR-04 TR-01's EMA 9/15 three-candle scalp on Delta gold and bitcoin, 15 minutes ═════════════════════════════
# The code is the 11-channel study's tr01 (yc_channels.py) with the bar size as a parameter; the order's life is counted
# in rows from the signal row (two more candles), which is the same thing on complete data.

def tr04(m, B, p, cache):
    tf = int(p.get("tf", 15))
    b = B[tf]
    c = ctx(m, B, tf, cache)
    e9, e15, ba = c.ema(9), c.ema(15), c.body_avg(20)
    out = []
    for j in range(20, len(b.c)):
        if not np.isfinite(ba[j]):
            continue
        r, bd = rng(b, j), body(b, j)
        if not r > 0:
            continue
        exp = int(b.i1[j]) + 2 * tf
        if e9[j] > e15[j] and e9[j] > e9[j - 3] and e15[j] > e15[j - 3] and b.l[j] <= e9[j] and b.c[j] > e15[j]:
            pin = lw(b, j) >= 2 * bd
            big = green(b, j) and bd >= 0.6 * r and bd >= ba[j]
            cross = b.o[j] < e9[j] < b.c[j]
            if pin or big or cross:
                out.append(sig(b, j, 1, float(b.l[j]), "TR04_LONG", entry_stop=float(b.h[j]), expire_k=exp))
        elif e9[j] < e15[j] and e9[j] < e9[j - 3] and e15[j] < e15[j - 3] and b.h[j] >= e9[j] and b.c[j] < e15[j]:
            pin = uw(b, j) >= 2 * bd
            big = red(b, j) and bd >= 0.6 * r and bd >= ba[j]
            cross = b.o[j] > e9[j] > b.c[j]
            if pin or big or cross:
                out.append(sig(b, j, -1, float(b.h[j]), "TR04_SHORT", entry_stop=float(b.l[j]), expire_k=exp))
    return out


def tr04_x(m, B, p, cache):
    return Exits(target_r=2.0)
