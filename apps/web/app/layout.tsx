import type { Metadata } from "next";
import { Chakra_Petch, Geist, Geist_Mono } from "next/font/google";

import { Nav } from "@/components/nav";
import { StatusBar } from "@/components/status-bar";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Squared, engineered display face for headings and big numerals -- the
// "machined" counterpart to Geist's neutral body text.
const display = Chakra_Petch({
  variable: "--font-chakra",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
});

export const metadata: Metadata = {
  title: "FIN-SCOPE",
  description: "Financial Intelligence, Simulation & Controlled Decision Engine",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${display.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Nav />
        <div className="flex-1">{children}</div>
        <StatusBar />
      </body>
    </html>
  );
}
