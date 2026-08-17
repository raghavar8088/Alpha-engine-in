"use client";

import Link from "next/link";

export default function PageHeader({
  crumb,
  title,
  subtitle,
  actions,
  onRefresh,
  refreshing = false,
}: {
  crumb: string;
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  /** Re-read this module's data. Rendered top-right, before any page-specific actions. */
  onRefresh?: () => void | Promise<void>;
  refreshing?: boolean;
}) {
  return (
    <div className="page-header">
      <div className="crumbs">
        <Link href="/dashboard">Home</Link>
        <span>&rsaquo;</span>
        <span className="current">{crumb}</span>
      </div>
      <div className="row">
        <div>
          <h1>{title}</h1>
          {subtitle && <p className="sub">{subtitle}</p>}
        </div>
        {(actions || onRefresh) && (
          <div className="actions">
            {onRefresh && (
              <button
                className="refresh"
                onClick={() => onRefresh()}
                disabled={refreshing}
                title="Re-read this module's data now"
              >
                <span className={refreshing ? "spin" : ""}><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" /></svg></span>
                {refreshing ? "Refreshing…" : "Refresh"}
              </button>
            )}
            {actions}
          </div>
        )}
      </div>

      <style jsx>{`
        .page-header {
          margin-bottom: 24px;
        }
        .crumbs {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12.5px;
          color: var(--text-faint);
          margin-bottom: 10px;
        }
        .crumbs a {
          color: var(--text-faint);
          text-decoration: none;
        }
        .crumbs a:hover {
          color: var(--purple);
        }
        .current {
          color: var(--text-muted);
          font-weight: 600;
        }
        .row {
          display: flex;
          justify-content: space-between;
          align-items: flex-end;
          flex-wrap: wrap;
          gap: 16px;
        }
        h1 {
          font-family: var(--font-display);
          font-weight: 800;
          font-size: 28px;
          letter-spacing: -0.2px;
          margin: 0 0 4px;
          text-wrap: balance;
        }
        .sub {
          color: var(--text-muted);
          font-size: 13.5px;
          margin: 0;
          max-width: 720px;
        }
        .actions {
          display: flex;
          gap: 10px;
          align-items: center;
          flex-wrap: wrap;
        }
        .refresh {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          color: var(--text-muted);
          border-radius: 9px;
          padding: 8px 14px;
          font-size: 12.5px;
          font-weight: 600;
          cursor: pointer;
        }
        .refresh:hover:not(:disabled) {
          color: var(--purple);
          border-color: rgba(125, 52, 220, 0.3);
          background: var(--purple-dim);
        }
        .refresh:disabled {
          opacity: 0.6;
          cursor: default;
        }
        .refresh :global(svg) {
          display: block;
        }
        .spin {
          display: inline-flex;
          animation: spin 0.9s linear infinite;
        }
        @keyframes spin {
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </div>
  );
}
