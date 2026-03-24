"use client";

import Link from "next/link";
import { OrderStatusBadge } from "./order-status-badge";
import { Search, ChevronRight, Calendar, MapPin } from "lucide-react";
import type { TSOrderListItem } from "@/lib/title-search/types";

export function OrderList({ orders }: { orders: TSOrderListItem[] }) {
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
        <Link href="/apps/title-search/orders/new" className="btn-cta gap-2">
          <Search className="h-4 w-4" />
          New Order
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {orders.map((order) => (
        <Link
          key={order.id}
          href={`/apps/title-search/orders/${order.id}`}
          className="group flex items-center gap-4 card-warm px-5 py-4 hover:border-primary/20"
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

          {/* Arrow */}
          <ChevronRight className="h-5 w-5 text-muted-foreground/30 group-hover:text-primary/60 transition-colors shrink-0" />
        </Link>
      ))}
    </div>
  );
}
