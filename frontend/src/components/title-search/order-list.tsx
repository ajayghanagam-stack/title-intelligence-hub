"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { OrderStatusBadge } from "./order-status-badge";
import { Search, ChevronRight, ChevronLeft, Calendar, MapPin, Trash2, Check, X } from "lucide-react";
import { deleteOrder } from "@/lib/title-search/api";
import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import type { TSOrderListItem } from "@/lib/title-search/types";

const PAGE_SIZE = 10;

export function OrderList({
  orders,
  onOrderDeleted,
}: {
  orders: TSOrderListItem[];
  onOrderDeleted?: (orderId: string) => void;
}) {
  const router = useRouter();
  const { currentOrgId } = useOrg();
  const { orgPath } = useOrgSlug();
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<Record<string, string>>({});
  const [page, setPage] = useState(0);

  // Sort latest first, then paginate
  const sorted = [...orders].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const paged = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const handleDelete = async (orderId: string) => {
    if (!currentOrgId || deletingId) return;
    setDeletingId(orderId);
    setErrorMsg((prev) => { const next = { ...prev }; delete next[orderId]; return next; });
    try {
      await deleteOrder(currentOrgId, orderId);
      setConfirmId(null);
      onOrderDeleted?.(orderId);
      window.dispatchEvent(new Event("order-deleted"));
      // If deleting the last item on current page, go back one page
      const newTotal = sorted.length - 1;
      const newTotalPages = Math.max(1, Math.ceil(newTotal / PAGE_SIZE));
      if (page >= newTotalPages) setPage(Math.max(0, newTotalPages - 1));
    } catch (err) {
      setConfirmId(null);
      setErrorMsg((prev) => ({
        ...prev,
        [orderId]: err instanceof Error ? err.message : "Failed to delete",
      }));
    } finally {
      setDeletingId(null);
    }
  };

  if (orders.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50 mb-4">
          <Search className="h-7 w-7 text-muted-foreground/60" />
        </div>
        <p className="text-lg font-medium text-foreground/80 mb-1">
          No orders yet
        </p>
        <p className="text-sm text-muted-foreground mb-6">
          Create your first title search order to get started
        </p>
        <Link href={orgPath("/apps/title-search/orders/new")} className="btn-cta gap-2">
          <Search className="h-4 w-4" />
          New Order
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="order-list">
      {paged.map((order) => {
        const isConfirming = confirmId === order.id;
        const isDeleting = deletingId === order.id;
        const error = errorMsg[order.id];

        return (
          <div key={order.id} data-testid={`order-row-${order.id}`}>
            <div
              onClick={() => {
                if (isConfirming || isDeleting) return;
                router.push(orgPath(`/apps/title-search/orders/${order.id}`));
              }}
              className={`group flex items-center gap-4 card-warm px-5 py-4 cursor-pointer ${
                isConfirming ? "border-red-200 bg-red-50/30" : "hover:border-primary/20"
              }`}
            >
              {/* Location icon */}
              <div className="shrink-0">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-600 ring-1 ring-blue-200">
                  <MapPin className="h-5 w-5" />
                </div>
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-foreground group-hover:text-primary transition-colors truncate">
                  {order.property_address}
                </p>
                <div className="flex items-center gap-3 mt-1">
                  <OrderStatusBadge
                    status={order.status}
                    stage={order.pipeline_stage}
                  />
                  <span className="text-xs text-muted-foreground">
                    {order.county}, {order.state_code}
                  </span>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Calendar className="h-3 w-3" />
                    {new Date(order.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>

              {/* Right side: trash icon OR inline confirm/cancel */}
              {isConfirming ? (
                <div
                  className="shrink-0 flex items-center gap-2"
                  onClick={(e) => e.stopPropagation()}
                >
                  <span className="text-xs text-red-600 font-medium">
                    {isDeleting ? "Deleting..." : "Delete?"}
                  </span>
                  <button
                    onClick={() => handleDelete(order.id)}
                    disabled={isDeleting}
                    className="p-1.5 rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                    title="Confirm delete"
                  >
                    <Check className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => setConfirmId(null)}
                    disabled={isDeleting}
                    className="p-1.5 rounded-md text-muted-foreground hover:bg-muted transition-colors"
                    title="Cancel"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setErrorMsg((prev) => { const next = { ...prev }; delete next[order.id]; return next; });
                      setConfirmId(order.id);
                    }}
                    className="shrink-0 p-2 rounded-lg text-muted-foreground/40 hover:text-red-600 hover:bg-red-50 transition-colors"
                    title="Delete order"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                  <ChevronRight className="h-5 w-5 text-muted-foreground/30 group-hover:text-primary/60 transition-colors shrink-0" />
                </>
              )}
            </div>

            {/* Error message below the row */}
            {error && (
              <div className="flex items-center gap-2 px-5 py-2 text-xs text-amber-800 bg-amber-50 border border-t-0 border-amber-200 rounded-b-xl">
                <span className="flex-1">{error}</span>
                <button
                  onClick={() => setErrorMsg((prev) => { const next = { ...prev }; delete next[order.id]; return next; })}
                  className="p-0.5 rounded text-amber-400 hover:text-amber-600"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>
        );
      })}

      {/* Pagination controls */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-4 border-t border-border/40" data-testid="pagination-controls">
          <span className="text-xs text-muted-foreground">
            Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-muted hover:bg-muted/80 text-foreground"
              data-testid="pagination-prev"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Prev
            </button>
            <span className="text-xs font-medium text-muted-foreground tabular-nums">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-muted hover:bg-muted/80 text-foreground"
              data-testid="pagination-next"
            >
              Next
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
