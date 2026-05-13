"use client";

// Phase 5.2 screen #3 — Classification Review.
//
// Operator confirms or overrides the AI's predicted document type for a
// single stack. Backend route is
// `POST /loans/{loan_id}/documents/{doc_id}/classify` — body carries an
// optional `doc_type` (omitted = accept current prediction; provided =
// reclassify). On success we re-fetch the doc list and route to the next
// stack still needing review (or back to the loan overview if none left).
//
// The page deliberately doesn't render a real PDF preview — that piece
// is shared infrastructure with the extract page and lands in the bbox
// renderer (Phase 5.5). Until pages with rendered images are wired,
// the classify view shows the page-range + the predicted vs. corrected
// type side-by-side, with a free-text notes field.

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Brain,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Minus,
  Plus,
} from "lucide-react";

import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import {
  useConfirmClassification,
  useLoanDocuments,
} from "@/hooks/use-loan-operator";
import { LoanPageImage } from "@/components/loan-onboarding/logik-intake/loan-page-image";
import { cn } from "@/lib/utils";

export default function ClassifyDocPage({
  params,
}: {
  params: { loanId: string; docId: string };
}) {
  const { loanId, docId } = params;
  const router = useRouter();
  const { orgPath } = useOrgSlug();
  const { package: loan } = useLoanPackage(loanId);
  const { data: documents = [] } = useLoanDocuments(loanId);
  const confirm = useConfirmClassification(loanId);
  const [override, setOverride] = useState<string>("");
  const [taxYear, setTaxYear] = useState<string>("2023");
  const [zoom, setZoom] = useState<number>(100);

  const doc = useMemo(
    () => documents.find((d) => d.id === docId),
    [documents, docId]
  );
  const remaining = useMemo(
    () =>
      documents.filter((d) => d.status === "needs_review" && d.id !== docId),
    [documents, docId]
  );
  const pendingCount = useMemo(
    () => documents.filter((d) => d.status === "needs_review").length,
    [documents],
  );
  const docIndex = useMemo(
    () => documents.findIndex((d) => d.id === docId),
    [documents, docId],
  );
  // Page strip — first page selected by default. Operators rarely need
  // every page during classification (the prediction is global to the
  // stack), but a strip helps confirm boundaries on multi-page docs.
  const [activePageIdx, setActivePageIdx] = useState(0);
  // Build the doc-type select from the loan's configured doc types.
  // Falls back to a small built-in list if loan_context isn't loaded
  // yet — this keeps the page usable even on slow first paint.
  const docTypeOptions = useMemo(() => {
    const types = loan?.doc_types ?? [];
    if (types.length > 0) return types;
    return [
      { key: "Others", label: "Others", required: false },
      { key: "urla_1003", label: "1003 / URLA", required: true },
      { key: "paystub", label: "Paystub", required: false },
      { key: "w2", label: "W-2", required: false },
    ];
  }, [loan]);

  // Resolve the predicted doc-type label, alternatives list and tax-doc
  // flag. These power the prototype-aligned right-pane: a Brain box +
  // "Other Possibilities" picker. Predicted always shows first, marked
  // Selected. Alts come from the loan's configured doc types.
  const predictedKey = doc?.doc_type ?? "";
  const findLabel = (key: string) =>
    docTypeOptions.find((t) => t.key === key)?.label ?? key;
  const predictedLabel = findLabel(predictedKey);
  const isAutoEligible =
    typeof doc?.classification_confidence === "number" &&
    doc.classification_confidence >= 0.85;
  const altItems = useMemo(() => {
    const head = {
      key: predictedKey,
      label: predictedLabel,
      subtext:
        typeof doc?.classification_confidence === "number"
          ? `${Math.round(doc.classification_confidence * 100)}% confidence`
          : null,
    };
    const tail = docTypeOptions
      .filter((t) => t.key !== predictedKey)
      .map((t) => ({ key: t.key, label: t.label, subtext: null as string | null }));
    return [head, ...tail];
  }, [predictedKey, predictedLabel, doc?.classification_confidence, docTypeOptions]);
  const lowerName = `${predictedKey} ${predictedLabel}`.toLowerCase();
  const isTaxDoc =
    lowerName.includes("1040") ||
    lowerName.includes("w-2") ||
    lowerName.includes("w2") ||
    lowerName.includes("tax");

  if (!loan || !doc) {
    return (
      <div className="mx-auto max-w-7xl px-2 py-8">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  async function handleConfirm() {
    const target = override.trim();
    const isReclassify = target.length > 0 && target !== doc!.doc_type;
    await confirm.mutateAsync({
      docId,
      doc_type: isReclassify ? target : undefined,
      notes: null,
    });
    // Route to the next pending review or back to overview.
    const next = remaining[0];
    if (next) {
      router.push(
        orgPath(`/apps/loan-onboarding/loans/${loanId}/classify/${next.id}`)
      );
    } else {
      router.push(orgPath(`/apps/loan-onboarding/loans/${loanId}`));
    }
  }

  const totalDocs = documents.length || 1;
  const docPos = docIndex >= 0 ? docIndex + 1 : 1;
  const totalPages = doc.page_count;
  const currentPageNum = doc.pages[activePageIdx]?.page_number ?? doc.first_page;
  const canPrev = activePageIdx > 0;
  const canNext = activePageIdx < doc.pages.length - 1;

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <Link
        href={orgPath(`/apps/loan-onboarding/loans/${loanId}`)}
        className="mb-4 inline-flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-[11px] font-semibold text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Pipeline
      </Link>

      <header className="mb-4 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold tracking-tight">
            Classification Review
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {pendingCount} document{pendingCount === 1 ? "" : "s"} require
            classification. Document {docPos} of {totalDocs} shown —{" "}
            {predictedLabel}
          </p>
        </div>
        {pendingCount > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-brand-orange/15 px-2.5 py-1 text-[10px] font-bold text-brand-orange ring-1 ring-brand-orange/40">
            <Clock className="h-3 w-3" />
            {pendingCount} pending
          </span>
        )}
      </header>

      <div className="flex gap-3.5">
        {/* THUMBNAIL STRIP — one tile per page of the current document.
            Each tile loads the page JPEG via LoanPageImage so operators
            see the actual content (not a generic icon). */}
        <div
          className="flex w-[80px] shrink-0 flex-col items-center gap-1.5 overflow-y-auto"
          style={{ maxHeight: 560 }}
        >
          {doc.pages.map((p, idx) => {
            const isActive = idx === activePageIdx;
            return (
              <button
                key={p.page_id ?? `page-${idx}`}
                type="button"
                onClick={() => setActivePageIdx(idx)}
                className={cn(
                  "group relative flex h-[90px] w-[72px] shrink-0 flex-col items-stretch overflow-hidden rounded-md border-2 bg-brand-white transition",
                  isActive
                    ? "border-brand-teal"
                    : "border-border hover:border-brand-teal/60",
                )}
                aria-label={`Page ${p.page_number}`}
                aria-pressed={isActive}
              >
                <div className="flex-1 overflow-hidden bg-muted/20">
                  <LoanPageImage
                    loanId={loanId}
                    pageId={p.page_id ?? null}
                    alt={`Page ${p.page_number} thumbnail`}
                    className="!h-full !w-full !object-cover"
                  />
                </div>
                <span
                  className={cn(
                    "block px-1 py-0.5 text-center text-[9px] font-semibold tabular-nums",
                    isActive
                      ? "bg-brand-teal text-brand-white"
                      : "bg-brand-white text-muted-foreground/70",
                  )}
                >
                  {p.page_number}
                </span>
              </button>
            );
          })}
        </div>

        {/* DOCUMENT VIEWER — zoom bar + white bordered body */}
        <section className="flex min-w-0 flex-1 flex-col gap-2">
          {/* Zoom bar */}
          <div className="flex items-center gap-1 rounded-md bg-brand-charcoal px-3 py-1.5">
            <button
              type="button"
              onClick={() => setZoom((z) => Math.max(50, z - 25))}
              className="inline-flex h-6 w-6 items-center justify-center rounded bg-brand-white/10 text-brand-white/70 hover:bg-brand-white/20"
              aria-label="Zoom out"
            >
              <Minus className="h-3 w-3" />
            </button>
            <button
              type="button"
              onClick={() => setZoom(100)}
              className={cn(
                "rounded px-2 py-0.5 text-[11px] font-semibold transition",
                zoom === 100
                  ? "bg-brand-teal text-brand-charcoal"
                  : "bg-brand-white/10 text-brand-white/70 hover:bg-brand-white/20",
              )}
            >
              100%
            </button>
            <button
              type="button"
              onClick={() => setZoom(150)}
              className={cn(
                "rounded px-2 py-0.5 text-[11px] font-semibold transition",
                zoom === 150
                  ? "bg-brand-teal text-brand-charcoal"
                  : "bg-brand-white/10 text-brand-white/70 hover:bg-brand-white/20",
              )}
            >
              150%
            </button>
            <button
              type="button"
              onClick={() => setZoom((z) => Math.min(200, z + 25))}
              className="inline-flex h-6 w-6 items-center justify-center rounded bg-brand-white/10 text-brand-white/70 hover:bg-brand-white/20"
              aria-label="Zoom in"
            >
              <Plus className="h-3 w-3" />
            </button>
            <span className="ml-2 text-[11px] text-brand-white/50">
              Current: {zoom}%
            </span>
            <div className="ml-auto flex items-center gap-1">
              <button
                type="button"
                disabled={!canPrev}
                onClick={() => setActivePageIdx((i) => Math.max(0, i - 1))}
                className="rounded bg-brand-white/10 px-1.5 py-0.5 text-brand-white/60 hover:bg-brand-white/20 hover:text-brand-white disabled:opacity-40"
                aria-label="Previous page"
              >
                <ChevronLeft className="h-3 w-3" />
              </button>
              <span className="text-[10px] tabular-nums text-brand-white/60">
                Page {currentPageNum} of {totalPages}
              </span>
              <button
                type="button"
                disabled={!canNext}
                onClick={() =>
                  setActivePageIdx((i) =>
                    Math.min(doc.pages.length - 1, i + 1),
                  )
                }
                className="rounded bg-brand-white/10 px-1.5 py-0.5 text-brand-white/60 hover:bg-brand-white/20 hover:text-brand-white disabled:opacity-40"
                aria-label="Next page"
              >
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          </div>

          {/* Viewer body */}
          <div className="relative overflow-auto rounded-md border border-border bg-brand-white">
            <div
              style={{
                transformOrigin: "top left",
                transform: `scale(${zoom / 100})`,
                width: `${Math.round(10000 / zoom)}%`,
                transition: "transform .15s",
              }}
            >
              <div className="aspect-[8.5/11] w-full">
                <LoanPageImage
                  loanId={loanId}
                  pageId={doc.pages[activePageIdx]?.page_id ?? null}
                  alt={`Page ${currentPageNum} of ${doc.doc_type}`}
                />
              </div>
            </div>
          </div>
          <p className="text-[11px] text-muted-foreground">
            {doc.page_count} page{doc.page_count === 1 ? "" : "s"} ·{" "}
            {doc.pages.filter((p) => p.content_signal === "text").length} text-
            embedded ·{" "}
            {doc.pages.filter((p) => p.content_signal === "image").length}{" "}
            scanned
          </p>
        </section>

        {/* RIGHT PANE — mirrors LogikIntake prototype's Classification Review:
            (1) AI Classification Result card with a teal Brain box + Other
            Possibilities click-to-pick list. (2) Action card with optional
            Tax Year select for tax docs + Confirm + Skip Review Later. */}
        <aside className="flex w-[280px] shrink-0 flex-col gap-2.5">
          {/* AI Classification Result */}
          <div className="card-warm p-3">
            <p className="mb-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              AI Classification Result
            </p>
            <div className="mb-2.5 flex items-center gap-2 rounded-md border border-brand-teal bg-brand-teal/10 px-3 py-2.5">
              <Brain className="h-4 w-4 shrink-0 text-brand-teal" />
              <div className="min-w-0">
                <p className="truncate text-[12px] font-bold text-foreground">
                  {predictedLabel}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {typeof doc.classification_confidence === "number"
                    ? `Confidence: ${Math.round(doc.classification_confidence * 100)}%`
                    : "Confidence: —"}
                  {isAutoEligible && " · Auto-classify eligible"}
                </p>
              </div>
            </div>

            <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Other Possibilities
            </p>
            <div className="space-y-1">
              {altItems.map((alt, idx) => {
                const isPicked =
                  override === alt.key ||
                  (override === "" && idx === 0);
                return (
                  <button
                    key={alt.key}
                    type="button"
                    onClick={() => setOverride(alt.key)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md border-[1.5px] px-2.5 py-1.5 text-left transition",
                      isPicked
                        ? "border-brand-teal bg-brand-teal/5"
                        : "border-transparent bg-muted/40 hover:bg-muted/60",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12px] font-bold text-foreground">
                        {alt.label}
                      </p>
                      {alt.subtext && (
                        <p className="text-[10px] text-muted-foreground">
                          {alt.subtext}
                        </p>
                      )}
                    </div>
                    {isPicked && (
                      <span className="shrink-0 rounded-full bg-brand-teal/15 px-1.5 py-0.5 text-[9px] font-bold text-brand-teal ring-1 ring-brand-teal/40">
                        Selected
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Action card */}
          <div className="card-warm p-3">
            {isTaxDoc && (
              <>
                <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                  Tax Year
                </p>
                <select
                  value={taxYear}
                  onChange={(e) => setTaxYear(e.target.value)}
                  className="mb-2.5 h-9 w-full rounded-md border-[1.5px] border-border bg-white px-2.5 text-xs focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
                >
                  <option>2023</option>
                  <option>2022</option>
                </select>
              </>
            )}
            <button
              type="button"
              disabled={confirm.isPending}
              onClick={handleConfirm}
              className="mb-2 inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-teal px-3 py-2 text-[12px] font-bold text-brand-white shadow-sm transition hover:shadow-md hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Check className="h-3 w-3" />
              {confirm.isPending ? "Saving…" : "Confirm Classification"}
            </button>
            <Link
              href={orgPath(`/apps/loan-onboarding/loans/${loanId}`)}
              className="inline-flex w-full items-center justify-center rounded-md border border-border bg-card px-3 py-2 text-[11px] font-bold text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              Skip — Review Later
            </Link>
            {confirm.error && (
              <p className="mt-2 text-xs text-destructive">
                {confirm.error.message}
              </p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
