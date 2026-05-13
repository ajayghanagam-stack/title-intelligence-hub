"use client";

// Phase 5.2 — LogikIntake audit log drawer.
//
// Right-edge slide-in panel that surfaces the loan-file audit timeline.
// Backed by `GET /loans/{loanId}/audit-events` which returns the real
// `audit_events` rows scoped to this package (via target_id ∈ {loan_id,
// stack_ids, page_ids}). Earlier iterations synthesized the timeline from
// loan + validation state — that fallback is now gone.
//
// Backend `action` strings map onto a small set of UI EventKinds:
//   created | status | acknowledged | override | extraction_edit | rejected
//   | reuploaded
// Anything we don't recognize falls through to "status" so new actions
// don't blow up the drawer until the mapping catches up.

import { useEffect, useMemo } from "react";
import {
  Check,
  Clock,
  FileEdit,
  FileText,
  Shield,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { useLoanAuditEvents } from "@/hooks/use-loan-operator";
import type { LoanAuditEvent } from "@/lib/loan-onboarding/api";
import { cn } from "@/lib/utils";

type EventKind =
  | "created"
  | "status"
  | "acknowledged"
  | "override"
  | "extraction_edit"
  | "rejected"
  | "reuploaded";

type TimelineEvent = {
  id: string;
  at: string;
  kind: EventKind;
  title: string;
  detail?: string;
};

// Static mapping from backend action → UI label + kind. Anything missing
// here falls through to `actionToFallback()`.
const ACTION_MAP: Record<string, { kind: EventKind; title: string }> = {
  lo_package_created: { kind: "created", title: "Loan file created" },
  lo_files_uploaded: { kind: "created", title: "Files uploaded" },
  lo_pipeline_started: { kind: "status", title: "Pipeline started" },
  lo_document_classified: {
    kind: "status",
    title: "Document classification confirmed",
  },
  lo_extraction_field_edited: {
    kind: "extraction_edit",
    title: "Extraction field edited",
  },
  lo_extraction_override_upserted: {
    kind: "extraction_edit",
    title: "Extraction override applied",
  },
  lo_extraction_override_removed: {
    kind: "extraction_edit",
    title: "Extraction override removed",
  },
  lo_page_override_applied: {
    kind: "override",
    title: "Page classification override",
  },
  lo_page_override_batch_applied: {
    kind: "override",
    title: "Batch page override applied",
  },
  lo_page_override_removed: {
    kind: "override",
    title: "Page override removed",
  },
  lo_validation_acknowledged: {
    kind: "acknowledged",
    title: "Validation acknowledged",
  },
  "lo.hard_stop.override_recorded": {
    kind: "override",
    title: "Hard-stop override recorded",
  },
  lo_loan_advanced: { kind: "status", title: "Loan advanced" },
  lo_document_rejected: {
    kind: "rejected",
    title: "Document marked rejected",
  },
  lo_document_reuploaded: {
    kind: "reuploaded",
    title: "Document re-uploaded",
  },
  lo_hitl_review_submitted: {
    kind: "acknowledged",
    title: "HITL review submitted",
  },
  lo_remediation_uploaded: {
    kind: "reuploaded",
    title: "Remediation upload received",
  },
  lo_remediation_pages_uploaded: {
    kind: "reuploaded",
    title: "Remediation pages uploaded",
  },
};

function actionToFallback(action: string): { kind: EventKind; title: string } {
  // Pretty-print the raw action so unmapped events are still legible.
  const pretty = action.replace(/^lo[._]/, "").replace(/[._]/g, " ");
  return { kind: "status", title: pretty || action };
}

function describe(evt: LoanAuditEvent): string | undefined {
  const md = evt.metadata || {};
  // Pull a few well-known fields the LO routes write into metadata. Falls
  // back to undefined so the row simply omits the detail line.
  const candidates = [
    md.notes,
    md.note,
    md.override_note,
    md.reason,
    md.doc_type,
    md.field_name,
    md.label,
    md.filename,
    md.status,
  ];
  for (const c of candidates) {
    if (typeof c === "string" && c.trim()) return c.trim();
  }
  return undefined;
}

export function AuditDrawer({
  open,
  onClose,
  loanId,
}: {
  open: boolean;
  onClose: () => void;
  loanId: string;
}) {
  const { data: rawEvents = [], isLoading, error } = useLoanAuditEvents(loanId);

  const events = useMemo<TimelineEvent[]>(() => {
    return rawEvents.map((evt) => {
      const mapped = ACTION_MAP[evt.action] ?? actionToFallback(evt.action);
      return {
        id: evt.id,
        at: evt.created_at,
        kind: mapped.kind,
        title: mapped.title,
        detail: describe(evt),
      };
    });
  }, [rawEvents]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="audit-drawer-title"
      className="fixed inset-0 z-50"
    >
      <button
        type="button"
        aria-label="Close drawer"
        onClick={onClose}
        className="absolute inset-0 bg-brand-charcoal/30 backdrop-blur-sm"
      />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l bg-card shadow-2xl">
        <header className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-brand-teal">
              Audit Log
            </p>
            <h2
              id="audit-drawer-title"
              className="mt-0.5 text-base font-bold tracking-tight"
            >
              Activity Timeline
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full p-1.5 text-muted-foreground hover:bg-muted"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading events…</p>
          ) : error ? (
            <p className="text-sm text-destructive">
              {error instanceof Error
                ? error.message
                : "Failed to load audit events."}
            </p>
          ) : events.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No audit events yet.
            </p>
          ) : (
            <ol className="space-y-4">
              {events.map((evt) => (
                <li key={evt.id} className="flex gap-3">
                  <EventIcon kind={evt.kind} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-foreground">
                      {evt.title}
                    </p>
                    {evt.detail && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {evt.detail}
                      </p>
                    )}
                    <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      {formatStamp(evt.at)}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>

        <footer className="border-t bg-muted/20 px-5 py-3 text-[11px] text-muted-foreground">
          Sourced live from{" "}
          <code className="font-mono">/loans/{loanId}/audit-events</code>.
        </footer>
      </aside>
    </div>
  );
}

function EventIcon({ kind }: { kind: EventKind }) {
  const map: Record<EventKind, { icon: React.ReactNode; cls: string }> = {
    created: {
      icon: <FileText className="h-3.5 w-3.5" />,
      cls: "bg-brand-teal/10 text-brand-teal",
    },
    status: {
      icon: <Clock className="h-3.5 w-3.5" />,
      cls: "bg-muted text-muted-foreground",
    },
    acknowledged: {
      icon: <Check className="h-3.5 w-3.5" />,
      cls: "bg-brand-orange/10 text-brand-charcoal",
    },
    override: {
      icon: <Shield className="h-3.5 w-3.5" />,
      cls: "bg-destructive/10 text-destructive",
    },
    extraction_edit: {
      icon: <FileEdit className="h-3.5 w-3.5" />,
      cls: "bg-brand-purple/10 text-brand-purple",
    },
    rejected: {
      icon: <Trash2 className="h-3.5 w-3.5" />,
      cls: "bg-destructive/10 text-destructive",
    },
    reuploaded: {
      icon: <Upload className="h-3.5 w-3.5" />,
      cls: "bg-brand-teal/10 text-brand-teal",
    },
  };
  const cfg = map[kind];
  return (
    <span
      className={cn(
        "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
        cfg.cls
      )}
    >
      {cfg.icon}
    </span>
  );
}

function formatStamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

