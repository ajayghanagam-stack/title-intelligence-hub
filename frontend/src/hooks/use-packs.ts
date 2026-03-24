"use client";

import { useState, useEffect, useCallback } from "react";
import { useOrg } from "./use-org";
import type { Pack } from "@/lib/ti-types";

export function usePacks() {
  const { orgFetch } = useOrg();
  const [packs, setPacks] = useState<Pack[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPacks = useCallback(async () => {
    try {
      setLoading(true);
      const data = await orgFetch<Pack[]>("/api/v1/apps/title-intelligence/packs");
      setPacks(data);
    } catch {
      setPacks([]);
    } finally {
      setLoading(false);
    }
  }, [orgFetch]);

  useEffect(() => {
    fetchPacks();
  }, [fetchPacks]);

  return { packs, loading, refetch: fetchPacks };
}
