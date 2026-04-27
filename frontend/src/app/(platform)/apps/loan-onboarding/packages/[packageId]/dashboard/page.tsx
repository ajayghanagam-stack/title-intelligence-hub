"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  Package as PackageIcon,
  Download,
  Layers,
  FileText,
  ArrowRight,
  AlertCircle,
  Upload,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
} from "lucide-react";
import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import { useLoanPipeline } from "@/hooks/use-loan-pipeline";
import {
  getExtractions,
  getStacks,
  getValidationResults,
  listPageOverrides,
} from "@/lib/loan-onboarding/api";
import {
  buildExtractionCSV,
  buildExtractionJSON,
  buildExtractionXML,
  triggerDownload,
} from "@/lib/loan-onboarding/extraction-export";
import { LOAN_DOC_TYPE_LABELS } from "@/lib/loan-onboarding/constants";
import type {
  LoanConfidenceBreakdown,
  LoanPageOverride,
  LoanStack,
  LoanStackExtraction,
  LoanValidationResult,
} from "@/lib/loan-onboarding/types";
import {
  ConfidenceBreakdown,
  blendOverallNoSplit,
} from "@/components/loan-onboarding/confidence-breakdown";
import { ExtractedFieldsPanel } from "@/components/loan-onboarding/extracted-fields-panel";
import { cn } from "@/lib/utils";

const TERMINAL = new Set(["completed", "failed", "awaiting_review"]);
const STACKS_PAGE_SIZE = 6;
const EXTRACTIONS_PAGE_SIZE = 6;

const STATUS_LABEL: Record<string, string> = {
  uploading: "Uploading",
  processing: "Processing",
  completed: "Complete",
  failed: "Failed",
  awaiting_review: "In Review",
};

const STATUS_COLOR: Record<string, string> = {
  uploading: "text-muted-foreground",
  processing: "text-sky-600",
  completed: "text-emerald-600",
  failed: "text-red-600",
  awaiting_review: "text-amber-600",
};

/**
 * Dashboard tab — package overview matching the Loan Onboarding prototype:
 * a header, a final-packet download card, and a stack-level scores grid.
 * No aggregate counts, histogram, or pipeline timings — the Results tab
 * carries the diagnostic detail.
 */
