"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useOrg } from "./use-org";
import { getToken } from "@/lib/auth";
import type { TIPipelineStatus } from "@/lib/ti-types";

export function usePipelineStatus(packId: string, polling = false) {
  const { orgFetch, currentOrgId } = useOrg();
  const [pipeline, setPipeline] = useState<TIPipelineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await orgFetch<TIPipelineStatus>(
        `/api/v1/apps/title-intelligence/packs/${packId}/pipeline`
      );
      setPipeline(data);
      setLoading(false);

      // Stop polling if completed or failed
      if (
        data.status === "completed" ||
        data.status === "failed"
      ) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      }
    } catch {
      setLoading(false);
    }
  }, [orgFetch, packId]);

  // SSE streaming for real-time updates during processing
  useEffect(() => {
    if (!polling || !currentOrgId) return;

    const token = getToken();
    if (!token) {
      // Fall back to polling if no token for SSE
      fetchStatus();
      intervalRef.current = setInterval(fetchStatus, 3000);
      return () => {
        if (intervalRef.current) clearInterval(intervalRef.current);
      };
    }

    // Use fetch-based SSE to pass auth headers (EventSource can't set headers)
    const abortController = new AbortController();
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";
    const url = `${apiUrl}/api/v1/apps/title-intelligence/packs/${packId}/pipeline/stream`;
    let active = true;

    async function connectSSE() {
      try {
        const response = await fetch(url, {
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Org-Id": currentOrgId!,
          },
          signal: abortController.signal,
        });

        if (!response.ok || !response.body) {
          // Fall back to polling
          if (active) {
            intervalRef.current = setInterval(fetchStatus, 3000);
          }
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done || !active) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6)) as TIPipelineStatus;
                setPipeline(data);
                setLoading(false);
              } catch {
                // Ignore parse errors
              }
            }
          }
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        // Fall back to polling on SSE failure
        if (active && !intervalRef.current) {
          intervalRef.current = setInterval(fetchStatus, 3000);
        }
      }
    }

    // Initial fetch for immediate data, then connect SSE
    fetchStatus();
    connectSSE();

    return () => {
      active = false;
      abortController.abort();
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [polling, packId, currentOrgId, fetchStatus]);

  // Non-polling mode: just fetch once
  useEffect(() => {
    if (!polling) {
      fetchStatus();
    }
  }, [polling, fetchStatus]);

  return { pipeline, loading, refetch: fetchStatus };
}
