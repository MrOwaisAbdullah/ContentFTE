import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ContentFTE Console",
  description: "Internal operator console for the ContentFTE engine",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
