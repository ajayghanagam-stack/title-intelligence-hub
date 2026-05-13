"use client";

// Phase 5.2 — LogikIntake loan-overview page.
//
// Layout mirrors the LGK-0851 prototype (prototype/src/app/logik-intake/
// loans/[loanId]/page.tsx):
//   1. Slim header (LoanHeader, pipeline rail hidden — see below)
//   2. Upload banner (only while files are still being POSTed)
//   3. Pipeline rail CARD with numbered stages + info banner + optional
//      hard-stop banner
//   4. "Documents (N) · X Progressing · Y Review Needed" chip row
//   5. Flat 4-column doc-card grid with stage pills derived from each
//      stack's `classification_status` and `extraction_status`
//   6. Decision-Ready advance footer (preserved from the old layout)
//
// The pipeline rail is rendered as a standalone card here instead of
// inside `LoanHeader` because the prototype's rich rail includes
// "Complete" / "Bottleneck" sub-labels and per-stage drilldown links
// that don't fit the slim header rail. `LoanHeader` accepts
// `hidePipelineRail` so the sub-pages keep their existing slim rail.

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  Clock,
  Eye,
  FileText,
  Info,
  Loader2,
  RefreshCw,
} from "lucide-react";

import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import {
  useLoanDocuments,
  useLoanPipeline,
  useLoanValidations,
} from "@/hooks/use-loan-operator";
import { LoanHeader } from "@/components/loan-onboarding/logik-intake/loan-header";
import {
  PipelineStagesBar,
  getBottleneckStage,
} from "@/components/loan-onboarding/logik-intake/pipeline-stages-bar";
import { RemediationModal } from "@/components/loan-onboarding/logik-intake/remediation-modal";
import {
  processPackage,
  uploadPackageFiles,
} from "@/lib/loan-onboarding/api";
import { dequeueUpload } from "@/lib/loan-onboarding/upload-queue";
import { cn } from "@/lib/utils";
import type {
  LoanClassificationStatus,
  LoanExtractionStatus,
  LoanStack,
} from "@/lib/loan-onboarding/types";

type UploadPhase =
  | { kind: "idle" }
  | { kind: "uploading"; fileCount: number; totalBytes: number }
  | { kind: "starting" }
  | { kind: "done" }
  | { kind: "error"; message: string };

// Operator-facing pill state per doc card. Derived from the stack's
// classification/extraction statuses below — kept in the page so the
// derivation rules stay co-located with the pill visuals.
type DocStage =
  | "classify-review"
  | "doc-fail"
  | "extracting"
  | "extracted"
  | "validating"
  | "validated";

function deriveDocStage(
  doc: LoanStack,
  pipelineFinished: boolean,
): DocStage {
  if (
    doc.classification_status === "needs_review" ||
    doc.classification_status === "unclassifiable"
  ) {
    return "classify-review";
  }
  if (doc.status === "rejected") return "doc-fail";
  switch (doc.extraction_status) {
    case "confirmed":
      return "validated";
    case "needs_review":
      // Surface low-confidence/missing-field extractions as a separate
      // "Extracted" pill so the operator drills into the extract page;
      // the prototype lumps both into "Extracted" with the action being
      // implicit on click.
      return "extracted";
    case "extracted":
      return "extracted";
    case "extracting":
      return "extracting";
    case "not_started":
    default:
      // `not_started` covers two very different things:
      //   1. The extract stage hasn't started yet (pipeline still running)
      //   2. Extraction was *skipped* for this stack (extraction_enabled=False,
      //      no schema for this doc_type, or it's the Others bucket)
      // Previously we optimistically returned "extracting" for both, which
      // left case (2) showing "Extracting…" forever after the pipeline
      // finished. Once the pipeline is done, fall back to whatever
      // terminal pill the stack's own status indicates:
      //   - accepted  → "validated" (reviewer approved without field extraction)
      //   - validated → "validated" (validate stage passed, extract skipped)
      //   - anything else (classified/pending) is treated as still in flight
      //     so we don't lie about state mid-pipeline if our detection is off.
      if (pipelineFinished) {
        if (doc.status === "accepted" || doc.status === "validated") {
          return "validated";
        }
        // Catch-all terminal for stacks the pipeline finished on without
        // a clear extract row — surface the classify-review pill so the
        // reviewer is prompted to act rather than waiting for nothing.
        return "classify-review";
      }
      return "extracting";
  }
}

