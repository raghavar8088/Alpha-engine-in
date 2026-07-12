"use client";

export default function Footer() {
  return (
    <footer className="footer">
      <div className="cols">
        <div>
          <div className="brand">TradingAI</div>
          <p className="desc">
            An NSE-focused research and execution terminal — live market data, strategy backtesting, options
            analytics, and an AI research layer, built on the Dhan API.
          </p>
        </div>
        <div>
          <div className="head">Platform</div>
          <a href="/dashboard">Market Data</a>
          <a href="/strategies">Strategies</a>
          <a href="/backtesting">Backtesting</a>
          <a href="/live">Live Engine</a>
        </div>
        <div>
          <div className="head">Analytics</div>
          <a href="/options">Options</a>
          <a href="/risk">Risk</a>
          <a href="/ai">AI Research</a>
          <a href="/portfolio">Portfolio</a>
        </div>
        <div>
          <div className="head">Data sources</div>
          <p className="note">NSE public indices feed &middot; Dhan broker API &middot; RSS market news</p>
          <p className="note">Not investment advice. Backtests are simulations, not guarantees of future results.</p>
        </div>
      </div>
      <div className="bottom">© {new Date().getFullYear()} TradingAI. Personal research project, not a registered broker or investment advisor.</div>

      <style jsx>{`
        .footer {
          margin-top: 56px;
          padding: 36px 0 28px;
          border-top: 1px solid var(--panel-border);
        }
        .cols {
          display: grid;
          grid-template-columns: 1.4fr 1fr 1fr 1.2fr;
          gap: 28px;
        }
        .brand {
          font-family: var(--font-display);
          font-weight: 800;
          font-size: 16px;
          margin-bottom: 10px;
        }
        .desc {
          font-size: 12.5px;
          color: var(--text-muted);
          line-height: 1.6;
          max-width: 320px;
          margin: 0;
        }
        .head {
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-faint);
          margin-bottom: 10px;
        }
        a {
          display: block;
          font-size: 13px;
          color: var(--text-muted);
          text-decoration: none;
          margin-bottom: 8px;
        }
        a:hover {
          color: var(--purple);
        }
        .note {
          font-size: 11.5px;
          color: var(--text-faint);
          line-height: 1.5;
          margin: 0 0 8px;
        }
        .bottom {
          margin-top: 26px;
          padding-top: 18px;
          border-top: 1px solid var(--panel-border);
          font-size: 11.5px;
          color: var(--text-faint);
        }
        @media (max-width: 800px) {
          .cols {
            grid-template-columns: 1fr 1fr;
          }
        }
        @media (max-width: 500px) {
          .cols {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </footer>
  );
}
