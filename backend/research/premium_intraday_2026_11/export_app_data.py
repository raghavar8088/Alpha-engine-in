"""Generate frontend/app/premium-strategies/intraday/researchData.ts from the frozen research results.

Inputs (all in this folder): prereg.json, results/new_strategies.json, results/imported_top25.json, register.json,
and the desk's test report (premium-intraday-service/tests/report.json). Regenerate rather than hand-edit.
"""
import hashlib
import json

from common import HERE, ROOT, SERVICE

OUT = ROOT / "frontend" / "app" / "premium-strategies" / "intraday" / "researchData.ts"
BRANCH = "https://github.com/raghavar8088/Alpha-engine-in/tree/research/premium-intraday-prereg-20261122"

COMMON = [
    ["Universe", "Top 150 NSE stocks by 20-session median traded value, price at least Rs 50, at least 15 sessions of "
                 "history, no probable split or bonus in the last 20 sessions; a stock opening more than 15% from its "
                 "previous close is set aside for the day. Shorts only in F&O underlyings (previous session's list)."],
    ["Bars and timing", "Five-minute bars; every decision is taken when a bar closes, using only closed bars. 09:30 "
                        "screen, 09:40 persistence check, 09:45 plan; the first bar that can trigger is 09:45-09:50."],
    ["Entry", "At the close of the trigger bar, only if that close is inside the setup's entry range; beyond it the "
              "setup is recorded as missed. Fill = close plus slippage by the stock's traded-value band "
              "(1.50 / 2.85 / 3.73 / 4.12 bp a side)."],
    ["Sizing", "0.25% of the day's starting equity at risk, counting the stop distance and the estimated round-trip "
               "cost per share; one position at most 50% of equity; all positions at most 1.5x equity; at most 2% of "
               "the trigger bar's volume (a partial fill otherwise)."],
    ["Book limits", "3 positions at once, 0.75% total open stop risk, at most 2 positions and 0.5% risk in one sector, "
                    "one position per stock; new entries stop after a 1% daily loss (realised + open) and after 14:30."],
    ["Exits", "Stop: a market order (a bar that opens through it fills at the open). Target: a limit order filled only "
              "when the price trades through it by a tick. A bar touching both counts as the stop. Time exit at the "
              "strategy's time; square-off from 15:05, retried at 15:10; still open after that is a failed exit with "
              "an alert."],
    ["Costs", "Angel One's intraday charges (the app's fee card): brokerage min(Rs 20, 0.25%) an order, STT 0.025% of "
              "the sell, NSE 0.00297%, SEBI and IPFT Rs 10/crore, stamp 0.003% of the buy, GST 18% on fees."],
]

