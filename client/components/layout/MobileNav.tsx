'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, TrendingUp, History, FlaskConical, Settings, BarChart2 } from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/mock-trading', label: 'Mock', icon: BarChart2 },
  { href: '/strategies', label: 'Strategies', icon: TrendingUp },
  { href: '/trades', label: 'Trades', icon: History },
  { href: '/backtest', label: 'Backtest', icon: FlaskConical },
  { href: '/settings', label: 'Settings', icon: Settings },
]

export function MobileNav() {
  const pathname = usePathname()

  return (
    <nav className="lg:hidden fixed bottom-0 left-0 right-0 z-50 bg-surface border-t border-border px-2 py-2">
      <div className="flex justify-around">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex flex-col items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
                active ? 'text-primary' : 'text-text-muted hover:text-text-secondary'
              )}
            >
              <Icon size={20} />
              <span>{label}</span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
