"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  FileStack,
  Files,
  Gauge,
  ChevronRight,
  ArrowRight,
  Shuffle,
} from "lucide-react";
import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import { useLoanPipeline } from "@/hooks/use-loan-pipeline";
import { PackageStatusBadge } from "@/components/loan-onboarding/package-status-badge";
import { StackExpanded } from "@/components/loan-onboarding/stack-expanded";
import { blendOverallNoSplit } from "@/components/loan-onboarding/confidence-breakdown";
import {
  getExtractions,
  getStacks,
  getValidationResults,
  listPageOverrides,
} from "@/lib/loan-onboarding/api";
import { LOAN_DOC_TYPE_LABELS } from "@/lib/loan-onboarding/constants";
import { cn } from "@/lib/utils";
import type {
  LoanStack,
  LoanStackExtraction,
  LoanValidationResult,
  LoanPageOverride,
} from "@/lib/loan-onboarding/types";

const TERMINAL = new Set(["completed", "failed", "awaiting_review"]);

type StackBucket = "clean" | "warnings";
type TabKey = "all" | StackBucket;

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

function confidenceTone(value: number | null | undefined): string {
  if (value === null || value === undefined)
    return "bg-muted text-muted-foreground ring-border";
  if (value >= 0.85) return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (value >= 0.7) return "bg-amber-50 text-amber-700 ring-amber-200";
  return "bg-red-50 text-red-700 ring-red-200";
}

/**
 * Classify a stack into one of two mutually-exclusive buckets so every
 * stack appears in exactly one sub-tab (plus "All Stacks"):
 *   - warnings → at least one validation rule failed
 *   - clean    → all rules passed
 */
function bucketFor(
  _stack: LoanStack,
  vr: LoanValidationResult | undefined
): StackBucket {
  const failed = vr?.rules_evaluated.filter((r) => !r.passed).length ?? 0;
  return failed > 0 ? "warnings" : "clean";
}

