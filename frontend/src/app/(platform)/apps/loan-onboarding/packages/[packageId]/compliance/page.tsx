"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Info,
  Settings2,
  ShieldCheck,
  X,
  XCircle,
} from "lucide-react";
import { useOrg } from "@/hooks/use-org";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import {
  useInvalidateCompliance,
  useLoanCompliance,
} from "@/hooks/use-loan-data";
import { updateComplianceContext } from "@/lib/loan-onboarding/api";
import {
  adaptComplianceReport,
  type ComplianceReport,
} from "@/lib/loan-onboarding/compliance";
import { DEFAULT_LOAN_CONTEXT } from "@/lib/loan-onboarding/loan-context";
import type { LoanContextInput } from "@/lib/loan-onboarding/types";
import { cn } from "@/lib/utils";
import { downloadCompliancePdf } from "@/lib/loan-onboarding/compliance-pdf";
import { LoanContextForm } from "@/components/loan-onboarding/loan-context-form";
import { LoanOfficerView } from "@/components/loan-onboarding/compliance/loan-officer-view";
import { QcComplianceView } from "@/components/loan-onboarding/compliance/qc-compliance-view";

type Persona = "lo" | "qc";

const STATUS_HEADER: Record<
  ComplianceReport["summary"]["overallStatus"],
  { tone: string; label: string; icon: typeof ShieldCheck }
> = {
  pass: {
    tone: "from-emerald-50 to-emerald-100/40 border-emerald-200 text-emerald-900",
    label: "Compliant",
    icon: CheckCircle2,
  },
  needs_attention: {
    tone: "from-amber-50 to-amber-100/40 border-amber-200 text-amber-900",
    label: "Needs Attention",
    icon: AlertTriangle,
  },
  fail: {
    tone: "from-red-50 to-red-100/40 border-red-200 text-red-900",
    label: "Critical Issues",
    icon: XCircle,
  },
};

export default function CompliancePage() {
  const params = useParams();
  const packageId = params.packageId as string;
  const { currentOrgId } = useOrg();
  const { package: pkg, loading: pkgLoading } = useLoanPackage(packageId);
  const [persona, setPersona] = useState<Persona>("lo");
  const [contextModalOpen, setContextModalOpen] = useState(false);

  // GET /compliance — backend evaluates-if-missing-or-returns-cached. The
  // previous version POSTed /compliance/evaluate inside a useEffect that had
  // `pkg` in its deps, so every package refetch (e.g. tab navigation) re-ran
  // a full evaluation against unchanged inputs. Switching to the cached GET
  // makes Compliance tab loads paint instantly on repeat visits.
  const packageStatus = pkg?.status ?? null;
  const complianceQuery = useLoanCompliance({ packageId, packageStatus });
  const invalidateCompliance = useInvalidateCompliance(packageId);

  const report: ComplianceReport | null = useMemo(() => {
    if (!complianceQuery.data) return null;
    return adaptComplianceReport(complianceQuery.data, pkg ?? null);
  }, [complianceQuery.data, pkg]);

  const loading = complianceQuery.isLoading;

  if (pkgLoading || loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">
          Evaluating compliance…
        </p>
      </div>
    );
  }

  if (!pkg || !report) {
    return (
      <p className="text-muted-foreground py-10 text-center">
        Compliance report unavailable — package not found.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <ComplianceHeader
        report={report}
        orgId={currentOrgId ?? ""}
        onEditContext={() => setContextModalOpen(true)}
      />
      <PersonaTabs persona={persona} onChange={setPersona} />
      {persona === "lo" ? (
        <LoanOfficerView report={report} />
      ) : (
        <QcComplianceView report={report} />
      )}
      <DisclaimerNote />

      {contextModalOpen && currentOrgId && (
        <EditContextModal
          orgId={currentOrgId}
          packageId={packageId}
          initial={pkg.loan_context ?? DEFAULT_LOAN_CONTEXT}
          onClose={() => setContextModalOpen(false)}
          onSaved={async () => {
            // Backend's PATCH /compliance/context already persisted a fresh
            // LOComplianceRun against the new context (compliance_service.
            // update_loan_context calls evaluate(persist=True)). Invalidate
            // both the package detail (for `loan_context`) and the compliance
            // run cache; the next render reads the persisted run via the
            // useLoanCompliance hook above without an extra refetch wired
            // up here.
            await invalidateCompliance();
          }}
        />
      )}
    </div>
  );
}

