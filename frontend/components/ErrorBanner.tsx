export default function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-banner">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v5M12 16h.01" />
      </svg>
      <span>{message}</span>
      {onRetry && (
        <button onClick={onRetry}>Retry</button>
      )}

      <style jsx>{`
        .error-banner {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 16px;
          border-radius: 12px;
          background: var(--loss-dim);
          border: 1px solid rgba(217, 45, 63, 0.22);
          color: var(--loss);
          font-size: 13px;
        }
        svg {
          width: 16px;
          height: 16px;
          flex-shrink: 0;
        }
        span {
          flex: 1;
        }
        button {
          background: #fff;
          border: 1px solid rgba(217, 45, 63, 0.3);
          color: var(--loss);
          font-size: 12px;
          font-weight: 700;
          padding: 5px 12px;
          border-radius: 999px;
        }
        button:hover {
          background: var(--loss-dim);
        }
      `}</style>
    </div>
  );
}