export default function LoanPackageResultsPage() {
  const params = useParams();
  const packageId = params.packageId as string;
  const { currentOrgId } = useOrg();
  const { orgPath } = useOrgSlug();
  const {
    package: pkg,
    loading,
    refetch: refetchPkg,
  } = useLoanPackage(packageId);
  const { pipeline } = useLoanPipeline(
    packageId,
    pkg ? !TERMINAL.has(pkg.status) : true
  );

  const pipelineStatus = pipeline?.status;
  useEffect(() => {
    if (pipelineStatus && TERMINAL.has(pipelineStatus)) {
      refetchPkg();
    }
  }, [pipelineStatus, refetchPkg]);

  const [stacks, setStacks] = useState<LoanStack[]>([]);
  const [validation, setValidation] = useState<LoanValidationResult[]>([]);
  const [overrides, setOverrides] = useState<LoanPageOverride[]>([]);
  const [extractions, setExtractions] = useState<LoanStackExtraction[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // Bumped after each page-override move/undo so the effect below re-runs and
  // stacks/validation/overrides are re-fetched with the latest rebuild output.
  const [refreshToken, setRefreshToken] = useState(0);

  const toggleExpanded = (stackId: string) =>
    setExpanded((prev) => ({ ...prev, [stackId]: !prev[stackId] }));

  useEffect(() => {
    if (!currentOrgId || !packageId) return;
    setSummaryLoading(true);
    Promise.all([
      getStacks(currentOrgId, packageId).catch(() => [] as LoanStack[]),
      getValidationResults(currentOrgId, packageId).catch(
        () => [] as LoanValidationResult[]
      ),
      listPageOverrides(currentOrgId, packageId).catch(
        () => [] as LoanPageOverride[]
      ),
      getExtractions(currentOrgId, packageId)
        .then((r) => r.stacks)
        .catch(() => [] as LoanStackExtraction[]),
    ])
      .then(([s, v, o, ex]) => {
        setStacks(s);
        setValidation(v);
        setOverrides(o);
        setExtractions(ex);
      })
      .finally(() => setSummaryLoading(false));
  }, [currentOrgId, packageId, pipeline?.status, refreshToken]);

  const overridesByPageId = useMemo(
    () => new Map(overrides.map((o) => [o.page_id, o])),
    [overrides]
  );

  const validationByStack = useMemo(
    () => new Map(validation.map((v) => [v.stack_id, v])),
    [validation]
  );

  const extractionByStack = useMemo(
    () => new Map(extractions.map((e) => [e.stack_id, e])),
    [extractions]
  );

  const sortedStacks = useMemo(
    () => [...stacks].sort((a, b) => a.stack_index - b.stack_index),
    [stacks]
  );

  // Bucket every stack once for both the tab counts and the filtered list.
  const bucketed = useMemo(() => {
    const map = new Map<string, StackBucket>();
    for (const s of sortedStacks) {
      map.set(s.id, bucketFor(s, validationByStack.get(s.id)));
    }
    return map;
  }, [sortedStacks, validationByStack]);

  const counts = useMemo(() => {
    let clean = 0,
      warnings = 0;
    for (const b of bucketed.values()) {
      if (b === "clean") clean++;
      else warnings++;
    }
    return { all: sortedStacks.length, clean, warnings };
  }, [bucketed, sortedStacks.length]);

  const filteredStacks = useMemo(() => {
    if (activeTab === "all") return sortedStacks;
    return sortedStacks.filter((s) => bucketed.get(s.id) === activeTab);
  }, [activeTab, sortedStacks, bucketed]);

  // Metrics — Total Pages is the sum of stack page_counts (authoritative
  // post-pipeline). Falls back to pipeline.total only while stacks are still
  // loading. We can't use `??` against pipeline.total because the backend
  // returns 0 (not null) when the pipeline isn't reporting progress, and 0
  // is a valid-looking-but-wrong number that would short-circuit the sum.
  const stackPageSum = sortedStacks.reduce((acc, s) => acc + s.page_count, 0);
  const totalPages = stackPageSum > 0 ? stackPageSum : (pipeline?.total ?? 0);

  const avgConfidence = useMemo(() => {
    // Compute per-stack effective overall (classification + validation only,
    // no split-accuracy) so the headline average matches what the per-stack
    // pills and the dashboard donut display.
    const vals = sortedStacks
      .map((s) => {
        const vr = validationByStack.get(s.id);
        return vr ? blendOverallNoSplit(vr.confidence_breakdown) : null;
      })
      .filter((v): v is number => v !== null && v !== undefined);
    if (vals.length === 0) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [sortedStacks, validationByStack]);

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
  const liveStage = pipeline?.pipeline_stage ?? pkg.pipeline_stage;

  const TAB_DEFS: {
    key: TabKey;
    label: string;
    count: number;
    activeClass: string;
  }[] = [
    {
      key: "all",
      label: "All Stacks",
      count: counts.all,
      activeClass: "border-foreground text-foreground",
    },
    {
      key: "clean",
      label: "Clean",
      count: counts.clean,
      activeClass: "border-emerald-500 text-emerald-700",
    },
    {
      key: "warnings",
      label: "Warnings",
      count: counts.warnings,
      activeClass: "border-amber-500 text-amber-700",
    },
  ];

  return (
    <div className="space-y-6" data-testid="loan-package-results">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">{pkg.name}</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            {pkg.doc_types.length} expected doc types
          </p>
        </div>
        <PackageStatusBadge status={liveStatus} stage={liveStage} />
      </div>

      {/* Reorganization banner — only when pages have been moved */}
      {overrides.length > 0 && (
        <div
          className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50/70 px-5 py-4"
          data-testid="reorganization-banner"
        >
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/15 ring-1 ring-amber-500/30">
              <Shuffle className="h-4 w-4 text-amber-700" />
            </div>
            <div>
              <p className="text-sm font-semibold text-amber-900">
                Package reorganized · {overrides.length} page
                {overrides.length === 1 ? "" : "s"} moved
              </p>
              <p className="text-[12px] text-amber-800/80 mt-0.5">
                Stacks below reflect your manual overrides. Review the change
                summary and download the reorganized packet from the
                Dashboard.
              </p>
            </div>
          </div>
          <Link
            href={orgPath(
              `/apps/loan-onboarding/packages/${packageId}/dashboard`
            )}
            className="btn-cta gap-2 py-2 px-4 text-sm shrink-0"
            data-testid="reorganization-banner-cta"
          >
            Review &amp; download
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      )}

      {/* Three metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <MetricCard
          label="Total Pages"
          value={summaryLoading ? "—" : String(totalPages)}
          icon={<Files className="h-5 w-5" />}
          iconClass="bg-sky-50 text-sky-600 ring-sky-200"
          testId="metric-total-pages"
        />
        <MetricCard
          label="Document Stacks"
          value={summaryLoading ? "—" : String(sortedStacks.length)}
          icon={<FileStack className="h-5 w-5" />}
          iconClass="bg-violet-50 text-violet-600 ring-violet-200"
          testId="metric-stacks"
        />
        <MetricCard
          label="Avg Confidence"
          value={
            summaryLoading
              ? "—"
              : avgConfidence === null
                ? "—"
                : `${Math.round(avgConfidence * 100)}%`
          }
          icon={<Gauge className="h-5 w-5" />}
          iconClass={
            avgConfidence !== null && avgConfidence >= 0.85
              ? "bg-emerald-50 text-emerald-600 ring-emerald-200"
              : avgConfidence !== null && avgConfidence >= 0.7
                ? "bg-amber-50 text-amber-600 ring-amber-200"
                : "bg-muted text-muted-foreground ring-border"
          }
          testId="metric-avg-confidence"
        />
      </div>

      {/* Sub-tabs + filtered stack list */}
      <div className="section-card" data-testid="stack-results">
        <div
          className="flex gap-1 border-b border-border/70 overflow-x-auto -mx-5 px-5 mb-4"
          role="tablist"
          aria-label="Filter stacks by status"
        >
          {TAB_DEFS.map((t) => {
            const isActive = activeTab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => setActiveTab(t.key)}
                className={cn(
                  "relative px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px inline-flex items-center gap-2",
                  isActive
                    ? t.activeClass
                    : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
                )}
                data-testid={`stack-tab-${t.key}`}
              >
                {t.label}
                <span
                  className={cn(
                    "inline-flex items-center justify-center rounded-full px-1.5 min-w-[20px] h-5 text-[10px] font-mono tabular-nums",
                    isActive
                      ? "bg-muted text-foreground"
                      : "bg-muted/60 text-muted-foreground"
                  )}
                >
                  {t.count}
                </span>
              </button>
            );
          })}
        </div>

        {summaryLoading ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            Loading results…
          </div>
        ) : filteredStacks.length === 0 ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            No stacks in this bucket.
          </div>
        ) : (
          <ul className="divide-y divide-border/60">
            {filteredStacks.map((stack) => {
              const vr = validationByStack.get(stack.id);
              const rulesTotal = vr?.rules_evaluated.length ?? 0;
              const rulesPassed =
                vr?.rules_evaluated.filter((r) => r.passed).length ?? 0;
              const rulesFailed = rulesTotal - rulesPassed;
              const typeLabel =
                LOAN_DOC_TYPE_LABELS[stack.doc_type] ?? stack.doc_type;
              const bucket = bucketed.get(stack.id) ?? "clean";
              const isOpen = !!expanded[stack.id];

              const bucketRing =
                bucket === "warnings"
                  ? "bg-amber-50 text-amber-600 ring-amber-200"
                  : "bg-emerald-50 text-emerald-600 ring-emerald-200";

              return (
                <li
                  key={stack.id}
                  className="py-3"
                  data-testid={`stack-row-${stack.stack_index}`}
                >
                  <button
                    type="button"
                    onClick={() => toggleExpanded(stack.id)}
                    aria-expanded={isOpen}
                    aria-controls={`stack-details-${stack.stack_index}`}
                    className="w-full flex flex-wrap items-center gap-3 text-left hover:bg-muted/40 rounded-md -mx-2 px-2 py-1 transition-colors"
                  >
                    <ChevronRight
                      className={cn(
                        "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                        isOpen && "rotate-90"
                      )}
                    />
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <div
                        className={cn(
                          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ring-1",
                          bucketRing
                        )}
                      >
                        {bucket === "clean" ? (
                          <CheckCircle2 className="h-4 w-4" />
                        ) : (
                          <AlertTriangle className="h-4 w-4" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">
                          {typeLabel}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Pages {stack.first_page}–{stack.last_page} ·{" "}
                          {stack.page_count}pp
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 text-[11px] font-mono">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1",
                          confidenceTone(stack.classification_confidence)
                        )}
                      >
                        Classify {pct(stack.classification_confidence)}
                      </span>
                      {(() => {
                        const eff = vr
                          ? blendOverallNoSplit(vr.confidence_breakdown)
                          : null;
                        return (
                          <span
                            className={cn(
                              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1",
                              confidenceTone(eff)
                            )}
                          >
                            Overall {pct(eff)}
                          </span>
                        );
                      })()}
                      {rulesTotal > 0 && (
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1",
                            rulesFailed === 0
                              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                              : "bg-red-50 text-red-700 ring-red-200"
                          )}
                        >
                          {rulesPassed}/{rulesTotal} rules
                        </span>
                      )}
                    </div>
                  </button>

                  {isOpen && currentOrgId && (
                    <div id={`stack-details-${stack.stack_index}`}>
                      <StackExpanded
                        orgId={currentOrgId}
                        packageId={packageId}
                        stack={stack}
                        validation={vr}
                        allStacks={sortedStacks}
                        packageDocTypes={pkg.doc_types.map((d) => d.key)}
                        overrides={overridesByPageId}
                        extraction={
                          pkg.extraction_enabled
                            ? extractionByStack.get(stack.id)
                            : null
                        }
                        onMutated={() => setRefreshToken((n) => n + 1)}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: string;
  icon: React.ReactNode;
  iconClass: string;
  testId?: string;
}

function MetricCard({ label, value, icon, iconClass, testId }: MetricCardProps) {
  return (
    <div className="section-card" data-testid={testId}>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <div className="mt-2 flex items-center gap-3">
        <div
          className={cn(
            "flex h-10 w-10 items-center justify-center rounded-xl ring-1",
            iconClass
          )}
        >
          {icon}
        </div>
        <p className="text-3xl font-bold tabular-nums leading-none">{value}</p>
      </div>
    </div>
  );
}
