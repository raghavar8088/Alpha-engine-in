"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const GROUPS: { label: string; links: { href: string; label: string; icon: React.ReactNode }[] }[] = [
  {
    label: "Trading",
    links: [
      {
        href: "/dashboard",
        label: "Market Data",
        icon: <path d="M3 17l6-6 4 4 8-8M15 6h6v6" />,
      },
      {
        href: "/chart",
        label: "Chart",
        icon: (
          <>
            <rect x="4" y="10" width="3" height="10" />
            <rect x="10.5" y="5" width="3" height="15" />
            <rect x="17" y="13" width="3" height="7" />
          </>
        ),
      },
      {
        href: "/portfolio",
        label: "Portfolio",
        icon: (
          <>
            <rect x="3" y="3" width="7" height="9" rx="1" />
            <rect x="14" y="3" width="7" height="5" rx="1" />
            <rect x="14" y="12" width="7" height="9" rx="1" />
            <rect x="3" y="16" width="7" height="5" rx="1" />
          </>
        ),
      },
      {
        href: "/orders",
        label: "Orders",
        icon: <path d="M4 19h16M7 15l3-4 3 2 4-6" />,
      },
      {
        href: "/trading-calls",
        label: "Trading Calls",
        icon: (
          <>
            <path d="M5 4h10l4 4v12H5V4z" />
            <path d="M15 4v4h4" />
            <path d="M9 13l2 2 4-4" />
          </>
        ),
      },
      {
        href: "/positions",
        label: "Positions",
        icon: (
          <>
            <path d="M4 19V10M10 19V5M16 19v-7M20 19H4" />
          </>
        ),
      },
      {
        href: "/fno-positions",
        label: "F&O Positions",
        icon: (
          <>
            <circle cx="12" cy="12" r="9" />
            <path d="M8 10.5c0-1.4 1.2-2.5 4-2.5s4 1.1 4 2.5-1.4 2-4 2.5-4 1.1-4 2.5 1.2 2.5 4 2.5 4-1.1 4-2.5" />
          </>
        ),
      },
      {
        href: "/watchlist",
        label: "Watchlist",
        icon: (
          <>
            <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
            <circle cx="12" cy="12" r="3" />
          </>
        ),
      },
    ],
  },
  {
    label: "Strategy Lab",
    links: [
      {
        href: "/strategies",
        label: "Strategies",
        icon: (
          <>
            <path d="M12 3l8 4-8 4-8-4 8-4z" />
            <path d="M4 11l8 4 8-4" />
            <path d="M4 15l8 4 8-4" />
          </>
        ),
      },
      {
        href: "/backtesting",
        label: "Backtesting",
        icon: (
          <>
            <path d="M3 3v18h18" />
            <path d="M7 14l3-4 3 2 5-7" />
          </>
        ),
      },
      {
        href: "/stock-research",
        label: "Stock Research",
        icon: (
          <>
            <circle cx="11" cy="11" r="7" />
            <path d="M21 21l-4.3-4.3" />
            <path d="M8 11h6M11 8v6" />
          </>
        ),
      },
      {
        href: "/live",
        label: "Live Engine",
        icon: (
          <>
            <circle cx="12" cy="12" r="3" />
            <path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8" />
          </>
        ),
      },
      {
        href: "/prelive",
        label: "Pre-Live Desk · Buying",
        icon: (
          <>
            <path d="M4 4h16v12H4z" />
            <path d="M4 20h16M8 16v4M16 16v4" />
            <path d="M7 11l3-3 2 2 4-5" />
          </>
        ),
      },
      {
        // Named and iconed to be unmistakable against the buying desk above: the two
        // have opposite risk profiles (bounded loss vs capped gain and a large tail)
        // and must never be confused for one another at a glance.
        href: "/prelive-selling",
        label: "Pre-Live Desk · Selling",
        icon: (
          <>
            <path d="M4 4h16v12H4z" />
            <path d="M4 20h16M8 16v4M16 16v4" />
            <path d="M7 7l3 3 2-2 4 5" />
          </>
        ),
      },
    ],
  },
  {
    label: "Analytics",
    links: [
      {
        href: "/options",
        label: "Options",
        icon: (
          <>
            <circle cx="12" cy="12" r="9" />
            <path d="M9 9c0-1.5 1-2.5 3-2.5s3 1 3 2.5-1 2-3 3v1" />
            <path d="M12 16h.01" />
          </>
        ),
      },
      {
        href: "/risk",
        label: "Risk",
        icon: (
          <>
            <path d="M12 2l9 4v6c0 5-3.8 9-9 10-5.2-1-9-5-9-10V6l9-4z" />
            <path d="M12 8v5M12 16h.01" />
          </>
        ),
      },
      {
        href: "/ai",
        label: "AI Research",
        icon: (
          <>
            <path d="M12 2a5 5 0 015 5c0 1.6-.8 2.7-1.6 3.6-.6.7-1.1 1.2-1.1 2.1v.3H9.7v-.3c0-.9-.5-1.4-1.1-2.1C7.8 9.7 7 8.6 7 7a5 5 0 015-5z" />
            <path d="M9.5 16h5M10 19h4" />
          </>
        ),
      },
    ],
  },
  {
    label: "System",
    links: [
      {
        href: "/settings/broker",
        label: "Broker Settings",
        icon: (
          <>
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 00.34 1.87l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.7 1.7 0 00-1.87-.34 1.7 1.7 0 00-1.04 1.56V21a2 2 0 11-4 0v-.09A1.7 1.7 0 008.5 19.4a1.7 1.7 0 00-1.87.34l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.7 1.7 0 004.6 15a1.7 1.7 0 00-1.56-1.04H3a2 2 0 110-4h.09A1.7 1.7 0 004.6 8.5a1.7 1.7 0 00-.34-1.87l-.06-.06a2 2 0 112.83-2.83l.06.06A1.7 1.7 0 008.5 4.6a1.7 1.7 0 001.04-1.56V3a2 2 0 114 0v.09a1.7 1.7 0 001.04 1.56 1.7 1.7 0 001.87-.34l.06-.06a2 2 0 112.83 2.83l-.06.06A1.7 1.7 0 0019.4 8.5a1.7 1.7 0 001.56 1.04H21a2 2 0 110 4h-.09a1.7 1.7 0 00-1.51 1.46z" />
          </>
        ),
      },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <>
      <button className="menu-btn" aria-label="Open menu" onClick={() => setOpen(true)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <aside className={`sidebar${open ? " open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 17l6-6 4 4 8-8" />
              <path d="M15 6h6v6" />
            </svg>
          </div>
          <div className="brand-name">TradingAI</div>
          <button className="close-btn" aria-label="Close menu" onClick={() => setOpen(false)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
          </button>
        </div>

        <nav>
          {GROUPS.map((group) => (
            <div className="nav-group" key={group.label}>
              <div className="group-label">{group.label}</div>
              {group.links.map((link) => {
                const active = pathname === link.href;
                return (
                  <Link key={link.href} href={link.href} className={`nav-item${active ? " active" : ""}`}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                      {link.icon}
                    </svg>
                    {link.label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <Link href="/settings/broker" className="connect-cta">
          Connect Broker
        </Link>
      </aside>
    </>
  );
}
