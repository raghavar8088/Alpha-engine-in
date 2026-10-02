"use client";

/** "Copy for TradingView" + "Download .txt", the same on every list in Fundamental Rating.
 *
 * Copy is always the flat list (what TradingView's Add symbol box takes on paste). The
 * download carries "###Section" headers when the list has more than one group and the box
 * is ticked, because TradingView's Import list is the only door sections survive through.
 */

import { useMemo, useState } from "react";
import {
  TvItem,
  downloadTxt,
  groupCount,
  prettyGroup,
  tvFilename,
  tvFlat,
  tvSections,
} from "./tradingview";

export default function TvExport({
  items,
  name,
  groupOrder = [],
  groupLabel = prettyGroup,
  sectionsLabel = "sections by grade",
  hint = true,
}: {
  items: TvItem[];
  /** Becomes the file name. */
  name: string;
  groupOrder?: string[];
  groupLabel?: (g: string) => string;
  sectionsLabel?: string;
  hint?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [fallback, setFallback] = useState<string | null>(null);
  const [sections, setSections] = useState(true);

  const flat = useMemo(() => tvFlat(items), [items]);
  const groups = useMemo(() => groupCount(items), [items]);
  const n = flat ? flat.split(",").length : 0;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(flat);
      setFallback(null);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // Clipboard can be blocked (http, iframe, permissions). Show the text so it can still
      // be selected by hand rather than failing silently.
      setFallback(flat);
    }
  };

  const download = () => {
    const text = sections && groups > 1 ? tvSections(items, groupOrder, groupLabel) : flat;
    downloadTxt(tvFilename(name), text);
  };

  return (
    <div className="tvx">
      <div className="row">
        <button className="primary" onClick={copy} disabled={!n}>
          {copied ? "Copied" : `Copy ${n} for TradingView`}
        </button>
        <button className="ghost" onClick={download} disabled={!n}>
          Download .txt
        </button>
        {groups > 1 && (
          <label className="chk">
            <input type="checkbox" checked={sections} onChange={(e) => setSections(e.target.checked)} />
            {sectionsLabel}
          </label>
        )}
        {hint && (
          <span className="hint">
            Paste the copy into a TradingView watchlist&apos;s <b>Add symbol</b> box, or use{" "}
            <b>Import list…</b> with the .txt{groups > 1 ? " to keep the sections" : ""}.
          </span>
        )}
      </div>
      {fallback !== null && (
        <textarea
          className="box"
          readOnly
          rows={2}
          value={fallback}
          onFocus={(e) => e.target.select()}
          aria-label="TradingView list - select and copy"
        />
      )}
      <style jsx>{`
        .tvx { display: flex; flex-direction: column; gap: 8px; }
        .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
        .primary, .ghost {
          padding: 7px 13px; border-radius: 9px; font-size: 12.5px; font-weight: 700; cursor: pointer;
          border: 1px solid var(--panel-border);
        }
        .primary { background: var(--purple); color: #fff; border-color: var(--purple); }
        .ghost { background: var(--canvas-soft); color: var(--text); }
        .primary:disabled, .ghost:disabled { opacity: 0.5; cursor: default; }
        .chk { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted); cursor: pointer; }
        .hint { font-size: 11.5px; color: var(--text-faint); line-height: 1.45; flex: 1 1 260px; }
        .box {
          width: 100%; font-family: ui-monospace, monospace; font-size: 11px; padding: 8px 10px;
          border-radius: 8px; border: 1px solid var(--panel-border); background: var(--canvas-soft); color: var(--text);
        }
      `}</style>
    </div>
  );
}
