"""The research register: sources, hypotheses, and what became of each. Writes register.json and
RESEARCH_REGISTER.md (the page reads register.json through export_app_data.py).

Evidence labels: "published" (peer-reviewed or a working paper), "regulator" (SEBI/NSE publication), "practitioner"
(books, firms, blogs; not independently tested), "our test" (this app's own replays). "International" marks evidence
from other markets that still needs validation on Indian equities. Links were checked on 22 Nov 2026; where only an
abstract or index page was read, `read` says so.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

SOURCES = [
    {"id": "S01", "title": "A Profitable Day Trading Strategy For The U.S. Equity Market (Stocks in Play, 5-minute ORB)",
     "authors": "C. Zarattini, A. Barbon, A. Aziz (Swiss Finance Institute RP 24-98)", "date": "2024",
     "link": "https://ideas.repec.org/p/chf/rpseri/rp2498.html", "type": "published (working paper)", "market": "US equities",
     "sample": "2016-2023", "costs": "commissions included per summaries; slippage not confirmed", "region": "International",
     "read": "abstract and secondary write-ups", "finding": "The opening-range breakout pays mainly on 'stocks in play' (high "
     "relative volume, often news); the 5-minute range did best."},
    {"id": "S02", "title": "Can Day Trading Really Be Profitable? Evidence of Sustainable Long-term Profits from ORB",
     "authors": "C. Zarattini, A. Aziz", "date": "2023", "link": "https://papers.ssrn.com/abstract=4416622",
     "type": "published (working paper)", "market": "QQQ (US)", "sample": "2016 - Feb 2023",
     "costs": "commission $0.0005/share, no slippage", "region": "International", "read": "abstract and secondary write-ups",
     "finding": "676% on QQQ, 24% winners, 0.13R a trade; an independent rebuild with costs found ~0.002R (near zero)."},
    {"id": "S03", "title": "Volume Weighted Average Price (VWAP): The Holy Grail for Day Trading Systems",
     "authors": "C. Zarattini, A. Aziz", "date": "13 Nov 2023", "link": "https://ssrn.com/abstract=4631351",
     "type": "published (working paper)", "market": "QQQ, TQQQ (US)", "sample": "Jan 2018 - Sep 2023",
     "costs": "unclear; public replications came in far lower", "region": "International", "read": "secondary sources only",
     "finding": "Long above VWAP, short below; reported Sharpe ~2.1 is disputed by replications."},
    {"id": "S04", "title": "Market intraday momentum", "authors": "L. Gao, Y. Han, S. Li, G. Zhou",
     "date": "2018 (J. Financial Economics 129(2))", "link": "https://www3.nd.edu/~zda/intramom.pdf", "type": "published",
     "market": "S&P 500 ETF (US)", "sample": "1993-2013", "costs": "gross", "region": "International", "read": "paper/summary",
     "finding": "First half-hour return predicts the last half-hour; stronger on high-volatility, high-volume days."},
    {"id": "S05", "title": "Hedging demand and market intraday momentum", "authors": "G. Baltussen, Z. Da, S. Lammers, M. Martens",
     "date": "2021 (J. Financial Economics 142(1))", "link": "https://pure.eur.nl/en/publications/hedging-demand-and-market-intraday-momentum/",
     "type": "published", "market": "60+ futures (equity, bond, commodity, FX)", "sample": "1974-2020", "costs": "gross",
     "region": "International", "read": "abstract", "finding": "Option market makers' gamma hedging drives late-day momentum."},
    {"id": "S06", "title": "Intraday patterns in the cross-section of stock returns", "authors": "S. Heston, R. Korajczyk, R. Sadka",
     "date": "2010 (J. Finance 65(4))", "link": "https://arxiv.org/pdf/1005.3535.pdf", "type": "published", "market": "NYSE stocks",
     "sample": "2001-2005 (TAQ)", "costs": "not a cost-inclusive strategy test", "region": "International", "read": "abstract",
     "finding": "Returns continue at the same half-hour on later days (institutional flows); short-term reversal from liquidity."},
    {"id": "S07", "title": "Stock returns after major price shocks: the impact of information", "authors": "P. Savor",
     "date": "2012 (J. Financial Economics 106(3))", "link": "https://ideas.repec.org/a/eee/jfinec/v106y2012i3p635-659.html",
     "type": "published", "market": "US stocks", "sample": "analyst-report events", "costs": "not a trading test",
     "region": "International", "read": "abstract", "finding": "Price shocks WITH information drift; shocks without information reverse."},
    {"id": "S08", "title": "Stock price reaction to news and no-news: drift and reversal after headlines", "authors": "W. Chan",
     "date": "2003 (J. Financial Economics 70(2))", "link": "https://econpapers.repec.org/RePEc:eee:jfinec:v:70:y:2003:i:2:p:223-260",
     "type": "published", "market": "US stocks (monthly)", "sample": "headline data", "costs": "risk-adjusted, gross",
     "region": "International", "read": "abstract", "finding": "Drift after bad news; reversal after large moves without news; "
     "mainly in smaller, less liquid stocks."},
    {"id": "S09", "title": "Industry information diffusion and the lead-lag effect in stock returns", "authors": "K. Hou",
     "date": "2007 (Review of Financial Studies 20(4))", "link": "https://ideas.repec.org/a/oup/rfinst/v20y2007i4p1113-1138.html",
     "type": "published", "market": "US stocks (daily/weekly)", "sample": "long history", "costs": "gross",
     "region": "International", "read": "abstract", "finding": "Big firms lead small firms within industries; slow diffusion of "
     "industry news, strongest after bad news."},
    {"id": "S10", "title": "A tug of war: overnight versus intraday expected returns", "authors": "D. Lou, C. Polk, S. Skouras",
     "date": "2019 (J. Financial Economics 134(1))", "link": "https://eprints.lse.ac.uk/87481/", "type": "published",
     "market": "US stocks", "sample": "multi-decade", "costs": "gross", "region": "International", "read": "abstract",
     "finding": "Momentum profits are earned overnight; intraday components often have the opposite sign."},
    {"id": "S11", "title": "Intraday price reversals in the US stock index futures market: a 15-year study",
     "authors": "J. Grant, A. Wolf, S. Yu", "date": "2005 (J. Banking & Finance 29(5))",
     "link": "https://ideas.repec.org/a/eee/jbfina/v29y2005i5p1311-1327.html", "type": "published",
     "market": "S&P 500 futures", "sample": "Nov 1987 - Sep 2002", "costs": "bid-ask estimate: significance drops sharply",
     "region": "International", "read": "abstract", "finding": "Large opening moves reverse intraday, but not clearly after costs."},
    {"id": "S12", "title": "Impact of the introduction of call auction on price discovery: evidence from India",
     "authors": "S. Agarwalla, J. Jacob, A. Pandey (IIM Ahmedabad)", "date": "2015 (Int. Review of Financial Analysis 39)",
     "link": "https://econpapers.repec.org/RePEc:eee:finana:v:39:y:2015:i:c:p:167-178", "type": "published", "market": "NSE (top 50)",
     "sample": "around the 2010 pre-open call auction", "costs": "not a trading study", "region": "India",
     "read": "abstract (via the earlier independent study)", "finding": "Negative intraday return correlations after the call "
     "auction: the opening price overshoots."},
    {"id": "S13", "title": "Predictable patterns following large price changes and volume: evidence from the Indian stock market",
     "authors": "S. Parthasarathy", "date": "2019 (Review of Behavioral Finance 11(4))",
     "link": "https://ideas.repec.org/a/eme/rbfpps/rbf-06-2018-0058.html", "type": "published", "market": "Indian stocks (daily)",
     "sample": "not stated in abstract", "costs": "not stated", "region": "India", "read": "abstract",
     "finding": "Large one-day moves on LOW volume reverse over 20 days; on HIGH volume they continue."},
    {"id": "S14", "title": "Analysis of intraday trading by individuals in the equity cash segment", "authors": "SEBI",
     "date": "24 Jul 2024", "link": "https://www.sebi.gov.in/media-and-notifications/press-releases/jul-2024/sebi-study-finds-that-7-out-of-10-individual-intraday-traders-in-equity-cash-segment-make-losses_84948.html",
     "type": "regulator", "market": "NSE/BSE cash intraday, individuals at the top 10 brokers", "sample": "FY19, FY22, FY23",
     "costs": "included", "region": "India", "read": "press release",
     "finding": "71% of individual intraday traders lost money in FY23 (80% of very frequent traders); costs were 57% of "
     "loss-makers' trading losses."},
    {"id": "S15", "title": "Bulk deals on NSE: front-running and price leakage", "authors": "IIM Calcutta (WP 863); Managerial Finance (2022)",
     "date": "2010-2019 samples", "link": "https://studentlive.iimcal.ac.in/sites/all/files/pdfs/wp_863.pdf", "type": "published (working paper)",
     "market": "NSE bulk deals", "sample": "2010-2019", "costs": "not a trading test", "region": "India", "read": "abstract",
     "finding": "Abnormal returns before the event (leakage); temporary price impact exceeds permanent (reversal)."},
    {"id": "S16", "title": "An analysis of corporate insider trading and earnings announcements in India", "authors": "NSE-IGIDR WP",
     "date": "2014-15", "link": "https://nsearchives.nseindia.com/research/content/NSE-IGIDR-WP4-14-15.pdf", "type": "published (working paper)",
     "market": "Indian listed firms", "sample": "not read in full", "costs": "not a trading test", "region": "India",
     "read": "search summary", "finding": "Prices anticipate the sign of earnings surprises and then underreact to them."},
    {"id": "S17", "title": "Day Trading with Short Term Price Patterns and Opening Range Breakout (NR7, ORB)", "authors": "T. Crabel",
     "date": "1990 (Traders Press)", "link": "https://store.traders.com/-v07-c04-orb-pdf.html", "type": "practitioner",
     "market": "US futures", "sample": "1980s", "costs": "not stated", "region": "International", "read": "secondary descriptions",
     "finding": "Narrow-range days (NR4/NR7) precede range expansion; break of the opening range by a 'stretch'."},
    {"id": "S18", "title": "News as sources of jumps in stock returns (21 million articles, 9,000 firms)", "authors": "Y. Jeon, T. McCurdy, X. Zhao",
     "date": "2022 (J. Financial Economics 145(2))", "link": "https://ideas.repec.org/a/eee/jfinec/v145y2022i2p1-17.html",
     "type": "published", "market": "US stocks", "sample": "decades", "costs": "not a trading test", "region": "International",
     "read": "abstract", "finding": "Jumps cluster on news days; their size and frequency follow news flow."},
    {"id": "S19", "title": "NSE-IND-001..010 independent intraday study (opening-auction reversal, ADR transmission, sector "
     "residual reversal, same-slot periodicity, market intraday momentum)", "authors": "this project (D:/NSE-Intraday-Research)",
     "date": "5-6 Nov 2026", "link": "https://claude.ai/artifact/XnU2PkhUaoz3Y5tN4fSbCi", "type": "our test",
     "market": "NSE cash", "sample": "2013-2026 (hold-out 2023-Nov 2026)", "costs": "included", "region": "India", "read": "full",
     "finding": "0/10 qualified. Opening-auction reversal: 96% of the edge is auction prints never revisited. ADR transmission: "
     "+10.1 bp net from the first continuous trade, -12.4 bp from 10:15."},
    {"id": "S20", "title": "Intraday Stocks: audit of the 54 tournament strategies", "authors": "this project",
     "date": "4 Nov 2026", "link": "INTRADAY_STOCKS_54_STRATEGY_AUDIT.md", "type": "our test", "market": "NSE top 200",
     "sample": "4 Nov 2024 - 3 Nov 2026", "costs": "included (measured slippage)", "region": "India", "read": "full",
     "finding": "No look-ahead; every replayable rule loses after ~10.5 bp a round trip (+0.8 bp before costs)."},
    {"id": "S21", "title": "Stock selection research S0-S7 (where vs which way)", "authors": "this project", "date": "2 Oct 2026",
     "link": "INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md", "type": "our test", "market": "NSE top 200",
     "sample": "Sep 2024 - Oct 2026", "costs": "10 bp hurdle", "region": "India", "read": "full",
     "finding": "WHERE a stock moves is predictable (relative volume, ATR, gap, results day); WHICH WAY is not; overnight "
     "+13 bp/day vs intraday -7.5 bp."},
    {"id": "S22", "title": "NIFTY 50 first-15-minute momentum study", "authors": "this project", "date": "25 Oct 2026",
     "link": "research-reports/nifty50-strategies-2026-10/REPORT.md", "type": "our test", "market": "NIFTY 50 constituents",
     "sample": "Oct 2021 - Oct 2026", "costs": "included", "region": "India", "read": "full",
     "finding": "8 of 9 lost; continuation after 09:30 ~0 bp for risers vs ~15 bp costs; trend days pay, range days lose."},
]

H = [
    {"id": "N01", "family": "Sector-confirmed opening-range breakout", "status": "implemented",
     "mechanism": "Sector-wide information (news, flows, index rebalancing) diffuses through a sector over hours (S09); a "
     "stock that leads a BROADLY strong sector and breaks its opening range is more likely to be carrying that information "
     "than an isolated breakout (S07, S08).",
     "fails_when": "the sector's headline move comes from one heavyweight while most members fall (narrow); the market "
     "rotates after the open; range days.",
     "invalidation": "out of sample, the sector-confirmed rule earns no more per trade than the same breakout without the "
     "sector condition, or loses after costs.",
     "evidence": ["S01", "S02", "S09", "S07", "S20", "S22"],
     "evidence_note": "International (S01, S02, S09: needs Indian validation); our tests: plain ORB loses on NSE (S20, S22).",
     "vs_existing": "Tournament ORB-in-play: 30-minute range, top-20 relative volume, no sector condition, ATR stop. Stock "
     "Momentum orb15: no sector condition, stop at the signal candle (tight), Rs 10k positions. N01 adds the sector "
     "confirmation, the 09:40 persistence check, a structural stop (range midpoint, 0.35-1.5%) and a walk-forward target.",
     "data": "ok"},
    {"id": "N02", "family": "Relative-strength leaders and laggards", "status": "implemented",
     "mechanism": "Stocks outperforming both their sector and NIFTY in the first half hour, and still doing so at 09:40, are "
     "absorbing persistent order flow (institutional orders worked through the day: S06); intraday continuation is "
     "stronger on high-volume days (S04).",
     "fails_when": "the leadership is a single block trade or an auction artefact; mean reversion dominates in quiet markets.",
     "invalidation": "out of sample the 09:40-confirmed leaders earn <= 0 after costs, or no more than the 09:30 list alone.",
     "evidence": ["S06", "S04", "S10", "S21"], "evidence_note": "International; S10 and S21 warn intraday components are weak.",
     "vs_existing": "Stock Momentum 'relative': 09:30 out/underperformance then a break of the previous bar, candle stop. N02 "
     "requires persistence to 09:40, a break of the morning's extreme, a VWAP-based stop (0.4-1.5%), and an opposite-sector "
     "filter.", "data": "ok"},
    {"id": "N03", "family": "VWAP pullback on trend days", "status": "implemented",
     "mechanism": "On broad trend days institutions benchmark execution to VWAP, so pullbacks to VWAP in leaders meet "
     "VWAP-anchored demand (S03, practitioner); intraday momentum is stronger on high-volatility days (S04, S05).",
     "fails_when": "the morning trend reverses (no trend day); VWAP is crossed decisively.",
     "invalidation": "out of sample, pullback entries on classified trend days lose after costs, or the trend-day condition "
     "does not improve on all days.", "evidence": ["S03", "S04", "S05", "S22"],
     "evidence_note": "International (S03 disputed by replications); S22: trend days pay on NIFTY 50, range days lose.",
     "vs_existing": "Tournament VWAP Reclaim trades crosses of VWAP on any day; Stock Momentum 'vwap' trades breaks above "
     "VWAP. N03 trades only on a classified trend morning and enters on the PULLBACK to VWAP, not the break.", "data": "ok"},
    {"id": "N04", "family": "Failed-gap reversal (no news)", "status": "implemented",
     "mechanism": "Gaps without public information are liquidity or sentiment shocks that reverse (S07, S08, S11); the NSE "
     "opening auction overshoots (S12); low-volume large moves reverse in India (S13). Entry waits for continuous-trading "
     "confirmation because the naive fade's edge is mostly auction prints (S19).",
     "fails_when": "the gap is informed (news, results, sector-wide); high volume; trend days in the gap's direction.",
     "invalidation": "out of sample, confirmed failed gaps without news do not earn a positive net R, or the no-news filter "
     "does not improve them.", "evidence": ["S07", "S08", "S11", "S12", "S13", "S19"],
     "evidence_note": "S12, S13 are Indian; S19 (our test) found the plain fade ~0 net from the first continuous trade.",
     "vs_existing": "Tournament Gap Fade enters at 09:45 if price sits between the open and the previous close, low volume. "
     "Stock Momentum gap_fade breaks against the gap. N04 requires the gap to FAIL (a red opening range and a close back "
     "below the open, then a break of the range low), no material news, room to the previous close >= 1R.", "data": "ok"},
    {"id": "N05", "family": "Volatility compression then expansion", "status": "implemented",
     "mechanism": "Ranges mean-revert: unusually narrow days (NR7, inside days) and a narrow opening range tend to be "
     "followed by range expansion, and the break of the range shows its direction (S17).",
     "fails_when": "compression continues all day; the break is false (no follow-through).",
     "invalidation": "out of sample, compressed-range breaks lose after costs (the stops are small, so costs weigh more).",
     "evidence": ["S17"], "evidence_note": "Practitioner only (no independent test); our crypto session lab's NR4 finalist failed its hold-out.",
     "vs_existing": "Selected ORB picks the LARGEST expected movers; N05 picks the most COMPRESSED stocks. No existing rule "
     "conditions on NR7/inside days.", "data": "ok"},
    {"id": "N06", "family": "News-catalyst continuation", "status": "implemented",
     "mechanism": "Firm-specific information released outside market hours is absorbed gradually (S07, S16, S18); a gap in "
     "the news' direction that holds through the opening range on heavy volume continues.",
     "fails_when": "the news is fully priced at the open (overnight drift, S10); intraday reversal of overnight gains on NSE (S21).",
     "invalidation": "out of sample, catalyst gaps that hold do not continue after costs.", "evidence": ["S07", "S16", "S18", "S10", "S21"],
     "evidence_note": "S16 is Indian (underreaction, daily); S21 (ours) finds intraday returns negative on average.",
     "vs_existing": "Tournament Gap and Go and Stock Momentum gap_go use price and volume only; N06 requires a MATERIAL NSE "
     "announcement disseminated before 09:15 (exchange timestamp).",
     "data": "announcements Nov 2025 onward only: tested on that period, the rest prospectively"},
    {"id": "D01", "family": "ADR overnight transmission (INFY, WIPRO, HDFCBANK, ICICIBANK, DRREDDY)", "status": "deferred",
     "mechanism": "US ADR prices carry overnight information into the NSE open.", "fails_when": "the open has absorbed it.",
     "invalidation": "-", "evidence": ["S19"],
     "evidence_note": "Our test: hold-out Sharpe 2.42 from the official open, +10.1 bp net from the first continuous trade, "
     "-12.4 bp from 10:15.",
     "why": "the edge is gone by 10:15 and this desk enters only after the 09:45 plan on five-minute bars; it needs a 09:15 "
     "entry path and a fresh quote at the open.", "missing": "a 09:15 entry path; ADR closes and USD/INR before the open"},
    {"id": "D02", "family": "Pre-open auction imbalance", "status": "deferred",
     "mechanism": "Order imbalance at the NSE pre-open call auction predicts the first minutes' direction.",
     "fails_when": "-", "invalidation": "-", "evidence": ["S12"],
     "why": "the pre-open snapshot has been stored only since Oct 2026, too short to test; collect forward first.",
     "missing": "two years of pre-open order book (total buy/sell quantity per stock)"},
    {"id": "D03", "family": "Bulk/block deal follow-through", "status": "deferred",
     "mechanism": "Disclosed institutional deals move prices the next day.", "fails_when": "leakage before disclosure.",
     "invalidation": "-", "evidence": ["S15"], "why": "Indian evidence points to leakage BEFORE the event and temporary impact "
     "that reverses, so a next-day continuation rule has no support; the data exists (nse_events) for a later test.",
     "missing": "-"},
    {"id": "D04", "family": "Results-day expected move (size, not direction)", "status": "deferred",
     "mechanism": "Results days have larger moves (our S21: +80 bp expected move), useful for selection, not direction.",
     "fails_when": "-", "invalidation": "-", "evidence": ["S21"], "why": "a selection input, already used by Selected ORB; "
     "not a separate directional strategy.", "missing": "-"},
    {"id": "R01", "family": "Market intraday momentum (first half hour -> last half hour)", "status": "rejected",
     "mechanism": "S04, S05.", "fails_when": "-", "invalidation": "-", "evidence": ["S04", "S05", "S19"],
     "why": "the effect lives in the last half hour (15:00-15:30) and this desk must be flat by 15:10; our NSE-IND-008 test "
     "of it was negative (-7.9 bp net)."},
    {"id": "R02", "family": "Same half-hour periodicity", "status": "rejected", "mechanism": "S06.", "fails_when": "-",
     "invalidation": "-", "evidence": ["S06", "S19"], "why": "our NSE-IND-010 test: -11.2 bp net per trade (2.3 bp gross)."},
    {"id": "R03", "family": "Sector residual reversal", "status": "rejected", "mechanism": "stocks that diverge from their "
     "sector converge.", "fails_when": "-", "invalidation": "-", "evidence": ["S19"],
     "why": "our NSE-IND-009 test: -19.0 bp net; N04 keeps only the narrower no-news failed-gap case."},
    {"id": "R04", "family": "Opening-auction reversal (fade the open)", "status": "rejected", "mechanism": "S12.",
     "fails_when": "-", "invalidation": "-", "evidence": ["S12", "S19"],
     "why": "96% of the gross edge came from auction prints never revisited that day (not tradable); ~0 net from the first "
     "continuous trade."},
    {"id": "R05", "family": "Circuit-limit magnet", "status": "rejected", "mechanism": "prices accelerate toward price bands.",
     "fails_when": "-", "invalidation": "-", "evidence": [], "why": "a locked stock cannot be exited (failed exits by design); "
     "most of the universe is F&O with no fixed bands."},
    {"id": "R06", "family": "52-week-high breakout intraday", "status": "rejected", "mechanism": "anchoring.", "fails_when": "-",
     "invalidation": "-", "evidence": ["S19"], "why": "our NSE-IND-005 test: -19.2 bp net in the hold-out."},
    {"id": "R07", "family": "Expiry-cycle effects in the cash market", "status": "rejected", "mechanism": "hedging flows.",
     "fails_when": "-", "invalidation": "-", "evidence": ["S19"], "why": "our NSE-IND-007 test failed validation."},
]


def main():
    doc = {"built": "2026-11-22", "sources": SOURCES, "hypotheses": H,
           "labels": {"published": "peer-reviewed paper or working paper", "regulator": "SEBI / NSE publication",
                      "practitioner": "book, firm or blog; not independently tested", "our test": "this app's own replay"}}
    (HERE / "register.json").write_text(json.dumps(doc, indent=1))
    lines = ["# Premium Intraday Strategies: research register", "",
             "*22 Nov 2026. Sources with links, dates, markets, samples and cost treatment; every hypothesis with its "
             "mechanism, when it should fail, what would invalidate it, how it differs from the existing catalogs, and "
             "whether it was implemented, deferred or rejected. 'International' evidence still needs validation on Indian "
             "equities.*", "", "## Hypotheses", "",
             "| ID | Family | Status | Evidence | Why / difference from existing |", "|---|---|---|---|---|"]
    for h in H:
        why = h.get("why") or h.get("vs_existing", "")
        lines.append(f"| {h['id']} | {h['family']} | {h['status']} | {', '.join(h['evidence'])} | {why} |")
    lines += ["", "## Implemented hypotheses in full", ""]
    for h in H:
        if h["status"] != "implemented":
            continue
        lines += [f"### {h['id']} {h['family']}", f"- **Mechanism.** {h['mechanism']}", f"- **Should fail when.** {h['fails_when']}",
                  f"- **Invalidated if.** {h['invalidation']}", f"- **Evidence.** {h['evidence_note']}",
                  f"- **Different from the existing catalogs.** {h['vs_existing']}", f"- **Data.** {h['data']}", ""]
    lines += ["## Sources", "", "| ID | Title | Authors | Date | Market / sample | Costs | Type | Region | Read |",
              "|---|---|---|---|---|---|---|---|---|"]
    for s in SOURCES:
        lines.append(f"| {s['id']} | [{s['title']}]({s['link']}) | {s['authors']} | {s['date']} | {s['market']}; "
                     f"{s['sample']} | {s['costs']} | {s['type']} | {s['region']} | {s['read']} |")
    (HERE / "RESEARCH_REGISTER.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("register:", len(SOURCES), "sources,", len(H), "hypotheses")


if __name__ == "__main__":
    main()
