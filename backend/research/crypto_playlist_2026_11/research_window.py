"""Slices of the research data, rebuilt with the same builders the desk uses."""

from __future__ import annotations

import numpy as np

import cp_markets as CM

_FULL: dict = {}


def full(name: str):
    if name not in _FULL:
        if name == "XAGUSD":
            _FULL[name] = None           # no silver minutes in the research data
        else:
            _FULL[name] = CM.load(name)
    return _FULL[name]


def slice_days(m, first_day: int, last_day: int | None = None):
    last_day = m.n_days if last_day is None else last_day
    a, z = int(m.d0[first_day]), int(m.d1[last_day - 1])
    if m.name == "BTCUSD":
        return CM.btc_market(m.t[a:z], m.o[a:z], m.h[a:z], m.l[a:z], m.c[a:z], m.vol_all[a:z], m.bv[a:z])
    key = np.repeat(m.date[first_day:last_day].astype(np.int64), (m.d1 - m.d0)[first_day:last_day])
    mm = CM.BM._finish(m.name, m.t[a:z], m.o[a:z], m.h[a:z], m.l[a:z], m.c[a:z], m.half[a:z], m.vol[a:z], key, False)
    return CM.YM._as_mkt(mm, m.name, m.name, m.cost)


def window(name: str, days: int | None = None, since: str | None = None, until: str | None = None):
    """The last `days` trading days, or the days from `since` to `until` (ISO dates), of a research market."""
    m = full(name)
    if m is None:
        return None
    if since is not None:
        d0 = int(np.searchsorted(m.date, np.datetime64(since)))
        d1 = int(np.searchsorted(m.date, np.datetime64(until), "right")) if until else m.n_days
        return slice_days(m, d0, d1)
    return slice_days(m, max(0, m.n_days - days))
