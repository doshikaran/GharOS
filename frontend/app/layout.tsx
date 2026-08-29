import type { Metadata } from "next";
import { Fraunces, Instrument_Serif, Inter } from "next/font/google";
import { ThemeProvider } from "next-themes";
import "./globals.css";

const fraunces = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  style: ["normal", "italic"],
});

const inter = Inter({
  variable: "--font-body",
  subsets: ["latin"],
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
    "GharOS — an autonomous household operating system: a ledger and archive that happens to think.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${inter.variable} ${instrumentSerif.variable} h-full`}
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
