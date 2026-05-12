"use client";

// Phase 5.2 screen #5 — Extraction Review.
//
// Mirrors the LogikIntake prototype's `screenExtractionReview()`:
// header (title + subline + Low Confidence pill) → flex row of
// [light-grey-wrapped page preview + green "Verified legible" footer]
// + [340px right card with title slbl, optional amber callout, inline
// editable field rows, and "Confirm & Save Extraction" CTA]. No bbox
// overlay, no per-field state pills — the prototype keeps editing
// inline and conveys confidence via a single colored dot per row.

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowLeft, Check, RefreshCw } from "lucide-react";

import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import {
  useLoanDocExtraction,
  useLoanDocuments,
  usePatchExtractionField,
  useRerunExtraction,
} from "@/hooks/use-loan-operator";
import { bandFor } from "@/components/loan-onboarding/logik-intake/confidence-band";
import { LoanPageImage } from "@/components/loan-onboarding/logik-intake/loan-page-image";
import { cn } from "@/lib/utils";
import type { LoanDocExtractionField } from "@/lib/loan-onboarding/api";

// Next.js App Router does a "soft navigation" between dynamic-segment
// values of the same `[docId]/page.tsx` file: the page component
// instance is reused, `useState` initializers do NOT re-run, and any
// child component reconciled with a matching `key` keeps its local
// state (the `draft` value in `ExtractionFieldRow` was the visible
// symptom — flood_cert's typed value persisted into mi_certificate's
// input). The bullet-proof fix is to force a full remount on every
// docId change by keying the body component. Anything below this
// boundary gets fresh `useState`, fresh memos, fresh closures.
export default function ExtractDocPage({
  params,
}: {
  params: { loanId: string; docId: string };
}) {
  const { loanId, docId } = params;
  return <ExtractDocPageBody key={docId} loanId={loanId} docId={docId} />;
}