export default function LoanPackageDashboardPage() {
  const params = useParams();
  const packageId = params.packageId as string;
  const { currentOrgId } = useOrg();
  const { orgPath } = useOrgSlug();
  const { package: pkg, loading } = useLoanPackage(packageId);
  // Keep live status polling so the dashboard reflects status changes when
  // visited during processing — but we only consume `pipeline.status`.
  const { pipeline } = useLoanPipeline(
    packageId,
    pkg ? !TERMINAL.has(pkg.status) : true
  );

  const [stacks, setStacks] = useState<LoanStack[]>([]);
  const [overrides, setOverrides] = useState<LoanPageOverride[]>([]);
  const [validations, setValidations] = useState<LoanValidationResult[]>([]);
  const [extractions, setExtractions] = useState<LoanStackExtraction[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [stacksPage, setStacksPage] = useState(0);
  const [extractionsPage, setExtractionsPage] = useState(0);
  // Collapse/expand state for the two summary panels. Stack-level scores
  // collapse by default — extracted fields are the higher-signal output for
  // most loan officers, so they get the prime real estate (expanded).
  const [stacksOpen, setStacksOpen] = useState(false);
  const [extractionsOpen, setExtractionsOpen] = useState(true);

  useEffect(() => {
    if (!currentOrgId || !packageId) return;
    setSummaryLoading(true);
    Promise.all([
      getStacks(currentOrgId, packageId).catch(() => [] as LoanStack[]),
      listPageOverrides(currentOrgId, packageId).catch(
        () => [] as LoanPageOverride[]
      ),
      getValidationResults(currentOrgId, packageId).catch(
        () => [] as LoanValidationResult[]
      ),
      getExtractions(currentOrgId, packageId)
        .then((r) => r.stacks)
        .catch(() => [] as LoanStackExtraction[]),
    ])
      .then(([s, o, v, ex]) => {
        setStacks(s);
        setOverrides(o);
        setValidations(v);
        setExtractions(ex);
      })
      .finally(() => setSummaryLoading(false));
  }, [currentOrgId, packageId, pipeline?.status]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading package…</p>
      </div>
    );
  }

  if (!pkg) {
    return (
      <p className="text-muted-foreground py-10 text-center">
        Package not found
      </p>
    );
  }

  const liveStatus = pipeline?.status ?? pkg.status;
  const statusLabel = STATUS_LABEL[liveStatus] ?? liveStatus;
  const statusColor = STATUS_COLOR[liveStatus] ?? "text-foreground";

  // Page-number lookup for the change summary.
  const pageNumberById = new Map<string, number>();
  stacks.forEach((s) =>
    s.pages.forEach((p) => pageNumberById.set(p.page_id, p.page_number))
  );

  const breakdownByStackId = new Map<string, LoanConfidenceBreakdown>();
  validations.forEach((v) => {
    breakdownByStackId.set(v.stack_id, v.confidence_breakdown);
  });

  const reorganized = overrides.length > 0;
  const labelFor = (key: string) => LOAN_DOC_TYPE_LABELS[key] ?? key;
  const sortedOverrides = [...overrides].sort((a, b) => {
    const ap = pageNumberById.get(a.page_id) ?? Number.MAX_SAFE_INTEGER;
    const bp = pageNumberById.get(b.page_id) ?? Number.MAX_SAFE_INTEGER;
    return ap - bp;
  });

  // Pagination — stack-level scores grid.
  const stacksTotalPages = Math.max(
    1,
    Math.ceil(stacks.length / STACKS_PAGE_SIZE)
  );
  const stacksSafePage = Math.min(
    Math.max(0, stacksPage),
    stacksTotalPages - 1
  );
  const stacksPageStart = stacksSafePage * STACKS_PAGE_SIZE;
  const pagedStacks = stacks.slice(
    stacksPageStart,
    stacksPageStart + STACKS_PAGE_SIZE
  );

  // Pagination — extracted-fields confidence grid. Real extraction rows
  // (every configured field gets a row even when status="missing") plus
  // synthetic placeholder rows for doc types that were configured for
  // extraction but produced no matching stack — so the loan officer can
  // tell "the pipeline ran and found nothing" apart from "the pipeline
  // never tried this doc type". Synthetic rows show every configured
  // field at 0% / status="missing".
  const realExtractionsWithFields = extractions.filter(
    (e) => e.fields.length > 0
  );
  const docTypesWithRealStacks = new Set(
    realExtractionsWithFields.map((e) => e.doc_type)
  );
  const configuredFieldsByDoc = pkg.extraction_fields_by_doc ?? {};
  const placeholderExtractions: LoanStackExtraction[] = pkg.extraction_enabled
    ? Object.entries(configuredFieldsByDoc)
        .filter(
          ([docKey, fields]) =>
            Array.isArray(fields) &&
            fields.length > 0 &&
            !docTypesWithRealStacks.has(docKey)
        )
        .map(([docKey, fields], idx) => ({
          // Prefix the synthetic id so it can never collide with a real
          // stack uuid; stack_index pushes placeholders to the end of the
          // page list. doc_type matches the configured key so the label
          // helper picks up the human-readable name.
          stack_id: `placeholder-${docKey}`,
          stack_index: 10_000 + idx,
          doc_type: docKey,
          fields: fields.map((name) => ({
            name,
            value: "",
            confidence: 0,
            status: "missing" as const,
            page: null,
            bbox: null,
          })),
          located_count: 0,
          total_count: fields.length,
        }))
    : [];
  const extractionsWithFields = [
    ...realExtractionsWithFields,
    ...placeholderExtractions,
  ];
  const placeholderStackIds = new Set(
    placeholderExtractions.map((e) => e.stack_id)
  );
  const extractionsTotalPages = Math.max(
    1,
    Math.ceil(extractionsWithFields.length / EXTRACTIONS_PAGE_SIZE)
  );
  const extractionsSafePage = Math.min(
    Math.max(0, extractionsPage),
    extractionsTotalPages - 1
  );
  const extractionsPageStart = extractionsSafePage * EXTRACTIONS_PAGE_SIZE;
  const pagedExtractions = extractionsWithFields.slice(
    extractionsPageStart,
    extractionsPageStart + EXTRACTIONS_PAGE_SIZE
  );

  // Average confidence over *located* fields per extraction stack, rounded
  // to a percent. Returns null when no fields were located so callers can
  // show a neutral state rather than 0%.
  const avgConfidencePct = (e: LoanStackExtraction): number | null => {
    const located = e.fields.filter(
      (f) => f.status === "located" || f.status === "low_confidence"
    );
    if (located.length === 0) return null;
    const total = located.reduce((acc, f) => acc + (f.confidence ?? 0), 0);
    return Math.round((total / located.length) * 100);
  };

  // Subtitle — prototype shows "{loan_ref} · {borrower}". Fall back to
  // package name if neither is set.
  const subtitleParts = [pkg.loan_reference, pkg.borrower_name].filter(
    Boolean
  ) as string[];
  const subtitle =
    subtitleParts.length > 0 ? subtitleParts.join(" · ") : pkg.name;

  return (
    <div className="space-y-6" data-testid="loan-package-dashboard">
      {/* Header — eyebrow + serif title + subtitle + right-aligned status */}
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <div className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground uppercase mb-2">
            Package Overview
          </div>
          <h1 className="font-serif text-[42px] leading-none text-foreground">
            Onboarding dashboard
          </h1>
          <p className="text-[13px] text-muted-foreground mt-3">{subtitle}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground uppercase">
            Package status
          </div>
          <div
            className={cn(
              "font-serif text-[24px] mt-1",
              statusColor
            )}
          >
            {statusLabel}
          </div>
        </div>
      </div>

      {/* Final packet card */}
      <div
        className="bg-card border border-border rounded-md p-6"
        data-testid="final-packet-card"
      >
        <div className="flex items-start gap-5">
          <div className="w-12 h-12 rounded bg-amber-50 border border-amber-200 flex items-center justify-center shrink-0">
            <PackageIcon className="h-5 w-5 text-amber-700" strokeWidth={1.8} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <div className="font-serif text-[20px] font-semibold text-foreground">
                Final packet
              </div>
              {reorganized && (
                <span className="font-mono text-[9px] tracking-[0.15em] uppercase px-2 py-0.5 rounded bg-amber-500 text-white">
                  Reorganized · {overrides.length} page
                  {overrides.length === 1 ? "" : "s"} moved
                </span>
              )}
            </div>
            <div className="text-[13px] text-muted-foreground mb-4">
              {reorganized
                ? "The final packet differs from the original upload. Pages have been re-stacked into their correct document types based on classification and human review. Download the reorganized packet below, or retrieve the original upload."
                : "No page reorganization yet. Download the classified packet or the original upload below."}
            </div>

            {reorganized && (
              <div
                className="mb-4 border border-border rounded bg-muted/30 p-4 max-h-48 overflow-auto"
                data-testid="change-summary-list"
              >
                <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase mb-2">
                  Change summary
                </div>
                <ul className="space-y-1.5">
                  {sortedOverrides.map((o) => {
                    const pageNum = pageNumberById.get(o.page_id);
                    return (
                      <li
                        key={o.id}
                        className="flex items-center gap-2 text-[12px] text-foreground"
                      >
                        <FileText className="h-3 w-3 text-muted-foreground shrink-0" />
                        <span className="font-mono text-[10px] text-muted-foreground tabular-nums">
                          Pg{pageNum ?? "—"}
                        </span>
                        <span>{labelFor(o.previous_doc_type)}</span>
                        <ArrowRight className="h-3 w-3 text-amber-600 shrink-0" />
                        <span className="font-medium text-amber-700">
                          {labelFor(o.assigned_doc_type)}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            <div className="grid grid-cols-[1fr_auto_auto] gap-3 items-stretch">
              <button
                type="button"
                disabled
                title="Download endpoint not yet available"
                className="px-5 py-3 bg-amber-500 text-white text-[13px] font-medium flex items-center justify-center gap-2 rounded-md shadow-sm hover:bg-amber-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                data-testid="download-final-packet"
              >
                <Download className="h-4 w-4" />
                Download final packet (reorganized)
              </button>
              <button
                type="button"
                disabled
                title="Per-stack ZIP not yet available"
                className="px-4 py-3 border border-border bg-background text-[13px] flex items-center justify-center gap-2 rounded-md hover:bg-muted/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                data-testid="download-per-stack-zip"
              >
                <Layers className="h-4 w-4" />
                Per-stack ZIP
              </button>
              <button
                type="button"
                disabled
                title="Original upload download not yet available"
                className="px-4 py-3 border border-border bg-background text-[13px] flex items-center justify-center gap-2 rounded-md hover:bg-muted/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                data-testid="download-original-upload"
              >
                <FileText className="h-4 w-4" />
                Original upload
              </button>
            </div>
            <div className="flex items-center gap-2 mt-3 text-[11px] text-muted-foreground">
              <AlertCircle className="h-3 w-3" />
              Reorganized packet is regenerated on download — page order,
              bookmarks, and stack-level tables of contents reflect the
              current classification.
            </div>

            {(liveStatus === "completed" ||
              liveStatus === "awaiting_review") && (
              <div
                className="mt-5 pt-4 border-t border-border flex items-center justify-between gap-4"
                data-testid="upload-another-cta"
              >
                <div className="text-[12px] text-muted-foreground">
                  Done with this package? Start the next one.
                </div>
                <Link
                  href={orgPath("/apps/loan-onboarding/packages/new")}
                  className="px-4 py-2 bg-amber-500 text-white text-[13px] font-medium flex items-center gap-2 rounded-md shadow-sm hover:bg-amber-600 transition-colors shrink-0"
                >
                  <Upload className="h-4 w-4" />
                  Upload another package
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Extracted fields download card — JSON / CSV / MISMO XML feeds.
          Hidden only when no extractions came back; we don't gate on the
          package's extraction toggle so historical packages keep their
          download links even if the toggle is now off. */}
      {(() => {
        const totalFields = extractions.reduce(
          (acc, e) => acc + e.fields.length,
          0
        );
        if (totalFields === 0) return null;
        // Recompute "located" from field rows (located OR low_confidence)
        // so the badge matches what's rendered in each tile. Backend's
        // persisted located_count counts strict "located" only — see the
        // panel header for the rationale.
        const locatedFields = extractions.reduce(
          (acc, e) =>
            acc +
            e.fields.filter(
              (f) => f.status === "located" || f.status === "low_confidence"
            ).length,
          0
        );
        const stem =
          (pkg.loan_reference || pkg.name || "loan-package").trim() ||
          "loan-package";
        // Filename-safe slug — prototype uses raw refs, but file pickers on
        // some browsers reject `/` and `:` so normalize before download.
        const slug = stem.replace(/[^A-Za-z0-9._-]+/g, "-").slice(0, 80);
        return (
          <div
            className="bg-card border border-border rounded-md p-6"
            data-testid="extraction-downloads-card"
          >
            <div className="flex items-start gap-5">
              <div className="w-12 h-12 rounded bg-sky-50 border border-sky-200 flex items-center justify-center shrink-0">
                <FileText className="h-5 w-5 text-sky-700" strokeWidth={1.8} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <div className="font-serif text-[20px] font-semibold text-foreground">
                    Extracted fields
                  </div>
                  <span className="font-mono text-[9px] tracking-[0.15em] uppercase px-2 py-0.5 rounded bg-sky-500 text-white tabular-nums">
                    {locatedFields}/{totalFields} located
                  </span>
                </div>
                <div className="text-[13px] text-muted-foreground mb-4">
                  Download the structured field feed for downstream LOS
                  systems. JSON for general consumption, CSV for spreadsheets,
                  MISMO 3.4 XML for direct LOS import.
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <button
                    type="button"
                    onClick={() =>
                      triggerDownload(
                        `extraction-${slug}.json`,
                        buildExtractionJSON(extractions, pkg),
                        "application/json"
                      )
                    }
                    className="px-4 py-3 border border-border bg-background text-[13px] flex items-center justify-center gap-2 rounded-md hover:bg-muted/40 transition-colors"
                    data-testid="extraction-download-json"
                  >
                    <Download className="h-4 w-4" /> JSON
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      triggerDownload(
                        `extraction-${slug}.csv`,
                        buildExtractionCSV(extractions),
                        "text/csv"
                      )
                    }
                    className="px-4 py-3 border border-border bg-background text-[13px] flex items-center justify-center gap-2 rounded-md hover:bg-muted/40 transition-colors"
                    data-testid="extraction-download-csv"
                  >
                    <Download className="h-4 w-4" /> CSV
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      triggerDownload(
                        `extraction-${slug}.xml`,
                        buildExtractionXML(extractions, pkg),
                        "application/xml"
                      )
                    }
                    className="px-4 py-3 border border-border bg-background text-[13px] flex items-center justify-center gap-2 rounded-md hover:bg-muted/40 transition-colors"
                    data-testid="extraction-download-mismo"
                  >
                    <Download className="h-4 w-4" /> MISMO XML
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Stack-level scores grid */}
      <div
        className="bg-card border border-border rounded-md overflow-hidden"
        data-testid="stack-scores-grid"
      >
        <button
          type="button"
          onClick={() => setStacksOpen((v) => !v)}
          aria-expanded={stacksOpen}
          aria-controls="stack-scores-body"
          className={cn(
            "w-full px-6 py-4 flex items-center justify-between text-left hover:bg-muted/30 transition-colors",
            stacksOpen && "border-b border-border"
          )}
          data-testid="stack-scores-toggle"
        >
          <div className="flex items-center gap-2">
            <ChevronDown
              className={cn(
                "h-4 w-4 text-muted-foreground transition-transform",
                !stacksOpen && "-rotate-90"
              )}
            />
            <div className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground uppercase">
              Stack-level scores
            </div>
          </div>
          {stacks.length > 0 && (
            <span className="font-mono text-[10px] text-muted-foreground tabular-nums">
              {stacksOpen
                ? `${stacksPageStart + 1}–${Math.min(stacksPageStart + STACKS_PAGE_SIZE, stacks.length)} of ${stacks.length}`
                : `${stacks.length}`}{" "}
              stack{stacks.length === 1 ? "" : "s"}
            </span>
          )}
        </button>
        {stacksOpen && (stacks.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {summaryLoading ? "Loading stacks…" : "No stacks available yet."}
          </p>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2">
              {pagedStacks.map((s, i) => {
                const breakdown = breakdownByStackId.get(s.id) ?? {
                  classification: null,
                  split_accuracy: null,
                  validation: null,
                };
                // Recompute overall from classification + validation only so
                // the status dot stays consistent with the donut center.
                const effectiveOverall = blendOverallNoSplit(breakdown);
                const pct =
                  effectiveOverall == null
                    ? null
                    : Math.round(effectiveOverall * 100);
                const dot =
                  pct == null
                    ? "bg-muted-foreground/40"
                    : pct >= 90
                      ? "bg-emerald-500"
                      : pct >= 75
                        ? "bg-amber-500"
                        : "bg-red-500";
                const col = i % 2;
                const row = Math.floor(i / 2);
                const lastRow = Math.floor((pagedStacks.length - 1) / 2);
                return (
                  <div
                    key={s.id}
                    className={cn(
                      "p-5 border-border",
                      col !== 1 && "md:border-r",
                      row !== lastRow && "border-b"
                    )}
                    data-testid={`stack-tile-${s.stack_index}`}
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="min-w-0">
                        <div className="font-serif text-[14px] text-foreground leading-tight truncate">
                          {labelFor(s.doc_type)}
                        </div>
                        <div className="font-mono text-[10px] text-muted-foreground mt-1">
                          {s.page_count} page{s.page_count === 1 ? "" : "s"}
                        </div>
                      </div>
                      <span
                        className={cn(
                          "w-1.5 h-1.5 rounded-full mt-2 shrink-0",
                          dot
                        )}
                        aria-hidden
                      />
                    </div>
                    <ConfidenceBreakdown
                      breakdown={breakdown}
                      overall={s.overall_confidence ?? null}
                      omit={["split_accuracy"]}
                      compact
                    />
                  </div>
                );
              })}
            </div>
            {stacksTotalPages > 1 && (
              <div
                className="px-4 py-2 border-t border-border bg-muted/30 flex items-center justify-between gap-2"
                data-testid="stack-scores-pagination"
              >
                <button
                  type="button"
                  onClick={() => setStacksPage(Math.max(0, stacksSafePage - 1))}
                  disabled={stacksSafePage === 0}
                  className="px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                  aria-label="Previous page"
                  data-testid="stack-scores-page-prev"
                >
                  <ChevronLeft className="h-3 w-3" /> Prev
                </button>
                <span className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase tabular-nums">
                  {stacksSafePage + 1} / {stacksTotalPages}
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setStacksPage(
                      Math.min(stacksTotalPages - 1, stacksSafePage + 1)
                    )
                  }
                  disabled={stacksSafePage >= stacksTotalPages - 1}
                  className="px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                  aria-label="Next page"
                  data-testid="stack-scores-page-next"
                >
                  Next <ChevronRight className="h-3 w-3" />
                </button>
              </div>
            )}
          </>
        ))}
      </div>

      {/* Extracted-fields confidence grid — per-stack avg confidence + the
          full per-field rows (name · value · confidence%). Renders whenever
          extraction was enabled on the package OR we already have rows
          (legacy packages). When the package has the toggle on but the grid
          is empty, render a diagnostic placeholder so the user can see why
          (no fields configured, or no stacks matched the doc-type keys)
          rather than just nothing. */}
      {(pkg.extraction_enabled || extractionsWithFields.length > 0) && (
        <div
          className="bg-card border border-border rounded-md overflow-hidden"
          data-testid="extraction-scores-grid"
        >
          <button
            type="button"
            onClick={() => setExtractionsOpen((v) => !v)}
            aria-expanded={extractionsOpen}
            aria-controls="extraction-scores-body"
            className={cn(
              "w-full px-6 py-4 flex items-center justify-between text-left hover:bg-muted/30 transition-colors",
              extractionsOpen && "border-b border-border"
            )}
            data-testid="extraction-scores-toggle"
          >
            <div className="flex items-center gap-2">
              <ChevronDown
                className={cn(
                  "h-4 w-4 text-muted-foreground transition-transform",
                  !extractionsOpen && "-rotate-90"
                )}
              />
              <div className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground uppercase">
                Extracted-fields confidence
              </div>
            </div>
            <span className="font-mono text-[10px] text-muted-foreground tabular-nums">
              {extractionsWithFields.length === 0
                ? "no data"
                : extractionsOpen
                  ? `${extractionsPageStart + 1}–${Math.min(
                      extractionsPageStart + EXTRACTIONS_PAGE_SIZE,
                      extractionsWithFields.length
                    )} of ${extractionsWithFields.length} stack${
                      extractionsWithFields.length === 1 ? "" : "s"
                    }`
                  : `${extractionsWithFields.length} stack${
                      extractionsWithFields.length === 1 ? "" : "s"
                    }`}
            </span>
          </button>
          {extractionsOpen && extractionsWithFields.length === 0 && (
            <div
              className="px-6 py-8 text-center text-[12px] text-muted-foreground"
              data-testid="extraction-scores-empty"
            >
              {summaryLoading
                ? "Loading extracted fields…"
                : "No extracted fields to show."}
            </div>
          )}
          {extractionsOpen && extractionsWithFields.length > 0 && (
          <>
          <div>
            {pagedExtractions.map((e, i) => {
              const isPlaceholder = placeholderStackIds.has(e.stack_id);
              const pct = avgConfidencePct(e);
              const dot =
                pct == null
                  ? "bg-muted-foreground/40"
                  : pct >= 90
                    ? "bg-emerald-500"
                    : pct >= 75
                      ? "bg-amber-500"
                      : "bg-red-500";
              const bar =
                pct == null
                  ? "bg-muted-foreground/30"
                  : pct >= 90
                    ? "bg-emerald-500"
                    : pct >= 75
                      ? "bg-amber-500"
                      : "bg-red-500";
              return (
                <div
                  key={e.stack_id}
                  className={cn(
                    "p-5 border-border",
                    i !== pagedExtractions.length - 1 && "border-b",
                    // Faint amber wash on placeholder rows so they read as
                    // "informational" instead of looking like a failed stack.
                    isPlaceholder && "bg-amber-50/30"
                  )}
                  data-testid={`extraction-tile-${e.stack_index}`}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <div className="font-serif text-[14px] text-foreground leading-tight truncate">
                          {labelFor(e.doc_type)}
                        </div>
                        {isPlaceholder && (
                          <span
                            className="font-mono text-[8px] tracking-[0.15em] uppercase px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200"
                            data-testid="extraction-tile-placeholder-badge"
                          >
                            No stack found
                          </span>
                        )}
                      </div>
                      <div className="font-mono text-[10px] text-muted-foreground mt-1 tabular-nums">
                        {isPlaceholder
                          ? `0/${e.total_count} field${e.total_count === 1 ? "" : "s"} — no pages classified as this doc type`
                          : (() => {
                              // Recompute from rows so the count agrees with
                              // the per-field rendering below (located OR
                              // low_confidence both carry a value).
                              const found = e.fields.filter(
                                (f) =>
                                  f.status === "located" ||
                                  f.status === "low_confidence"
                              ).length;
                              return `${found}/${e.fields.length} field${e.fields.length === 1 ? "" : "s"} located`;
                            })()}
                      </div>
                    </div>
                    <span
                      className={cn(
                        "w-1.5 h-1.5 rounded-full mt-2 shrink-0",
                        dot
                      )}
                      aria-hidden
                    />
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", bar)}
                        style={{ width: `${pct ?? 0}%` }}
                      />
                    </div>
                    <span className="font-mono text-[11px] text-foreground tabular-nums shrink-0">
                      {pct == null ? "—" : `${pct}%`}
                    </span>
                  </div>
                  <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase mt-2">
                    Avg confidence
                  </div>
                  {/* Per-field rows: name · value · confidence%. Reuses the
                      same panel rendered on the Results screen so the two
                      surfaces stay in sync. */}
                  <ExtractedFieldsPanel extraction={e} />
                </div>
              );
            })}
          </div>
          {extractionsTotalPages > 1 && (
            <div
              className="px-4 py-2 border-t border-border bg-muted/30 flex items-center justify-between gap-2"
              data-testid="extraction-scores-pagination"
            >
              <button
                type="button"
                onClick={() =>
                  setExtractionsPage(Math.max(0, extractionsSafePage - 1))
                }
                disabled={extractionsSafePage === 0}
                className="px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                aria-label="Previous page"
                data-testid="extraction-scores-page-prev"
              >
                <ChevronLeft className="h-3 w-3" /> Prev
              </button>
              <span className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase tabular-nums">
                {extractionsSafePage + 1} / {extractionsTotalPages}
              </span>
              <button
                type="button"
                onClick={() =>
                  setExtractionsPage(
                    Math.min(extractionsTotalPages - 1, extractionsSafePage + 1)
                  )
                }
                disabled={extractionsSafePage >= extractionsTotalPages - 1}
                className="px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                aria-label="Next page"
                data-testid="extraction-scores-page-next"
              >
                Next <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          )}
          </>
          )}
        </div>
      )}
    </div>
  );
}
