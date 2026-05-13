"use client";

// Phase 5.2 — LogikIntake remediation modal.
//
// Surfaces remediation paths for a flagged stack without requiring the user
// to leave the loan-overview screen. All three paths are now wired against
// real backend endpoints:
//   - Re-classify routes to the classify screen for the stack
//   - Re-upload posts a replacement PDF to /loans/{loanId}/documents/{docId}
//     /reupload (multipart) and re-runs the remediation pipeline
//   - Reject posts a terminal reject to /loans/{loanId}/documents/{docId}
//     /reject and clears the HITL flag

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Layers, RefreshCw, Upload, X } from "lucide-react";

import { useOrgSlug } from "@/hooks/use-org-slug";
import {
  useRejectStack,
  useReuploadStack,
} from "@/hooks/use-loan-operator";
import { cn } from "@/lib/utils";
import type { LoanStack } from "@/lib/loan-onboarding/types";

export function RemediationModal({
  open,
  onClose,
  loanId,
  stack,
}: {
  open: boolean;
  onClose: () => void;
  loanId: string;
  stack: LoanStack | null;
}) {
  const router = useRouter();
  const { orgPath } = useOrgSlug();
  const reject = useRejectStack(loanId);
  const reupload = useReuploadStack(loanId);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [notes, setNotes] = useState("");
  const [confirmingReject, setConfirmingReject] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Reset transient UI state whenever the modal is closed/reopened.
  useEffect(() => {
    if (!open) {
      setNotes("");
      setConfirmingReject(false);
    }
  }, [open]);

  if (!open || !stack) return null;

  // The classify route takes a *stack* id (the loan-overview cards already
  // route there with `${doc.id}`), so we just forward the stack id.
  const reclassifyHref = orgPath(
    `/apps/loan-onboarding/loans/${loanId}/classify/${stack.id}`
  );

  const busy = reject.isPending || reupload.isPending;

  async function handleReupload(file: File) {
    try {
      await reupload.mutateAsync({
        docId: stack!.id,
        file,
        notes: notes.trim() || null,
      });
      onClose();
    } catch {
      // useReuploadStack surfaces the error via reupload.error below.
    }
  }

  async function handleReject() {
    try {
      await reject.mutateAsync({
        docId: stack!.id,
        notes: notes.trim() || null,
      });
      onClose();
    } catch {
      // useRejectStack surfaces the error via reject.error below.
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="remediation-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <button
        type="button"
        aria-label="Close dialog"
        onClick={onClose}
        className="absolute inset-0 bg-brand-charcoal/40 backdrop-blur-sm"
      />

      <div className="relative z-10 w-full max-w-md overflow-hidden rounded-xl border bg-card shadow-2xl">
        <header className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-brand-orange">
              Needs Review
            </p>
            <h2
              id="remediation-modal-title"
              className="mt-0.5 text-base font-bold tracking-tight"
            >
              {stack.doc_type || "Unclassified"}
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

        <div className="space-y-3 px-5 py-5">
          <p className="text-sm text-muted-foreground">
            Confidence{" "}
            <span className="font-mono tabular-nums">
              {Math.round((stack.overall_confidence ?? 0) * 100)}%
            </span>{" "}
            · {stack.page_count} page{stack.page_count === 1 ? "" : "s"} · pages{" "}
            {stack.first_page}–{stack.last_page}. Pick a path to resolve the
            document.
          </p>

          <label
            htmlFor="remediation-notes"
            className="block text-[11px] font-bold uppercase tracking-wider text-muted-foreground"
          >
            Reviewer notes (optional)
          </label>
          <textarea
            id="remediation-notes"
            rows={2}
            maxLength={2000}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            disabled={busy}
            placeholder="Why are you remediating this document?"
            className="w-full rounded-lg border bg-card px-3 py-2 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20 disabled:opacity-60"
          />

          <ActionRow
            icon={<Layers className="h-4 w-4" />}
            title="Re-classify"
            description="Confirm or override the doc type."
            onClick={() => {
              router.push(reclassifyHref);
              onClose();
            }}
            disabled={busy}
          />
          <ActionRow
            icon={<Upload className="h-4 w-4" />}
            title={reupload.isPending ? "Uploading…" : "Re-upload"}
            description="Replace this document with a fresh PDF."
            onClick={() => fileInputRef.current?.click()}
            disabled={busy}
          />
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              // Reset so re-selecting the same file still triggers onChange.
              e.target.value = "";
              if (file) void handleReupload(file);
            }}
          />
          {!confirmingReject ? (
            <ActionRow
              icon={<RefreshCw className="h-4 w-4" />}
              title="Mark rejected"
              description="Drop this document from the loan file."
              onClick={() => setConfirmingReject(true)}
              disabled={busy}
              tone="destructive"
            />
          ) : (
            <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2.5">
              <p className="text-sm font-semibold text-destructive">
                Reject this document?
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                This is terminal — the stack will be marked rejected and dropped
                from the loan file. The audit log records who rejected it.
              </p>
              <div className="mt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setConfirmingReject(false)}
                  disabled={busy}
                  className="rounded-md px-2 py-1 text-xs font-semibold text-muted-foreground hover:bg-muted disabled:opacity-60"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleReject}
                  disabled={busy}
                  className="rounded-md bg-destructive px-2 py-1 text-xs font-semibold text-destructive-foreground hover:bg-destructive/90 disabled:opacity-60"
                >
                  {reject.isPending ? "Rejecting…" : "Confirm reject"}
                </button>
              </div>
            </div>
          )}

          {(reupload.error || reject.error) && (
            <p className="text-xs text-destructive">
              {(reupload.error || reject.error)?.message}
            </p>
          )}
        </div>

        <footer className="flex justify-end border-t bg-muted/20 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md px-3 py-1.5 text-sm font-semibold text-muted-foreground hover:bg-muted disabled:opacity-60"
          >
            Close
          </button>
        </footer>
      </div>
    </div>
  );
}

function ActionRow({
  icon,
  title,
  description,
  disabled,
  hint,
  onClick,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  disabled?: boolean;
  hint?: string;
  onClick?: () => void;
  tone?: "default" | "destructive";
}) {
  const isDestructive = tone === "destructive";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={disabled ? hint : undefined}
      className={cn(
        "flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors",
        disabled
          ? "cursor-not-allowed opacity-60"
          : isDestructive
            ? "hover:border-destructive hover:bg-destructive/5"
            : "hover:border-brand-teal hover:bg-brand-teal/5"
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          disabled
            ? "bg-muted text-muted-foreground"
            : isDestructive
              ? "bg-destructive/10 text-destructive"
              : "bg-brand-teal/10 text-brand-teal"
        )}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{title}</span>
        <span className="block text-[11px] text-muted-foreground">
          {description}
        </span>
      </span>
    </button>
  );
}
