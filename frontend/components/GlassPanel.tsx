export default function GlassPanel({
  children,
  title,
  note,
  tint = "white",
  style,
}: {
  children: React.ReactNode;
  title?: string;
  note?: string;
  tint?: "white" | "lavender";
  style?: React.CSSProperties;
}) {
  return (
    <div className={`panel ${tint === "lavender" ? "lavender" : ""}`} style={style}>
      {title && (
        <div className="panel-head">
          <div className="panel-title">{title}</div>
          {note && <div className="panel-note">{note}</div>}
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
      `}</style>
    </div>
  );
}
