import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

// Design tokens in globals.css assume these CSS variables (plan §3).
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap" });
const jakarta = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-jakarta", display: "swap" });

export const metadata: Metadata = {
  title: "ContentFTE - Autonomous Fleet Control Operator Console",
  description: "Internal operator console for the ContentFTE autonomous publishing engine",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`dark ${inter.variable} ${jetbrains.variable} ${jakarta.variable}`}>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("theme");var light=t==="light"||(t==="system"&&!window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",!light);}catch(e){}})();`,
          }}
        />
      </head>
      <body>
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:text-sm focus:text-ink focus:shadow-lg"
    >
      Skip to main content
    </a>
    {children}
  </body>
    </html>
  );
}
