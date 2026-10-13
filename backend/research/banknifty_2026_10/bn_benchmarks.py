"""Naive, signal-free benchmarks on the same real BANKNIFTY option closes, the same contract,
costs and exits as bn_swing_replay.py - to tell a daily strategy's TIMING apart from simply
holding calls through 2016-2026's rise (17,000 -> 55,000). Diagnostic only: not trials."""
import statistics
import bn_common as C
import bn_swing_replay as SW


def run(kind, hold):
    return SW.run_rule(f"naive_{kind}_{hold}", lambda i, h, a: kind, None, None, hold)


def main():
    SW.init_worker()
    out = {}
    for kind in ("CE", "PE", "STRADDLE"):
        for hold in (1, 2, 5):
            tr = run(kind, hold)
            ex = [t[9] for t in tr if C.kdate(t[0]) <= C.EXPLORE_END]
            ho = [t[9] for t in tr if C.kdate(t[0]) > C.EXPLORE_END]
            out[f"{kind}_{hold}"] = {"explore": (len(ex), statistics.mean(ex), C.tstat(ex)), "holdout": (len(ho), statistics.mean(ho), C.tstat(ho))}
            print(f"always {kind:<8} held {hold} session(s): explore {len(ex):4d} tr {statistics.mean(ex):+7.0f}/tr t {C.tstat(ex):+.2f} | "
                  f"holdout {len(ho):4d} tr {statistics.mean(ho):+7.0f}/tr t {C.tstat(ho):+.2f}")
    import json, os
    with open(os.path.join(C.DATA, "benchmarks.json"), "w") as f:
        json.dump(out, f, indent=1)
    return out


if __name__ == "__main__":
    main()
