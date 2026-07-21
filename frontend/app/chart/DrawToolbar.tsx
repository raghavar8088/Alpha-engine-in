"use client";

/** Floating, draggable drawing toolbar — the TradingView-style pill that sits
 * over the chart canvas itself rather than in a side panel. It's a second,
 * more discoverable entry point onto the exact same state WorkspacePanel's
 * "Draw" section already drives (activeTool / drawColor), so a tool picked
 * here or there behaves identically and neither needs to know the other
 * exists.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { DrawingTool } from "./WorkspacePanel";

interface ToolDef {
  id: NonNullable<DrawingTool>;
  label: string;
}

const TOOLS: ToolDef[] = [
  { id: "trendline", label: "Trend Line" },
  { id: "horizontal", label: "Horizontal Line" },
  { id: "rectangle", label: "Rectangle" },
  { id: "fibonacci", label: "Fib Retracement" },
  { id: "long_position", label: "Long Position" },
  { id: "short_position", label: "Short Position" },
  { id: "ray", label: "Ray" },
  { id: "arrow", label: "Arrow" },
  { id: "vertical", label: "Vertical Line" },
  { id: "channel", label: "Parallel Channel" },
  { id: "text", label: "Text" },
];

/** Minimal line-icon set drawn inline so the toolbar has no image/font
 * dependency. Kept visually close to TradingView's own glyphs without
 * reproducing them pixel-for-pixel. */
function ToolIcon({ id }: { id: ToolDef["id"] }) {
  const common = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (id) {
    case "trendline":
      return (
        <svg {...common}>
          <circle cx="5" cy="19" r="1.6" fill="currentColor" stroke="none" />
          <circle cx="19" cy="5" r="1.6" fill="currentColor" stroke="none" />
          <path d="M5 19L19 5" />
        </svg>
      );
    case "horizontal":
      return (
        <svg {...common}>
          <circle cx="7" cy="12" r="1.6" fill="currentColor" stroke="none" />
          <path d="M4 12h16" />
        </svg>
      );
    case "rectangle":
      return (
        <svg {...common}>
          <rect x="5" y="6" width="14" height="12" rx="1.5" />
        </svg>
      );
    case "fibonacci":
      return (
        <svg {...common}>
          <path d="M4 6h16M4 10.5h11M4 15h16M4 18.5h7" />
        </svg>
      );
    case "text":
      return (
        <svg {...common}>
          <path d="M5 6h14M12 6v12" />
        </svg>
      );
    case "long_position":
      return (
        <svg {...common}>
          <rect x="4" y="12" width="16" height="6" fill="rgba(14,159,110,0.3)" stroke="#0e9f6e" />
          <path d="M4 8h16" stroke="#0e9f6e" />
        </svg>
      );
    case "short_position":
      return (
        <svg {...common}>
          <rect x="4" y="6" width="16" height="6" fill="rgba(217,45,63,0.3)" stroke="#d92d3f" />
          <path d="M4 16h16" stroke="#d92d3f" />
        </svg>
      );
    case "ray":
      return (
        <svg {...common}>
          <circle cx="5" cy="19" r="1.6" fill="currentColor" stroke="none" />
          <path d="M5 19L21 3" />
        </svg>
      );
    case "arrow":
      return (
        <svg {...common}>
          <path d="M5 19L19 5" />
          <path d="M19 5H12M19 5V12" />
        </svg>
      );
    case "vertical":
      return (
        <svg {...common}>
          <circle cx="12" cy="5" r="1.6" fill="currentColor" stroke="none" />
          <path d="M12 5v14" />
        </svg>
      );
    case "channel":
      return (
        <svg {...common}>
          <path d="M4 9l16-4M4 17l16-4" />
        </svg>
      );
    default:
      return null;
  }
}

function CursorIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 3l6.5 16 2-6.5L20 10.5 5 3z" />
    </svg>
  );
}

interface Props {
  activeTool: DrawingTool;
  onSelectTool: (tool: DrawingTool) => void;
  colors: string[];
  activeColor: string;
  onSelectColor: (color: string) => void;
  disabled: boolean;
}

const STORAGE_KEY = "chart.drawToolbar.pos";

