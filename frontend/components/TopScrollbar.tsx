"use client";

// A second horizontal scrollbar ABOVE a wide table, moving in step with the table's own bar, which stays at the bottom
// (13 Nov 2026). It is the NSE Stock Ratings tab's strip made shareable: the strip's scroll range is made equal to the
// box's (even when the box also scrolls vertically), it re-measures whenever the box or the table inside changes width
// (another tab, a filter, the window), and it is hidden while nothing overflows. The look comes from the global
// ::-webkit-scrollbar rules in globals.css, so both bars match.
import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";

// longhands only: React unsets a dropped longhand without re-applying a shorthand, so "margin" + "marginBottom" would
// lose the gap after the first hide/show
const STRIP: CSSProperties = { overflowX: "auto", overflowY: "hidden", marginBottom: 4 };
const STRIP_OFF: CSSProperties = { ...STRIP, visibility: "hidden", height: 0, marginBottom: 0 };

/** The strip alone, for a scrolling box that already has its own ref. */
export function TopScrollbar({ target }: { target: RefObject<HTMLElement | null> }) {
  const barRef = useRef<HTMLDivElement>(null);
  const [inner, setInner] = useState(0);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const box = target.current;
    const bar = barRef.current;
    if (!box || !bar) return;
    const measure = () => {
      const range = box.scrollWidth - box.clientWidth;
      setOverflows(range > 1);
      setInner(bar.clientWidth + Math.max(0, range));
      bar.scrollLeft = box.scrollLeft;
    };
    const fromBox = () => {
      if (Math.abs(bar.scrollLeft - box.scrollLeft) > 0.5) bar.scrollLeft = box.scrollLeft;
    };
    const fromBar = () => {
      if (Math.abs(box.scrollLeft - bar.scrollLeft) > 0.5) box.scrollLeft = bar.scrollLeft;
    };
    box.addEventListener("scroll", fromBox, { passive: true });
    bar.addEventListener("scroll", fromBar, { passive: true });
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    if (box.firstElementChild) ro.observe(box.firstElementChild);
    measure();
    return () => {
      box.removeEventListener("scroll", fromBox);
      bar.removeEventListener("scroll", fromBar);
      ro.disconnect();
    };
  }, [target]);

  useEffect(() => {          // after the strip re-renders at a new width, line it up with the table again
    const box = target.current;
    const bar = barRef.current;
    if (box && bar) bar.scrollLeft = box.scrollLeft;
  }, [inner, target]);

  // aria-hidden and out of the tab order: the box's own bar and keyboard scrolling stay the accessible way to scroll
  return (
    <div ref={barRef} style={overflows ? STRIP : STRIP_OFF} aria-hidden="true" tabIndex={-1}>
      <div style={{ width: inner, height: 1 }} />
    </div>
  );
}

/** A horizontally scrolling box with the strip above it: wrap a wide table in this in place of a plain div. */
export function ScrollBox({ className, children }: { className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <>
      <TopScrollbar target={ref} />
      <div ref={ref} className={className}>{children}</div>
    </>
  );
}