function ExtractDocPageBody({
  loanId,
  docId,
}: {
  loanId: string;
  docId: string;
}) {
  const router = useRouter();
  const { orgPath } = useOrgSlug();
  const { package: loan } = useLoanPackage(loanId);
  const { data: documents = [] } = useLoanDocuments(loanId);
  const { data: extraction, isLoading } = useLoanDocExtraction(loanId, docId);
  const patch = usePatchExtractionField(loanId, docId);
  const rerun = useRerunExtraction(loanId, docId);

  const doc = useMemo(
    () => documents.find((d) => d.id === docId),
    [documents, docId],
  );

  // Page nav: union of pages with any grounded field + the doc's page range.
  const fields = useMemo(
    () => extraction?.fields ?? [],
    [extraction?.fields],
  );
  const pageNumbers = useMemo(() => {
    const pages = new Set<number>();
    for (const f of fields) {
      if (typeof f.page === "number") pages.add(f.page);
    }
    if (doc) {
      for (let p = doc.first_page; p <= doc.last_page; p += 1) pages.add(p);
    }
    return Array.from(pages).sort((a, b) => a - b);
  }, [fields, doc]);

  // Body is keyed by `docId` upstream, so this useState is guaranteed
  // to (re)initialize whenever the user navigates to a different doc.
  const [activePage, setActivePage] = useState<number | null>(null);
  const currentPage = activePage ?? pageNumbers[0] ?? doc?.first_page ?? 1;
  const currentPageRecord = useMemo(
    () => doc?.pages.find((p) => p.page_number === currentPage) ?? null,
    [doc, currentPage],
  );

  // Counts: only fields the agent actually extracted (status != "missing")
  // can be "low confidence" — missing rows are visually distinct (grey)
  // and prompt the operator to fill them in, not to verify a value.
  const lowCount = useMemo(
    () =>
      fields.filter(
        (f) => f.status !== "missing" && bandFor(f.confidence) !== "auto",
      ).length,
    [fields],
  );
  const missingCount = useMemo(
    () =>
      fields.filter(
        (f) => f.status === "missing" && !(f.value ?? "").trim(),
      ).length,
    [fields],
  );

  // The two distinct "values are not showing" cases:
  //   - extraction_present === false → extract stage was skipped (no schema
  //     fields for this doc_type at run time, or extraction disabled on the
  //     package). The DB has zero extracted rows; every visible row is a
  //     schema placeholder.
  //   - extraction_present === true but schema_field_count exceeds the
  //     number of fields the AI actually emitted → admin added/promoted
  //     fields *after* the loan ran. The old fields still have values; the
  //     new ones come through as placeholders.
  // In both cases the operator's only path to populated values is re-running
  // the extract stage against the *current* resolver schema.
  const extractionPresent = extraction?.extraction_present ?? true;
  const schemaFieldCount = extraction?.schema_field_count ?? 0;
  const extractedRowCount = fields.filter((f) => f.status !== "missing").length;
  const newSchemaFieldCount = Math.max(
    0,
    schemaFieldCount - extractedRowCount,
  );
  const showRerunBanner =
    schemaFieldCount > 0 &&
    (!extractionPresent || newSchemaFieldCount > 0);

  if (!loan || !doc) {
    return (
      <div className="mx-auto max-w-7xl px-2 py-8">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  const totalPages = doc.last_page - doc.first_page + 1;
  const docLabel = extraction?.doc_type || doc.doc_type;
  const cardTitle = `Extracted Fields — ${docLabel}`;
  const reviewBits: string[] = [];
  if (lowCount > 0) {
    reviewBits.push(
      `${lowCount} field${lowCount === 1 ? "" : "s"} flagged for review`,
    );
  }
  if (missingCount > 0) {
    reviewBits.push(
      `${missingCount} missing value${missingCount === 1 ? "" : "s"}`,
    );
  }
  const subline = `${docLabel}${
    loan ? ` — ${loan.borrower_name ?? loan.name} · ${loan.id}` : ""
  }${reviewBits.length > 0 ? ` · ${reviewBits.join(" · ")}` : ""}`;

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <Link
        href={orgPath(`/apps/loan-onboarding/loans/${loanId}`)}
        className="mb-4 inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-[11px] font-semibold text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <ArrowLeft className="h-3 w-3" />
        Back to Pipeline
      </Link>

      {/* Header — title + subline + Low Confidence pill (amber) */}
      <header className="mb-4 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold tracking-tight">
            Extraction Review
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">{subline}</p>
        </div>
        {lowCount > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-[10px] font-bold text-amber-800 ring-1 ring-amber-300">
            <AlertTriangle className="h-3 w-3" />
            {lowCount} Low Confidence
          </span>
        )}
      </header>

      <div className="flex gap-3.5">
        {/* DOCUMENT VIEWER — light-grey wrapper containing an inner white
            card with the page image + green "Verified legible" footer. */}
        <div className="min-h-[420px] flex-1 overflow-hidden rounded-md border border-border bg-slate-50">
          <div className="bg-card p-4 sm:p-[18px]">
            {pageNumbers.length > 1 && (
              <div className="mb-2 flex items-center gap-1">
                {pageNumbers.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setActivePage(p)}
                    className={cn(
                      "h-7 min-w-7 rounded-md px-2 text-[11px] font-semibold ring-1 ring-inset transition",
                      p === currentPage
                        ? "bg-brand-teal text-brand-white ring-brand-teal"
                        : "bg-muted text-muted-foreground ring-border hover:bg-muted/70",
                    )}
                  >
                    {p}
                  </button>
                ))}
              </div>
            )}
            <div className="relative aspect-[8.5/11] w-full overflow-hidden rounded-md border border-border bg-muted/20">
              <LoanPageImage
                loanId={loanId}
                pageId={currentPageRecord?.page_id ?? null}
                alt={`Page ${currentPage} of ${docLabel}`}
                className="absolute inset-0"
              />
            </div>
            <div className="mt-2 border-t-2 border-green-600 bg-green-50 px-2 py-1.5 text-[9px] font-semibold text-green-800">
              {docLabel} · Page {currentPage} of {totalPages} · Verified legible
            </div>
          </div>
        </div>

        {/* EXTRACTED FIELDS CARD — fixed 340px right column */}
        <aside className="w-[340px] shrink-0">
          <div className="card-warm p-3">
            <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              {cardTitle}
            </p>
            {showRerunBanner && (
              <div className="mb-2.5 rounded-md border border-brand-teal/40 bg-brand-teal/5 p-2.5 text-[11px] text-foreground">
                <div className="flex items-start gap-1.5">
                  <RefreshCw className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-teal" />
                  <div className="flex-1">
                    <p className="font-semibold">
                      {!extractionPresent
                        ? "Extraction has not run for this document"
                        : `${newSchemaFieldCount} new field${newSchemaFieldCount === 1 ? "" : "s"} added to the schema since this loan was processed`}
                    </p>
                    <p className="mt-0.5 text-muted-foreground">
                      {!extractionPresent
                        ? "Configure fields in Admin → Extraction Schemas, then re-run to populate values."
                        : "Re-run extraction to populate the new fields against the current schema."}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => rerun.mutate()}
                  disabled={rerun.isPending}
                  className="mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-teal px-2.5 py-1.5 text-[11px] font-bold text-brand-white shadow-sm transition hover:brightness-105 disabled:opacity-60"
                >
                  <RefreshCw
                    className={cn(
                      "h-3 w-3",
                      rerun.isPending && "animate-spin",
                    )}
                  />
                  {rerun.isPending ? "Re-running…" : "Re-run Extraction"}
                </button>
                {rerun.error && (
                  <p className="mt-1.5 text-[10px] text-destructive">
                    {rerun.error.message}
                  </p>
                )}
                {rerun.isSuccess && rerun.data && (
                  <p className="mt-1.5 text-[10px] text-emerald-700">
                    Re-ran extraction · {rerun.data.fields_extracted} field
                    {rerun.data.fields_extracted === 1 ? "" : "s"}
                    {rerun.data.status === "skipped"
                      ? " · status: skipped (check schema config)"
                      : ""}
                  </p>
                )}
              </div>
            )}
            {lowCount > 0 && (
              <div className="mb-2.5 flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-800">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-orange" />
                <span>
                  {lowCount} field{lowCount === 1 ? "" : "s"} extracted at low
                  confidence (amber). Review and correct before confirming.
                </span>
              </div>
            )}
            {isLoading ? (
              <p className="py-2 text-[12px] text-muted-foreground">
                Loading fields…
              </p>
            ) : fields.length === 0 ? (
              <p className="py-2 text-[12px] text-muted-foreground">
                No extraction schema configured for{" "}
                <span className="font-semibold">{docLabel}</span>. Add fields
                in Admin → Extraction Schemas to enable extraction review.
              </p>
            ) : (
              <div className="divide-y divide-border">
                {fields.map((field) => (
                  <ExtractionFieldRow
                    key={field.key ?? field.name}
                    field={field}
                    onSave={(value) =>
                      patch.mutate({ fieldId: field.name, value })
                    }
                  />
                ))}
              </div>
            )}
            {patch.error && (
              <p className="mt-2 text-[11px] text-destructive">
                {patch.error.message}
              </p>
            )}
            <button
              type="button"
              onClick={() =>
                router.push(orgPath(`/apps/loan-onboarding/loans/${loanId}`))
              }
              className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-teal px-3 py-2 text-[12px] font-bold text-brand-white shadow-sm transition hover:shadow-md hover:brightness-105"
            >
              <Check className="h-3 w-3" />
              Confirm &amp; Save Extraction
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

