"use client";

// Delta Exchange Live Trading (14 Nov 2026; both desks from 16 Nov): REAL money on Delta Exchange India for the
// Premium strategies the owner picked - the bitcoin desk (TH-05, TL-04, TH-01, TD-02, and from 18 Nov eleven more, 15
// on BTCUSD) and the gold desk (RU-02, CP-23, YT-14, DR-01, CP-05, CP-06, TL-04's gold book from 16 Nov, and from
// 18 Nov seventeen more Premium gold books and six Gold Desk H1 templates, 30 on XAUTUSD). Each desk card shows how
// many of its strategies are in a paper trade; the desk view shows each one's own paper trades (18 Nov). Each desk is
// premium_live's: it copies the paper desk's trades of its picks (their signals come from Delta's live candles) into
// real Delta orders, each with its stop and target held on Delta, at one contract a trade (or $1 to $5 of risk picked
// on the page) and a $20 daily loss stop. Each desk has its own ON/OFF switch (one confirmation; no PIN since 15 Nov,
// the owner's choice). The page shows both desks at a glance and one desk in full; the gold desk is also on Premium
// Strategies. Every request that changes a desk is LiveDelta's (unchanged); the overview only reads. From 21 Nov each
// desk card also shows its real-money trading days, total return, avg % a trading day, win rate, PF and drawdown.
// 22 Nov: the owner's third list - the bitcoin desk 24 (seven more bitcoin books and DD-04's and BX-02's ether books on
// ETHUSD, its second product), the gold desk 99 (ten Premium gold books, a seventh H1 template, 38 more Factory ones).
// 24 Nov: the owner's fourth list - the bitcoin desk 32 (NJ-43, TD-03, NJ-28, SC-02, NJ-37 and DD-04's bitcoin book;
// the ether books of DD-03 and BX-01), the gold desk 102 (JR-05, BG-05, JR-01).
import { useCallback, useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import { apiFetch } from "../../lib/api";
import LiveDelta, { MODE, ago, usd, tone, spct, type LiveStatus } from "../premium-strategies/LiveDelta";

type DeskKey = "crypto" | "gold";
const DESKS: { key: DeskKey; label: string; product: string; path: string; intro: string }[] = [
  { key: "crypto", label: "Bitcoin desk", product: "BTCUSD · ETHUSD", path: "/api/premium-paper/live/desk/crypto",
    intro: "TH-05, TL-04 and TH-01 were picked on 14 Nov, TD-02 on 15 Nov, eleven more on 18 Nov from the Premium leaderboard (TH-06, DT-02, RU-06, NJ-47, RU-03, TH-04, DT-01, TH-07, NJ-27, PT-04, SB-04), and nine on 22 Nov from its Crypto tab: seven on bitcoin (DT-05, TL-03, RU-04, KA-01, DD-01, TD-04, TC-04) and the ether books of DD-04 and BX-02, which trade Delta's ETHUSD, and eight on 24 Nov from the same tab: six on bitcoin (NJ-43, TD-03, NJ-28, SC-02, NJ-37 and DD-04's bitcoin book) and the ether books of DD-03 and BX-01; each after 0 to 27 paper trades. Every signal of the 32 is copied to Delta at one contract, however late it is seen and however far the price has moved." },
  { key: "gold", label: "Gold desk", product: "XAUTUSD", path: "/api/premium-paper/live",
    intro: "RU-02, CP-23, YT-14, DR-01 and CP-05 were picked on 13 Nov, CP-06 on 15 Nov, TL-04's gold book on 16 Nov, and on 18 Nov seventeen more gold books from the Premium leaderboard and six templates of the Gold Desk's H1 test (EMA Ribbon, Round Number, Donchian fast and slow, Pivot R1/S1, Keltner), each after 0 to 20 paper trades, and on 19 Nov the Gold Desk Strategy Factory board's top 20 (SF0181, SF0020, SF0245 and on). On 22 Nov ten more gold books from the Premium Gold tab (CP-21, YT-18, TF-01, CP-01, FL-02, MH-01, DT-02, BG-08, RU-06, JR-03), the H1 test's Prior Session High/Low Break and 38 more of the Factory board's top 56 joined, and on 24 Nov three more Premium gold books (JR-05, BG-05, JR-01). Every gold signal comes from Delta's own XAUTUSD data. Every open paper trade of the 102 is copied to Delta at one contract, however late it is seen and however far the price has moved." },
];
const POLL_MS = 15000;

function useDesks() {
  const [st, setSt] = useState<Record<DeskKey, LiveStatus | null>>({ crypto: null, gold: null });
  const [err, setErr] = useState<Record<DeskKey, string | null>>({ crypto: null, gold: null });
  const [now, setNow] = useState(() => Date.now() / 1000);
  const load = useCallback(async () => {
    await Promise.all(DESKS.map(async (d) => {
      try {
        const s = (await apiFetch(d.path)) as LiveStatus;
        setSt((x) => ({ ...x, [d.key]: s }));
        setErr((x) => ({ ...x, [d.key]: null }));
      } catch (e) {
        setErr((x) => ({ ...x, [d.key]: e instanceof Error ? e.message : "could not be read" }));
      }
    }));
    setNow(Date.now() / 1000);
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);
  return { st, err, now };
}

export default function DeltaLiveTradingPage() {
  const { st, err, now } = useDesks();
  const [desk, setDesk] = useState<DeskKey>("crypto");
  useEffect(() => {                                   // ?desk=gold opens the gold desk (a link can name one)
    try {
      const q = new URLSearchParams(window.location.search).get("desk");
      if (q === "gold" || q === "crypto") setDesk(q);
    } catch { /* no URL */ }
  }, []);
  const choose = (k: DeskKey) => {
    setDesk(k);
    try {
      const u = new URL(window.location.href);
      if (k === "crypto") u.searchParams.delete("desk"); else u.searchParams.set("desk", k);
      window.history.replaceState(null, "", u.toString());
    } catch { /* no URL */ }
  };

  const both = DESKS.map((d) => st[d.key]).filter((x): x is LiveStatus => !!x);
  const wallet = both.filter((s) => s.wallet).sort((a, b) => (b.wallet_at ?? 0) - (a.wallet_at ?? 0))[0];
  const today = both.reduce((a, s) => a + s.today.live, 0);
  const allPnl = both.reduce((a, s) => a + s.totals.live.pnl_usd, 0);
  const closed = both.reduce((a, s) => a + s.totals.live.trades, 0);
  const wins = both.reduce((a, s) => a + s.totals.live.wins, 0);
  const open = both.reduce((a, s) => a + s.open.length, 0);
  const openPnl = both.reduce((a, s) => a + s.open.reduce((b, t) => b + (t.unrealised_usd ?? 0), 0), 0);
  const cur = DESKS.find((d) => d.key === desk)!;

  return (
    <div className="dlx">
      <PageHeader
        crumb="Delta Exchange Live Trading"
        title="Delta Exchange Live Trading"
        subtitle="Real money on Delta Exchange India for the bitcoin, ether and gold strategies you picked, traded on Delta's live BTCUSD, ETHUSD and XAUTUSD data."
      />

      <section className="dlx-account" aria-label="Delta account">
        <div className="dlx-stat">
          <span className="dlx-k">Delta wallet</span>
          <span className="dlx-v">{wallet?.wallet ? usd(wallet.wallet.balance) : "—"}</span>
          <span className="dlx-s">{wallet?.wallet ? `${usd(wallet.wallet.available)} free · ${usd(wallet.wallet.blocked)} in use · read ${ago(wallet.wallet_at, now)}` : "read when a desk is live"}</span>
        </div>
        <div className="dlx-stat">
          <span className="dlx-k">Today, both desks (IST)</span>
          <span className={`dlx-v ${tone(today)}`}>{both.length ? usd(today, true) : "—"}</span>
          <span className="dlx-s">real money, closed and open trades of the day</span>
        </div>
        <div className="dlx-stat">
          <span className="dlx-k">All real trades</span>
          <span className={`dlx-v ${tone(allPnl)}`}>{both.length ? usd(allPnl, true) : "—"}</span>
          <span className="dlx-s">{`${closed} closed · ${closed ? Math.round((100 * wins) / closed) : 0}% won`}</span>
        </div>
        <div className="dlx-stat">
          <span className="dlx-k">Open now</span>
          <span className={`dlx-v ${open ? tone(openPnl) : ""}`}>{open ? usd(openPnl, true) : "0"}</span>
          <span className="dlx-s">{`${open} position${open === 1 ? "" : "s"} across both desks`}</span>
        </div>
      </section>

      <div className="dlx-desks" role="tablist" aria-label="Desks">
        {DESKS.map((d) => {
          const s = st[d.key];
          const m = s ? MODE[s.mode] ?? MODE.off : null;
          const on = desk === d.key;
          return (
            <button key={d.key} type="button" role="tab" aria-selected={on} aria-controls="dlx-panel" id={`dlx-tab-${d.key}`}
              className={`dlx-desk${on ? " on" : ""}`} onClick={() => choose(d.key)}>
              <span className="dlx-desk-top">
                <span className="dlx-desk-name">{d.label} <span className="dlx-prod">{d.product}</span></span>
                {m ? <span className={`dlx-pill ${m.cls}`}>{s!.mode === "live" ? "LIVE" : s!.mode === "shadow" ? "SHADOW" : "OFF"}</span>
                  : <span className="dlx-pill off">{err[d.key] ? "unreadable" : "…"}</span>}
              </span>
              {s ? (
                <>
                  <span className="dlx-picks" title={s.picks.map((p) => p.acct).join(" · ")}>
                    {`${s.picks.length} strategies`}
                    {s.picks.some((p) => p.paper) ? <span className="dlx-on">{` · ${s.picks.filter((p) => p.paper && p.paper.open.length).length} in a paper trade`}</span> : null}
                  </span>
                  <span className="dlx-desk-nums">
                    <span>Today <b className={tone(s.today.live)}>{usd(s.today.live, true)}</b></span>
                    <span>All <b className={tone(s.totals.live.pnl_usd)}>{usd(s.totals.live.pnl_usd, true)}</b></span>
                    <span>{s.totals.live.trades} closed</span>
                    <span>{s.open.length} open</span>
                  </span>
                  {s.results && s.results.trades > 0 ? (
                    <span className="dlx-desk-stats" title={`Real money, closed trades. Return = net P&L ÷ the most margin the desk held at one time (${usd(s.results.peak_margin_usd)}).`}>
                      <span className="dlx-st"><span className="dlx-st-k">Trading days</span><b>{s.results.days}</b></span>
                      <span className="dlx-st"><span className="dlx-st-k">Total return</span><b className={tone(s.results.return_pct)}>{spct(s.results.return_pct)}</b></span>
                      <span className="dlx-st"><span className="dlx-st-k">Avg % / trading day</span><b className={tone(s.results.avg_day_pct)}>{spct(s.results.avg_day_pct)}</b></span>
                      <span className="dlx-st"><span className="dlx-st-k">Win rate</span><b>{s.results.win_pct === null ? "—" : `${s.results.win_pct.toFixed(1)}%`}</b></span>
                      <span className="dlx-st"><span className="dlx-st-k">Profit factor</span><b>{s.results.pf === null ? "—" : s.results.pf.toFixed(2)}</b></span>
                      <span className="dlx-st"><span className="dlx-st-k">Max drawdown</span><b className={tone(s.results.max_dd_usd)}>{usd(s.results.max_dd_usd, true)}</b></span>
                    </span>
                  ) : null}
                  <span className="dlx-desk-foot">
                    {s.switched_off ? <span className="loss">Switched off: {s.switched_off}</span>
                      : `checked ${ago(s.last_cycle_at, now)}${s.errors_in_row ? ` · ${s.errors_in_row} venue error${s.errors_in_row === 1 ? "" : "s"} in a row` : ""}`}
                  </span>
                </>
              ) : (
                <span className="dlx-desk-foot">{err[d.key] ? `could not be read: ${err[d.key]}` : "loading…"}</span>
              )}
            </button>
          );
        })}
      </div>

      <div id="dlx-panel" role="tabpanel" aria-labelledby={`dlx-tab-${desk}`}>
        <LiveDelta key={desk} desk={desk} intro={<>{cur.intro}</>} />
      </div>

      <details className="dlx-how">
        <summary>How these desks trade</summary>
        <p>
          Each strategy runs on the Premium paper desk on Delta&apos;s live one-minute candles (BTCUSD for bitcoin,
          ETHUSD for ether, XAUTUSD for gold). When one of them enters, its desk sends the same trade to your Delta account as a real
          order: a market entry of 1 contract, the smallest order Delta allows (or sized to a risk of $1 to $5 if you
          pick one), with that strategy&apos;s own stop and target placed on Delta. When the strategy exits, the real
          trade is closed. A desk never adds trades of its own, and every strategy can be in a trade at the same time:
          each is its own order with its own stop and target, and Delta shows their sum as one position per product.
        </p>
        <p>
          Each desk has its own <b>Live trading</b> switch; since 19 Nov neither has a daily loss stop (every signal is
          taken at one contract). <b>ON</b> starts real orders
          after one confirmation; <b>OFF</b> stops new trades at once, and a position already open still closes at its
          stop, its target or its strategy&apos;s exit. <b>Test without orders</b> logs every decision without sending
          anything. The two desks share one Delta account and its keys.
        </p>
        <p>
          Each desk lists its strategies&apos; own <b>paper</b> trades beside the <b>real</b> ones: whether each is in a
          paper trade now (and its R so far), its paper record since it started, and, for each of the latest paper
          trades, what the desk did with it: copied (with the real result), skipped and why, or not copied because the
          desk was off or the trade came before the desk was switched on. Every signal is read from Delta&apos;s own
          live one-minute candles; the Gold Desk H1 templates come from the Gold Desk, which trades Delta&apos;s
          XAUTUSD too.
        </p>
      </details>

      <style jsx>{`
        .dlx { padding: 0 0 40px; display: flex; flex-direction: column; gap: 16px; }
        .dlx-account { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
        .dlx-stat { display: flex; flex-direction: column; gap: 4px; padding: 14px 16px; border-radius: 14px; background: var(--panel);
          border: 1px solid var(--panel-border); min-width: 0; }
        .dlx-k { font-size: 10.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .dlx-v { font-family: var(--font-data); font-size: 24px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
        .dlx-v.gain, .dlx-desk-nums b.gain { color: var(--gain); }
        .dlx-v.loss, .dlx-desk-nums b.loss, .dlx-desk-foot .loss { color: var(--loss); }
        .dlx-s { font-size: 12px; color: var(--text-muted); }
        .dlx-desks { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
        .dlx-desk { display: flex; flex-direction: column; gap: 8px; text-align: left; padding: 14px 16px; border-radius: 14px;
          background: var(--panel); border: 1px solid var(--panel-border); color: var(--text); cursor: pointer; font: inherit;
          transition: border-color 0.15s, box-shadow 0.15s; }
        .dlx-desk:hover { border-color: var(--panel-border-hover); }
        .dlx-desk.on { border-color: var(--brand); box-shadow: 0 0 0 1px var(--brand) inset; background: var(--panel-tint, var(--panel)); }
        .dlx-desk:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
        .dlx-desk-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
        .dlx-desk-name { font-size: 15px; font-weight: 800; }
        .dlx-prod { font-size: 11px; font-weight: 700; padding: 1px 7px; border-radius: 999px; margin-left: 4px;
          background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .dlx-pill { font-size: 11.5px; font-weight: 800; padding: 3px 10px; border-radius: 999px; letter-spacing: 0.03em; }
        .dlx-pill.live { background: var(--loss); color: #fff; }
        .dlx-pill.shadow { background: var(--brand-dim); color: var(--brand); }
        .dlx-pill.off { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .dlx-picks { font-size: 13px; font-weight: 700; color: var(--text-secondary); }
        .dlx-on { color: var(--brand); }
        .dlx-desk-nums { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12.5px; color: var(--text-muted); }
        .dlx-desk-nums b { font-family: var(--font-data); color: var(--text); }
        .dlx-desk-foot { font-size: 11.5px; color: var(--text-faint); }
        .dlx-desk-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 12px; padding: 10px 0 2px;
          border-top: 1px solid var(--panel-border); }
        .dlx-st { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
        .dlx-st-k { font-size: 10px; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-faint); }
        .dlx-st b { font-family: var(--font-data); font-size: 15px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
        .dlx-st b.gain { color: var(--gain); }
        .dlx-st b.loss { color: var(--loss); }
        .dlx-how { padding: 12px 16px; border-radius: 14px; background: var(--panel); border: 1px solid var(--panel-border); }
        .dlx-how summary { cursor: pointer; font-size: 13px; font-weight: 800; color: var(--text); }
        .dlx-how p { margin: 10px 0 0; font-size: 13px; line-height: 1.6; color: var(--text-secondary); }
        @media (max-width: 640px) {
          .dlx-v { font-size: 20px; }
          .dlx-account { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .dlx-stat { padding: 12px; }
        }
      `}</style>
    </div>
  );
}