// Mirrors `isPipelineFinished` in pipeline-stages-bar.tsx. Duplicated
// (rather than imported) because pipeline-stages-bar's helper is a private
// module function — exporting it would widen its API surface for a single
// caller. Two short, identical functions is cheaper than the indirection.
function isPipelineFinishedLoose(
  pipelineStage: string | null,
  status: string,
): boolean {
  return (
    status === "completed" ||
    status === "decision_ready" ||
    status === "awaiting_review" ||
    pipelineStage === "complete"
  );
}

// Per-document 5-stage progression dots (mirrors the prototype + v6.html).
// Each card shows a row of 5 small circles, one per pipeline stage:
//   Ingestion → Classification → Doc Validation → Extraction → Data Validation
// Status mapping:
//   - Ingestion is always "done" (we only render docs that have been ingested).
//   - Classification reflects LoanStack.classification_status.
//   - Doc Validation tracks completion of classification (the deterministic
//     validation runs immediately after classify).
//   - Extraction / Data Validation reflect LoanStack.extraction_status.
type DotStatus = "done" | "block" | "todo";

function computeStageDots(d: LoanStack): DotStatus[] {
  const classifyOk = d.classification_status === "classified";
  const classifyBlocked =
    d.classification_status === "needs_review" ||
    d.classification_status === "unclassifiable";
  const extracted =
    d.extraction_status === "extracted" ||
    d.extraction_status === "needs_review" ||
    d.extraction_status === "confirmed";
  const confirmed = d.extraction_status === "confirmed";
  return [
    "done",
    classifyOk ? "done" : classifyBlocked ? "block" : "todo",
    classifyOk ? "done" : "todo",
    extracted ? "done" : "todo",
    confirmed ? "done" : "todo",
  ];
}

const DOT_COLORS: Record<DotStatus, string> = {
  done: "bg-brand-teal border-brand-teal",
  block: "bg-brand-orange border-brand-orange",
  todo: "bg-card border-border",
};

const STAGE_PILL: Record<
  DocStage,
  { label: string; tone: string; Icon: typeof Check }
> = {
  extracted: {
    label: "Extracted ✓",
    tone: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    Icon: Check,
  },
  validated: {
    label: "Validated ✓",
    tone: "bg-brand-teal/10 text-brand-teal ring-brand-teal/30",
    Icon: Check,
  },
  extracting: {
    label: "Extracting…",
    tone: "bg-sky-50 text-sky-700 ring-sky-200",
    Icon: RefreshCw,
  },
  validating: {
    label: "Validating…",
    tone: "bg-brand-teal/10 text-brand-teal ring-brand-teal/30",
    Icon: RefreshCw,
  },
  "classify-review": {
    label: "Classify — Review",
    tone: "bg-brand-orange/15 text-[#7A5000] ring-brand-orange/40",
    Icon: Eye,
  },
  "doc-fail": {
    label: "Validation Issue",
    tone: "bg-rose-50 text-rose-700 ring-rose-200",
    Icon: AlertTriangle,
  },
};

