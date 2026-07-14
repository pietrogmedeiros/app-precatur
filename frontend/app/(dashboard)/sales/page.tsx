"use client";

import { useEffect, useRef, useState } from "react";
import Script from "next/script";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

// The Metabase embed ships a custom element <metabase-dashboard>. Declare it so
// TSX accepts it and its embedding attributes.
declare global {
  namespace JSX {
    interface IntrinsicElements {
      "metabase-dashboard": React.DetailedHTMLProps<
        React.HTMLAttributes<HTMLElement> & {
          token?: string;
          "with-title"?: string;
          "with-downloads"?: string;
        },
        HTMLElement
      >;
    }
  }
  interface Window {
    metabaseConfig?: Record<string, unknown>;
  }
}

// Refetch a little before the backend's 10-minute token expiry so the dashboard
// never goes stale while the tab is open.
const REFRESH_MS = 8 * 60 * 1000;

export default function DashboardPage() {
  const [token, setToken] = useState<string | null>(null);
  const [instanceUrl, setInstanceUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const { token, instanceUrl } = await api.metabaseToken();
        if (!active) return;
        // metabaseConfig MUST exist before embed.js runs; embed.js is rendered
        // only once instanceUrl is set below, so this always lands first.
        window.metabaseConfig = {
          theme: { preset: "light" },
          isGuest: true,
          instanceUrl,
        };
        setInstanceUrl(instanceUrl);
        setToken(token);
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      }
    }

    load();
    timer.current = setInterval(load, REFRESH_MS);
    return () => {
      active = false;
      if (timer.current) clearInterval(timer.current);
    };
  }, []);

  return (
    <div className="flex min-h-[calc(100vh-4rem)] flex-col">
      {instanceUrl ? (
        <Script src={`${instanceUrl}/app/embed.js`} strategy="afterInteractive" />
      ) : null}

      {error ? (
        <div className="p-4 sm:p-6 md:p-8">
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              Não foi possível carregar o dashboard: {error}. Verifique se a API está no ar e se{" "}
              <code>METABASE_SECRET_KEY</code> está configurada no servidor.
            </CardContent>
          </Card>
        </div>
      ) : token ? (
        <metabase-dashboard
          token={token}
          with-title="true"
          with-downloads="true"
          className="flex-1"
          style={{ display: "block", width: "100%", height: "100%" }}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted border-t-primary" />
        </div>
      )}
    </div>
  );
}
