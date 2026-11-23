"use client";

// The desk's OWN switch (POST /api/premium-intraday/control). It is not a Main Control switch: Main Control's
// switch in the shared page header would match /premium-strategies/* and show the Premium Strategies desk's switch
// here, so this page draws its own header and this switch instead.
import { useState } from "react";
import { apiFetch } from "../../../lib/api";
import { API, ago } from "./desk";

export default function DeskSwitch({ status, error, onChange }: { status: any; error?: string | null; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!status && error) {
    return <div className="pis-switch pis-muted">The desk is not reachable: its server part is not deployed yet, or the backend is restarting.</div>;
  }
  if (!status) return <div className="pis-switch pis-muted">Reading the desk…</div>;
  if (status.configured === false) {
    return <div className="pis-switch pis-muted">Desk not deployed on the server yet (no database configured).</div>;
  }
  const enabled = status.control?.enabled !== false;
  const w = status.worker || {};
  const flip = async () => {
    const next = !enabled;
    const msg = next
      ? "Switch the Premium Intraday desk ON?\n\nIt resumes its morning scans and paper entries from the next session."
      : "Switch the Premium Intraday desk OFF?\n\nNew scans and new paper entries stop now. Paper positions already open " +
        "keep being managed to their exits (stops, targets, the 15:05 square-off). Nothing else in the app is affected.";
    if (!window.confirm(msg)) return;
    setBusy(true);
    setErr(null);
    try {
      await apiFetch(`${API}/control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next, reason: "page switch" }),
      });
      onChange();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not change the switch");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="pis-switch">
      <div>
        <div className="pis-switch-state">
          <span className={`pis-dot ${enabled ? "on" : "off"}`} />
          {enabled ? "ON" : "OFF"} · {w.state || "worker not reporting"}
        </div>
        <div className="pis-muted pis-small">
          Worker {w.t ? `seen ${ago(w.t)}` : "not seen"}
          {w.rss_mb ? ` · ${w.rss_mb} MB` : ""}
          {w.open_positions ? ` · ${w.open_positions} open` : ""}
        </div>
        {err && <div className="pis-err pis-small">{err}</div>}
      </div>
      <button className="pis-btn" onClick={flip} disabled={busy}>
        {busy ? "Saving…" : enabled ? "Switch OFF" : "Switch ON"}
      </button>
    </div>
  );
}
