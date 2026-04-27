"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, FileText, X } from "lucide-react";
import { UploadDropzone } from "@/components/title-intelligence/upload-dropzone";
import { DocTypeSelector } from "@/components/loan-onboarding/doc-type-selector";
import { ExtractionConfig } from "@/components/loan-onboarding/extraction-config";
import {
  RuleBuilder,
  UNSUPPORTED_PRESET_IDS,
} from "@/components/loan-onboarding/rule-builder";
import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackages } from "@/hooks/use-loan-packages";
import { uploadFiles } from "@/lib/api";
import { processPackage } from "@/lib/loan-onboarding/api";
import {
  DEFAULT_HITL_THRESHOLD,
  OTHERS_DOC_TYPE_KEY,
  SUGGESTED_DOC_TYPES,
} from "@/lib/loan-onboarding/constants";
import type {
  LoanDocTypeSpec,
  LoanPackageRule,
} from "@/lib/loan-onboarding/types";

export default function NewLoanPackagePage() {
  const router = useRouter();
  const { currentOrgId } = useOrg();
  const { orgPath } = useOrgSlug();
  const { create } = useLoanPackages();

  const [files, setFiles] = useState<File[]>([]);
  const [docTypes, setDocTypes] = useState<LoanDocTypeSpec[]>(() =>
    // Seed every catalog type as selected by default — loan officers almost
    // always want the full superset in scope, and can deselect per package.
    // Others is excluded (backend reserves it implicitly and it's not shown).
    SUGGESTED_DOC_TYPES.filter((d) => d.key !== OTHERS_DOC_TYPE_KEY)
  );
  // No validations enabled by default — loan officers opt in per package.
  const [rules, setRules] = useState<LoanPackageRule[]>(() => []);
  // Extraction config (Section D). Default OFF — loan officers opt in per
  // package. When toggled on, doc-type field maps start empty and the user
  // either picks suggestion chips or types fields explicitly.
  const [extractionEnabled, setExtractionEnabled] = useState(false);
  const [extractionFields, setExtractionFields] = useState<
    Record<string, string[]>
  >(() => ({}));

  const [submitting, setSubmitting] = useState(false);
  const [stageLabel, setStageLabel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = files.length > 0 && !!currentOrgId && !submitting;

  const derivePackageName = () => {
    const first = files[0];
    if (first) {
      const base = first.name.replace(/\.[^.]+$/, "").trim();
      if (base) return base;
    }
    return `Loan Package ${new Date().toISOString().slice(0, 16).replace("T", " ")}`;
  };

  const handleSubmit = async () => {
    if (!canSubmit || !currentOrgId) return;
    setSubmitting(true);
    setError(null);
    try {
      setStageLabel("Creating package");
      // Backend reserves the "Others" key as an implicit catch-all bucket and
      // rejects it if listed explicitly. Strip it out before submit while
      // keeping it visible (and locked-selected) in the UI. Also drop the
      // UI-only `locked` field — backend DocTypeSpec uses extra="forbid".
      const submittableDocTypes = docTypes
        .filter((d) => d.key !== OTHERS_DOC_TYPE_KEY)
        .map(({ key, label, required }) => ({ key, label, required }));
      // Strip prototype-only presets the backend doesn't implement yet
      // (e.g. date_consistency). They're shown in the UI to match the
      // prototype but must not reach the classifier.
      const submittableRules = rules
        .filter(
          (r) =>
            !(
              r.rule_source === "preset" &&
              UNSUPPORTED_PRESET_IDS.has(r.rule_id)
            )
        )
        .map((r) => ({
          rule_source: r.rule_source,
          rule_id: r.rule_id,
          description: r.description ?? null,
          config: r.config,
        }));
      // Drop extraction map entries for doc types that aren't selected — keeps
      // the payload tight and prevents orphans on the server. Empty arrays
      // are also dropped (no point persisting a doc type with zero fields).
      const selectedKeys = new Set(submittableDocTypes.map((d) => d.key));
      const submittableExtractionFields: Record<string, string[]> = {};
      for (const [k, v] of Object.entries(extractionFields)) {
        if (!selectedKeys.has(k)) continue;
        if (v && v.length > 0) submittableExtractionFields[k] = v;
      }

      const pkg = await create({
        name: derivePackageName(),
        hitl_threshold: DEFAULT_HITL_THRESHOLD,
        doc_types: submittableDocTypes,
        validation_rules: submittableRules,
        extraction_enabled: extractionEnabled,
        extraction_fields_by_doc: submittableExtractionFields,
      });

      setStageLabel("Uploading files");
      await uploadFiles(
        `/api/v1/apps/loan-onboarding/packages/${pkg.id}/files`,
        files,
        { orgId: currentOrgId }
      );

      setStageLabel("Starting pipeline");
      await processPackage(currentOrgId, pkg.id);

      window.dispatchEvent(new Event("loan-package-created"));
      router.push(
        orgPath(`/apps/loan-onboarding/packages/${pkg.id}/processing`)
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create package");
    } finally {
      setSubmitting(false);
      setStageLabel(null);
    }
  };

  return (
    <div
      className="mx-auto w-full max-w-6xl space-y-8"
      data-testid="new-loan-package-page"
    >
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Create Loan Onboarding Package
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Configure the expected document mix and validation rules before we
          classify the borrower&apos;s files.
        </p>
      </div>

      {error && (
        <div
          className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
          data-testid="new-loan-package-error"
        >
          {error}
        </div>
      )}

      {/* 1. Upload */}
      <div className="section-card space-y-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Upload Package
        </h2>

        <UploadDropzone
          title="Upload a Loan Onboarding Package"
          buttonLabel="Select Package"
          onFilesSelected={(selected) =>
            setFiles((prev) => [...prev, ...selected])
          }
          uploading={submitting && stageLabel === "Uploading files"}
        />

        {files.length > 0 && (
          <div className="space-y-2">
            {files.map((f, i) => (
              <div
                key={`${f.name}-${i}`}
                className="flex items-center justify-between rounded-lg bg-muted/40 px-4 py-2.5 text-sm"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="truncate font-medium">{f.name}</span>
                  <span className="text-xs text-muted-foreground shrink-0">
                    {(f.size / 1024 / 1024).toFixed(1)} MB
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setFiles((prev) => prev.filter((_, j) => j !== i))
                  }
                  aria-label={`Remove ${f.name}`}
                  className="rounded-full p-1.5 text-muted-foreground hover:bg-background hover:text-red-500 transition-colors"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 3. Document types */}
      <div className="section-card space-y-6">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Document Types
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Choose the document types you expect in this package. The
            classifier picks from this list per page; pages that don&apos;t fit
            land in the catch-all bucket.
          </p>
        </div>
        <DocTypeSelector value={docTypes} onChange={setDocTypes} />
      </div>

      {/* 4. Validation rules */}
      <div className="section-card space-y-6">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Validation Rules
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Enable deterministic preset checks and add any bespoke
            natural-language rules to run against each document stack.
          </p>
        </div>
        <RuleBuilder value={rules} onChange={setRules} docTypes={docTypes} />
      </div>

      {/* 5. Field extraction (Section D) */}
      <div className="section-card space-y-6">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Field Extraction
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Configure structured fields to pull out of each document. Runs
            independently of validation and produces a downloadable feed for
            downstream LOS systems.
          </p>
        </div>
        <ExtractionConfig
          docTypes={docTypes}
          enabled={extractionEnabled}
          onEnabledChange={setExtractionEnabled}
          fieldsByDoc={extractionFields}
          onFieldsByDocChange={setExtractionFields}
        />
      </div>

      {/* Submit */}
      <div className="section-card">
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="w-full btn-cta gap-2 py-3"
          data-testid="create-loan-package-button"
        >
          {submitting
            ? stageLabel
              ? `${stageLabel}...`
              : "Submitting..."
            : (
              <>
                Create &amp; Process Package
                <ArrowRight className="h-4 w-4" />
              </>
            )}
        </button>
      </div>
    </div>
  );
}
