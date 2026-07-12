type PillTone = "gain" | "loss" | "warn" | "accent" | "muted";

const TONE_STYLES: Record<PillTone, { color: string; border: string; bg: string; dot?: string }> = {
  gain: { color: "var(--gain)", border: "rgba(14,159,110,.25)", bg: "var(--gain-dim)", dot: "var(--gain)" },
  loss: { color: "var(--loss)", border: "rgba(217,45,63,.22)", bg: "var(--loss-dim)" },
  warn: { color: "var(--warn)", border: "rgba(185,119,14,.3)", bg: "var(--warn-dim)" },
  accent: { color: "var(--purple)", border: "rgba(125,52,220,.22)", bg: "var(--purple-dim)" },
  muted: { color: "var(--text-muted)", border: "var(--panel-border)", bg: "var(--canvas-soft)" },
};

export default function StatusPill({ label, tone = "muted", pulse = false }: { label: string; tone?: PillTone; pulse?: boolean }) {
  const style = TONE_STYLES[tone];

  return (
    <span className="pill">
      {pulse && <span className="dot" />}
      {label}
      <style jsx>{`
        .pill {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          padding: 5px 12px;
          border-radius: 100px;
          font-size: 12px;
          font-weight: 600;
          border: 1px solid ${style.border};
          background: ${style.bg};
          color: ${style.color};
          white-space: nowrap;
        }
        .dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: ${style.dot ?? style.color};
          box-shadow: 0 0 8px ${style.dot ?? style.color};
          animation: pulse 1.8s ease-in-out infinite;
        }
        @keyframes pulse {
          0%,
          100% {
            opacity: 1;
            transform: scale(1);
          }
          50% {
            opacity: 0.45;
            transform: scale(0.72);
          }
        }
      `}</style>
    </span>
  );
}
