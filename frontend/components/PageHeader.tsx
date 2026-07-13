"use client";

import Link from "next/link";

export default function PageHeader({
  crumb,
  title,
  subtitle,
  actions,
}: {
  crumb: string;
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
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
        {actions && <div className="actions">{actions}</div>}
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
      `}</style>
    </div>
  );
}
