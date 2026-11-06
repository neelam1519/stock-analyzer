import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Suspense } from "react";

import { Providers } from "@/components/providers";
import { SidebarNav, SidebarNavFallback } from "@/components/sidebar-nav";
import { TopBar } from "@/components/top-bar";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Stock Analyzer",
  description: "Swing-trading research and signals for NSE equities",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full font-sans">
        <Providers>
          <div className="flex min-h-screen flex-col md:flex-row">
            <aside className="border-b border-line bg-surface px-4 py-3 md:w-56 md:shrink-0 md:border-b-0 md:border-r md:py-6">
              <div className="mb-3 px-3 font-mono text-sm font-semibold tracking-tight md:mb-6">stock·analyzer</div>
              <Suspense fallback={<SidebarNavFallback />}>
                <SidebarNav />
              </Suspense>
            </aside>
            <div className="flex min-w-0 flex-1 flex-col">
              <TopBar />
              <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