export default function DrawToolbar({
  activeTool, onSelectTool, colors, activeColor, onSelectColor, disabled,
}: Props) {
  const barRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(null);
  const [pos, setPos] = useState<{ x: number; y: number }>({ x: 12, y: 12 });
  const [dragging, setDragging] = useState(false);

  // Remembered per browser, not per symbol — the toolbar's position is a
  // workspace preference, not something that should reset every symbol switch.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setPos(JSON.parse(raw));
    } catch {
      // Corrupt or absent — the default top-left position is fine.
    }
  }, []);

  const clampToParent = useCallback((x: number, y: number) => {
    const parent = barRef.current?.parentElement;
    const bar = barRef.current;
    if (!parent || !bar) return { x, y };
    const maxX = Math.max(0, parent.clientWidth - bar.offsetWidth);
    const maxY = Math.max(0, parent.clientHeight - bar.offsetHeight);
    return { x: Math.min(Math.max(0, x), maxX), y: Math.min(Math.max(0, y), maxY) };
  }, []);

  const onHandleDown = useCallback(
    (e: React.MouseEvent) => {
      dragRef.current = { startX: e.clientX, startY: e.clientY, originX: pos.x, originY: pos.y };
      setDragging(true);
      e.preventDefault();
    },
    [pos],
  );

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const next = clampToParent(
        drag.originX + (e.clientX - drag.startX),
        drag.originY + (e.clientY - drag.startY),
      );
      setPos(next);
    };
    const onUp = () => {
      setDragging(false);
      dragRef.current = null;
      setPos((p) => {
        try {
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
        } catch {
          // Best-effort — losing the remembered position isn't worth surfacing.
        }
        return p;
      });
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, clampToParent]);

  return (
    <div
      ref={barRef}
      className={`draw-toolbar${dragging ? " dragging" : ""}${disabled ? " disabled" : ""}`}
      style={{ left: pos.x, top: pos.y }}
    >
      <button
        className="handle"
        onMouseDown={onHandleDown}
        title="Drag to move"
        aria-label="Move toolbar"
      >
        <svg width="10" height="18" viewBox="0 0 10 18" fill="currentColor">
          {[0, 1, 2].map((row) =>
            [0, 1].map((col) => (
              <circle key={`${row}-${col}`} cx={col === 0 ? 2.5 : 7.5} cy={2.5 + row * 6.5} r="1.4" />
            )),
          )}
        </svg>
      </button>

      <button
        className={activeTool === null ? "tool active" : "tool"}
        onClick={() => onSelectTool(null)}
        disabled={disabled}
        title="Cursor"
      >
        <CursorIcon />
      </button>

      <span className="sep" />

      {TOOLS.map((t) => (
        <button
          key={t.id}
          className={activeTool === t.id ? "tool active" : "tool"}
          onClick={() => onSelectTool(activeTool === t.id ? null : t.id)}
          disabled={disabled}
          title={t.label}
        >
          <ToolIcon id={t.id} />
        </button>
      ))}

      <span className="sep" />

      <div className="swatches">
        {colors.map((c) => (
          <button
            key={c}
            className={activeColor === c ? "swatch active" : "swatch"}
            style={{ background: c }}
            onClick={() => onSelectColor(c)}
            disabled={disabled}
            title={`Draw in ${c}`}
            aria-label={`Draw in ${c}`}
          />
        ))}
      </div>

      <style jsx>{`
        .draw-toolbar {
          position: absolute; z-index: 5; display: flex; align-items: center; gap: 2px;
          background: var(--panel); border: 1px solid var(--panel-border); border-radius: 10px;
          padding: 5px 7px; box-shadow: 0 6px 18px rgba(0, 0, 0, 0.22);
          user-select: none;
        }
        .draw-toolbar.dragging { box-shadow: 0 10px 26px rgba(0, 0, 0, 0.32); }
        .draw-toolbar.disabled { opacity: 0.5; pointer-events: none; }

        .handle {
          background: none; border: none; padding: 4px 5px; cursor: grab; color: var(--text-faint);
          display: flex; align-items: center; margin-right: 2px;
        }
        .handle:active { cursor: grabbing; }

        .tool {
          background: none; border: none; border-radius: 6px; padding: 6px; cursor: pointer;
          color: var(--text-muted); display: flex; align-items: center; justify-content: center;
        }
        .tool:hover:not(:disabled) { background: var(--canvas-soft); }
        .tool.active { background: var(--purple-dim); color: var(--purple); }
        .tool:disabled { cursor: default; }

        .sep { width: 1px; align-self: stretch; margin: 4px 3px; background: var(--panel-border); }

        .swatches { display: flex; align-items: center; gap: 5px; padding: 0 4px; }
        .swatch { width: 15px; height: 15px; border-radius: 50%; border: 1px solid var(--panel-border); cursor: pointer; padding: 0; }
        .swatch.active { box-shadow: 0 0 0 2px var(--canvas), 0 0 0 3px currentColor; }
        .swatch:disabled { cursor: default; }
      `}</style>
    </div>
  );
}
