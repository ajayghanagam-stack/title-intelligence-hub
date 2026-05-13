"use client";

// Phase 5.2 — LogikIntake hard-stop override dialog (4-eye flow).
//
// Hard stops on the validation page block decision-ready advance. Some are
// recoverable with supervisor sign-off (e.g., compensating documentation).
// This dialog captures: the failing rule's justification, a supervisor
// name, and an explicit confirmation checkbox before sending the same
// `:ack` payload the soft-flag flow uses. The backend treats the override
// note as the audit trail; supervisor name is included in the note prefix
// so the audit drawer can surface it.

import { useEffect, useState } from "react";
import { AlertTriangle, X } from "lucide-react";

import { cn } from "@/lib/utils";

export type OverrideTarget = {
  ruleLabel: string;
  ruleId: string;
  ruleSource: string;
  stackId: string;
  docType: string;
  detail?: string | null;
};

export function OverrideDialog({
  open,
  onClose,
  target,
  onSubmit,
  pending,
}: {
  open: boolean;
  onClose: () => void;
  target: OverrideTarget | null;
  onSubmit: (payload: {
    checkId: string;
    override_note: string;
  }) => void;
  pending?: boolean;
}) {
  const [supervisor, setSupervisor] = useState("");
  const [justification, setJustification] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    if (open) {
      setSupervisor("");
      setJustification("");
      setConfirmed(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pending) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, pending, onClose]);

  if (!open || !target) return null;

  const canSubmit =
    confirmed && supervisor.trim().length > 0 && justification.trim().length >= 10 && !pending;

  const handleSubmit = () => {
    if (!canSubmit) return;
    const note = `Supervisor: ${supervisor.trim()} — ${justification.trim()}`;
    onSubmit({
      checkId: `${target.stackId}__${target.ruleSource}__${target.ruleId}`,
      override_note: note,
    });
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="override-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <button
        type="button"
        aria-label="Close dialog"
        onClick={() => !pending && onClose()}
        className="absolute inset-0 bg-brand-charcoal/40 backdrop-blur-sm"
      />

      <div className="relative z-10 w-full max-w-lg overflow-hidden rounded-xl border border-destructive/40 bg-card shadow-2xl">
        <header className="flex items-center justify-between border-b border-destructive/30 bg-destructive/5 px-5 py-4">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-destructive">
                Hard Stop Override
              </p>
              <h2
                id="override-dialog-title"
                className="mt-0.5 text-base font-bold tracking-tight"
              >
                {target.ruleLabel}
              </h2>
            </div>
          </div>
          <button
            type="button"
            onClick={() => !pending && onClose()}
            disabled={pending}
            aria-label="Close"
            className="rounded-full p-1.5 text-muted-foreground hover:bg-muted disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-4 px-5 py-5">
          <div className="rounded-md bg-muted/40 p-3 text-xs">
            <p className="text-muted-foreground">
              {target.docType} · {target.ruleSource} · {target.ruleId}
            </p>
            {target.detail && (
              <p className="mt-1.5 text-foreground">{target.detail}</p>
            )}
          </div>

          <label className="block">
            <span className="text-xs font-semibold text-muted-foreground">
              Supervisor name
            </span>
            <input
              type="text"
              value={supervisor}
              onChange={(e) => setSupervisor(e.target.value)}
              maxLength={200}
              placeholder="e.g., Jane Doe"
              className="mt-1 h-9 w-full rounded-md border bg-card px-2 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            />
          </label>

          <label className="block">
            <span className="text-xs font-semibold text-muted-foreground">
              Justification (min 10 characters)
            </span>
            <textarea
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              maxLength={2000}
              rows={4}
              placeholder="Explain why this hard stop can be safely overridden…"
              className="mt-1 w-full rounded-md border bg-card px-2 py-2 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            />
          </label>

          <label className="flex items-start gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-input"
            />
            <span>
              I confirm this override is documented per policy and will appear
              in the audit log.
            </span>
          </label>
        </div>

        <footer className="flex justify-end gap-2 border-t bg-muted/20 px-5 py-3">
          <button
            type="button"
            onClick={() => !pending && onClose()}
            disabled={pending}
            className="rounded-md px-3 py-1.5 text-sm font-semibold text-muted-foreground hover:bg-muted disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-semibold text-white",
              canSubmit
                ? "bg-destructive hover:bg-destructive/90"
                : "cursor-not-allowed bg-destructive/40"
            )}
          >
            {pending ? "Submitting…" : "Submit override"}
          </button>
        </footer>
      </div>
    </div>
  );
}
