"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowRight, Clock } from "lucide-react";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import { useLoanPipeline } from "@/hooks/use-loan-pipeline";
import { PipelineProgress } from "@/components/loan-onboarding/pipeline-progress";
import { PackageStatusBadge } from "@/components/loan-onboarding/package-status-badge";

const TERMINAL = new Set(["completed", "failed", "awaiting_review"]);

function formatElapsed(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds - minutes * 60);
  return `${minutes}m ${rem}s`;
}

/**
 * Processing tab — dual purpose:
 *
 * While the pipeline is running, renders the live vertical stepper. Once the
 * pipeline reaches a terminal state (completed / failed / awaiting_review)
 * the same view becomes a read-only run summary: total elapsed time, final
 * status, per-stage timings, and any error. The stepper itself naturally
 * renders the terminal state (all green / red), so we just add a header
 * banner with the headline numbers + a CTA over to Results.
 */
export default function LoanPackageProcessingPage() {
  const params = useParams();
  const packageId = params.packageId as string;
  const { orgPath } = useOrgSlug();
  const { package: pkg, loading } = useLoanPackage(packageId);
  const { pipeline } = useLoanPipeline(
    packageId,
    pkg ? !TERMINAL.has(pkg.status) : true
  );

  const liveStatus = pipeline?.status ?? pkg?.status;
  const isTerminal = !!liveStatus && TERMINAL.has(liveStatus);
  const resultsHref = orgPath(
    `/apps/loan-onboarding/packages/${packageId}/results`
  );

  const totalElapsed = pipeline?.stage_timings?.reduce(
    (sum, t) => sum + (t.elapsed_seconds ?? 0),
    0
  );

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
