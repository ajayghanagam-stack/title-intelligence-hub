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
} from "lucide-react";
import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import { useLoanPipeline } from "@/hooks/use-loan-pipeline";
import {
  deleteExtractionOverride,
  fetchFinalPacketPdfBlob,
  fetchPerStackZipBlob,
  getExtractions,
  getStacks,
  listExtractionOverrides,
  listPageOverrides,
  upsertExtractionOverride,
} from "@/lib/loan-onboarding/api";
import {
  buildExtractionCSV,
  buildExtractionJSON,
  buildExtractionXML,
  triggerDownload,
} from "@/lib/loan-onboarding/extraction-export";
import { LOAN_DOC_TYPE_LABELS } from "@/lib/loan-onboarding/constants";
import {
  ExtractionWorkbench,
  type WorkbenchFieldRow,
} from "@/components/loan-onboarding/extraction-workbench";
import type {
  LoanExtractionOverride,
  LoanPageOverride,
  LoanStack,
  LoanStackExtraction,
} from "@/lib/loan-onboarding/types";
import { cn } from "@/lib/utils";

/**
 * Type inference + validation helpers for the Reviewed-value column on the
 * Extracted field values list. Mirrors the prototype's classifier — the
 * goal is to give the loan officer a hint about the expected format and to
 * catch obvious typos at save time. No persistence; edits live in component
 * state until we wire a backend correction endpoint.
 */
type FieldKind =
  | "currency"
  | "date"
  | "year"
  | "percentage"
  | "creditScore"
  | "term"
  | "address"
  | "identifier"
  | "text"
  | "enum:bureau"
  | "enum:filingStatus"
  | "enum:loanPurpose";

const FIELD_TYPE_LABEL: Record<FieldKind, string> = {
  currency: "Currency",
  date: "Date",
  year: "Year",
  percentage: "Percentage",
  creditScore: "Credit score",
  term: "Term",
  address: "Address",
  identifier: "Identifier",
  text: "Text",
  "enum:bureau": "Credit bureau",
  "enum:filingStatus": "Filing status",
  "enum:loanPurpose": "Loan purpose",
};

const inferFieldKind = (fieldName: string): FieldKind => {
  const n = (fieldName || "").toLowerCase();
  if (
    /(amount|wages|salary|pay|earnings|income|balance|premium|cash|coverage|price|earnest|consideration|withheld)/.test(
      n
    )
  )
    return "currency";
  if (/(date|period|effective)/.test(n)) return "date";
  if (/year/.test(n)) return "year";
  if (/(rate|apr)/.test(n)) return "percentage";
  if (/credit\s*score/.test(n)) return "creditScore";
  if (/term/.test(n)) return "term";
  if (/address/.test(n)) return "address";
  if (/(account|policy)\s*number/.test(n)) return "identifier";
  if (/license/.test(n)) return "identifier";
  if (/bureau/.test(n)) return "enum:bureau";
  if (/filing\s*status/.test(n)) return "enum:filingStatus";
  if (/loan\s*purpose/.test(n)) return "enum:loanPurpose";
  return "text";
};

/**
 * Reviewed values are stored as opaque text on the backend
 * (`LOExtractionOverride.value` is a `Text` column), so we only enforce
 * "non-empty" here. The inferred `FieldKind` is still surfaced as a chip
 * next to the field name to hint at the expected shape, but it does not
 * gate saves — type-aware coercion is downstream's job.
 */
const validateFieldValue = (value: string, _type: FieldKind): string | null => {
  const v = (value ?? "").trim();
  if (!v) return "Value is required";
  return null;
};

