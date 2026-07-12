export default function EmptyState({ title, note }: { title: string; note?: string }) {
  return (
    <div className="empty-state">
      <div className="ring">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19h16M6 15l4-5 3 3 5-7" />
        </svg>
      </div>
      <div className="title">{title}</div>
      {note && <div className="note">{note}</div>}

      <style jsx>{`
        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          text-align: center;
          padding: 44px 24px;
          color: var(--text-muted);
        }
        .ring {
          width: 44px;
          height: 44px;
          border-radius: 50%;
          background: var(--canvas-soft);
          display: grid;
          place-items: center;
          color: var(--text-faint);
          margin-bottom: 14px;
        }
        .ring svg {
          width: 20px;
          height: 20px;
        }
        .title {
          font-size: 13.5px;
          font-weight: 600;
          color: var(--text);
        }
        .note {
          margin-top: 4px;
          font-size: 12.5px;
          color: var(--text-faint);
          max-width: 360px;
        }
      `}</style>
    </div>
  );
}
