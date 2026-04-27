"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import { useLoanPipeline } from "@/hooks/use-loan-pipeline";
import { PipelineProgress } from "@/components/loan-onboarding/pipeline-progress";

const TERMINAL = new Set(["completed", "failed", "awaiting_review"]);

/**
 * Processing tab — renders the centered vertical pipeline stepper while
 * the pipeline is running. When the live pipeline status transitions to
 * a terminal value (completed / failed / awaiting_review) we auto-push to
 * the Results tab so the user sees the outcome without a manual click.
 */
export default function LoanPackageProcessingPage() {
  const router = useRouter();
  const params = useParams();
  const packageId = params.packageId as string;
  const { orgPath } = useOrgSlug();
  const { package: pkg, loading } = useLoanPackage(packageId);
  const { pipeline } = useLoanPipeline(
    packageId,
    pkg ? !TERMINAL.has(pkg.status) : true
  );

  const liveStatus = pipeline?.status ?? pkg?.status;

  // Auto-switch to Results when the pipeline terminates.
  useEffect(() => {
    if (!liveStatus || !TERMINAL.has(liveStatus)) return;
    const base = orgPath(`/apps/loan-onboarding/packages/${packageId}`);
    router.replace(`${base}/results`);
  }, [liveStatus, packageId, orgPath, router]);

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
      <div className="w-full max-w-xl">
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
