"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Search, Plus } from "lucide-react";
import { useOrg } from "@/hooks/use-org";
import { listOrders } from "@/lib/title-search/api";
import { OrderList } from "@/components/title-search/order-list";
import type { TSOrderListItem } from "@/lib/title-search/types";

const FILTERS = [
  { value: "", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "processing", label: "Processing" },
  { value: "review_required", label: "Review Required" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

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
      {/* Hero Header */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[oklch(0.178_0.010_50)] to-[oklch(0.250_0.015_55)] p-8 text-white">
        {/* Decorative circles */}
        <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-[oklch(0.750_0.170_65/0.15)]" />
        <div className="pointer-events-none absolute -bottom-6 -left-6 h-28 w-28 rounded-full bg-[oklch(0.560_0.230_340/0.10)]" />

        <div className="relative flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/10 ring-1 ring-white/20 backdrop-blur-sm">
              <Search className="h-7 w-7 text-[oklch(0.750_0.170_65)]" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">
                Title Search & Abstracting
              </h1>
              <p className="mt-1 text-sm text-white/70">
                AI-powered county record searches and chain-of-title analysis
              </p>
            </div>
          </div>
          <Link
            href="/apps/title-search/orders/new"
            className="btn-cta gap-2"
            data-testid="new-order-button"
          >
            <Plus className="h-4 w-4" />
            New Order
          </Link>
        </div>
      </div>

      {/* Status Filter Pills */}
      <div className="flex gap-2" data-testid="status-filters">
        {FILTERS.map((s) => (
          <button
            key={s.value}
            onClick={() => setStatusFilter(s.value)}
            className={`rounded-full px-4 py-1.5 text-xs font-medium transition-all ${
              statusFilter === s.value
                ? "bg-[oklch(0.750_0.170_65)] text-white shadow-md shadow-[oklch(0.750_0.170_65/0.25)]"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            }`}
            data-testid={`filter-${s.value || "all"}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading orders...</p>
        </div>
      ) : (
        <OrderList
          orders={orders}
          onOrderDeleted={(id) =>
            setOrders((prev) => prev.filter((o) => o.id !== id))
          }
        />
      )}
    </div>
  );
}
