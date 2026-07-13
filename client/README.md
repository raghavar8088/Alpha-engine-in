# NIFTY-PILOT SOVEREIGN — Frontend Dashboard

Production-grade trading dashboard for the NIFTY-PILOT SOVEREIGN algorithmic engine.
Hybrid of Google Material Design 3 and Groww dark trading UI.

## Quick Start

```bash
cd client
npm install
npm run dev        # → http://localhost:3000
```

The Go engine must be running on `http://localhost:8090` first:
```bash
cd NIFTY-PILOT-SOVEREIGN/engine
go run cmd/niftypilot/main.go
```

## Build

```bash
npm run build      # Production build
npm run type-check # TypeScript strict check (must be 0 errors)
npm run lint       # ESLint check
```

## Pages

| Route | Description |
|-------|-------------|
| `/` | Dashboard — equity cards, equity curve, daily P&L, open positions |
| `/strategies` | Strategy Leaderboard — all 29 strategies, sortable/filterable |
| `/trades` | Trade History — full trade log with modal breakdown |
| `/backtest` | Backtest Results — walk-forward framework (run backtest first) |
| `/settings` | Engine connection, kill switch, regulatory flags |

## Architecture

```
client/
├── app/                        # Next.js 15 App Router pages
│   ├── api/proxy/[...path]/    # Proxy → Go engine on port 8090
│   ├── layout.tsx              # Root layout (fonts, providers)
│   ├── page.tsx                # Dashboard (/)
│   ├── strategies/page.tsx     # Strategy leaderboard
│   ├── trades/page.tsx         # Trade history
│   ├── backtest/page.tsx       # Backtest results
│   └── settings/page.tsx       # Settings + kill switch
├── components/
│   ├── layout/                 # Sidebar, Header, MobileNav
│   ├── dashboard/              # EquityCard, Charts, Positions table
│   ├── strategies/             # Leaderboard, filters
│   ├── trades/                 # Trades table, TradeModal
│   ├── risk/                   # KillSwitchBanner, MarginBar
│   └── ui/                     # Skeleton, Badge, Card
├── hooks/                      # TanStack Query hooks (polling)
├── lib/                        # types, constants, formatters, api client
└── store/                      # Zustand global state
```

## API Polling

| Endpoint | Interval | Purpose |
|----------|----------|---------|
| `/health` | 5s | Market status badge |
| `/api/market` | 3s | Nifty spot, VIX, regime |
| `/api/equity` | 5s | Capital, margin, P&L |
| `/api/positions` | 5s | Open positions |
| `/api/trades` | 10s | Full trade history |
| `/api/strategies` | 10s | Per-strategy stats |

## Design System

| Token | Value | Usage |
|-------|-------|-------|
| `#0B0E11` | Background | Page background |
| `#161B22` | Surface | Card backgrounds |
| `#1C2128` | Surface Elevated | Modals, dropdowns |
| `#30363D` | Border | Card borders |
| `#4285F4` | Primary | Buttons, active states |
| `#00C087` | Profit Green | Positive P&L |
| `#FF5733` | Loss Red | Negative P&L |
| `#F5A623` | Neutral Yellow | Warnings, EventRisk |

## Currency Formatting

All INR values use the Indian number system:
- ₹1,00,00,000 (not ₹10,000,000)
- ₹45,67,890
- ₹1.2Cr (compact)
- ₹45L (compact)

## Timestamps

All timestamps are displayed in IST (UTC+5:30). The engine sends UTC ISO strings;
the `formatIST()` formatter converts them. UTC is never shown in the UI.

## Known Limitations

1. **Kill switch backend** — The kill switch UI is fully built but the Go engine does
   not yet expose `/api/kill-switch` endpoints. Clicking activate shows a toast.

2. **Backtest page** — Shows a placeholder until `go run ... --backtest` is executed
   and results written to `backtest_results/`.

3. **Synthetic data watermark** — A "SYNTHETIC DATA" badge appears on all price displays
   because the live AngelOne feed is not yet wired in the engine.

4. **WebSocket not used** — All updates are via polling (TanStack Query). WebSocket
   is planned as a future enhancement for sub-second price updates.

5. **In-memory engine** — The Go engine stores all trades in memory. A restart loses
   trade history; the frontend will show an empty state until new trades come in.

## Future Enhancements

- WebSocket connection for real-time tick data
- Export trades to CSV
- Grafana dashboard provisioning files
- Dark/light theme toggle
- Mobile PWA manifest