export default function LoanOverviewPage({
  params,
}: {
  params: { loanId: string };
}) {
  const { loanId } = params;
  const { orgPath } = useOrgSlug();
  const { currentOrgId } = useOrg();
  const queryClient = useQueryClient();
  const { package: loan, loading: loanLoading, refetch: refetchLoan } =
    useLoanPackage(loanId);
  const { data: documents = [], isLoading: docsLoading } =
    useLoanDocuments(loanId);
  const { data: validations = [] } = useLoanValidations(loanId);
  // Pulls /pipeline so the rail can label each completed stage with its
  // elapsed-seconds — the package poll alone only carries pipeline_stage,
  // not the per-stage timing map.
  const { data: pipeline } = useLoanPipeline(loanId);
  const [remediating, setRemediating] = useState<LoanStack | null>(null);
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>({ kind: "idle" });

  // Dequeue and drive the upload + processPackage handoff from the modal.
  // Module-level Map.delete makes this StrictMode-safe — no `cancelled`
  // flag needed (and the flag would actively break the upload in dev).
  useEffect(() => {
    const queued = dequeueUpload(loanId);
    if (!queued) return;
    const fileCount = queued.files.length;
    const totalBytes = queued.files.reduce((sum, f) => sum + f.size, 0);
    setUploadPhase({ kind: "uploading", fileCount, totalBytes });
    (async () => {
      try {
        await uploadPackageFiles(queued.orgId, loanId, queued.files);
        setUploadPhase({ kind: "starting" });
        await processPackage(queued.orgId, loanId);
        await refetchLoan();
        setUploadPhase({ kind: "done" });
      } catch (err) {
        setUploadPhase({
          kind: "error",
          message: err instanceof Error ? err.message : "Upload failed",
        });
      }
    })();
  }, [loanId, refetchLoan]);

  // ── Validation rollups for the banners ──────────────────────────────
  // Hard stops + open soft flags come from the per-stack rule evaluations;
  // we don't have a top-level field for them on LOPackage so we compute
  // them here. Cheap — N rules per stack is tiny.
  const openHardStops = useMemo(() => {
    let n = 0;
    for (const vr of validations) {
      for (const r of vr.rules_evaluated || []) {
        const isHard = (r.severity || r.type || "").toLowerCase() === "hard";
        if (!r.passed && isHard) n += 1;
      }
    }
    return n;
  }, [validations]);

  // ── Force one final refetch when the pipeline terminates ───────────
  // useLoanDocuments stops polling the moment the package flips into
  // `awaiting_review` (a terminal state from the operator's POV). If the
  // last in-flight poll happened *before* stage_review wrote its final
  // accepted/needs_review/rejected stack statuses (a 3s race window), the
  // doc grid would otherwise stay frozen on stale "validated" rows
  // forever — producing the "Extracting…" stuck-state. Triggering one
  // forced invalidation when status transitions to terminal closes that
  // race.
  const prevStatusRef = useRef<string | null>(null);
  useEffect(() => {
    if (!loan) return;
    const prev = prevStatusRef.current;
    const cur = loan.status;
    prevStatusRef.current = cur;
    if (prev === null) return; // first observation — nothing to compare
    if (prev === cur) return;
    const TERMINAL = new Set([
      "completed",
      "awaiting_review",
      "decision_ready",
      "failed",
    ]);
    if (TERMINAL.has(cur) && !TERMINAL.has(prev)) {
      // Status just flipped non-terminal → terminal. Force a final refetch
      // of the views that stopped polling so they pick up the post-review
      // stack statuses (accepted/needs_review/rejected) and extraction
      // rows that landed in the last write batch.
      queryClient.invalidateQueries({
        queryKey: ["lo-loan-documents", currentOrgId, loanId],
      });
      queryClient.invalidateQueries({
        queryKey: ["lo-loan-validations", currentOrgId, loanId],
      });
      queryClient.invalidateQueries({
        queryKey: ["lo-loan-checklist", currentOrgId, loanId],
      });
    }
  }, [loan, queryClient, currentOrgId, loanId]);

  const pipelineFinished = useMemo(
    () =>
      loan
        ? isPipelineFinishedLoose(loan.pipeline_stage, loan.status)
        : false,
    [loan],
  );

  // ── Document-grid rollups ────────────────────────────────────────────
  const docStages = useMemo(
    () =>
      documents.map((d) => ({
        doc: d,
        stage: deriveDocStage(d, pipelineFinished),
      })),
    [documents, pipelineFinished],
  );
  const reviewNeeded = useMemo(
    () => docStages.filter(({ stage }) => stage === "classify-review").length,
    [docStages],
  );
  const progressing = useMemo(
    () =>
      docStages.filter(
        ({ stage }) => stage !== "classify-review" && stage !== "doc-fail",
      ).length,
    [docStages],
  );

  if (loanLoading || !loan) {
    return (
      <div className="mx-auto max-w-7xl px-2 py-8">
        <p className="text-sm text-muted-foreground">Loading loan file…</p>
      </div>
    );
  }

  const bottleneck = getBottleneckStage(loan.pipeline_stage, loan.status);

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-2 py-2">
      <LoanHeader
        loan={loan}
        hidePipelineRail
        actions={
          bottleneck && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-orange/15 px-3 py-1.5 text-[11px] font-bold text-[#7A5000] ring-1 ring-brand-orange/40">
              <Clock className="h-3 w-3" />
              Bottleneck: Stage {bottleneck.index + 1} — {bottleneck.label}
            </span>
          )
        }
      />

      <UploadBanner phase={uploadPhase} />

      <PipelineRailCard
        loanId={loanId}
        loan={loan}
        totalDocs={documents.length}
        progressing={progressing}
        reviewNeeded={reviewNeeded}
        bottleneckLabel={bottleneck?.label ?? "Classification"}
        openHardStops={openHardStops}
        orgPath={orgPath}
        stageTimings={pipeline?.stage_timings}
      />

      <DocCountHeader
        total={documents.length}
        progressing={progressing}
        reviewNeeded={reviewNeeded}
      />

      {docsLoading ? (
        <p className="text-sm text-muted-foreground">Loading documents…</p>
      ) : documents.length === 0 ? (
        <DocsEmptyState
          pipelineStage={loan.pipeline_stage}
          status={loan.status}
        />
      ) : (
        <DocCardGrid
          loanId={loanId}
          docStages={docStages}
          orgPath={orgPath}
          onRemediate={setRemediating}
        />
      )}

      <RemediationModal
        open={remediating !== null}
        onClose={() => setRemediating(null)}
        loanId={loanId}
        stack={remediating}
      />
    </div>
  );
}

