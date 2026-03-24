"use client";

import { cn } from "@/lib/utils";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  FileCheck,
  Stamp,
  Scale,
  ShieldAlert,
  GitCompare,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { CATEGORY_LABELS } from "@/lib/ti-constants";
import type { ReadinessData, CategoryScore } from "@/lib/ti-types";

const STATUS_CONFIG = {
  ready: {
    label: "Ready to Close",
    icon: CheckCircle2,
    color: "text-emerald-700",
    bg: "bg-gradient-to-br from-emerald-50 to-emerald-100/50",
    ring: "ring-emerald-200",
    stroke: "stroke-emerald-500",
    scoreColor: "text-emerald-700",
  },
  at_risk: {
    label: "At Risk",
    icon: AlertTriangle,
    color: "text-amber-700",
    bg: "bg-gradient-to-br from-amber-50 to-amber-100/50",
    ring: "ring-amber-200",
    stroke: "stroke-amber-500",
    scoreColor: "text-amber-700",
  },
  not_ready: {
    label: "Not Ready",
    icon: XCircle,
    color: "text-red-700",
    bg: "bg-gradient-to-br from-red-50 to-red-100/50",
    ring: "ring-red-200",
    stroke: "stroke-red-500",
    scoreColor: "text-red-700",
  },
};

function getStatusKey(score: number): "ready" | "at_risk" | "not_ready" {
  if (score >= 90) return "ready";
  if (score >= 60) return "at_risk";
  return "not_ready";
}

function ScoreDonut({ score, statusKey }: { score: number; statusKey: "ready" | "at_risk" | "not_ready" }) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const config = STATUS_CONFIG[statusKey];

  return (
    <div className="relative h-[100px] w-[100px] flex-shrink-0">
      <svg className="h-full w-full -rotate-90" viewBox="0 0 100 100">
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          strokeWidth="6"
          className="stroke-black/[0.04]"
        />
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={cn(config.stroke, "transition-all duration-1000 ease-out")}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className={cn(
            "text-3xl font-bold tabular-nums leading-none",
            config.scoreColor
          )}
        >
          {score}
        </span>
        <span className="text-[10px] font-medium text-muted-foreground mt-1">
          of 100
        </span>
      </div>
    </div>
  );
}

const CATEGORY_ICON_CONFIG: Record<
  string,
  { icon: typeof FileCheck; color: string; bg: string; ring: string }
> = {
  requirements: {
    icon: FileCheck,
    color: "text-violet-600",
    bg: "bg-violet-50",
    ring: "ring-violet-200",
  },
  endorsements: {
    icon: Stamp,
    color: "text-blue-600",
    bg: "bg-blue-50",
    ring: "ring-blue-200",
  },
  liens: {
    icon: Scale,
    color: "text-red-600",
    bg: "bg-red-50",
    ring: "ring-red-200",
  },
  exceptions: {
    icon: ShieldAlert,
    color: "text-orange-600",
    bg: "bg-orange-50",
    ring: "ring-orange-200",
  },
  consistency: {
    icon: GitCompare,
    color: "text-sky-600",
    bg: "bg-sky-50",
    ring: "ring-sky-200",
  },
};

function CategoryCard({ cat }: { cat: CategoryScore }) {
  const config = CATEGORY_ICON_CONFIG[cat.category] || {
    icon: FileCheck,
    color: "text-stone-600",
    bg: "bg-stone-50",
    ring: "ring-stone-200",
  };

  const Icon = config.icon;
  const pct = cat.max_score > 0 ? (cat.score / cat.max_score) * 100 : 0;
  const ok = pct >= 80;

  return (
    <div className={cn("rounded-xl p-4 ring-1 transition-all hover:shadow-sm", config.bg, config.ring)}>
      <div className="flex items-start justify-between mb-3">
        <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg bg-white/80 shadow-sm", config.color)}>
          <Icon className="h-4.5 w-4.5" />
        </div>
        {ok ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-amber-500" />
        )}
      </div>
      <p className="text-2xl font-bold tabular-nums">
        {cat.score}<span className="text-sm font-normal text-muted-foreground">/{cat.max_score}</span>
      </p>
      <p className={cn("text-xs font-semibold mt-0.5", config.color)}>
        {CATEGORY_LABELS[cat.category] || cat.category}
      </p>
      {cat.details && (
        <p className="text-[11px] text-muted-foreground mt-1.5 line-clamp-2 leading-relaxed">
          {cat.details}
        </p>
      )}
    </div>
  );
}

export function ReadinessDashboard({ data }: { data: ReadinessData }) {
  const statusKey = (data.status as "ready" | "at_risk" | "not_ready") || getStatusKey(data.score);
  const sc = STATUS_CONFIG[statusKey];
  const StatusIcon = sc.icon;

  const openFlags = data.open_flags_count ?? data.checklist.filter((c) => c.status === "blocked").length;

  return (
    <div className="space-y-4">
      {/* Main readiness card */}
      <div className={cn("rounded-2xl ring-1 overflow-hidden", sc.bg, sc.ring)}>
        <div className="p-6">
          <div className="flex items-center gap-6">
            <ScoreDonut score={data.score} statusKey={statusKey} />

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2.5 mb-1">
                <StatusIcon className={cn("h-5 w-5", sc.color)} />
                <span className={cn("text-lg font-semibold", sc.color)}>
                  {sc.label}
                </span>
              </div>

              <div className="flex items-center gap-4 mt-2">
                {openFlags > 0 && (
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground bg-white/60 px-2.5 py-1 rounded-full">
                    <AlertTriangle className="h-3 w-3 text-amber-500" />
                    {openFlags} open {openFlags === 1 ? "flag" : "flags"}
                  </span>
                )}
                {data.estimated_days != null && (
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground bg-white/60 px-2.5 py-1 rounded-full">
                    <Clock className="h-3 w-3" />
                    Est. {data.estimated_days} days to clear
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* AI Summary */}
          {data.summary && (
            <div className="mt-5 rounded-xl bg-white/60 border border-amber-200/40 px-4 py-3">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-700 mb-1.5">
                <Sparkles className="h-3.5 w-3.5" />
                AI Summary
              </p>
              <p className="text-sm leading-relaxed text-foreground/80">
                {data.summary}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Category Scorecard Grid */}
      {data.categories.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {data.categories.map((cat) => (
            <CategoryCard key={cat.category} cat={cat} />
          ))}
        </div>
      )}
    </div>
  );
}
