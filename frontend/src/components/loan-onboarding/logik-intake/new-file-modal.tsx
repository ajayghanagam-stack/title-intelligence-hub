"use client";

// Phase 5.2 — LogikIntake quick-start "New File" modal.
//
// Light-weight gateway off the queue page. Accepts a program profile +
// dropped files and creates a package via the same `useLoanPackages.create`
// mutation the rich `/packages/new` page uses. The chosen profile drives the
// initial doc-type checklist; users who need fine-grained control can still
// reach the full configurator at /packages/new (we expose a "Use full form"
// link in the footer).

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Loader2, Plus, X } from "lucide-react";

import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackages } from "@/hooks/use-loan-packages";
import {
  DEFAULT_HITL_THRESHOLD,
  OTHERS_DOC_TYPE_KEY,
  SUGGESTED_DOC_TYPES,
} from "@/lib/loan-onboarding/constants";
import { enqueueUpload } from "@/lib/loan-onboarding/upload-queue";
import { cn } from "@/lib/utils";

// Mirrors the program-profile fixture on
// `/admin/program-profiles/page.tsx` — kept inline here so the modal
// doesn't depend on a fixture module that may move.
type ProgramProfile = {
  id: string;
  name: string;
  type: "GSE" | "Government" | "Non-QM";
  docKeys: string[];
};

const PROFILES: ProgramProfile[] = [
  {
    id: "conv-30",
    name: "Conventional 30yr",
    type: "GSE",
    docKeys: ["urla_1003", "paystub", "w2", "bank_stmt", "credit_report"],
  },
  {
    id: "fha-purchase",
    name: "FHA Purchase",
    type: "Government",
    docKeys: ["urla_1003", "paystub", "w2", "bank_stmt", "credit_report"],
  },
  {
    id: "va-30",
    name: "VA 30yr",
    type: "Government",
    docKeys: ["urla_1003", "paystub", "w2"],
  },
  {
    id: "jumbo",
    name: "Jumbo",
    type: "Non-QM",
    docKeys: ["urla_1003", "f1040", "bank_stmt"],
  },
];

