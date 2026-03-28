"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/hooks/use-org";
import { getOrder, getPipelineStatus } from "@/lib/title-search/api";
import { PipelineProgress } from "@/components/title-search/pipeline-progress";
import { OrderStatusBadge } from "@/components/title-search/order-status-badge";
import type { TSOrder, TSPipelineStatus } from "@/lib/title-search/types";

export default function OrderDetailPage() {
  const params = useParams();
  const orderId = params.orderId as string;
  const { currentOrgId } = useOrg();
  const [order, setOrder] = useState<TSOrder | null>(null);
  const [pipeline, setPipeline] = useState<TSPipelineStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!currentOrgId || !orderId) return;

    const fetchData = async () => {
      try {
        const [orderData, pipelineData] = await Promise.all([
          getOrder(currentOrgId, orderId),
          getPipelineStatus(currentOrgId, orderId),
        ]);
        setOrder(orderData);
        setPipeline(pipelineData);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [currentOrgId, orderId]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading order...</p>
      </div>
    );
  }

  if (!order)
    return <p className="text-muted-foreground py-10 text-center">Order not found</p>;

  return (
    <div className="space-y-8">
      <div className="section-card">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
            Property Details
          </h3>
          <OrderStatusBadge
            status={order.status}
            stage={order.pipeline_stage}
          />
        </div>
        <div className="grid grid-cols-2 gap-4 text-sm">
          {order.borrower_name && (
            <div className="col-span-2">
              <span className="text-muted-foreground">Borrower / Owner</span>
              <p className="font-medium mt-0.5">{order.borrower_name}</p>
            </div>
          )}
          <div>
            <span className="text-muted-foreground">Address</span>
            <p className="font-medium mt-0.5">
              {order.property_address}
              {order.city || order.zip_code ? (
                <span className="text-muted-foreground">
                  {order.city ? `, ${order.city}` : ""}
                  {order.zip_code ? ` ${order.zip_code}` : ""}
                </span>
              ) : null}
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">County / State</span>
            <p className="font-medium mt-0.5">
              {order.county}, {order.state_code}
            </p>
          </div>
          {order.parcel_number && (
            <div>
              <span className="text-muted-foreground">Parcel Number</span>
              <p className="font-medium mt-0.5">{order.parcel_number}</p>
            </div>
          )}
          <div>
            <span className="text-muted-foreground">Product Type</span>
            <p className="font-medium mt-0.5">
              {(order.search_scope || "full").replace("_", " ").replace(/\b\w/g, c => c.toUpperCase())} ({order.search_years} years)
            </p>
          </div>
          {order.effective_date && (
            <div>
              <span className="text-muted-foreground">Effective Date</span>
              <p className="font-medium mt-0.5">
                {new Date(order.effective_date).toLocaleDateString()}
              </p>
            </div>
          )}
          {order.order_reference && (
            <div>
              <span className="text-muted-foreground">Order / Loan #</span>
              <p className="font-medium mt-0.5">{order.order_reference}</p>
            </div>
          )}
          <div>
            <span className="text-muted-foreground">Created</span>
            <p className="font-medium mt-0.5">
              {new Date(order.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>
      </div>

      {pipeline && (
        <PipelineProgress
          stages={pipeline.stages}
          error={pipeline.pipeline_error}
        />
      )}
    </div>
  );
}