const TERMINAL = new Set(["completed", "failed", "awaiting_review"]);
const STACKS_VISIBLE = 12;

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
  const [extractions, setExtractions] = useState<LoanStackExtraction[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(true);
  // Reviewed-value editing state — drafts, saved values (hydrated from the
  // backend `lo_extraction_overrides` table), per-field errors, and an
  // in-flight set so we can disable Save/Reset while the request is open.
  // Keys are the composite override key `${stack_id}::${doc_type}::${field_name}`
  // — same shape the backend uses for its unique constraint.
  const [fieldEdits, setFieldEdits] = useState<Record<string, string>>({});
  const [fieldSaved, setFieldSaved] = useState<Record<string, string>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string | null>>(
    {}
  );
  const [fieldBusy, setFieldBusy] = useState<Record<string, boolean>>({});
  const [packetDownloading, setPacketDownloading] = useState(false);
  const [packetError, setPacketError] = useState<string | null>(null);
  const [zipDownloading, setZipDownloading] = useState(false);
  const [zipError, setZipError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentOrgId || !packageId) return;
    setSummaryLoading(true);
    Promise.all([
      getStacks(currentOrgId, packageId).catch(() => [] as LoanStack[]),
      listPageOverrides(currentOrgId, packageId).catch(
        () => [] as LoanPageOverride[]
      ),
      getExtractions(currentOrgId, packageId)
        .then((r) => r.stacks)
        .catch(() => [] as LoanStackExtraction[]),
      listExtractionOverrides(currentOrgId, packageId).catch(
        () => [] as LoanExtractionOverride[]
      ),
    ])
      .then(([s, o, ex, fieldOverrides]) => {
        setStacks(s);
        setOverrides(o);
        setExtractions(ex);
        // Seed `fieldSaved` from persisted overrides so re-saved values
        // re-appear with the green Saved badge after a refresh.
        setFieldSaved(
          Object.fromEntries(
            fieldOverrides.map((o) => [
              `${o.stack_id}::${o.doc_type}::${o.field_name}`,
              o.value,
            ])
          )
        );
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

  const reorganized = overrides.length > 0;
  const labelFor = (key: string) => LOAN_DOC_TYPE_LABELS[key] ?? key;
  const sortedOverrides = [...overrides].sort((a, b) => {
    const ap = pageNumberById.get(a.page_id) ?? Number.MAX_SAFE_INTEGER;
    const bp = pageNumberById.get(b.page_id) ?? Number.MAX_SAFE_INTEGER;
    return ap - bp;
  });

  // Stack-level scores grid — show up to STACKS_VISIBLE tiles (4-col grid).
  const visibleStacks = stacks.slice(0, STACKS_VISIBLE);

  // Extracted field values list — flatten one row per configured field,
  // joining real extraction results with synthetic placeholder rows for
  // configured doc types that didn't produce a matching stack. Each row
  // gets a stable composite key so edit state survives re-renders.
  const realExtractionsWithFields = extractions.filter(
    (e) => e.fields.length > 0
  );
  const docTypesWithRealStacks = new Set(
    realExtractionsWithFields.map((e) => e.doc_type)
  );
  const configuredFieldsByDoc = pkg.extraction_fields_by_doc ?? {};
  // Group real stacks by doc_type so placeholder rows can adopt a real
  // stack_id when one exists. Without this, the workbench can't resolve
  // pages for a configured doc type whose extraction never ran (or returned
  // an empty fields list) and renders "No pages in this document".
  const stacksByDocType = new Map<string, LoanStack[]>();
  for (const s of stacks) {
    const arr = stacksByDocType.get(s.doc_type) ?? [];
    arr.push(s);
    stacksByDocType.set(s.doc_type, arr);
  }
  const buildPlaceholderFields = (names: string[]) =>
    names.map((name) => ({
      name,
      value: "",
      confidence: 0,
      status: "missing" as const,
      page: null,
      bbox: null,
    }));
  const placeholderExtractions: LoanStackExtraction[] = pkg.extraction_enabled
    ? Object.entries(configuredFieldsByDoc)
        .filter(
          ([docKey, fields]) =>
            Array.isArray(fields) &&
            fields.length > 0 &&
            !docTypesWithRealStacks.has(docKey)
        )
        .flatMap(([docKey, fields], idx) => {
          const matchingStacks = stacksByDocType.get(docKey) ?? [];
          if (matchingStacks.length > 0) {
            // A real stack of this doc type exists but extraction never
            // ran (or returned no fields). Use the real stack_id so the
            // workbench can render its pages and the bbox resolver can
            // fall through to detected_fields on those pages.
            return matchingStacks.map((stack) => ({
              stack_id: stack.id,
              stack_index: stack.stack_index,
              doc_type: docKey,
              fields: buildPlaceholderFields(fields),
              located_count: 0,
              total_count: fields.length,
            }));
          }
          // No stack of this doc type at all — synthetic placeholder.
          return [
            {
              stack_id: `placeholder-${docKey}`,
              stack_index: 10_000 + idx,
              doc_type: docKey,
              fields: buildPlaceholderFields(fields),
              located_count: 0,
              total_count: fields.length,
            },
          ];
        })
    : [];
  const allExtractions = [
    ...realExtractionsWithFields,
    ...placeholderExtractions,
  ];

  // Each row carries everything the workbench needs to render + everything
  // saveDraft/resetDraft need to round-trip a backend override. The
  // `type` field stays for validateFieldValue (currently a no-op gate),
  // and `fieldTypeLabel` is the "Currency" / "Date" chip the workbench
  // shows next to the field name.
  type FieldRow = WorkbenchFieldRow & { type: FieldKind };
  const flatFields: FieldRow[] = allExtractions.flatMap((e) =>
    e.fields.map((f) => {
      const kind = inferFieldKind(f.name);
      return {
        key: `${e.stack_id}::${e.doc_type}::${f.name}`,
        stackId: e.stack_id,
        docType: e.doc_type,
        docTypeLabel: labelFor(e.doc_type),
        fieldName: f.name,
        fieldTypeLabel: FIELD_TYPE_LABEL[kind],
        originalValue:
          f.status === "missing"
            ? null
            : (f.value ?? "").toString() || null,
        confidence:
          f.status === "missing" ? null : Math.round((f.confidence ?? 0) * 100),
        status: f.status,
        page: f.page ?? null,
        bbox: f.bbox ?? null,
        type: kind,
      };
    })
  );

  // Download counts + filename slug for the Downloads footer on the
  // Extracted field values card. "Located" counts located OR
  // low_confidence so the badge matches what each row renders. The
  // override list snapshots `fieldSaved` so downloads honor unsaved
  // edits the moment the user clicks Save.
  const totalConfiguredFields = flatFields.length;
  const totalExtractedFields = flatFields.filter(
    (f) => f.status === "located" || f.status === "low_confidence"
  ).length;
  const docsWithFields = allExtractions.filter(
    (e) => e.fields.length > 0
  ).length;
  const overridesForExport: LoanExtractionOverride[] = Object.entries(
    fieldSaved
  ).map(([key, value]) => {
    const [stack_id, doc_type, field_name] = key.split("::");
    return {
      id: key,
      package_id: packageId,
      stack_id,
      doc_type,
      field_name,
      value,
      edited_by: null,
      edited_at: new Date().toISOString(),
    };
  });
  const stem =
    (pkg.loan_reference || pkg.name || "loan-package").trim() ||
    "loan-package";
  // Filename-safe slug — file pickers on some browsers reject `/` and `:`.
  const slug = stem.replace(/[^A-Za-z0-9._-]+/g, "-").slice(0, 80);

  // Trigger a browser download from a fetched Blob. Anchor stays attached
  // for the click — Firefox ignores programmatic clicks on detached anchors,
  // and Safari races immediate `revokeObjectURL` against the download.
  const _saveBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };

  // Reorganized final-packet PDF download. The backend assembles pages in
  // current `stack_index` order so any "Move to…" overrides applied in the
  // workbench are reflected immediately — no caching, no re-running the
  // pipeline.
  const downloadFinalPacket = async () => {
    if (!currentOrgId || packetDownloading) return;
    setPacketDownloading(true);
    setPacketError(null);
    try {
      const blob = await fetchFinalPacketPdfBlob(currentOrgId, packageId);
      _saveBlob(blob, `${slug}-final-packet.pdf`);
    } catch (e) {
      setPacketError(
        e instanceof Error ? e.message : "Failed to download final packet"
      );
    } finally {
      setPacketDownloading(false);
    }
  };

  // Per-stack ZIP download — one PDF per detected stack, bundled together.
  // Same `lo_stacks` source-of-truth as the reorganized PDF, so overrides
  // are reflected on the next click.
  const downloadPerStackZip = async () => {
    if (!currentOrgId || zipDownloading) return;
    setZipDownloading(true);
    setZipError(null);
    try {
      const blob = await fetchPerStackZipBlob(currentOrgId, packageId);
      _saveBlob(blob, `${slug}-per-stack.zip`);
    } catch (e) {
      setZipError(
        e instanceof Error ? e.message : "Failed to download per-stack ZIP"
      );
    } finally {
      setZipDownloading(false);
    }
  };

  const getDraft = (row: WorkbenchFieldRow): string => {
    if (fieldEdits[row.key] !== undefined) return fieldEdits[row.key];
    if (fieldSaved[row.key] !== undefined) return fieldSaved[row.key];
    return row.originalValue ?? "";
  };
  const updateDraft = (row: WorkbenchFieldRow, value: string) => {
    setFieldEdits((prev) => ({ ...prev, [row.key]: value }));
    if (fieldErrors[row.key]) {
      const err = validateFieldValue(value, "text");
      setFieldErrors((prev) => ({ ...prev, [row.key]: err }));
    }
  };
  const saveDraft = async (row: WorkbenchFieldRow) => {
    if (!currentOrgId) return;
    const draft = getDraft(row);
    const err = validateFieldValue(draft, "text");
    if (err) {
      setFieldErrors((prev) => ({ ...prev, [row.key]: err }));
      return;
    }
    setFieldBusy((prev) => ({ ...prev, [row.key]: true }));
    try {
      await upsertExtractionOverride(currentOrgId, packageId, {
        doc_type: row.docType,
        field_name: row.fieldName,
        stack_id: row.stackId,
        value: draft,
      });
      setFieldSaved((prev) => ({ ...prev, [row.key]: draft }));
      setFieldEdits((prev) => {
        const next = { ...prev };
        delete next[row.key];
        return next;
      });
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[row.key];
        return next;
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to save";
      setFieldErrors((prev) => ({ ...prev, [row.key]: msg }));
    } finally {
      setFieldBusy((prev) => {
        const next = { ...prev };
        delete next[row.key];
        return next;
      });
    }
  };
  const resetDraft = async (row: WorkbenchFieldRow) => {
    if (!currentOrgId) return;
    // Local-only edits never hit the server, so a Reset on an unsaved
    // draft just clears local state. Saved values must be deleted on the
    // backend so the next download reflects the AI value again.
    const wasPersisted = fieldSaved[row.key] !== undefined;
    if (wasPersisted) {
      setFieldBusy((prev) => ({ ...prev, [row.key]: true }));
      try {
        await deleteExtractionOverride(currentOrgId, packageId, {
          doc_type: row.docType,
          field_name: row.fieldName,
          stack_id: row.stackId,
        });
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Failed to reset";
        setFieldErrors((prev) => ({ ...prev, [row.key]: msg }));
        setFieldBusy((prev) => {
          const next = { ...prev };
          delete next[row.key];
          return next;
        });
        return;
      }
      setFieldBusy((prev) => {
        const next = { ...prev };
        delete next[row.key];
        return next;
      });
    }
    setFieldEdits((prev) => {
      const next = { ...prev };
      delete next[row.key];
      return next;
    });
    setFieldSaved((prev) => {
      const next = { ...prev };
      delete next[row.key];
      return next;
    });
    setFieldErrors((prev) => {
      const next = { ...prev };
      delete next[row.key];
      return next;
    });
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

            <div className="grid grid-cols-2 gap-3 items-stretch">
              <button
                type="button"
                onClick={() => {
                  void downloadFinalPacket();
                }}
                disabled={
                  packetDownloading ||
                  !currentOrgId ||
                  stacks.length === 0 ||
                  liveStatus === "uploading" ||
                  liveStatus === "processing"
                }
                title={
                  liveStatus === "uploading" || liveStatus === "processing"
                    ? "Available once processing completes"
                    : stacks.length === 0
                    ? "No stacks to assemble yet"
                    : "Download the reorganized PDF"
                }
                className="px-4 py-3 bg-amber-500 text-white text-[13px] font-medium flex items-center justify-center gap-2 rounded-md shadow-sm hover:bg-amber-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                data-testid="download-final-packet"
              >
                <Download className="h-4 w-4" />
                {packetDownloading
                  ? "Preparing PDF…"
                  : "Download final packet (reorganized)"}
              </button>
              <button
                type="button"
                onClick={() => {
                  void downloadPerStackZip();
                }}
                disabled={
                  zipDownloading ||
                  !currentOrgId ||
                  stacks.length === 0 ||
                  liveStatus === "uploading" ||
                  liveStatus === "processing"
                }
                title={
                  liveStatus === "uploading" || liveStatus === "processing"
                    ? "Available once processing completes"
                    : stacks.length === 0
                    ? "No stacks to assemble yet"
                    : "Download one PDF per stack, bundled in a ZIP"
                }
                className="px-4 py-3 bg-amber-100 text-amber-900 text-[13px] font-medium border border-amber-200 flex items-center justify-center gap-2 rounded-md shadow-sm hover:bg-amber-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                data-testid="download-per-stack-zip"
              >
                <Layers className="h-4 w-4" />
                {zipDownloading ? "Preparing ZIP…" : "Per-stack ZIP"}
              </button>
            </div>
            <div className="flex items-center gap-2 mt-3 text-[11px] text-muted-foreground">
              <AlertCircle className="h-3 w-3" />
              Reorganized packet is regenerated on download — page order,
              bookmarks, and stack-level tables of contents reflect the
              current classification.
            </div>
            {packetError && (
              <div
                className="mt-2 text-[11px] text-destructive"
                data-testid="download-final-packet-error"
              >
                {packetError}
              </div>
            )}
            {zipError && (
              <div
                className="mt-2 text-[11px] text-destructive"
                data-testid="download-per-stack-zip-error"
              >
                {zipError}
              </div>
            )}

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

      {/* Stack-level scores grid — compact 4-col grid mirroring the
          Loan Onboarding prototype: serif name + status dot + big serif
          percentage + page count. Shows up to STACKS_VISIBLE tiles. */}
      <div
        className="bg-card border border-border"
        data-testid="stack-scores-grid"
      >
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <div className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground uppercase">
            Stack-level scores
          </div>
          {stacks.length > 0 && (
            <span className="font-mono text-[10px] text-muted-foreground tabular-nums">
              {stacks.length > STACKS_VISIBLE
                ? `Top ${STACKS_VISIBLE} of ${stacks.length}`
                : `${stacks.length} stack${stacks.length === 1 ? "" : "s"}`}
            </span>
          )}
        </div>
        {visibleStacks.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {summaryLoading ? "Loading stacks…" : "No stacks available yet."}
          </p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-0">
            {visibleStacks.map((s, i) => {
              const overall = s.overall_confidence ?? null;
              const pct = overall == null ? null : Math.round(overall * 100);
              const dot =
                pct == null
                  ? "bg-muted-foreground/40"
                  : pct >= 90
                    ? "bg-emerald-500"
                    : pct >= 75
                      ? "bg-amber-500"
                      : "bg-red-500";
              const numberColor =
                pct == null
                  ? "text-muted-foreground"
                  : pct >= 75
                    ? "text-emerald-600"
                    : "text-red-600";
              const col = i % 4;
              const row = Math.floor(i / 4);
              const lastRow = Math.floor((visibleStacks.length - 1) / 4);
              return (
                <div
                  key={s.id}
                  className={cn(
                    "p-4 border-border",
                    col !== 3 && "md:border-r",
                    row !== lastRow && "border-b"
                  )}
                  data-testid={`stack-tile-${s.stack_index}`}
                >
                  <div className="flex items-start justify-between mb-1.5">
                    <div className="font-serif text-[13px] text-foreground leading-tight">
                      {labelFor(s.doc_type)}
                    </div>
                    <span
                      className={cn(
                        "w-1.5 h-1.5 rounded-full mt-1.5 shrink-0",
                        dot
                      )}
                      aria-hidden
                    />
                  </div>
                  <div className="flex items-baseline gap-2">
                    <div
                      className={cn(
                        "font-serif text-[22px] leading-none tabular-nums",
                        numberColor
                      )}
                    >
                      {pct == null ? "—" : pct}
                    </div>
                    <div className="font-mono text-[10px] text-muted-foreground">
                      %
                    </div>
                  </div>
                  <div className="font-mono text-[10px] text-muted-foreground mt-1">
                    {s.page_count} page{s.page_count === 1 ? "" : "s"}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Extracted field values — 3-column workbench mirroring the
          prototype: documents sidebar, page viewer with bbox highlight,
          and per-field editor with pencil-to-edit + save / cancel. */}
      {(pkg.extraction_enabled || flatFields.length > 0) && (
        <div
          className="space-y-4"
          data-testid="extraction-fields-section"
        >
          {flatFields.length === 0 ? (
            <div
              className="bg-card border border-border px-6 py-12 text-center"
              data-testid="extraction-fields-empty"
            >
              <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase mb-2">
                No fields configured
              </div>
              <div className="text-[12px] text-muted-foreground">
                {summaryLoading
                  ? "Loading extracted fields…"
                  : "No extraction fields were chosen for this package. Configure fields in the upload step to enable downstream exports."}
              </div>
            </div>
          ) : (
            <>
              {currentOrgId && (
                <ExtractionWorkbench
                  orgId={currentOrgId}
                  packageId={packageId}
                  extractions={allExtractions}
                  stacks={stacks}
                  rows={flatFields}
                  fieldEdits={fieldEdits}
                  fieldSaved={fieldSaved}
                  fieldErrors={fieldErrors}
                  fieldBusy={fieldBusy}
                  onChangeDraft={updateDraft}
                  onSaveDraft={saveDraft}
                  onCancelDraft={resetDraft}
                />
              )}

              {/* Downloads — JSON / CSV / MISMO XML feeds for the LOS. */}
              <div
                className="bg-card border border-border px-6 py-5"
                data-testid="extraction-downloads-card"
              >
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase">
                      Downloads
                    </div>
                    <div className="text-[12px] text-muted-foreground mt-0.5">
                      Download the extracted field set in the format your
                      downstream LOS expects.
                    </div>
                  </div>
                  <span className="font-mono text-[9px] tracking-[0.15em] uppercase px-2 py-0.5 rounded bg-background border border-border text-muted-foreground tabular-nums">
                    {totalExtractedFields}/{totalConfiguredFields} located ·{" "}
                    {docsWithFields} doc{docsWithFields === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <button
                    type="button"
                    onClick={() =>
                      triggerDownload(
                        `extraction-${slug}.json`,
                        buildExtractionJSON(allExtractions, pkg, overridesForExport),
                        "application/json"
                      )
                    }
                    className="px-4 py-3 bg-amber-500 text-white text-[13px] font-medium flex items-center justify-center gap-2 rounded-md shadow-sm hover:bg-amber-600 transition-colors"
                    data-testid="extraction-download-json"
                  >
                    <Download className="h-4 w-4" /> JSON
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      triggerDownload(
                        `extraction-${slug}.csv`,
                        buildExtractionCSV(allExtractions, overridesForExport),
                        "text/csv"
                      )
                    }
                    className="px-4 py-3 bg-amber-500 text-white text-[13px] font-medium flex items-center justify-center gap-2 rounded-md shadow-sm hover:bg-amber-600 transition-colors"
                    data-testid="extraction-download-csv"
                  >
                    <Download className="h-4 w-4" /> CSV
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      triggerDownload(
                        `extraction-${slug}.xml`,
                        buildExtractionXML(allExtractions, pkg, overridesForExport),
                        "application/xml"
                      )
                    }
                    className="px-4 py-3 bg-amber-500 text-white text-[13px] font-medium flex items-center justify-center gap-2 rounded-md shadow-sm hover:bg-amber-600 transition-colors"
                    data-testid="extraction-download-mismo"
                  >
                    <Download className="h-4 w-4" /> MISMO XML
                  </button>
                </div>
                <div className="flex items-center gap-2 mt-3 text-[11px] text-muted-foreground">
                  <AlertCircle className="h-3 w-3" />
                  Field-level confidence is preserved in every export. Missing
                  fields are flagged with status=&quot;missing&quot; so
                  downstream systems can route them for follow-up.
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
