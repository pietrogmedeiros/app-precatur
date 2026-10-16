import type { Metadata } from "next";
import "./globals.css";
import { SCRIPT_TEMA } from "@/lib/tema";

export const metadata: Metadata = {
  title: "App Precatur",
  description: "Painel de vendas — dados agregados e individuais",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: o script abaixo muda a classe do <html> antes
    // do React hidratar — a diferença é intencional.
    <html lang="pt-BR" suppressHydrationWarning>
      <body className="min-h-screen bg-background antialiased">
        <script dangerouslySetInnerHTML={{ __html: SCRIPT_TEMA }} />
        {children}
      </body>
    </html>
  );
}
