import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "App Precatur",
  description: "Painel de vendas — dados agregados e individuais",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-background antialiased">{children}</body>
    </html>
  );
}
