import type { Metadata } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'
import { Sidebar } from '@/components/layout/Sidebar'
import { MobileNav } from '@/components/layout/MobileNav'
import { KillSwitchBanner } from '@/components/risk/KillSwitchBanner'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'NIFTY-PILOT SOVEREIGN — Trading Dashboard',
  description: 'Institutional-grade algorithmic paper trading dashboard for NSE index derivatives',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} ${jetbrainsMono.variable} bg-background text-text-primary antialiased`}>
        <Providers>
          <KillSwitchBanner />
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex-1 lg:ml-60 flex flex-col min-h-screen">
              <main className="flex-1 pb-20 lg:pb-0">
                {children}
              </main>
            </div>
          </div>
          <MobileNav />
        </Providers>
      </body>
    </html>
  )
}
