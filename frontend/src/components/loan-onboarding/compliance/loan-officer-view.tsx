"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Mail,
  XCircle,
} from "lucide-react";
import type {
  ComplianceReport,
  CloseabilityState,
  DealKiller,
  BorrowerAsk,
} from "@/lib/loan-onboarding/compliance";
import { cn } from "@/lib/utils";
import {
  Pagination,
  usePagination,
} from "@/components/title-intelligence/pagination";

const PAGE_SIZE = 10;

const TONE_STYLE: Record<
  CloseabilityState["tone"],
  { ring: string; bg: string; text: string; icon: typeof CheckCircle2 }
> = {
  ready: {
    ring: "ring-emerald-200 border-emerald-200",
    bg: "bg-gradient-to-br from-emerald-50 to-emerald-100/40",
    text: "text-emerald-900",
    icon: CheckCircle2,
  },
  review: {
    ring: "ring-amber-200 border-amber-200",
    bg: "bg-gradient-to-br from-amber-50 to-amber-100/40",
    text: "text-amber-900",
    icon: AlertTriangle,
  },
  blocked: {
    ring: "ring-red-200 border-red-200",
    bg: "bg-gradient-to-br from-red-50 to-red-100/40",
    text: "text-red-900",
    icon: XCircle,
  },
};

export function LoanOfficerView({ report }: { report: ComplianceReport }) {
  return (
    <div className="space-y-6" data-testid="compliance-lo-view">
      <CloseabilityCard state={report.loView.closeability} />
      <DealKillersCard dealKillers={report.loView.dealKillers} />
      <BorrowerAsksCard asks={report.loView.borrowerAsks} />
    </div>
  );
}

function CloseabilityCard({ state }: { state: CloseabilityState }) {
  const tone = TONE_STYLE[state.tone];
  const Icon = tone.icon;
  return (
    <div
      className={cn("rounded-lg border p-5", tone.ring, tone.bg, tone.text)}
      data-testid="compliance-closeability"
    >
      <div className="flex items-start gap-3">
        <Icon className="h-6 w-6 shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase opacity-80">
            Closeability
          </div>
          <div className="text-lg font-semibold mt-0.5">{state.label}</div>
          <div className="text-sm opacity-90 mt-1">{state.headline}</div>
          <div className="text-xs opacity-75 mt-1">{state.detail}</div>
        </div>
        <div className="grid grid-cols-2 gap-3 shrink-0">
          <Tally label="Critical" count={state.criticalCount} />
          <Tally label="High" count={state.highCount} />
        </div>
      </div>
    </div>
  );
}

function Tally({ label, count }: { label: string; count: number }) {
  return (
    <div className="bg-white/70 rounded-md px-3 py-2 border border-white/60 text-center min-w-[64px]">
      <div className="font-mono text-[9px] tracking-[0.15em] uppercase opacity-70">
        {label}
      </div>
      <div className="text-xl font-semibold tabular-nums mt-0.5">{count}</div>
    </div>
  );
}

