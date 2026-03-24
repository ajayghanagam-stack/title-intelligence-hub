"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/hooks/use-org";
import {
  getPackage,
  issuePackage,
  downloadPackagePdf,
} from "@/lib/title-search/api";
import type { TSPackage } from "@/lib/title-search/types";
import {
  Package,
  Download,
  CheckCircle2,
  AlertTriangle,
  FileBox,
} from "lucide-react";

export default function PackagePage() {
  const params = useParams();
  const orderId = params.orderId as string;
  const { currentOrgId } = useOrg();
  const [pkg, setPkg] = useState<TSPackage | null>(null);
  const [loading, setLoading] = useState(true);
  const [issuing, setIssuing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentOrgId || !orderId) return;
    getPackage(currentOrgId, orderId)
      .then(setPkg)
      .catch(() => setPkg(null))
      .finally(() => setLoading(false));
  }, [currentOrgId, orderId]);

  const handleIssue = async () => {
    if (!currentOrgId) return;
    setIssuing(true);
    setError(null);
    try {
      const updated = await issuePackage(currentOrgId, orderId);
      setPkg(updated);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to issue package"
      );
    } finally {
      setIssuing(false);
    }
  };

  const handleDownload = async () => {
    if (!currentOrgId) return;
    try {
      const blob = await downloadPackagePdf(currentOrgId, orderId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${pkg?.package_number || "package"}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading package...</p>
      </div>
    );
  }

  if (!pkg) {
    return (
      <div className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50 mb-4">
          <FileBox className="h-7 w-7 text-muted-foreground/60" />
        </div>
        <p className="text-lg font-medium text-foreground/80 mb-1">
          No package generated yet
        </p>
        <p className="text-sm text-muted-foreground">
          The abstract package will be assembled once the pipeline completes
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6 pt-4">
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-800">Error</p>
            <p className="text-sm text-red-700 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      <div className="section-card">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600 ring-1 ring-blue-200">
              <Package className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">{pkg.package_number}</h2>
              <p className="text-sm text-muted-foreground capitalize">
                {pkg.status}
                {pkg.issued_by && ` by ${pkg.issued_by}`}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            {pkg.status === "draft" && (
              <button
                onClick={handleIssue}
                disabled={issuing}
                className="btn-cta gap-1.5 text-sm"
              >
                {issuing ? "Issuing..." : "Issue Package"}
              </button>
            )}
            <button
              onClick={handleDownload}
              className="btn-secondary gap-1.5 text-sm"
            >
              <Download className="h-4 w-4" />
              Download PDF
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-muted-foreground">Search Scope</span>
            <p className="font-medium capitalize mt-0.5">
              {pkg.search_scope || "N/A"}
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Years Covered</span>
            <p className="font-medium mt-0.5">{pkg.years_covered || "N/A"}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Total Documents</span>
            <p className="font-medium mt-0.5">{pkg.total_documents || 0}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Chain Complete</span>
            <p className="font-medium flex items-center gap-1 mt-0.5">
              {pkg.chain_complete ? (
                <>
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" /> Yes
                </>
              ) : (
                <>
                  <AlertTriangle className="h-4 w-4 text-amber-600" /> No
                </>
              )}
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Open Flags</span>
            <p className="font-medium mt-0.5">{pkg.open_flags_count || 0}</p>
          </div>
          {pkg.issued_at && (
            <div>
              <span className="text-muted-foreground">Issued At</span>
              <p className="font-medium mt-0.5">
                {new Date(pkg.issued_at).toLocaleString()}
              </p>
            </div>
          )}
        </div>
      </div>

      {pkg.property_summary && (
        <div className="section-card">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-4">
            Property Summary
          </h3>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {Object.entries(pkg.property_summary).map(([key, value]) => (
              <div key={key}>
                <span className="text-muted-foreground capitalize">
                  {key.replace(/_/g, " ")}
                </span>
                <p className="font-medium mt-0.5">{value || "N/A"}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
