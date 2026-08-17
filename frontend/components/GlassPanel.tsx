export default function GlassPanel({
  children,
  title,
  note,
  tint = "white",
  style,
  onRefresh,
  refreshing = false,
}: {
  children: React.ReactNode;
  title?: string;
  note?: string;
  tint?: "white" | "lavender";
  style?: React.CSSProperties;
  /** Re-read just this panel, without reloading the whole module. */
  onRefresh?: () => void | Promise<void>;
  refreshing?: boolean;
}) {
  return (
    <div className={`panel ${tint === "lavender" ? "lavender" : ""}`} style={style}>
      {(title || onRefresh) && (
        <div className="panel-head">
          <div className="panel-title">{title}</div>
          <div className="panel-right">
            {note && <div className="panel-note">{note}</div>}
            {onRefresh && (
              <button
                className="panel-refresh"
                onClick={() => onRefresh()}
                disabled={refreshing}
                title="Reload this table"
              >
                <span className={refreshing ? "spin" : ""}><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" /></svg></span>
              </button>
            )}
          </div>
        </div>
      )}
      {children}

      <style jsx>{`
        .panel {
          background: var(--panel);
          border: 1px solid var(--panel-border);
          border-radius: 18px;
          box-shadow: var(--shadow-sm);
          overflow: hidden;
        }
        .panel.lavender {
          background: var(--canvas-edge);
          border-color: transparent;
        }
        .panel-head {
          padding: 16px 20px;
          border-bottom: 1px solid var(--panel-border);
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
        }
        .panel-title {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 14.5px;
        }
        .panel-note {
          font-size: 11.5px;
          color: var(--text-faint);
          white-space: nowrap;
        }
        .panel-right {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .panel-refresh {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          color: var(--text-muted);
          border-radius: 7px;
          padding: 5px 8px;
          cursor: pointer;
        }
        .panel-refresh:hover:not(:disabled) {
          color: var(--purple);
          border-color: rgba(125, 52, 220, 0.3);
          background: var(--purple-dim);
        }
        .panel-refresh:disabled {
          opacity: 0.6;
          cursor: default;
        }
        .panel-refresh :global(svg) {
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
