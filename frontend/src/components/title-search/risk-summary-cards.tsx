"use client";

import { AlertOctagon, AlertTriangle, Info, Shield } from "lucide-react";
import { cn } from "@/lib/utils";

interface RiskSummaryCardsProps {
  counts: Record<string, number>;
}

const SEVERITY_CONFIG: Array<{
  key: string;
  label: string;
  icon: typeof AlertOctagon;
  borderColor: string;
  bgColor: string;
  textColor: string;
  countColor: string;
}> = [
  {
    key: "critical",
    label: "Critical",
    icon: AlertOctagon,
    borderColor: "border-l-red-500",
    bgColor: "bg-red-50/50",
    textColor: "text-red-700",
    countColor: "text-red-600",
  },
  {
    key: "high",
    label: "High",
    icon: AlertTriangle,
    borderColor: "border-l-amber-500",
    bgColor: "bg-amber-50/50",
    textColor: "text-amber-700",
    countColor: "text-amber-600",
  },
  {
    key: "medium",
    label: "Medium",
    icon: Info,
    borderColor: "border-l-yellow-500",
    bgColor: "bg-yellow-50/50",
    textColor: "text-yellow-700",
    countColor: "text-yellow-600",
  },
  {
    key: "low",
    label: "Low",
    icon: Shield,
    borderColor: "border-l-blue-500",
    bgColor: "bg-blue-50/50",
    textColor: "text-blue-700",
    countColor: "text-blue-600",
  },
];

export function RiskSummaryCards({ counts }: RiskSummaryCardsProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {SEVERITY_CONFIG.map(
        ({ key, label, icon: Icon, borderColor, bgColor, textColor, countColor }) => {
          const count = counts[key] ?? 0;

          return (
            <div
              key={key}
              className={cn(
                "rounded-lg border border-border/50 border-l-4 px-4 py-3",
                borderColor,
                bgColor,
                "transition-shadow hover:shadow-sm"
              )}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <Icon className={cn("h-4 w-4", textColor)} />
                <span className={cn("text-xs font-semibold uppercase tracking-wider", textColor)}>
                  {label}
                </span>
              </div>
              <p className={cn("text-2xl font-bold tabular-nums", countColor)}>
                {count}
              </p>
            </div>
          );
        }
      )}
    </div>
  );
}
