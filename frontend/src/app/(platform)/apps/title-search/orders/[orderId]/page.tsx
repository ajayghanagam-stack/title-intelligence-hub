"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/hooks/use-org";
import {
  getOrder,
  getPipelineStatus,
  downloadPackagePdf,
} from "@/lib/title-search/api";
import { PipelineProgress } from "@/components/title-search/pipeline-progress";
import { OrderStatusBadge } from "@/components/title-search/order-status-badge";
import type { TSOrder, TSPipelineStatus } from "@/lib/title-search/types";
import {
  Download,
  RefreshCw,
  MapPin,
  Calendar,
  User,
  Hash,
  FileSearch,
} from "lucide-react";

export default function OrderDetailPage() {
  const params = useParams();
  const orderId = params.orderId as string;
  const { currentOrgId } = useOrg();
  const [order, setOrder] = useState<TSOrder | null>(null);
  const [pipeline, setPipeline] = useState<TSPipelineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [polling, setPolling] = useState(true);

  const fetchData = useCallback(async () => {
    if (!currentOrgId || !orderId) return;
    try {
      const [orderData, pipelineData] = await Promise.all([
        getOrder(currentOrgId, orderId),
        getPipelineStatus(currentOrgId, orderId),
      ]);
      setOrder(orderData);
      setPipeline(pipelineData);

      // Stop polling when pipeline is complete or failed
      const done =
        orderData.status === "completed" ||
        orderData.status === "review_required" ||
        orderData.status === "failed";
      if (done) setPolling(false);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [currentOrgId, orderId]);

  useEffect(() => {
    fetchData();
    if (!polling) return;
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [fetchData, polling]);

  const handleDownloadPdf = async () => {
    if (!currentOrgId) return;
    setDownloading(true);
    try {
      const blob = await downloadPackagePdf(currentOrgId, orderId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `title-search-${orderId.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    } finally {
      setDownloading(false);
    }
  };

  if (loading) {
    return (
      <div
        className="flex flex-col items-center justify-center py-20 gap-3"
        data-testid="order-detail-loading"
      >
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading order...</p>
      </div>
    );
  }

  if (!order)
    return (
      <p
        className="text-muted-foreground py-10 text-center"
        data-testid="order-not-found"
      >
        Order not found
      </p>
    );

  const isProcessing = order.status === "processing";
  const isDone =
    order.status === "completed" || order.status === "review_required";

  return (
    <div className="space-y-6" data-testid="order-detail-page">
      {/* Property Details Card */}
      <div className="section-card" data-testid="property-details-card">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/20 ring-1 ring-blue-500/10">
              <MapPin className="h-5 w-5 text-blue-700" />
            </div>
            <div>
              <h2
                className="text-lg font-semibold"
                data-testid="property-address"
              >
                {order.property_address}
              </h2>
              <p className="text-sm text-muted-foreground">
                {order.county}, {order.state_code}
                {order.city ? ` - ${order.city}` : ""}
                {order.zip_code ? ` ${order.zip_code}` : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <OrderStatusBadge
              status={order.status}
              stage={order.pipeline_stage}
            />
            {isProcessing && (
              <RefreshCw className="h-4 w-4 text-muted-foreground animate-spin" />
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          {order.borrower_name && (
            <div data-testid="field-borrower">
              <span className="flex items-center gap-1.5 text-muted-foreground text-xs mb-1">
                <User className="h-3 w-3" /> Owner / Borrower
              </span>
              <p className="font-medium">{order.borrower_name}</p>
            </div>
          )}
          {order.parcel_number && (
            <div data-testid="field-parcel">
              <span className="flex items-center gap-1.5 text-muted-foreground text-xs mb-1">
                <Hash className="h-3 w-3" /> Parcel Number
              </span>
              <p className="font-medium">{order.parcel_number}</p>
            </div>
          )}
          <div data-testid="field-product-type">
            <span className="flex items-center gap-1.5 text-muted-foreground text-xs mb-1">
              <FileSearch className="h-3 w-3" /> Product Type
            </span>
            <p className="font-medium">
              {(order.search_scope || "full")
                .replace("_", " ")
                .replace(/\b\w/g, (c: string) => c.toUpperCase())}{" "}
              ({order.search_years} years)
            </p>
          </div>
          {order.effective_date && (
            <div data-testid="field-effective-date">
              <span className="flex items-center gap-1.5 text-muted-foreground text-xs mb-1">
                <Calendar className="h-3 w-3" /> Effective Date
              </span>
              <p className="font-medium">
                {new Date(order.effective_date).toLocaleDateString()}
              </p>
            </div>
          )}
          {order.order_reference && (
            <div data-testid="field-order-ref">
              <span className="text-muted-foreground text-xs mb-1 block">
                Order / Loan #
              </span>
              <p className="font-medium">{order.order_reference}</p>
            </div>
          )}
          <div data-testid="field-created">
            <span className="text-muted-foreground text-xs mb-1 block">
              Created
            </span>
            <p className="font-medium">
              {new Date(order.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>

        {order.legal_description && (
          <div
            className="mt-4 pt-4 border-t text-sm"
            data-testid="field-legal-desc"
          >
            <span className="text-muted-foreground text-xs mb-1 block">
              Legal Description
            </span>
            <p className="font-medium text-xs leading-relaxed">
              {order.legal_description}
            </p>
          </div>
        )}
      </div>

      {/* Pipeline Progress */}
      {pipeline && (
        <PipelineProgress
          stages={pipeline.stages}
          error={pipeline.pipeline_error}
        />
      )}

      {/* Actions Bar — visible when pipeline is done */}
      {isDone && (
        <div
          className="section-card flex items-center justify-between"
          data-testid="actions-bar"
        >
          <div>
            <p className="font-semibold text-sm">Report Ready</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Download the Generated Report as PDF
            </p>
          </div>
          <button
            onClick={handleDownloadPdf}
            disabled={downloading}
            className="btn-cta gap-2 text-sm"
            data-testid="download-pdf-button"
          >
            <Download className="h-4 w-4" />
            {downloading ? "Downloading..." : "Download PDF"}
          </button>
        </div>
      )}
    </div>
  );
}
