import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { SwrProvider } from "@/components/swr-provider";
import { ToastProvider } from "@/components/ui/toast";

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
  title: "Photos",
  description: "Find and share school event photos with the students in them.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        <SwrProvider>
          <ToastProvider>{children}</ToastProvider>
        </SwrProvider>
      </body>
    </html>
  );
}
