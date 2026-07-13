'use client'
import { useState } from 'react'
import { Header } from '@/components/layout/Header'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { REGULATORY_FLAGS } from '@/lib/constants'
import { useAppStore } from '@/store/useAppStore'
import { AlertTriangle, CheckCircle2, XCircle, Copy } from 'lucide-react'

function ConnectionTest() {
  const { engineUrl, setEngineUrl } = useAppStore()
  const [status, setStatus] = useState<'idle' | 'testing' | 'ok' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  async function test() {
    setStatus('testing')
    setErrorMsg('')
    try {
      const res = await fetch('/api/proxy/health')
      if (res.ok) {
        const data = await res.json() as { status: string }
        setStatus('ok')
        setErrorMsg(data.status)
      } else {
        setStatus('error')
        setErrorMsg(`HTTP ${res.status}`)
      }
    } catch (e) {
      setStatus('error')
      setErrorMsg(e instanceof Error ? e.message : 'Unreachable')
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="text-text-secondary text-sm block mb-2">Engine URL</label>
        <div className="flex gap-2">
          <input
            value={engineUrl}
            onChange={(e) => setEngineUrl(e.target.value)}
            className="flex-1 bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary text-sm font-mono focus:outline-none focus:border-primary"
          />
          <button
            onClick={test}
            disabled={status === 'testing'}
            className="px-4 py-2 bg-primary text-white rounded text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {status === 'testing' ? 'Testing...' : 'Test Connection'}
          </button>
        </div>
      </div>
      {status !== 'idle' && (
        <div className={`flex items-center gap-2 text-sm ${status === 'ok' ? 'text-profit-green' : 'text-loss-red'}`}>
          {status === 'ok' ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
          <span>{status === 'ok' ? `Connected — Engine status: ${errorMsg}` : `Error: ${errorMsg}`}</span>
        </div>
      )}
    </div>
  )
}

function KillSwitchPanel() {
  const { killSwitchActive, setKillSwitchActive } = useAppStore()
  const [confirm, setConfirm] = useState('')
  const [toast, setToast] = useState('')

  function activate() {
    if (confirm !== 'CONFIRM') {
      setToast('Type "CONFIRM" to activate the kill switch')
      return
    }
    setToast('⚠ Backend endpoint not yet implemented — kill switch UI is ready but the Go engine does not expose a /api/kill-switch endpoint yet.')
    setKillSwitchActive(true)
    setConfirm('')
  }

  function deactivate() {
    setToast('⚠ Backend endpoint not yet implemented — deactivation UI ready.')
    setKillSwitchActive(false)
  }

  return (
    <div className="border border-loss-red/30 rounded-lg p-4 space-y-4 bg-loss-red/5">
      <div className="flex items-center gap-2 text-loss-red">
        <AlertTriangle size={18} />
        <h3 className="font-semibold">Kill Switch Control</h3>
      </div>
      <p className="text-text-secondary text-sm">
        Activating the kill switch halts ALL trading immediately. All open positions remain open
        until manually closed through the broker interface.
      </p>
      {!killSwitchActive ? (
        <div className="space-y-3">
          <div>
            <label className="text-text-secondary text-sm block mb-1">
              Type <span className="font-mono text-loss-red">CONFIRM</span> to activate
            </label>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="CONFIRM"
              className="bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary text-sm font-mono focus:outline-none focus:border-loss-red w-40"
            />
          </div>
          <button
            onClick={activate}
            className="px-4 py-2 bg-loss-red text-white rounded text-sm font-semibold hover:bg-loss-red/90 transition-colors"
          >
            ACTIVATE KILL SWITCH
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-loss-red font-semibold">
            <div className="w-2 h-2 rounded-full bg-loss-red animate-pulse" />
            KILL SWITCH ACTIVE — All trading halted
          </div>
          <button
            onClick={deactivate}
            className="px-4 py-2 border border-profit-green text-profit-green rounded text-sm font-semibold hover:bg-profit-green/10 transition-colors"
          >
            DEACTIVATE KILL SWITCH
          </button>
        </div>
      )}
      {toast && (
        <div className="bg-neutral-yellow/10 border border-neutral-yellow/30 rounded p-3 text-neutral-yellow text-xs">
          {toast}
        </div>
      )}
    </div>
  )
}

export default function SettingsPage() {
  const { pollingInterval, setPollingInterval, compactMode, setCompactMode, defaultChartRange, setDefaultChartRange } = useAppStore()

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text).catch(() => {})
  }

  return (
    <div>
      <Header title="Settings" />
      <div className="p-6 space-y-6 max-w-2xl">
        {/* Engine Connection */}
        <Card>
          <CardHeader><CardTitle>Engine Connection</CardTitle></CardHeader>
          <CardContent>
            <ConnectionTest />
          </CardContent>
        </Card>

        {/* Paper trading status */}
        <Card>
          <CardHeader><CardTitle>Trading Mode</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-3">
              <span className="inline-flex items-center gap-1.5 bg-neutral-yellow/15 text-neutral-yellow border border-neutral-yellow/30 px-3 py-1.5 rounded-full text-sm font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-neutral-yellow" />
                PAPER TRADING ACTIVE
              </span>
            </div>
            <p className="text-text-muted text-sm">
              Capital: <span className="font-mono text-text-primary">₹1,00,00,000</span>
            </p>
            <p className="text-text-secondary text-xs border border-border/50 rounded p-2 bg-surface-elevated">
              ⚠ Live trading is NOT wired in this build. Both Angel One and Dhan adapters exist
              but require API credentials in the engine&apos;s <code className="font-mono">.env</code> file.
            </p>
          </CardContent>
        </Card>

        {/* Display Preferences */}
        <Card>
          <CardHeader><CardTitle>Display Preferences</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="text-text-secondary text-sm block mb-2">Theme</label>
              <span className="text-text-muted text-sm">Dark mode (locked — matches Groww dark UI)</span>
            </div>
            <div>
              <label className="text-text-secondary text-sm block mb-2">Default Chart Range</label>
              <div className="flex gap-2">
                {(['1W', '1M', '3M', 'ALL'] as const).map((r) => (
                  <button
                    key={r}
                    onClick={() => setDefaultChartRange(r)}
                    className={`px-3 py-1.5 text-xs rounded font-medium transition-colors ${
                      defaultChartRange === r
                        ? 'bg-primary text-white'
                        : 'bg-surface-elevated text-text-secondary hover:text-text-primary'
                    }`}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-text-secondary text-sm block mb-2">Polling Interval</label>
              <select
                value={pollingInterval}
                onChange={(e) => setPollingInterval(Number(e.target.value))}
                className="text-sm bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary focus:outline-none focus:border-primary"
              >
                <option value={3000}>3 seconds (fastest)</option>
                <option value={5000}>5 seconds (default)</option>
                <option value={10000}>10 seconds (low bandwidth)</option>
              </select>
            </div>
            <div className="flex items-center gap-3">
              <label className="text-text-secondary text-sm">Compact Mode</label>
              <button
                onClick={() => setCompactMode(!compactMode)}
                className={`w-10 h-5 rounded-full transition-colors ${compactMode ? 'bg-primary' : 'bg-surface-elevated border border-border'}`}
              >
                <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform ${compactMode ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>
          </CardContent>
        </Card>

        {/* Kill switch */}
        <Card id="kill-switch">
          <CardHeader><CardTitle>Kill Switch</CardTitle></CardHeader>
          <CardContent>
            <KillSwitchPanel />
          </CardContent>
        </Card>

        {/* Regulatory Flags */}
        <Card>
          <CardHeader><CardTitle>Regulatory Flags</CardTitle></CardHeader>
          <CardContent>
            <p className="text-text-muted text-xs mb-4">
              These values require periodic verification via NSE/SEBI circulars.
              Verify before live trading.
            </p>
            <div className="space-y-3">
              {REGULATORY_FLAGS.map((flag) => (
                <div key={flag.name} className="flex items-start justify-between gap-4 p-3 bg-surface-elevated rounded-lg">
                  <div className="flex-1 min-w-0">
                    <p className="text-text-primary text-sm font-medium">{flag.name}</p>
                    <p className="text-profit-green font-mono text-sm">{flag.value}</p>
                    <p className="text-text-muted text-xs mt-0.5">{flag.note}</p>
                    <p className="text-primary text-xs mt-0.5">{flag.circular}</p>
                  </div>
                  <button
                    onClick={() => copyToClipboard(flag.circular)}
                    className="shrink-0 p-1.5 text-text-muted hover:text-text-primary transition-colors"
                    title="Copy circular reference"
                  >
                    <Copy size={14} />
                  </button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
