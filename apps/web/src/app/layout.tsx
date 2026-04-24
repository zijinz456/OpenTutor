import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { TopBar } from "@/app/_components/top-bar";
import { LocaleProvider } from "@/lib/i18n-context";
import { ConnectionStatus } from "@/components/shared/connection-status";
import { PanicOverlay } from "@/components/panic/PanicOverlay";
import { PomodoroTimer } from "@/components/pomodoro/PomodoroTimer";
import "./globals.css";

// Space Grotesk (existing) — display font for large headings.
const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-space-grotesk",
});

// Inter — new primary UI typeface per ТЗ §8. Chosen for tabular-nums
// in timers, progress %, streak counts. Does NOT replace the existing
// --font-geist-sans yet; coexists as --font-inter so new THM-styled
// components can opt in via Tailwind's `font-inter` utility.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

// JetBrains Mono — new monospace typeface per ТЗ §8. For code panes,
// level chips (0x1 [ADEPT]), and path fragments.
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0B0F14" },
    { media: "(prefers-color-scheme: dark)", color: "#0B0F14" },
  ],
};

export const metadata: Metadata = {
  title: "LearnDopamine — Personalized Learning Agent",
  description: "Mission-first learning with AI notes, review rituals, and calmer study flows.",
  applicationName: "LearnDopamine",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "LearnDopamine",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/icon-192.png", sizes: "192x192" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${spaceGrotesk.variable} ${inter.variable} ${jetbrainsMono.variable}`}
    >
      <body className="antialiased">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-[100] focus:rounded-lg focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-foreground focus:shadow-lg focus:ring-2 focus:ring-ring"
        >
          Skip to content
        </a>
        <ConnectionStatus />
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <LocaleProvider>
            <TooltipProvider>
              <PanicOverlay>
                <TopBar />
                <main id="main-content" className="pt-12">
                  {children}
                </main>
                <PomodoroTimer />
              </PanicOverlay>
            </TooltipProvider>
            <Toaster />
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
