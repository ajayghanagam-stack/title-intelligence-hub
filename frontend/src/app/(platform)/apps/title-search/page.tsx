"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Search, Plus } from "lucide-react";
import { useOrg } from "@/hooks/use-org";
import { listOrders } from "@/lib/title-search/api";
import { OrderList } from "@/components/title-search/order-list";
import type { TSOrderListItem } from "@/lib/title-search/types";

export default function TitleSearchPage() {
  const { currentOrgId } = useOrg();
  const [orders, setOrders] = useState<TSOrderListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("");

  useEffect(() => {
    if (!currentOrgId) return;
    setLoading(true);
    listOrders(currentOrgId, statusFilter || undefined)
      .then(setOrders)
      .catch(() => setOrders([]))
      .finally(() => setLoading(false));
  }, [currentOrgId, statusFilter]);

  return (
    <div className="space-y-8" data-testid="title-search-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500/20 to-cyan-500/20 ring-1 ring-blue-500/10">
            <Search className="h-6 w-6 text-blue-700" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              Title Search & Abstracting
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Automated county record searches and chain-of-title analysis
            </p>
          </div>
        </div>
        <Link href="/apps/title-search/orders/new" className="btn-cta gap-2" data-testid="new-order-button">
          <Plus className="h-4 w-4" />
          New Order
        </Link>
      </div>

      <div className="flex gap-2" data-testid="status-filters">
        {[
          { value: "", label: "All" },
          { value: "pending", label: "Pending" },
          { value: "processing", label: "Processing" },
          { value: "review_required", label: "Review Required" },
          { value: "completed", label: "Completed" },
          { value: "failed", label: "Failed" },
        ].map((s) => (
          <button
            key={s.value}
            onClick={() => setStatusFilter(s.value)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              statusFilter === s.value
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            }`}
            data-testid={`filter-${s.value || "all"}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading orders...</p>
        </div>
      ) : (
        <OrderList
          orders={orders}
          onOrderDeleted={(id) => setOrders((prev) => prev.filter((o) => o.id !== id))}
        />
      )}
    </div>
  );
}
