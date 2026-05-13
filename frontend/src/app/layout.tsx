import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
// Logikality brand guideline §2 — primary typeface is Mona Sans
// (close visual analogue to Proxima Nova, OFL-licensed). Shipped via
// the @fontsource-variable package so the WOFF2 is bundled into the
// Next build and served same-origin — no Adobe Fonts / Typekit /
// Google Fonts CDN request. The CSS file registers the `Mona Sans`
// family which is referenced by the Tailwind `font-sans` token
// (see `tailwind.config.ts`). Arial/Helvetica/sans-serif remain the
// documented fallback chain.
import "@fontsource-variable/mona-sans";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "Logikality - Title Intelligence Hub",
  description: "Decision-ready AI for mortgage operations",
  icons: {
    icon: "/logikality_logo.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body
        className={`${GeistMono.variable} font-sans antialiased`}
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
