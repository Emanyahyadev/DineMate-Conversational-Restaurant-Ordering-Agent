import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AuthProvider } from "@/components/AuthProvider";
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
  title: "DineMate - Your AI restaurant assistant",
  description:
    "Ask about the menu, place an order, and check where it is, all in one conversation.",
  openGraph: {
    title: "DineMate",
    description: "Your AI restaurant assistant.",
    images: ["/dinemate-logo.png"],
  },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  // Lets the composer sit above the on-screen keyboard instead of behind it.
  interactiveWidget: "resizes-content" as const,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="font-sans min-h-full">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
