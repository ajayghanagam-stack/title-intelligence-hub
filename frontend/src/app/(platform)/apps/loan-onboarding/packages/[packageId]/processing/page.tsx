"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AlertCircle, ArrowRight, Clock, Loader2, Upload } from "lucide-react";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import { useLoanPipeline } from "@/hooks/use-loan-pipeline";
import { PipelineProgress } from "@/components/loan-onboarding/pipeline-progress";
import { PackageStatusBadge } from "@/components/loan-onboarding/package-status-badge";
import { uploadFiles } from "@/lib/api";
import { processPackage } from "@/lib/loan-onboarding/api";
import { dequeueUpload } from "@/lib/loan-onboarding/upload-queue";

const TERMINAL = new Set(["completed", "failed", "awaiting_review"]);

type UploadPhase =
  | { kind: "idle" }
  | { kind: "uploading"; fileCount: number; totalBytes: number }
  | { kind: "starting" }
  | { kind: "done" }
  | { kind: "error"; message: string };

function formatElapsed(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds - minutes * 60);
  return `${minutes}m ${rem}s`;
}

function formatMb(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Processing tab — dual purpose:
 *
 * 1. **Pre-flight**: when the user lands here straight from "Create & Process
 *    Package", the new-package form has stashed the selected `File` objects
 *    in the upload queue. We dequeue them here, run the multipart upload +
 *    pipeline trigger from this page, and surface progress as an "Uploading
 *    files…" banner above the (placeholder) stepper. This eliminates the
 *    dead-time the user used to see while the previous screen blocked on
 *    upload.
 *
 * 2. **In-flight / terminal**: while the pipeline runs, renders the live
 *    vertical stepper. Once the pipeline reaches a terminal state
 *    (completed / failed / awaiting_review) the same view becomes a
 *    read-only run summary (status pill, total elapsed, per-stage timings,
 *    error block) with a CTA over to Results.
 */
export default function LoanPackageProcessingPage() {
  const params = useParams();
  const router = useRouter();
  const packageId = params.packageId as string;
  const { orgPath } = useOrgSlug();
  const { package: pkg, loading } = useLoanPackage(packageId);
  const { pipeline } = useLoanPipeline(
    packageId,
    pkg ? !TERMINAL.has(pkg.status) : true
  );

  const [uploadPhase, setUploadPhase] = useState<UploadPhase>({ kind: "idle" });
  // Guard against StrictMode double-invoke and per-mount re-runs.
  const handoffStartedRef = useRef(false);
  // Guard so we only schedule the auto-redirect once per terminal transition.
  const redirectScheduledRef = useRef(false);

  // Pre-flight: if the new-package form handed off an upload payload for
  // this package id, drive the upload + pipeline trigger from here.
  useEffect(() => {
    if (handoffStartedRef.current) return;
    const queued = dequeueUpload(packageId);
    if (!queued) return;
    handoffStartedRef.current = true;

    const totalBytes = queued.files.reduce((s, f) => s + f.size, 0);
    setUploadPhase({
      kind: "uploading",
      fileCount: queued.files.length,
      totalBytes,
    });

    let cancelled = false;
    (async () => {
      try {
        await uploadFiles(
          `/api/v1/apps/loan-onboarding/packages/${packageId}/files`,
          queued.files,
          { orgId: queued.orgId }
        );
        if (cancelled) return;
        setUploadPhase({ kind: "starting" });
        await processPackage(queued.orgId, packageId);
        if (cancelled) return;
        setUploadPhase({ kind: "done" });
      } catch (err) {
        if (cancelled) return;
        setUploadPhase({
          kind: "error",
          message:
            err instanceof Error ? err.message : "Upload failed. Please retry.",
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [packageId]);

  const liveStatus = pipeline?.status ?? pkg?.status;
  const isTerminal = !!liveStatus && TERMINAL.has(liveStatus);
  const resultsHref = orgPath(
    `/apps/loan-onboarding/packages/${packageId}/results`
  );

  // Auto-redirect to the Results tab once the pipeline reaches a terminal
  // state. Use `replace` so the back button doesn't return to a stale
  // processing screen, and a small grace window so the user briefly sees the
  // "complete" state before the navigation.
  useEffect(() => {
    if (!isTerminal) return;
    if (redirectScheduledRef.current) return;
    redirectScheduledRef.current = true;
    const t = setTimeout(() => {
      router.replace(resultsHref);
    }, 800);
    return () => clearTimeout(t);
  }, [isTerminal, resultsHref, router]);

  const totalElapsed = pipeline?.stage_timings?.reduce(
    (sum, t) => sum + (t.elapsed_seconds ?? 0),
    0
  );

  // Show the placeholder stepper (all stages pending) the moment we know we're
  // pre-flighting an upload, so the user sees the pipeline scaffold before
  // the backend has any real status to report.
  const showPlaceholderStepper =
    !pipeline &&
    (uploadPhase.kind === "uploading" ||
      uploadPhase.kind === "starting" ||
      uploadPhase.kind === "done");

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading package…</p>
      </div>
    );
  }

  return (
    <div
      className="flex justify-center py-6"
      data-testid="loan-package-processing"
    >
      <div className="w-full max-w-xl space-y-4">
        {/* Pre-flight upload banner — visible only while we're driving the
            handoff. Disappears once the pipeline takes over. */}
        {uploadPhase.kind === "uploading" ? (
          <div
            className="section-card flex items-center gap-3"
            data-testid="loan-package-upload-banner"
          >
            <Upload className="h-5 w-5 text-amber-600 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">
                Uploading {uploadPhase.fileCount}{" "}
                {uploadPhase.fileCount === 1 ? "file" : "files"}…
              </p>
              <p className="text-xs text-muted-foreground tabular-nums">
                {formatMb(uploadPhase.totalBytes)} · pipeline starts
                automatically when the upload completes
              </p>
            </div>
            <Loader2 className="h-4 w-4 animate-spin text-amber-600 shrink-0" />
          </div>
        ) : null}

        {uploadPhase.kind === "starting" ? (
          <div className="section-card flex items-center gap-3">
            <Loader2 className="h-4 w-4 animate-spin text-amber-600 shrink-0" />
            <p className="text-sm font-medium">Starting pipeline…</p>
          </div>
        ) : null}

        {uploadPhase.kind === "error" ? (
          <div
            className="rounded-xl border border-red-200 bg-red-50/80 p-4 flex items-start gap-3"
            data-testid="loan-package-upload-error"
          >
            <AlertCircle className="h-5 w-5 text-red-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-red-800">Upload failed</p>
              <p className="text-sm text-red-700 mt-0.5">
                {uploadPhase.message}
              </p>
            </div>
          </div>
        ) : null}

        {isTerminal && liveStatus ? (
          <div
            className="section-card flex items-center justify-between gap-4"
            data-testid="loan-package-run-summary"
          >
            <div className="flex items-center gap-3">
              <PackageStatusBadge status={liveStatus} />
              {totalElapsed !== undefined && totalElapsed > 0 ? (
                <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground tabular-nums">
                  <Clock className="h-3.5 w-3.5" />
                  Total {formatElapsed(totalElapsed)}
                </span>
              ) : null}
            </div>
            <Link
              href={resultsHref}
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              View results
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        ) : null}

        {pipeline ? (
          <PipelineProgress
            stages={pipeline.stages}
            timings={pipeline.stage_timings}
            processed={pipeline.processed}
            total={pipeline.total}
            error={pipeline.pipeline_error}
          />
        ) : showPlaceholderStepper ? (
          // No pipeline data yet, but we've already kicked off the handoff —
          // render an empty stepper so the user sees the 5-stage scaffold
          // immediately.
          <PipelineProgress />
        ) : (
          <div className="section-card flex items-center justify-center py-10 gap-3">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            <p className="text-sm text-muted-foreground">
              Starting pipeline…
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