function DealKillersCard({ dealKillers }: { dealKillers: DealKiller[] }) {
  const [page, setPage] = useState(1);
  const { paginate, totalPages } = usePagination(dealKillers, PAGE_SIZE);
  const visible = useMemo(() => paginate(page), [paginate, page]);

  if (dealKillers.length === 0) {
    return (
      <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-5 flex items-center gap-3">
        <CheckCircle2 className="h-5 w-5 text-emerald-600" />
        <div>
          <div className="font-medium text-emerald-900">
            No critical or high-severity blockers
          </div>
          <div className="text-sm text-emerald-800/80">
            File can move to underwriting. Lower-severity items can be cleared
            during review.
          </div>
        </div>
      </div>
    );
  }
  return (
    <div
      className="bg-white border border-border rounded-lg overflow-hidden"
      data-testid="compliance-deal-killers"
    >
      <div className="px-5 py-3 border-b border-border flex items-center gap-2">
        <ClipboardList className="h-4 w-4 text-muted-foreground" />
        <div>
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-muted-foreground">
            Top Deal-Killers
          </div>
          <div className="text-sm text-foreground mt-0.5">
            Resolve these before submitting to underwriting
          </div>
        </div>
        <div className="ml-auto font-mono text-[10px] tracking-[0.15em] uppercase text-muted-foreground tabular-nums">
          {dealKillers.length} item{dealKillers.length === 1 ? "" : "s"}
        </div>
      </div>
      <ul>
        {visible.map((d) => (
          <li
            key={d.id}
            className="px-5 py-3 border-b border-border last:border-b-0"
            data-testid={`compliance-deal-killer-${d.id}`}
          >
            <div className="flex items-start gap-3">
              <span
                className={cn(
                  "h-2.5 w-2.5 rounded-full mt-1.5 shrink-0",
                  d.severity === "critical" ? "bg-red-500" : "bg-orange-500"
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={cn(
                      "font-mono text-[9px] tracking-[0.15em] uppercase px-1.5 py-0.5 rounded",
                      d.severity === "critical"
                        ? "bg-red-50 text-red-700 ring-1 ring-red-200"
                        : "bg-orange-50 text-orange-700 ring-1 ring-orange-200"
                    )}
                  >
                    {d.severity === "critical" ? "Critical" : "High"}
                  </span>
                  <span className="font-mono text-[9px] tracking-[0.15em] uppercase px-1.5 py-0.5 rounded bg-stone-100 text-stone-700 ring-1 ring-stone-200">
                    {d.category}
                  </span>
                </div>
                <div className="font-medium text-[14px] text-foreground mt-1.5 leading-snug">
                  {d.title}
                </div>
                <div className="text-[12px] text-muted-foreground mt-1 leading-relaxed">
                  <span className="font-mono text-[9px] tracking-[0.2em] uppercase mr-1.5">
                    Action
                  </span>
                  {d.remediation}
                </div>
              </div>
            </div>
          </li>
        ))}
      </ul>
      <div className="px-5 pb-3">
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          totalItems={dealKillers.length}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
        />
      </div>
    </div>
  );
}

function BorrowerAsksCard({ asks }: { asks: BorrowerAsk[] }) {
  const [page, setPage] = useState(1);
  const { paginate, totalPages } = usePagination(asks, PAGE_SIZE);
  const visible = useMemo(() => paginate(page), [paginate, page]);

  if (asks.length === 0) {
    return (
      <div className="bg-stone-50 border border-stone-200 rounded-lg p-4 flex items-center gap-3">
        <Mail className="h-4 w-4 text-stone-500" />
        <div className="text-sm text-stone-700">
          No outstanding borrower requests — every required document was
          submitted.
        </div>
      </div>
    );
  }
  return (
    <div
      className="bg-white border border-border rounded-lg overflow-hidden"
      data-testid="compliance-borrower-asks"
    >
      <div className="px-5 py-3 border-b border-border flex items-center gap-2">
        <Mail className="h-4 w-4 text-muted-foreground" />
        <div>
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-muted-foreground">
            Ask the Borrower For
          </div>
          <div className="text-sm text-foreground mt-0.5">
            Required documents not yet on file
          </div>
        </div>
        <div className="ml-auto font-mono text-[10px] tracking-[0.15em] uppercase text-muted-foreground tabular-nums">
          {asks.length} doc{asks.length === 1 ? "" : "s"}
        </div>
      </div>
      <ul>
        {visible.map((a) => (
          <li
            key={a.docKey}
            className="px-5 py-2.5 border-b border-border last:border-b-0 flex items-center gap-3"
            data-testid={`compliance-borrower-ask-${a.docKey}`}
          >
            <span className="h-2 w-2 rounded-full bg-amber-500 shrink-0" />
            <div className="font-medium text-[13px] text-foreground">
              {a.docLabel}
            </div>
            <div className="text-[11px] text-muted-foreground">{a.reason}</div>
          </li>
        ))}
      </ul>
      <div className="px-5 pb-3">
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          totalItems={asks.length}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
        />
      </div>
    </div>
  );
}
