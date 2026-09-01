import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "FIN-SCOPE",
  description: "Financial Intelligence, Simulation & Controlled Decision Engine",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <nav className="border-b border-neutral-200 px-6 py-3 flex gap-5 text-sm">
          <Link href="/" className="font-medium">
            FIN-SCOPE
          </Link>
          <Link href="/merchants" className="text-neutral-600 hover:text-neutral-900">
            Merchants
          </Link>
          <Link href="/events" className="text-neutral-600 hover:text-neutral-900">
            Events
          </Link>
        </nav>
        {children}
      </body>
    </html>
  );
}