function UploadBanner({ phase }: { phase: UploadPhase }) {
  if (phase.kind === "idle" || phase.kind === "done") return null;
  if (phase.kind === "error") {
    return (
      <div className="rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        Upload failed: {phase.message}
      </div>
    );
  }
  const label =
    phase.kind === "uploading"
      ? `Uploading ${phase.fileCount} file${phase.fileCount === 1 ? "" : "s"} (${(
          phase.totalBytes /
          1024 /
          1024
        ).toFixed(1)} MB)…`
      : "Starting pipeline…";
  return (
    <div className="flex items-center gap-3 rounded-xl border border-brand-teal/40 bg-brand-teal/10 p-4 text-sm text-brand-charcoal">
      <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand-teal" />
      <span>{label}</span>
    </div>
  );
}

function PipelineRailCard({
  loanId,
  loan,
  totalDocs,
  progressing,
  reviewNeeded,
  bottleneckLabel,
  openHardStops,
  orgPath,
  stageTimings,
}: {
  loanId: string;
  loan: { pipeline_stage: string | null; status: string };
  totalDocs: number;
  progressing: number;
  reviewNeeded: number;
  bottleneckLabel: string;
  openHardStops: number;
  orgPath: (p: string) => string;
  stageTimings?: Array<{ stage: string; elapsed_seconds: number | null }>;
}) {
  return (
    <section className="card-warm px-6 py-5">
      <p className="mb-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        Streaming Pipeline — Every document flows through all 5 stages
        independently
      </p>
      <PipelineStagesBar
        currentStage={loan.pipeline_stage}
        status={loan.status}
        richLayout
        loanId={loanId}
        orgPath={orgPath}
        stageTimings={stageTimings}
      />
      <PipelineInfoBanner
        totalDocs={totalDocs}
        progressing={progressing}
        reviewNeeded={reviewNeeded}
        bottleneckLabel={bottleneckLabel}
        pipelineStage={loan.pipeline_stage}
        status={loan.status}
      />
      {openHardStops > 0 && (
        <Link
          href={orgPath(
            `/apps/loan-onboarding/loans/${loanId}/doc-validation`,
          )}
          className="mt-2 flex items-start gap-2.5 rounded-md border border-rose-200 bg-rose-50/70 px-3.5 py-2.5 text-[12px] leading-relaxed text-[#7F1D1D] transition hover:bg-rose-50"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
          <span>
            <strong>
              {openHardStops} hard stop{openHardStops === 1 ? "" : "s"}
            </strong>{" "}
            blocking advance to Extraction. Open the Doc Validation page to
            upload the missing document(s) or record a supervisor override.{" "}
            <span className="font-bold text-rose-700 underline">
              Open Doc Validation →
            </span>
          </span>
        </Link>
      )}
    </section>
  );
}