RULES = {
    "N01": [
        ["Direction", "Long leaders of a strong sector; short laggards of a weak one (F&O only)."],
        ["09:30 stock", "Opening range (09:15-09:30) 0.40%-2.50% of the open; same-time volume at least 1.5x normal; "
                        "range closed up (long) or down (short); price above (below) VWAP; ahead of (behind) the median "
                        "of its sector peers since 09:15."],
        ["09:30 sector", "Strong: ranked 1-2, ahead of NIFTY, at least 60% of members above their open and above VWAP, "
                         "not narrow, at least 60% of members with data. Weak is the mirror (bottom 2)."],
        ["09:40 check", "Market bull trend or mixed (long), bear trend or mixed (short); the sector still top 3 (bottom 3) "
                        "with 55%+ (45%-) of members above their open and not narrow; the stock still beyond its range "
                        "midpoint and VWAP. Best 3 per side by volume x relative strength."],
        ["Trigger", "A five-minute close above the range high (below the range low), bars closing 09:50-11:30."],
        ["Entry range", "Range high to range high + max(30% of the range, 0.10%); mirror for shorts."],
        ["Stop", "Range midpoint; skipped if it is under 0.35% or over 1.50% from the entry."],
        ["Target / time", "2R long, 3R short (walk-forward choice, frozen); out at 15:00."],
        ["Cancelled", "A close back through the range midpoint before the trigger."],
    ],
    "N02": [
        ["Direction", "Long the strongest relative-strength leaders; short the weakest laggards (F&O only)."],
        ["09:30", "Strength = half (stock - sector peers) + half (stock - NIFTY) since 09:15; leaders need both parts "
                  "positive, 1.3x volume and price above VWAP; top 8 (bottom 8 for laggards). The stock's sector must "
                  "not oppose: not weak and ahead of NIFTY for longs."],
        ["09:40 check", "Still in the top (bottom) 8 with both parts of the same sign and 1.3x volume; market not the "
                        "opposite trend. Best 4 kept."],
        ["Trigger", "A close above the day's high as of 09:45 (below the low), bars closing 09:50-12:30; entry within "
                    "0.25% beyond it."],
        ["Stop", "VWAP at the trigger bar minus 0.10% (plus for shorts), widened to 0.40% if closer; skipped if over 1.50%."],
        ["Target / time", "2R long, 1.5R short (frozen); out at 15:00."],
        ["Cancelled", "A close through VWAP before the trigger."],
    ],
    "N03": [
        ["Direction", "With the trend on trend days only: long on a bull-trend morning, short on a bear-trend morning."],
        ["09:30", "Up at least 0.5% since the open (down for shorts), 1.2x volume, every five-minute close above (below) "
                  "VWAP; its sector moving the same way and not opposed."],
        ["09:40 check", "Market condition bull trend (NIFTY +0.20% or more since the open, 60%+ of stocks above their open "
                        "and VWAP) or bear trend for shorts; the stock never closed through VWAP. Best 5 per side."],
        ["Trigger", "10:00-13:30: a bar whose low comes within 0.10% of VWAP and closes back above VWAP and above its open "
                    "(mirror for shorts); entry only if that close is within 0.60% of VWAP."],
        ["Stop", "The lower of the bar's low and VWAP, minus 0.15%; band 0.35%-1.20%."],
        ["Target / time", "3R both sides (frozen); out at 15:00."],
        ["Cancelled", "Any close 0.20% through VWAP."],
    ],
    "N04": [
        ["Direction", "Against a gap that fails: a failed gap-up is a short (F&O only), a failed gap-down a long."],
        ["09:30", "Gap at least max(1.0%, half the daily ATR) from the previous close; same-time volume at most 2.5x; the "
                  "opening range turned against the gap and price back beyond the open. The sector is not moving with "
                  "the gap (fewer than half its members up since the open after a gap-up)."],
        ["09:40 check", "Not a trend day in the gap's direction; price still beyond the open and VWAP."],
        ["Trigger", "A close below the range low (short) or above the range high (long), bars closing 09:50-11:00; "
                    "entry within 0.30% beyond the level."],
        ["Stop", "The opposite range extreme; band 0.40%-2.00%."],
        ["Target / time", "2R or the previous close, whichever is nearer; skipped with less than 1R of room; out at 13:30."],
        ["News (ladder L3)", "Only without a material NSE announcement since the previous close (tested Nov 2025 on)."],
        ["Cancelled", "A close beyond the far side of the opening range (the gap held)."],
    ],
    "N05": [
        ["Before the open", "The previous session was an NR7 (narrowest range of 7) or an inside day."],
        ["09:30", "Opening range 0.25% wide or more but at most 70% of its 20-session median; volume at least 0.8x; "
                  "both directions (shorts F&O only)."],
        ["09:40 check", "Price still inside the opening range; market not the opposite trend. The 4 most compressed kept."],
        ["Trigger", "A close above the range high or below the range low, bars closing 09:50-12:00; the first side to "
                    "trigger cancels the other; entry within 25% of the range + 0.10% beyond the edge."],
        ["Stop", "The opposite edge, widened to 0.35% if closer; skipped if over 1.20%."],
        ["Target / time", "2R (frozen); out at 15:00."],
    ],
    "N06": [
        ["Before the open", "A material NSE announcement (results, board outcome, order, deal, rating, regulatory action, "
                            "takeover or management disclosure) disseminated between the previous session's 15:30 and 09:15, "
                            "by the exchange's own timestamp."],
        ["09:30", "Gap of at least 1.0% in either direction (shorts F&O only); same-time volume at least 2x; the whole "
                  "opening range on the gap's side of the previous close; price beyond VWAP; the sector not opposed."],
        ["09:40 check", "Still beyond VWAP and the range midpoint; market not the opposite trend."],
        ["Trigger", "A close beyond the opening range in the gap's direction, bars closing 09:50-11:00; entry within 0.40%."],
        ["Stop", "The other side of the opening range, widened to 0.40% if closer; skipped if over 2.00%."],
        ["Target / time", "2R (frozen); out at 15:00."],
        ["Cancelled", "A close back through the opening-range midpoint."],
    ],
}


def slim(s: dict) -> dict:
    keep = ("trades", "days_traded", "sessions", "net", "fees", "slippage", "costs", "return_pct", "mean_R", "mean_net_bp",
            "win_pct", "profit_factor", "max_dd_pct", "t_day", "avg_daily_net", "avg_daily_net_sessions", "months",
            "months_up", "avg_notional", "failed_exits", "partials", "net_ex_best5pct_days", "top_symbol_share")
    out = {k: s.get(k) for k in keep if s.get(k) is not None}
    for side in ("long", "short"):
        if s.get(side, {}).get("trades"):
            out[side] = {k: s[side].get(k) for k in ("trades", "mean_R", "net", "profit_factor", "t_day", "win_pct")}
    if s.get("exits"):
        out["exits"] = s["exits"]
    return out


