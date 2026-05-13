"use client";

// Phase 5.2 — shared loan-detail page header.
//
// All five operator screens (overview, classify, doc-validation, extract,
// validation) share the same chrome: borrower line + loan reference,
// pipeline rail, back-to-queue link.

import Link from "next/link";
import type { ReactNode } from "react";
import { ChevronLeft } from "lucide-react";

import { useOrgSlug } from "@/hooks/use-org-slug";
import { PipelineStagesBar } from "@/components/loan-onboarding/logik-intake/pipeline-stages-bar";
import type { LoanPackage } from "@/lib/loan-onboarding/types";

export function LoanHeader({
  loan,
  hidePipelineRail = false,
  actions,
}: {
  loan: LoanPackage;
  /**
   * When true, the slim five-stage rail is omitted from the header.
   * The loan-overview page sets this so it can render the prototype's
   * richer rail card below — having both would duplicate the rail.
   */
  hidePipelineRail?: boolean;
  /** Optional right-aligned slot — e.g. the loan-overview bottleneck pill. */
  actions?: ReactNode;
}) {
  const { orgPath } = useOrgSlug();
  const title = loan.borrower_name?.trim() || loan.name;
  const subtitle = loan.loan_reference?.trim();
  return (
    <header className="space-y-4 border-b pb-5">
      <Link
        href={orgPath("/apps/loan-onboarding")}
        className="inline-flex items-center gap-1 text-xs font-semibold text-brand-teal hover:underline"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
        Back to Loan File Queue
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          {subtitle && (
            <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
          )}
        </div>
        {actions && (
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        )}
      </div>
      {!hidePipelineRail && (
        <PipelineStagesBar
          currentStage={loan.pipeline_stage}
          status={loan.status}
        />
      )}
    </header>
  );
}