function PipelineInfoBanner({
  totalDocs,
  progressing,
  reviewNeeded,
  bottleneckLabel,
  pipelineStage,
  status,
}: {
  totalDocs: number;
  progressing: number;
  reviewNeeded: number;
  bottleneckLabel: string;
  pipelineStage: string | null;
  status: string;
}) {
  // While no LOStack rows have surfaced yet, the per-doc rollup ("All N
  // documents are flowing simultaneously…") is nonsense — we don't know
  // N yet. Show a stage-aware processing/terminal message instead.
  if (totalDocs === 0) {
    const message = emptyStageMessage(pipelineStage, status);
    return (
      <div className="mt-4 flex items-start gap-2.5 rounded-md border border-sky-200 bg-sky-50/60 px-3.5 py-2.5 text-[12px] leading-relaxed text-[#003D52]">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-brand-teal" />
        <span>{message}</span>
      </div>
    );
  }
  return (
    <div className="mt-4 flex items-start gap-2.5 rounded-md border border-sky-200 bg-sky-50/60 px-3.5 py-2.5 text-[12px] leading-relaxed text-[#003D52]">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-brand-teal" />
      <span>
        All {totalDocs} document{totalDocs === 1 ? "" : "s"}{" "}
        {totalDocs === 1 ? "is" : "are"} flowing simultaneously.{" "}
        <strong>
          {progressing} {progressing === 1 ? "is" : "are"} already at later
          stages
        </strong>
        .{" "}
        {reviewNeeded > 0 ? (
          <>
            <strong>
              {reviewNeeded} {reviewNeeded === 1 ? "is" : "are"} blocked at{" "}
              {bottleneckLabel}
            </strong>{" "}
            waiting for review.{" "}
          </>
        ) : null}
        The 5 coloured dots show each document&apos;s per-stage progress.
      </span>
    </div>
  );
}

// Branches the empty-state copy on where the pipeline actually is so the
// reader sees an accurate state rather than the same "may still be processing"
// line at every stage.
function emptyStageMessage(
  pipelineStage: string | null,
  status: string,
): string {
  if (status === "failed") {
    return "Pipeline failed before any documents could be classified. Check the loan timeline for details.";
  }
  if (status === "completed") {
    return "Pipeline completed but no documents were classified from this upload. Verify the source PDFs contain readable content.";
  }
  const stage = (pipelineStage || "").toLowerCase();
  if (stage === "ingest" || stage === "" || pipelineStage === null) {
    return "Pipeline is ingesting the uploaded files — documents will appear once classification starts.";
  }
  if (stage === "classify") {
    return "Pipeline is classifying pages — documents will appear here as soon as each one is identified.";
  }
  if (stage === "stack") {
    return "Pipeline is grouping classified pages into documents — they should appear in a few seconds.";
  }
  if (stage === "validate" || stage === "review") {
    return "Pipeline has reached validation but no documents have surfaced yet — refreshing shortly.";
  }
  return "Pipeline is still processing — documents will appear as they are identified.";
}

function DocCountHeader({
  total,
  progressing,
  reviewNeeded,
}: {
  total: number;
  progressing: number;
  reviewNeeded: number;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[13px] font-bold">Documents ({total})</span>
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-200">
        {progressing} Progressing
      </span>
      <span className="inline-flex items-center gap-1 rounded-full bg-brand-orange/15 px-2 py-0.5 text-[10px] font-bold text-[#7A5000] ring-1 ring-brand-orange/40">
        {reviewNeeded} Blocked — Review Needed
      </span>
    </div>
  );
}

