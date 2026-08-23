import { Sora, Manrope, JetBrains_Mono } from "next/font/google";
import Sidebar from "@/components/Sidebar";
import Footer from "@/components/Footer";
import SortableTables from "@/components/SortableTables";
import CommandPalette from "@/components/CommandPalette";
import "./globals.css";

const sora = Sora({ subsets: ["latin"], weight: ["600", "700", "800"], variable: "--font-display" });
const manrope = Manrope({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-ui" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-data" });

export const metadata = {
  title: "TradingAI",
  description: "Live NSE market data dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sora.variable} ${manrope.variable} ${jetbrainsMono.variable}`}>
      <head>
        {/* Applies the saved theme BEFORE first paint. Without this a dark-mode user gets
            a full-white flash on every navigation, because React only reaches the toggle
            after hydration. Deliberately tiny, deliberately blocking, and it must stay in
            sync with the key ThemeToggle writes. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('tradingai-theme');if(t==='dark'||t==='light'){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();`,
          }}
        />
      </head>
      <body style={{ display: "flex" }}>
        <SortableTables />
        {/* One instance for the whole app: ⌘K anywhere. Mounting it per page
            would mean several listeners racing for the same shortcut. */}
        <CommandPalette />
        <Sidebar />
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <main className="app-main" style={{ flex: 1, minWidth: 0, padding: "32px 40px 0", maxWidth: 1320, width: "100%", margin: "0 auto" }}>
            {children}
          </main>
          <div className="app-footer-wrap" style={{ maxWidth: 1320, width: "100%", margin: "0 auto", padding: "0 40px" }}>
            <Footer />
          </div>
        </div>
      </body>
    </html>
  );
}
