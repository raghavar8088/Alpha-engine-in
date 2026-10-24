"""Cached MCX futures bhavcopy -> fut.pkl, with build_dataset.py's own loader and bad-row filter.

    python build_futures.py <data6> <work6>
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import build_dataset as B  # noqa: E402


def main(data_dir, work_dir):
    os.makedirs(work_dir, exist_ok=True)
    fut, dropped = B.load(data_dir, "FUTCOM")
    bad = fut[(fut.traded) & ((fut.low > fut.high) | (fut.close <= 0))]
    print(f"futures: {len(fut):,} rows ({dropped} duplicates dropped); traded rows with bad OHLC or a price <= 0: {len(bad)}")
    for r in bad.itertuples():
        print(f"   dropped {r.sym} {r.expiry.date()} {r.date.date()} close {r.close}")
    fut = fut.drop(bad.index)
    for sym, g in fut.groupby("sym"):
        t = g[g.traded]
        print(f"  {sym:<11} contracts {g.expiry.nunique():>3}  days {g.date.min().date()} -> {g.date.max().date()}  "
              f"rows {len(g):>6,}  traded {len(t):>6,}")
    fut.to_pickle(os.path.join(work_dir, "fut.pkl"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