function ComplianceHeader({
  report,
  orgId,
  onEditContext,
}: {
  report: ComplianceReport;
  orgId: string;
  onEditContext: () => void;
}) {
  const cfg = STATUS_HEADER[report.summary.overallStatus];
  const Icon = cfg.icon;
  return (
    <div
      className={cn("rounded-lg border bg-gradient-to-br p-6", cfg.tone)}
      data-testid="compliance-header"
    >
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3 min-w-0">
          <Icon className="h-7 w-7 mt-0.5 shrink-0" />
          <div className="min-w-0">
            <div className="font-mono text-[10px] tracking-[0.2em] uppercase opacity-80">
              Compliance Status
            </div>
            <h1 className="text-2xl font-semibold mt-0.5">{cfg.label}</h1>
            <div className="text-sm opacity-80 mt-1">
              {report.packageName}
              {report.loanReference ? ` · ${report.loanReference}` : ""}
              {report.borrowerName ? ` · ${report.borrowerName}` : ""}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onEditContext}
            className="px-4 py-2 bg-white/70 text-foreground text-sm font-medium flex items-center gap-2 rounded-md border border-stone-300 hover:bg-white transition-colors"
            data-testid="compliance-edit-context"
          >
            <Settings2 className="h-4 w-4" /> Edit Context
          </button>
          <button
            type="button"
            onClick={() => {
              void downloadCompliancePdf(report, orgId);
            }}
            disabled={!orgId}
            className="px-4 py-2 bg-amber-500 text-white text-sm font-medium flex items-center gap-2 rounded-md shadow-sm hover:bg-amber-600 transition-colors disabled:opacity-50"
            data-testid="compliance-download-pdf"
          >
            <Download className="h-4 w-4" /> Download PDF
          </button>
        </div>
      </div>
    </div>
  );
}

function EditContextModal({
  orgId,
  packageId,
  initial,
  onClose,
  onSaved,
}: {
  orgId: string;
  packageId: string;
  initial: LoanContextInput;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}) {
  const [draft, setDraft] = useState<LoanContextInput>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      // PATCH persists context AND re-evaluates compliance server-side
      // (compliance_service.update_loan_context → evaluate(persist=True)).
      await updateComplianceContext(orgId, packageId, draft);
      // Then ask the parent to refresh its view from the just-persisted run.
      // The modal stays mounted (and the Save button stays in the "Saving…"
      // state) until both the PATCH and the refresh resolve, so the user
      // gets uninterrupted blocking feedback.
      await onSaved();
      onClose();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to save loan context"
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      data-testid="compliance-edit-context-modal"
    >
      <button
        type="button"
        aria-label="Close dialog"
        onClick={onClose}
        className="absolute inset-0 bg-black/40 cursor-default"
      />
      <div
        className="relative w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-lg border bg-background shadow-xl"
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-start justify-between gap-4 border-b px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold">Edit compliance context</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Updating these values re-runs the compliance engine on the next
              load. The PDF report will reflect them immediately.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-6 py-5">
          <LoanContextForm value={draft} onChange={setDraft} compact />
        </div>

        {error && (
          <div className="mx-6 mb-4 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t px-6 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 text-sm font-medium rounded-md border border-stone-300 hover:bg-stone-50 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
            className="px-4 py-2 text-sm font-medium rounded-md bg-amber-500 text-white shadow-sm hover:bg-amber-600 transition-colors disabled:opacity-50"
            data-testid="compliance-edit-context-save"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function PersonaTabs({
  persona,
  onChange,
}: {
  persona: Persona;
  onChange: (p: Persona) => void;
}) {
  return (
    <div
      className="inline-flex items-center gap-1 bg-stone-100 p-1 rounded-md border border-stone-200"
      role="tablist"
      data-testid="compliance-persona-tabs"
    >
      <PersonaTab
        active={persona === "lo"}
        onClick={() => onChange("lo")}
        label="Loan Officer"
        testId="compliance-persona-lo"
      />
      <PersonaTab
        active={persona === "qc"}
        onClick={() => onChange("qc")}
        label="QC / Compliance"
        testId="compliance-persona-qc"
      />
    </div>
  );
}

function PersonaTab({
  active,
  onClick,
  label,
  testId,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  testId: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        "px-4 py-1.5 text-sm font-medium rounded transition-colors",
        active
          ? "bg-white text-foreground shadow-sm ring-1 ring-stone-200"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      {label}
    </button>
  );
}

function DisclaimerNote() {
  return (
    <div className="flex items-start gap-2 text-[11px] text-muted-foreground bg-stone-50 border border-stone-200 rounded p-3">
      <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
      <p>
        This compliance report is an automated triage tool intended to assist
        the loan officer and compliance reviewer. It does not replace a
        licensed compliance officer&apos;s review or an attorney&apos;s legal
        opinion. Citations reference federal regulations as of the report
        generation date — confirm against the current eCFR before relying on
        them. State-specific requirements are not evaluated.
      </p>
    </div>
  );
}
