import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { SessionProvider } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flu",
  description: "Verified short-form views from creators the platform trains. Brands pay per verified view; creators earn from their first post.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#edeee9" },
    { media: "(prefers-color-scheme: dark)", color: "#10120d" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className={GeistSans.variable}>
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
