"""Angel One intraday equity rate card vs what the desk charged. No database needed.

The whole verdict would collapse if charges were overstated, so they are recomputed from
the published card on the desk's median position (Rs 10 lakh) and set against the mean of
the 1,596 live positions' stored fee_breakdown (measured 2026-10-10).
"""
P = 1_000_000.0
buy = sell = P
card = {
    "brokerage": min(20, buy * 0.0025) + min(20, sell * 0.0025),   # Rs 20 or 0.25%, lower
    "stt": sell * 0.00025,                                         # 0.025% sell side
    "exchange_txn": (buy + sell) * 0.0000297,                      # NSE 0.00297%
    "stamp_duty": buy * 0.00003,                                   # 0.003% buy side
    "sebi": (buy + sell) * 0.000001,                               # Rs 10 / crore
    "ipft": (buy + sell) * 0.000001,                               # Rs 10 / crore
}
card["gst"] = 0.18 * (card["brokerage"] + card["exchange_txn"] + card["sebi"] + card["ipft"])
measured = {"brokerage": 63840 / 1596, "stt": 398344 / 1596, "exchange_txn": 94639 / 1596,
            "stamp_duty": 47794 / 1596, "sebi": 3186 / 1596, "ipft": 3186 / 1596,
            "gst": 29673 / 1596}
print(f"{'component':<14}{'card':>10}{'measured':>11}")
for k, v in card.items():
    print(f"{k:<14}{v:>10.2f}{measured[k]:>11.2f}")
tot = sum(card.values())
print(f"{'TOTAL':<14}{tot:>10.2f}{sum(measured.values()):>11.2f}   = {tot / P * 1e4:.2f} bp a round trip")
