'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, TrendingUp, History, FlaskConical, Settings, BarChart2 } from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/mock-trading', label: 'Mock Trading', icon: BarChart2, badge: 'LIVE' },
  { href: '/strategies', label: 'Strategies', icon: TrendingUp },
  { href: '/trades', label: 'Trade History', icon: History },
  { href: '/backtest', label: 'Backtest', icon: FlaskConical },
  { href: '/settings', label: 'Settings', icon: Settings },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="hidden lg:flex flex-col w-60 min-h-screen bg-surface border-r border-border fixed left-0 top-0 z-40">
      {/* Logo */}
      <div className="px-5 py-6 border-b border-border">
        <div className="text-text-primary font-semibold text-sm leading-tight">
          NIFTY-PILOT
          <br />
          <span className="text-primary font-bold text-base tracking-tight">SOVEREIGN</span>
        </div>
        <span className="mt-2 inline-block bg-neutral-yellow/15 text-neutral-yellow text-xs font-medium px-2 py-0.5 rounded-full">
          PAPER TRADING
        </span>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map(({ href, label, icon: Icon, badge }) => {
          const active = pathname === href || (href !== '/' && pathname.startsWith(href))
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-all duration-150',
                active
                  ? 'bg-primary/15 text-primary'
                  : 'text-text-secondary hover:bg-surface-elevated hover:text-text-primary'
              )}
            >
              <Icon size={18} className="shrink-0" />
              <span className="flex-1">{label}</span>
              {badge && (
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-green-500/20 text-green-400 leading-none">
                  {badge}
                </span>
              )}
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-border">
        <p className="text-text-muted text-xs">Engine v1.0.0</p>
        <p className="text-text-muted text-xs">Go 1.25 · 29 Strategies</p>
      </div>
    </aside>
  )
}
