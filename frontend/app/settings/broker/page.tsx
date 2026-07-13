"use client";

import { useEffect, useState } from "react";
import { BrokerConnection, connectBroker, fetchBrokerStatus } from "@/lib/api";
import GlassPanel from "@/components/GlassPanel";
import StatusPill from "@/components/StatusPill";
import PageHeader from "@/components/PageHeader";

export default function BrokerSettingsPage() {
  const [accessToken, setAccessToken] = useState("");
  const [connection, setConnection] = useState<BrokerConnection | null>(null);
  const [checkingStatus, setCheckingStatus] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchBrokerStatus()
      .then(setConnection)
      .catch(() => {})
      .finally(() => setCheckingStatus(false));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await connectBroker(accessToken);
      setConnection(result);
      setAccessToken("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to connect broker");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="wrap">
      <PageHeader crumb="Broker Settings" title="Broker Settings" subtitle="Connect your Dhan account to enable live data, orders, and portfolio sync." />

      <GlassPanel style={{ padding: 28 }}>
        <div className="head-row">
          <h2>Dhan</h2>
          {!checkingStatus && (
            <StatusPill label={connection ? "Connected" : "Not connected"} tone={connection ? "gain" : "muted"} pulse={!!connection} />
          )}
        </div>

        <p className="hint">
          Generate an Access Token from{" "}
          <a href="https://developer.dhan.co" target="_blank" rel="noreferrer">
            developer.dhan.co
          </a>{" "}
          (Live Environment &gt; Access Token). Your Client ID is read automatically from the token itself, so
          there&apos;s nothing else to type or paste. The token is encrypted before being stored.
        </p>

        {connection && (
          <div className="connected-box">
            Client ID <strong>{connection.client_id}</strong> · connected {new Date(connection.connected_at).toLocaleString()}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <input
            type="password"
            placeholder="Dhan Access Token"
            value={accessToken}
            onChange={(e) => setAccessToken(e.target.value)}
            autoComplete="off"
            required
          />
          {error && <div className="form-error">{error}</div>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Connecting..." : connection ? "Reconnect" : "Connect"}
          </button>
        </form>
      </GlassPanel>

      <style jsx>{`
        .wrap {
          max-width: 560px;
        }
        .head-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }
        h2 {
          font-family: var(--font-display);
          font-size: 16px;
          margin: 0;
        }
        .hint {
          color: var(--text-muted);
          font-size: 13px;
          line-height: 1.6;
          margin: 0 0 18px;
        }
        .hint a {
          color: var(--accent);
        }
        .connected-box {
          background: var(--gain-dim);
          border: 1px solid rgba(14, 159, 110, 0.22);
          border-radius: 10px;
          padding: 12px 14px;
          font-size: 13px;
          margin-bottom: 18px;
        }
        form {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        input {
          padding: 11px 13px;
          border-radius: 8px;
          border: 1px solid var(--panel-border);
          background: var(--canvas-soft);
          color: var(--text);
          font-size: 13.5px;
        }
        input::placeholder {
          color: var(--text-faint);
        }
        input:focus {
          border-color: var(--accent);
        }
        .form-error {
          color: var(--loss);
          font-size: 13px;
        }
        button {
          padding: 11px;
          border-radius: 8px;
          border: 1px solid var(--accent);
          background: var(--accent-dim);
          color: var(--accent);
          font-weight: 600;
          font-size: 13.5px;
          cursor: pointer;
          transition: background-color 0.15s ease;
        }
        button:hover:not(:disabled) {
          background: var(--accent-hover);
        }
        button:disabled {
          opacity: 0.6;
          cursor: default;
        }
      `}</style>
    </div>
  );
}
