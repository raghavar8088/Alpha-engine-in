"use client";

import { useEffect, useRef, useState } from "react";

function parseNumeric(value: string): number | null {
  const cleaned = value.replace(/,/g, "");
  const num = Number(cleaned);
  return Number.isNaN(num) ? null : num;
}

export default function FlashOnChange({ value, children }: { value: string; children: React.ReactNode }) {
  const previous = useRef(value);
  const [flashColor, setFlashColor] = useState<"gain" | "loss" | "neutral" | null>(null);

  useEffect(() => {
    if (previous.current === value) return;

    const prevNum = parseNumeric(previous.current);
    const nextNum = parseNumeric(value);
    if (prevNum !== null && nextNum !== null && prevNum !== nextNum) {
      setFlashColor(nextNum > prevNum ? "gain" : "loss");
    } else {
      setFlashColor("neutral");
    }
    previous.current = value;

    const timer = setTimeout(() => setFlashColor(null), 700);
    return () => clearTimeout(timer);
  }, [value]);

  return (
    <span className={flashColor ? `flash-${flashColor}` : ""}>
      {children}
      <style jsx>{`
        span {
          display: block;
          border-radius: 6px;
          transition: background-color 0.6s ease;
        }
        .flash-gain {
          background-color: var(--gain-dim);
        }
        .flash-loss {
          background-color: var(--loss-dim);
        }
        .flash-neutral {
          background-color: var(--accent-dim);
        }
      `}</style>
    </span>
  );
}
