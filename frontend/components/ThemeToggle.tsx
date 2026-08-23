"use client";

/**
 * Light / Dark / System.
 *
 * THREE STATES, NOT TWO. A plain toggle silently overrides the OS preference the first
 * time it is touched and gives you no way back — so someone whose machine flips to dark at
 * sunset is stuck on whatever they picked at noon. "System" is the default and is a real,
 * selectable state.
 *
 * The choice is written to <html data-theme> and to localStorage. It has to be applied
 * BEFORE first paint or a dark-mode user gets a white flash on every navigation, which is
 * why layout.tsx carries a tiny blocking script that reads the same key. This component
 * only handles changes after hydration; that script owns the first paint.
 */

import { useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";

const KEY = "tradingai-theme";

const OPTIONS: { key: Theme; label: string; icon: React.ReactNode }[] = [
  {
    key: "light",
    label: "Light",
    icon: (
      <>
        <circle cx="12" cy="12" r="4.2" />
        <path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8" />
      </>
    ),
  },
  {
    key: "system",
    label: "System",
    icon: (
      <>
        <rect x="2.5" y="4" width="19" height="13" rx="2" />
        <path d="M8 21h8M12 17v4" />
      </>
    ),
  },
  {
    key: "dark",
    label: "Dark",
    icon: <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.8 6.8 0 0 0 10.5 10.5z" />,
  },
];

/** Write the choice to the document. `system` REMOVES the attribute rather than resolving
 *  it to a value — the media query in the stylesheet is what should decide from then on,
 *  and freezing today's answer into the DOM would break the moment the OS flipped. */
function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const stored = (localStorage.getItem(KEY) as Theme | null) ?? "system";
    setTheme(stored);
    apply(stored);
    setReady(true);
  }, []);

  const choose = (next: Theme) => {
    setTheme(next);
    localStorage.setItem(KEY, next);
    apply(next);
  };

  return (
    <div className="themetoggle" role="group" aria-label="Colour theme">
      {OPTIONS.map((o) => (
        <button
          key={o.key}
          className={ready && theme === o.key ? "opt on" : "opt"}
          onClick={() => choose(o.key)}
          title={`${o.label} theme`}
          aria-pressed={ready && theme === o.key}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9}
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {o.icon}
          </svg>
          <span className="sr">{o.label}</span>
        </button>
      ))}

      <style jsx>{`
        .themetoggle {
          display: flex;
          gap: 2px;
          padding: 3px;
          border-radius: 9px;
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
        }
        .opt {
          flex: 1;
          display: grid;
          place-items: center;
          padding: 6px 0;
          border: 0;
          border-radius: 6px;
          background: transparent;
          color: var(--text-faint);
          cursor: pointer;
        }
        .opt:hover { color: var(--text-muted); }
        .opt.on {
          background: var(--panel);
          color: var(--purple);
          box-shadow: var(--shadow-sm);
        }
        .opt:focus-visible { outline: 2px solid var(--purple); outline-offset: 1px; }
        svg { width: 15px; height: 15px; }
        .sr {
          position: absolute;
          width: 1px; height: 1px;
          overflow: hidden;
          clip: rect(0 0 0 0);
          white-space: nowrap;
        }
      `}</style>
    </div>
  );
}
