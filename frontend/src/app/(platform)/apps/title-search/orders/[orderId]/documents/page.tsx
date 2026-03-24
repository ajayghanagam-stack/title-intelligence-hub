"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/hooks/use-org";
import { getDocuments, downloadDocument } from "@/lib/title-search/api";
import { DOC_TYPE_LABELS } from "@/lib/title-search/constants";
import type { TSDocument } from "@/lib/title-search/types";
import { FileText, AlertTriangle, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export default function DocumentsPage() {
  const params = useParams();
  const orderId = params.orderId as string;
  const { currentOrgId } = useOrg();
  const [documents, setDocuments] = useState<TSDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("");

  const handleDownload = async (doc: TSDocument) => {
    if (!currentOrgId) return;
    try {
      const blob = await downloadDocument(currentOrgId, orderId, doc.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${DOC_TYPE_LABELS[doc.doc_type] || doc.doc_type}_${doc.recording_ref || doc.id.slice(0, 8)}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // Download failure is non-critical
    }
  };

  useEffect(() => {
    if (!currentOrgId || !orderId) return;
    setLoading(true);
    getDocuments(
      currentOrgId,
      orderId,
      filter ? { doc_type: filter } : undefined
    )
      .then(setDocuments)
      .catch(() => setDocuments([]))
      .finally(() => setLoading(false));
  }, [currentOrgId, orderId, filter]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading documents...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 pt-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          Documents ({documents.length})
        </h3>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-1.5 text-sm"
        >
          <option value="">All Types</option>
          {Object.entries(DOC_TYPE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>

      {documents.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50 mb-4">
            <FileText className="h-7 w-7 text-muted-foreground/60" />
          </div>
          <p className="text-lg font-medium text-foreground/80 mb-1">
            No documents found
          </p>
          <p className="text-sm text-muted-foreground">
            Documents will appear here once the pipeline processes your order
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {documents.map((doc) => (
            <div key={doc.id} className="section-card">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted/60">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div>
                    <p className="font-medium">
                      {DOC_TYPE_LABELS[doc.doc_type] || doc.doc_type}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {doc.recording_ref || "No ref"} &middot;{" "}
                      {doc.recording_date || "No date"}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {doc.needs_review && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-amber-200">
                      <AlertTriangle className="h-3 w-3" />
                      Review
                    </span>
                  )}
                  {doc.confidence !== null && (
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium tabular-nums",
                        doc.confidence >= 0.9
                          ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                          : doc.confidence >= 0.7
                            ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
                            : "bg-red-50 text-red-700 ring-1 ring-red-200"
                      )}
                    >
                      {Math.round(doc.confidence * 100)}%
                    </span>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 px-2"
                    onClick={() => handleDownload(doc)}
                  >
                    <Download className="h-3.5 w-3.5 mr-1" />
                    PDF
                  </Button>
                </div>
              </div>
              {(doc.grantor || doc.grantee) && (
                <div className="mt-3 flex gap-6 text-sm border-t pt-3">
                  {doc.grantor && (
                    <div>
                      <span className="text-muted-foreground">Grantor:</span>{" "}
                      <span className="font-medium">
                        {doc.grantor.names?.join(", ")}
                      </span>
                    </div>
                  )}
                  {doc.grantee && (
                    <div>
                      <span className="text-muted-foreground">Grantee:</span>{" "}
                      <span className="font-medium">
                        {doc.grantee.names?.join(", ")}
                      </span>
                    </div>
                  )}
                  {doc.consideration && (
                    <div>
                      <span className="text-muted-foreground">
                        Consideration:
                      </span>{" "}
                      <span className="font-medium">
                        ${doc.consideration.toLocaleString()}
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
