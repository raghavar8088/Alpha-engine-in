"use client";

import { useEffect, useState } from "react";
import { fetchFunds, fetchHoldings, fetchPortfolioAnalytics, fetchPositions, PortfolioAnalytics } from "@/lib/api";
import GlassPanel from "@/components/GlassPanel";
import StatCard from "@/components/StatCard";
import PageHeader from "@/components/PageHeader";

interface Holding {
  tradingSymbol: string;
  exchange: string;
  totalQty: number;
  avgCostPrice: number;
  lastTradedPrice: number;
}

interface Position {
  tradingSymbol: string;
  exchangeSegment: string;
  productType: string;
  positionType: string;
  netQty: number;
  buyAvg: number;
  unrealizedProfit: number;
  realizedProfit: number;
}

interface Funds {
  availabelBalance: number;
  withdrawableBalance: number;
  utilizedAmount: number;
  collateralAmount: number;
}

const inr = (n: number) =>
  n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function PortfolioPage() {
  const [holdings, setHoldings] = useState<Holding[] | null>(null);
  const [positions, setPositions] = useState<Position[] | null>(null);
  const [funds, setFunds] = useState<Funds | null>(null);
  const [analytics, setAnalytics] = useState<PortfolioAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchHoldings(), fetchPositions(), fetchFunds()])
      .then(([h, p, f]) => {
        setHoldings(h);
        setPositions(p);
        setFunds(f);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load portfolio"));
    fetchPortfolioAnalytics()
      .then(setAnalytics)
      .catch(() => {}); // analytics is additive; raw tables above already report load errors
  }, []);

  if (error) {
    return (
      <div>
        <PageHeader crumb="Portfolio" title="Portfolio" />
        <GlassPanel>
          <div style={{ padding: 20 }}>
            <p style={{ color: "var(--loss)", margin: "0 0 8px" }}>{error}</p>
            {error.toLowerCase().includes("not connected") && (
              <a href="/settings/broker" style={{ color: "var(--purple)" }}>
                Connect your Dhan account →
              </a>
            )}
          </div>
        </GlassPanel>
      </div>
    );
  }

  const holdingsValue = (holdings ?? []).reduce((sum, h) => sum + h.totalQty * h.lastTradedPrice, 0);
  const holdingsCost = (holdings ?? []).reduce((sum, h) => sum + h.totalQty * h.avgCostPrice, 0);
  const holdingsPnl = holdingsValue - holdingsCost;
  const positionsPnl = (positions ?? []).reduce((sum, p) => sum + p.unrealizedProfit + p.realizedProfit, 0);

  return (
    <div>
      <PageHeader crumb="Portfolio" title="Portfolio" subtitle="Holdings, positions, and portfolio analytics from your connected Dhan account." />

      <div className="stat-grid">
        <StatCard
          label="Available Balance"
          price={funds ? inr(funds.availabelBalance) : "-"}
          change={null}
          pctChange={null}
          sparklineValues={[]}
          index={0}
        />
        <StatCard
          label="Holdings Value"
          price={holdings ? inr(holdingsValue) : "-"}
          change={holdings ? holdingsPnl : null}
          pctChange={holdings && holdingsCost ? (holdingsPnl / holdingsCost) * 100 : null}
          sparklineValues={[]}
          index={1}
        />
        <StatCard
          label="Positions P&amp;L"
          price={positions ? inr(positionsPnl) : "-"}
          change={positions ? positionsPnl : null}
          pctChange={null}
          sparklineValues={[]}
          index={2}
        />
      </div>

      {analytics && (
        <div className="panel-stack" style={{ marginBottom: 20 }}>
          <GlassPanel title="Portfolio Analytics" note={`computed ${new Date(analytics.computed_at).toLocaleTimeString()}`}>
            <div className="analytics-grid">
              <div className="a-tile">
                <div className="a-label">Trading Exposure</div>
                <div className="a-value">{analytics.exposure_pct !== null ? `${analytics.exposure_pct}%` : "-"}</div>
                <div className="a-note">{analytics.exposure_note}</div>
              </div>
              <div className="a-tile">
                <div className="a-label">Holdings % of Portfolio</div>
                <div className="a-value">
                  {analytics.holdings_pct_of_portfolio !== null ? `${analytics.holdings_pct_of_portfolio}%` : "-"}
                </div>
              </div>
              <div className="a-tile">
                <div className="a-label">Beta vs NIFTY</div>
                <div className="a-value">{analytics.beta ?? "-"}</div>
                {analytics.beta_note && <div className="a-note">{analytics.beta_note}</div>}
              </div>
              <div className="a-tile">
                <div className="a-label">Alpha (annualized)</div>
                <div className="a-value">{analytics.alpha_annual_pct !== null ? `${analytics.alpha_annual_pct}%` : "-"}</div>
              </div>
              <div className="a-tile">
                <div className="a-label">Volatility (annualized)</div>
                <div className="a-value">
                  {analytics.volatility_annual_pct !== null ? `${analytics.volatility_annual_pct}%` : "-"}
                </div>
              </div>
              <div className="a-tile">
                <div className="a-label">Cash Available</div>
                <div className="a-value">{inr(analytics.capital_allocation.cash_available)}</div>
              </div>
            </div>
          </GlassPanel>

          <GlassPanel title="Sector Allocation" note={`${analytics.sector_allocation.length} sectors`}>
            <div className="sector-bars">
              {analytics.sector_allocation.map((s) => (
                <div className="sector-row" key={s.sector}>
                  <div className="sector-name">{s.sector}</div>
                  <div className="sector-track">
                    <div className="sector-fill" style={{ width: `${Math.max(s.pct, 1)}%` }} />
                  </div>
                  <div className="sector-pct">{s.pct}%</div>
                  <div className="sector-value">{inr(s.value)}</div>
                </div>
              ))}
            </div>
          </GlassPanel>
        </div>
      )}

      <div className="panel-stack">
        <GlassPanel title="Holdings" note={holdings ? `${holdings.length} symbols` : undefined}>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Qty</th>
                  <th>Avg Cost</th>
                  <th>LTP</th>
                  <th>P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {holdings === null && (
                  <tr>
                    <td colSpan={5} className="loading-cell">
                      Loading...
                    </td>
                  </tr>
                )}
                {holdings?.map((h) => {
                  const pnl = (h.lastTradedPrice - h.avgCostPrice) * h.totalQty;
                  const up = pnl >= 0;
                  return (
                    <tr key={h.tradingSymbol + h.exchange}>
                      <td className="sym-cell">{h.tradingSymbol}</td>
                      <td className="num">{h.totalQty}</td>
                      <td className="num">{inr(h.avgCostPrice)}</td>
                      <td className="num">{inr(h.lastTradedPrice)}</td>
                      <td className={`num ${up ? "up" : "down"}`}>
                        {up ? "+" : ""}
                        {inr(pnl)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassPanel>

        <GlassPanel title="Positions" note={positions ? `${positions.length} open` : undefined}>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Product</th>
                  <th>Net Qty</th>
                  <th>Buy Avg</th>
                  <th>Unrealized</th>
                </tr>
              </thead>
              <tbody>
                {positions === null && (
                  <tr>
                    <td colSpan={6} className="loading-cell">
                      Loading...
                    </td>
                  </tr>
                )}
                {positions?.length === 0 && (
                  <tr>
                    <td colSpan={6} className="loading-cell">
                      No open positions
                    </td>
                  </tr>
                )}
                {positions?.map((p) => {
                  const up = p.unrealizedProfit >= 0;
                  return (
                    <tr key={p.tradingSymbol}>
                      <td className="sym-cell">{p.tradingSymbol}</td>
                      <td>{p.positionType}</td>
                      <td>{p.productType}</td>
                      <td className="num">{p.netQty}</td>
                      <td className="num">{inr(p.buyAvg)}</td>
                      <td className={`num ${up ? "up" : "down"}`}>
                        {up ? "+" : ""}
                        {inr(p.unrealizedProfit)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassPanel>
      </div>

      <style jsx>{`
        .stat-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
          gap: 14px;
          margin-bottom: 28px;
        }
        .panel-stack {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }
        .analytics-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
          gap: 14px;
          padding: 18px 20px;
        }
        .a-label {
          font-size: 10.5px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: var(--text-faint);
        }
        .a-value {
          margin-top: 6px;
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 17px;
          font-weight: 600;
        }
        .a-note {
          margin-top: 5px;
          font-size: 10.5px;
          color: var(--text-faint);
          line-height: 1.4;
        }
        .sector-bars {
          display: flex;
          flex-direction: column;
          gap: 10px;
          padding: 16px 20px;
        }
        .sector-row {
          display: grid;
          grid-template-columns: 130px 1fr 50px 100px;
          align-items: center;
          gap: 12px;
          font-size: 12.5px;
        }
        .sector-name {
          font-weight: 500;
        }
        .sector-track {
          height: 8px;
          border-radius: 4px;
          background: var(--canvas-soft);
          overflow: hidden;
        }
        .sector-fill {
          height: 100%;
          border-radius: 4px;
          background: linear-gradient(90deg, var(--accent), var(--accent-hover));
        }
        .sector-pct {
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          text-align: right;
          color: var(--text-muted);
        }
        .sector-value {
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          text-align: right;
        }
        .table-scroll {
          overflow-x: auto;
        }
        table {
          width: 100%;
          border-collapse: collapse;
          min-width: 560px;
        }
        th {
          text-align: left;
          font-size: 11px;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-faint);
          font-weight: 600;
          padding: 12px 20px;
          border-bottom: 1px solid var(--panel-border);
        }
        td {
          padding: 13px 20px;
          font-size: 13.5px;
          border-bottom: 1px solid var(--panel-border);
        }
        tbody tr:hover {
          background: var(--canvas-soft);
        }
        tbody tr:last-child td {
          border-bottom: none;
        }
        .sym-cell {
          font-weight: 600;
        }
        .num {
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
        }
        .num.up {
          color: var(--gain);
        }
        .num.down {
          color: var(--loss);
        }
        .loading-cell {
          color: var(--text-faint);
          text-align: center;
          padding: 24px;
        }
      `}</style>
    </div>
  );
}