export function NewFileModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const { currentOrgId } = useOrg();
  const { orgPath } = useOrgSlug();
  const { create } = useLoanPackages();

  const [profileId, setProfileId] = useState<string>(PROFILES[0].id);
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Reset state every time the modal opens — operators expect a fresh slate.
  useEffect(() => {
    if (open) {
      setProfileId(PROFILES[0].id);
      setFiles([]);
      setSubmitting(false);
      setError(null);
    }
  }, [open]);

  // Close on Escape — basic dialog ergonomics. We don't trap focus here
  // because the modal is small and the close button is the first focusable.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, submitting, onClose]);

  const profile = useMemo(
    () => PROFILES.find((p) => p.id === profileId) ?? PROFILES[0],
    [profileId]
  );

  const checklist = useMemo(() => {
    return SUGGESTED_DOC_TYPES.filter(
      (d) => d.key !== OTHERS_DOC_TYPE_KEY && profile.docKeys.includes(d.key)
    );
  }, [profile]);

  const canSubmit = files.length > 0 && !!currentOrgId && !submitting;

  const handleFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const next = Array.from(incoming);
    setFiles((prev) => [...prev, ...next]);
  };

  const handleSubmit = async () => {
    if (!canSubmit || !currentOrgId) return;
    setSubmitting(true);
    setError(null);
    try {
      const baseName = files[0]?.name.replace(/\.[^.]+$/, "").trim();
      const docTypes = checklist.map(({ key, label, required }) => ({
        key,
        label,
        required,
      }));
      const pkg = await create({
        name: baseName || `Loan File ${new Date().toISOString().slice(0, 16)}`,
        hitl_threshold: DEFAULT_HITL_THRESHOLD,
        doc_types: docTypes,
        validation_rules: [],
        extraction_enabled: false,
        extraction_fields_by_doc: {},
      });
      // Hand the files off to the loan-overview page via an in-memory queue
      // and navigate immediately. The destination page runs the upload +
      // processPackage call with a visible "Uploading…" banner so the
      // operator sees continuous progress instead of a frozen modal. Doing
      // the upload inline here blocked the modal for 10–30s on large PDFs
      // and made the pipeline look like it was misbehaving on landing.
      enqueueUpload(pkg.id, { files, orgId: currentOrgId });
      window.dispatchEvent(new Event("loan-package-created"));
      router.push(orgPath(`/apps/loan-onboarding/loans/${pkg.id}`));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create file");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-file-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close dialog"
        onClick={() => !submitting && onClose()}
        className="absolute inset-0 bg-brand-charcoal/40 backdrop-blur-sm"
      />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-2xl overflow-hidden rounded-xl border bg-card shadow-2xl">
        <header className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-brand-teal">
              LogikIntake
            </p>
            <h2
              id="new-file-modal-title"
              className="mt-0.5 text-lg font-bold tracking-tight"
            >
              New Loan File
            </h2>
          </div>
          <button
            type="button"
            onClick={() => !submitting && onClose()}
            disabled={submitting}
            aria-label="Close"
            className="rounded-full p-1.5 text-muted-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-5 px-5 py-5">
          {/* Program profile */}
          <section>
            <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Program Profile
            </p>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              {PROFILES.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setProfileId(p.id)}
                  className={cn(
                    "rounded-lg border px-3 py-2.5 text-left text-sm transition-colors",
                    profileId === p.id
                      ? "border-brand-teal bg-brand-teal/5"
                      : "hover:bg-muted/30"
                  )}
                  aria-pressed={profileId === p.id}
                >
                  <p className="font-semibold">{p.name}</p>
                  <p className="text-[11px] text-muted-foreground">{p.type}</p>
                </button>
              ))}
            </div>
          </section>

          {/* Checklist preview */}
          <section>
            <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Expected Documents
            </p>
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {checklist.map((d) => (
                <li
                  key={d.key}
                  className="rounded-full bg-muted px-2.5 py-0.5 text-[11px] font-medium"
                >
                  {d.label}
                  {d.required && (
                    <span className="ml-1 text-brand-orange">*</span>
                  )}
                </li>
              ))}
            </ul>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              <span className="text-brand-orange">*</span> required · pages
              that don&rsquo;t fit fall into the catch-all bucket
            </p>
          </section>

          {/* Upload */}
          <section>
            <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Upload
            </p>
            <div
              className="mt-2 rounded-lg border-2 border-dashed border-border px-4 py-6 text-center"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                handleFiles(e.dataTransfer.files);
              }}
            >
              <p className="text-sm text-muted-foreground">
                Drag PDFs here, or
              </p>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="mt-2 inline-flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-xs font-semibold hover:bg-muted/30"
              >
                <Plus className="h-3.5 w-3.5" />
                Select files
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf"
                multiple
                className="hidden"
                onChange={(e) => handleFiles(e.target.files)}
              />
            </div>
            {files.length > 0 && (
              <ul className="mt-2 space-y-1.5">
                {files.map((f, i) => (
                  <li
                    key={`${f.name}-${i}`}
                    className="flex items-center justify-between rounded-md bg-muted/40 px-3 py-1.5 text-xs"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate font-medium">{f.name}</span>
                      <span className="shrink-0 text-muted-foreground">
                        {(f.size / 1024 / 1024).toFixed(1)} MB
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setFiles((prev) => prev.filter((_, j) => j !== i))
                      }
                      aria-label={`Remove ${f.name}`}
                      className="rounded-full p-1 text-muted-foreground hover:bg-background hover:text-destructive"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {error && (
            <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {error}
            </p>
          )}
        </div>

        <footer className="flex items-center justify-between border-t bg-muted/20 px-5 py-3">
          <button
            type="button"
            onClick={() => router.push(orgPath("/apps/loan-onboarding/packages/new"))}
            className="text-xs font-semibold text-brand-teal hover:underline"
          >
            Use full form →
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => !submitting && onClose()}
              disabled={submitting}
              className="rounded-md px-3 py-1.5 text-sm font-semibold text-muted-foreground hover:bg-muted disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              className="btn-cta gap-2 px-4 py-1.5 text-sm disabled:opacity-50"
            >
              {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {submitting ? "Creating…" : "Create file"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
