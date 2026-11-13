import type { Metadata } from "next";
import { Fira_Code, Fraunces, Work_Sans } from "next/font/google";
import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-fraunces",
  display: "swap",
});

const workSans = Work_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-work-sans",
  display: "swap",
});

const firaCode = Fira_Code({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-fira-code",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Cymbal Retail Malaysia — Executive Data Context Folio",
  description:
    "Side-by-side executive verification comparing ungrounded BigQuery SQL against Google Cloud Knowledge Studio (DevFest Kuala Lumpur 2026).",
};

const THEME_INIT_SCRIPT = `(function () {
  var theme = "light";
  try {
    if (window.localStorage.getItem("theme") === "dark") theme = "dark";
  } catch (e) {}
  document.documentElement.classList.toggle("theme-dark", theme === "dark");
})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${fraunces.variable} ${workSans.variable} ${firaCode.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="bg-surface-0 font-sans text-ink-1">{children}</body>
    </html>
  );
}