function DocsEmptyState({
  pipelineStage,
  status,
}: {
  pipelineStage: string | null;
  status: string;
}) {
  return (
    <div className="rounded-lg border border-dashed bg-muted/30 p-10 text-center text-sm text-muted-foreground">
      {emptyStageMessage(pipelineStage, status)}
    </div>
  );
}

function DocCardGrid({
  loanId,
  docStages,
  orgPath,
  onRemediate,
}: {
  loanId: string;
  docStages: Array<{ doc: LoanStack; stage: DocStage }>;
  orgPath: (p: string) => string;
  onRemediate: (doc: LoanStack) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
      {docStages.map(({ doc, stage }) => (
        <DocCard
          key={doc.id}
          doc={doc}
          stage={stage}
          loanId={loanId}
          orgPath={orgPath}
          onRemediate={onRemediate}
        />
      ))}
    </div>
  );
}

function DocCard({
  doc,
  stage,
  loanId,
  orgPath,
  onRemediate,
}: {
  doc: LoanStack;
  stage: DocStage;
  loanId: string;
  orgPath: (p: string) => string;
  onRemediate: (doc: LoanStack) => void;
}) {
  const pill = STAGE_PILL[stage];
  const StageIcon = pill.Icon;
  const dots = computeStageDots(doc);
  const needsAction = stage === "classify-review";
  const isProcessing = stage === "extracting" || stage === "validating";
  const isFail = stage === "doc-fail";
  const href = (() => {
    if (needsAction) {
      return orgPath(
        `/apps/loan-onboarding/loans/${loanId}/classify/${doc.id}`,
      );
    }
    if (stage === "extracted" || stage === "validated") {
      return orgPath(
        `/apps/loan-onboarding/loans/${loanId}/extract/${doc.id}`,
      );
    }
    return null;
  })();

  const cardClasses = cn(
    "group rounded-md border-[1.5px] bg-card p-3 transition hover:-translate-y-px hover:border-brand-teal hover:shadow-md",
    needsAction && "border-brand-orange bg-brand-orange/5",
    isProcessing && "border-brand-teal bg-brand-teal/5",
    isFail && "border-rose-300 bg-rose-50/60",
    !needsAction && !isProcessing && !isFail && "border-border opacity-90",
  );

  const body = (
    <>
      <FileText className="mb-1 h-4 w-4 text-brand-teal opacity-50" />
      <p
        className="truncate text-[11px] font-bold text-foreground"
        title={doc.doc_type}
      >
        {doc.doc_type || "Unclassified"}
      </p>
      <p className="truncate text-[10px] text-muted-foreground">
        Pages {doc.first_page}–{doc.last_page} · {doc.page_count} pp
      </p>
      <div className="my-2 flex gap-1" aria-label="Per-stage progress">
        {dots.map((d, i) => (
          <span
            key={i}
            className={cn(
              "h-2 w-2 rounded-full border",
              DOT_COLORS[d],
            )}
          />
        ))}
      </div>
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-bold ring-1",
          pill.tone,
        )}
      >
        <StageIcon className="h-2.5 w-2.5" />
        {pill.label}
      </span>
    </>
  );

  // HITL classify-review surfaces still use a Link to the classify page;
  // the prototype's "remediation" affordance is a button — we keep the
  // remediation button path for `doc-fail` only (where the operator
  // needs to upload a replacement) so classify-review can be a single
  // click into the existing review flow.
  if (isFail) {
    return (
      <button
        type="button"
        onClick={() => onRemediate(doc)}
        className={cn(cardClasses, "block w-full text-left")}
      >
        {body}
      </button>
    );
  }
  if (!href) {
    return <div className={cardClasses}>{body}</div>;
  }
  return (
    <Link href={href} className={cardClasses}>
      {body}
    </Link>
  );
}