// Inline-editable field row — 160px label column + value row (dot +
// input). Low-confidence rows tint the input amber. Save fires on blur
// when the value actually changed (no explicit Save button — matches
// the prototype's inline-editing pattern).
function ExtractionFieldRow({
  field,
  onSave,
}: {
  field: LoanDocExtractionField;
  onSave: (value: string) => void;
}) {
  const [draft, setDraft] = useState(field.value ?? "");
  const hasValue = (field.value ?? "").trim().length > 0;
  // A field is "missing" when the agent didn't return a value (status =
  // "missing" or empty). For these we suppress the colored confidence dot
  // (there's nothing to be confident about) and tint the input grey so it
  // reads as an empty placeholder rather than a low-confidence result.
  const isMissing = !hasValue || field.status === "missing";
  const band = bandFor(field.confidence);
  const isLow = !isMissing && band !== "auto";

  const dotClass = isMissing
    ? "bg-slate-300"
    : band === "auto"
      ? "bg-green-600"
      : band === "review"
        ? "bg-brand-orange"
        : "bg-red-600";

  const displayLabel = field.label || field.name;
  const requiredStar = field.required ? (
    <span className="ml-0.5 text-red-600" aria-label="required">
      *
    </span>
  ) : null;

  return (
    <div className="flex items-start gap-[10px] py-[9px]">
      <div className="min-w-[160px] shrink-0 pt-[6px] text-[11px] font-semibold text-slate-600">
        {displayLabel}
        {requiredStar}
      </div>
      <div className="flex flex-1 items-center gap-[6px]">
        <span
          className={cn("block h-2 w-2 shrink-0 rounded-full", dotClass)}
          aria-hidden
        />
        <input
          type="text"
          value={draft}
          placeholder={isMissing ? "Not found — enter value" : ""}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            if (draft !== (field.value ?? "")) onSave(draft);
          }}
          className={cn(
            "flex-1 rounded-md border-[1.5px] px-[10px] py-[6px] text-[12px] focus:outline-none focus:ring-2",
            isMissing
              ? "border-dashed border-slate-300 bg-slate-50 text-foreground placeholder:text-slate-400 focus:border-brand-teal focus:ring-brand-teal/20"
              : isLow
                ? "border-amber-300 bg-amber-50 text-foreground focus:ring-amber-200"
                : "border-border bg-card text-foreground focus:border-brand-teal focus:ring-brand-teal/20",
          )}
        />
      </div>
    </div>
  );
}
