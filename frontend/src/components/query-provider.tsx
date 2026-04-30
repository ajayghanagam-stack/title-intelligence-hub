"use client";

import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Single QueryClient per browser tab. Defaults are tuned for our usage:
 *
 * - staleTime 30s — most reads (packages list, package detail, subscriptions)
 *   are fine to serve from cache for 30s while a background revalidate runs.
 *   This is what makes tab switches paint instantly.
 * - gcTime 5min — keep cache around long enough to span typical navigation
 *   patterns without consuming much memory.
 * - retry 1 — auth errors throw immediately; server errors get one retry.
 * - refetchOnWindowFocus false — avoid surprising users with reloads when
 *   they alt-tab back; mutation flows handle their own invalidation.
 */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30 * 1000,
            gcTime: 5 * 60 * 1000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
