"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, FileText, X } from "lucide-react";
import { UploadDropzone } from "@/components/title-intelligence/upload-dropzone";
import { DocTypeSelector } from "@/components/loan-onboarding/doc-type-selector";
import { ExtractionConfig } from "@/components/loan-onboarding/extraction-config";
import { LoanContextForm } from "@/components/loan-onboarding/loan-context-form";
import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackages } from "@/hooks/use-loan-packages";
import { enqueueUpload } from "@/lib/loan-onboarding/upload-queue";
import {
  DEFAULT_HITL_THRESHOLD,
  OTHERS_DOC_TYPE_KEY,
  SUGGESTED_DOC_TYPES,
} from "@/lib/loan-onboarding/constants";
import { DEFAULT_LOAN_CONTEXT } from "@/lib/loan-onboarding/loan-context";
import type {
  DocValidations,
  LoanContextInput,
  LoanDocTypeSpec,
  LoanPackageRule,
} from "@/lib/loan-onboarding/types";
import { EMPTY_DOC_VALIDATIONS } from "@/lib/loan-onboarding/types";

// `date_consistency` is shown in the per-doc-type panel for parity with the
// prototype but has no backend evaluator yet — strip it before submit.
const UNSUPPORTED_PRESET_IDS = new Set(["date_consistency"]);

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
  // Per-doc-type validation toggles. No validations enabled by default — loan
  // officers opt in per package, per doc type. Seeded with an empty entry for
  // every initially-selected doc type so the UI can render the panel inline.
  const [validations, setValidations] = useState<Record<string, DocValidations>>(
    () => {
      const seed: Record<string, DocValidations> = {};
      for (const d of SUGGESTED_DOC_TYPES) {
        if (d.key === OTHERS_DOC_TYPE_KEY) continue;
        seed[d.key] = { ...EMPTY_DOC_VALIDATIONS, required_fields: [] };
      }
      return seed;
    }
  );
  // Extraction config (Section D). Default OFF — loan officers opt in per
  // package. When toggled on, doc-type field maps start empty and the user
  // either picks suggestion chips or types fields explicitly.
  const [extractionEnabled, setExtractionEnabled] = useState(false);
  const [extractionFields, setExtractionFields] = useState<
    Record<string, string[]>
  >(() => ({}));

  // Compliance context — defaults match `DEFAULT_LOAN_CONTEXT` (server-side
  // defaults). Off until the loan officer expands the section so packages that
  // skip compliance configuration land with `loan_context = null`.
  const [complianceEnabled, setComplianceEnabled] = useState(false);
  const [loanContext, setLoanContext] =
    useState<LoanContextInput>(DEFAULT_LOAN_CONTEXT);

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
      // Per-doc-type validations → wire-format `validation_rules`. Emit one
      // rule per preset, with `config.applies_to_doc_keys` listing the doc
      // types that have it enabled. For `missing_fields` we also pass the
      // per-doc field map. `date_consistency` is stripped — no backend
      // evaluator yet (matches prior `UNSUPPORTED_PRESET_IDS` behavior).
      const selectedDocKeys = new Set(submittableDocTypes.map((d) => d.key));
      const presetIds = [
        "missing_pages",
        "missing_signatures",
        "missing_fields",
      ] as const;
      const submittableRules: Pick<
        LoanPackageRule,
        "rule_source" | "rule_id" | "description" | "config"
      >[] = [];
      for (const presetId of presetIds) {
        if (UNSUPPORTED_PRESET_IDS.has(presetId)) continue;
        const enabledForKeys: string[] = [];
        const requiredFieldsByDoc: Record<string, string[]> = {};
        for (const [docKey, v] of Object.entries(validations)) {
          if (!selectedDocKeys.has(docKey)) continue;
          if (!v[presetId]) continue;
          enabledForKeys.push(docKey);
          if (presetId === "missing_fields" && v.required_fields.length > 0) {
            requiredFieldsByDoc[docKey] = [...v.required_fields];
          }
        }
        if (enabledForKeys.length === 0) continue;
        const config: Record<string, unknown> = {
          applies_to_doc_keys: enabledForKeys,
        };
        if (
          presetId === "missing_fields" &&
          Object.keys(requiredFieldsByDoc).length > 0
        ) {
          config.required_fields_by_doc = requiredFieldsByDoc;
        }
        submittableRules.push({
          rule_source: "preset",
          rule_id: presetId,
          description: null,
          config,
        });
      }
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
        // Only persist the loan context when the LO explicitly opted in —
        // submitting `null` lets the compliance engine fall back to defaults.
        loan_context: complianceEnabled ? loanContext : undefined,
      });

      // Hand the in-memory File objects off to the /processing page and
      // navigate immediately. The processing page owns the upload + pipeline
      // trigger from here so the user sees the pipeline scaffold without
      // waiting on the multipart upload to finish on this screen.
      enqueueUpload(pkg.id, { files, orgId: currentOrgId });
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
          Configure the expected document mix and per-document validation
          checks before we classify the borrower&apos;s files.
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
          title="Upload a Package"
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
        <DocTypeSelector
          value={docTypes}
          onChange={setDocTypes}
          validations={validations}
          onValidationsChange={setValidations}
        />
      </div>

      {/* 3. Field extraction (Section D) */}
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

      {/* 4. Compliance context */}
      <div className="section-card space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Compliance Context
            </h2>
            <p className="text-xs text-muted-foreground mt-1">
              Optional. Tell the compliance engine which program, purpose,
              state, and scenario flags apply so the rule set narrows correctly
              and the report header is accurate.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm shrink-0">
            <input
              type="checkbox"
              checked={complianceEnabled}
              onChange={(e) => setComplianceEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-input"
              data-testid="compliance-context-toggle"
            />
            <span>Configure now</span>
          </label>
        </div>

        {complianceEnabled ? (
          <LoanContextForm value={loanContext} onChange={setLoanContext} />
        ) : (
          <p className="text-xs text-muted-foreground">
            Skipping for now. You can fill this in later from the package&apos;s
            Compliance tab — but the report header and rule applicability will
            use defaults until then.
          </p>
        )}
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
