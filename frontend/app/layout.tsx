import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, Instrument_Sans, Instrument_Serif } from "next/font/google";
import { ThemeProvider } from "next-themes";
import "./globals.css";

const fraunces = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  style: ["normal", "italic"],
});

// 2026-08-29 private-bank pass: body face is Instrument Sans (was Inter),
// bound to the SAME --font-body variable so no component changes.
const instrumentSans = Instrument_Sans({
  variable: "--font-body",
  subsets: ["latin"],
});

// 2026-08-29 private-bank pass: IBM Plex Mono for data moments — ₹
// amounts, dates, IDs, proof lines — bound to --font-data-family, which
// tokens.css's --font-data falls back through (same pattern as
// --font-accent-family below). Use sites pair it with
// `font-variant-numeric: tabular-nums` so rupee columns align.
const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-data-family",
  subsets: ["latin"],
  weight: ["400", "500"],
});

// 2026-08-29 royal redesign (docs/design/2026-08-29-redesign-brief.md):
// the accent serif for hero/pull-quote/landing-page storytelling moments
// only — bound to --font-accent-family, which tokens.css's --font-accent
// falls back to. Instrument Serif only ships weight 400, normal + italic.
const instrumentSerif = Instrument_Serif({
  variable: "--font-accent-family",
  subsets: ["latin"],
  weight: ["400"],
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "GharOS",
  description:
    "GharOS, an autonomous household operating system: a ledger and archive that happens to think.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${instrumentSans.variable} ${ibmPlexMono.variable} ${instrumentSerif.variable} h-full`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col antialiased">
        <ThemeProvider attribute="data-theme" defaultTheme="system" enableSystem>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
