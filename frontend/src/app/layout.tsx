import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Clinical GraphRAG Pro",
  description:
    "Enterprise Clinical AI Platform — Intelligent medical document analysis powered by GraphRAG",
  keywords: ["clinical", "AI", "GraphRAG", "medical", "RAG"],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={`${inter.variable} ${jetbrains.variable} antialiased`} suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