def r(x, n=4):
    if isinstance(x, float):
        return round(x, n)
    if isinstance(x, dict):
        return {k: r(v, n) for k, v in x.items()}
    if isinstance(x, list):
        return [r(v, n) for v in x]
    return x


def main():
    pre_raw = (HERE / "prereg.json").read_bytes()
    pre = json.loads(pre_raw)
    new = json.loads((HERE / "results" / "new_strategies.json").read_text())
    imp = json.loads((HERE / "results" / "imported_top25.json").read_text())
    reg = json.loads((HERE / "register.json").read_text())
    rep_p = SERVICE / "tests" / "report.json"
    rep = json.loads(rep_p.read_text()) if rep_p.exists() else {}
    strategies = []
    for sid, s in new["strategies"].items():
        sides = {}
        for side in ("LONG", "SHORT"):
            x = s[side]
            sides[side] = {"target_R": x["target_R"], "status": x["status"], "reason": x["reason"],
                           "checks": x["checks"], "walk_forward": slim(x["walk_forward"]),
                           "wf_fold_mean_R": x["wf_fold_mean_R"], "final": slim(x["final"]),
                           "final_x2_mean_R": x["final_x2"].get("mean_R"), "final_x3_mean_R": x["final_x3"].get("mean_R"),
                           "pooled_t": x["pooled"].get("t_day"), "pooled_trades": x["pooled"].get("trades"),
                           "utilized_avg_pct": x["utilized_avg_pct"], "utilized_peak_pct": x["utilized_peak_pct"]}
        strategies.append({"id": sid, "name": s["name"], "family": s["family"], "primary": s["primary_level"],
                           "rules": RULES[sid], "sides": sides, "ladder": new["ladder"][sid],
                           "setup_ends_final": {k: v for k, v in s["setup_ends_final"].items()
                                                if k.endswith("|" + s["primary_level"])}})
    top = []
    for x in imp["top25"]:
        top.append({k: x[k] for k in ("rank", "id", "name", "source", "version", "rule", "evidence_date", "score",
                                      "factors", "contribution_1_minus_corr", "status", "reason", "variants", "overlaps")}
                   | {"rule_view": {k: x["rule_view"].get(k) for k in ("trades", "mean_R", "mean_net_bp", "win_pct",
                                                                       "profit_factor", "t_day")},
                      "book_view": slim(x["book_view"]), "book_R_2x": x["book_R_2x"]})
    data = {
        "generated": "2026-11-22",
        "prereg": {"sha256": hashlib.sha256(pre_raw).hexdigest(), "commit": "7e5b587", "branch": BRANCH,
                   "periods": pre["periods"], "folds": pre["folds"], "final_train": pre["final_train"],
                   "criteria": pre["criteria"], "trials": pre["trials"], "fixes": pre["development_fixes"],
                   "walk_forward_parameter": pre["walk_forward_parameter"], "t_bonferroni": new["t_bonferroni"],
                   "post_freeze_note": "After the freeze the code changed only for the live desk and for speed: the exit "
                                       "logic became one shared function (exit_check), bar indexes are computed with "
                                       "integer arithmetic, and the engine gained its OFF switch, restart restore and a "
                                       "per-side filter. Replaying the final period with the changed code reproduced all "
                                       "5,501 trades of all 72 configurations exactly (pinned files: commit 7e5b587)."},
        "common_rules": COMMON, "strategies": strategies,
        "imported": {"window": imp["window"], "sessions": imp["sessions"], "weights": imp["weights"],
                     "criteria": imp["criteria"], "candidates": imp["candidates"], "replayable": imp["replayable"],
                     "not_replayable": imp["not_replayable"], "dropped": imp["dropped_duplicates"], "top25": top,
                     "all": imp["all"]},
        "register": reg,
        "tests": {"checks": rep.get("checks", []), "live_day": rep.get("live_day_alone"),
                  "feed_route": rep.get("feed_route"), "writes": rep.get("writes_by_collection")},
    }
    data = r(data)
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("// GENERATED by backend/research/premium_intraday_2026_11/export_app_data.py from the frozen research "
                   "results. Do not edit by hand.\n/* eslint-disable */\nexport const RESEARCH: any = " + body + ";\n",
                   encoding="utf-8")
    print(OUT, f"{len(body) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
