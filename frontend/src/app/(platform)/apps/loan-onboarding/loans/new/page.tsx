"use client";

// LogikIntake — "New Loan File" full-page wizard.
//
// Mirrors the prototype at prototype/src/app/logik-intake/loans/new/page.tsx.
// Two phases:
//   1. EMPTY   — big teal-dashed upload zone + capabilities grid + optional
//                manual form. "Browse Files" / drop / "Create File" all
//                advance to phase 2.
//   2. REVIEW  — upload status banner, extraction-summary stat tiles, four
//                review cards (Borrower / Loan Details / Program & Investor /
//                Assignment), "What happens next" panel, sticky footer with
//                "Create File & Start Pipeline".
//
// On "Create File & Start Pipeline" we call useLoanPackages.create, hand
// the selected files off to the upload-queue, and navigate to the loan
// detail page where upload + pipeline processing kick off.

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Bell,
  Building2,
  Calendar,
  CheckCircle2,
  CircleDashed,
  Cloud,
  DollarSign,
  Edit3,
  FilePlus,
  FolderOpen,
  GitBranch,
  ListChecks,
  Loader2,
  MapPin,
  Plus,
  Sliders,
  Sparkles,
  User,
  X,
} from "lucide-react";

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

// ── Constants (mirror prototype) ──────────────────────────────────────

type Phase = "empty" | "review";

type LoanProgram =
  | "Conventional 30yr"
  | "FHA Purchase"
  | "VA 30yr"
  | "USDA Rural Development"
  | "Jumbo";

const PROGRAMS: LoanProgram[] = [
  "Conventional 30yr",
  "FHA Purchase",
  "VA 30yr",
  "USDA Rural Development",
  "Jumbo",
];

const INVESTORS = [
  "Fannie Mae DU",
  "Freddie Mac LPA",
  "Ginnie Mae I",
  "Ginnie Mae II",
  "Portfolio — Internal",
];

// Program profile → which doc-type keys are pre-checked on submit. Mirrors
// the lighter modal version that already shipped (kept so the queue stays
// configured similarly), extended to cover the full prototype's program
// list (USDA was missing before).
const PROGRAM_DOC_KEYS: Record<LoanProgram, string[]> = {
  "Conventional 30yr": [
    "urla_1003",
    "paystub",
    "w2",
    "bank_stmt",
    "credit_report",
  ],
  "FHA Purchase": [
    "urla_1003",
    "paystub",
    "w2",
    "bank_stmt",
    "credit_report",
  ],
  "VA 30yr": ["urla_1003", "paystub", "w2"],
  "USDA Rural Development": [
    "urla_1003",
    "paystub",
    "w2",
    "bank_stmt",
    "credit_report",
  ],
  Jumbo: ["urla_1003", "f1040", "bank_stmt"],
};

const CAPABILITIES = [
  {
    Icon: User,
    title: "Borrower & Co-Borrower names",
    source: "From 1003 Application or MISMO XML",
  },
  {
    Icon: MapPin,
    title: "Property address & details",
    source: "From Purchase Agreement or 1003",
  },
  {
    Icon: DollarSign,
    title: "Loan amount & purchase price",
    source: "From 1003, Closing Disclosure, or AUS",
  },
  {
    Icon: Sliders,
    title: "Loan program indicators",
    source: "From AUS Findings, 1003 Section 4",
  },
  {
    Icon: Building2,
    title: "Investor & AUS preferences",
    source: "From LOS sync or AUS report",
  },
  {
    Icon: Calendar,
    title: "Expected close date",
    source: "From Purchase Agreement",
  },
];

const NEXT_STEPS = [
  { Icon: FilePlus, t: "Create the loan file and add it to the queue" },
  {
    Icon: GitBranch,
    t: "Start the Loan Boarding pipeline — Uploaded files enter ingestion immediately",
  },
  {
    Icon: ListChecks,
    t: "Generate initial document checklist based on program + investor selection",
  },
  {
    Icon: Sparkles,
    t: "Continue extracting additional fields from the uploaded documents in the background",
  },
  {
    Icon: Bell,
    t: "Notify the assigned processor with the first task — files will be ready for classification review",
  },
];

const FILE_TYPE_TAGS = [
  "1003 Application",
  "MISMO XML",
  "AUS Findings",
  "Closing Disclosure",
  "Initial Doc Package",
  "Any mortgage document",
];

// ── Main page ─────────────────────────────────────────────────────────

export default function NewLoanFilePage() {
  const router = useRouter();
  const { currentOrgId } = useOrg();
  const { orgPath } = useOrgSlug();
  const { create } = useLoanPackages();

  const [phase, setPhase] = useState<Phase>("empty");
  const [manualOpen, setManualOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Inline error surfaced when the operator clicks Create before uploading
  // any files. Cleared when a file is added.
  const [fileRequiredError, setFileRequiredError] = useState(false);

  // Manual + review form state. Defaults mirror the prototype's demo
  // "extracted" values so the review phase looks populated end-to-end;
  // operators can edit any field before clicking Create.
  const [borrowerName, setBorrowerName] = useState("Sarah Mitchell");
  const [program, setProgram] = useState<LoanProgram>("Conventional 30yr");
  const [investor, setInvestor] = useState<string>("");
  const [propertyAddress, setPropertyAddress] = useState(
    "421 Oak Lane, San Jose CA 95101",
  );
  const [loanAmount, setLoanAmount] = useState("$385,000");

  const queueHref = orgPath("/apps/loan-onboarding");

  const onResetUpload = () => {
    setPhase("empty");
    setFiles([]);
    setFileRequiredError(false);
  };

  const onClearFiles = () => {
    setFiles([]);
    setFileRequiredError(false);
  };

  const handleFiles = (incoming: FileList | null) => {
    if (!incoming || incoming.length === 0) return;
    setFiles((prev) => [...prev, ...Array.from(incoming)]);
    setFileRequiredError(false);
    // Don't auto-advance to Review. Review only opens when the operator
    // explicitly toggled Manual Entry and then clicked Create — otherwise
    // Create goes straight to pipeline processing.
  };

  // Hard gate: a file must be uploaded before we accept the form and start
  // the pipeline. Manual details are supplementary — they cannot stand in
  // for the file upload (mirrors the prototype's HTML reference behavior).
  // Flow on Create from the empty phase:
  //   - no files            → show file-required warning
  //   - files + manualOpen  → step into Review so the operator can confirm
  //                            the manually entered details before submit
  //   - files + !manualOpen → submit immediately and navigate to pipeline
  const onCreate = async () => {
    if (!currentOrgId || submitting) return;
    if (files.length === 0) {
      setFileRequiredError(true);
      return;
    }
    if (phase === "empty" && manualOpen) {
      setPhase("review");
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      // Compute doc-type checklist from the chosen program profile. Doc
      // types not in the checklist still flow through the classifier but
      // land in the catch-all "Others" bucket.
      const keys = PROGRAM_DOC_KEYS[program];
      const docTypes = SUGGESTED_DOC_TYPES.filter(
        (d) => d.key !== OTHERS_DOC_TYPE_KEY && keys.includes(d.key),
      ).map(({ key, label, required }) => ({ key, label, required }));

      const trimmedName = borrowerName.trim() || "New Borrower";
      const pkg = await create({
        name: `Loan File — ${trimmedName}`,
        borrower_name: trimmedName,
        hitl_threshold: DEFAULT_HITL_THRESHOLD,
        doc_types: docTypes,
        validation_rules: [],
        extraction_enabled: true,
        extraction_fields_by_doc: {},
      });

      // Hand files off to the loan detail page (which runs upload + process
      // with a visible "Uploading…" banner). Skip if no files were dropped
      // — the loan still gets created and the operator can upload later
      // from the detail screen.
      if (files.length > 0) {
        enqueueUpload(pkg.id, { files, orgId: currentOrgId });
      }
      window.dispatchEvent(new Event("loan-package-created"));
      router.push(orgPath(`/apps/loan-onboarding/loans/${pkg.id}`));
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Failed to create loan file",
      );
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-8 py-8 pb-24">
      <button
        type="button"
        onClick={() => router.push(queueHref)}
        className="mb-4 inline-flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-[11px] font-semibold text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Queue
      </button>

      <header className="mb-5">
        <h1 className="text-xl font-bold tracking-tight">
          {phase === "empty"
            ? "New Loan File"
            : "New Loan File — Review Extracted Details"}
        </h1>
        <p className="mt-1 text-xs text-muted-foreground">
          {phase === "empty"
            ? "Drop a file to create the loan record and start the pipeline automatically — or fill in details manually."
            : "Logikality extracted these details from your uploaded files. Review and correct anything before creating the file."}
        </p>
      </header>

      {phase === "empty" ? (
        <EmptyState
          files={files}
          onFiles={handleFiles}
          onClearFiles={onClearFiles}
          manualOpen={manualOpen}
          toggleManual={() => setManualOpen((v) => !v)}
          borrowerName={borrowerName}
          setBorrowerName={setBorrowerName}
          program={program}
          setProgram={setProgram}
          investor={investor}
          setInvestor={setInvestor}
          propertyAddress={propertyAddress}
          setPropertyAddress={setPropertyAddress}
          loanAmount={loanAmount}
          setLoanAmount={setLoanAmount}
        />
      ) : (
        <ReviewState
          files={files}
          onAddFiles={handleFiles}
          onResetUpload={onResetUpload}
          borrowerName={borrowerName}
          setBorrowerName={setBorrowerName}
          program={program}
          setProgram={setProgram}
          investor={investor}
          setInvestor={setInvestor}
          propertyAddress={propertyAddress}
          setPropertyAddress={setPropertyAddress}
          loanAmount={loanAmount}
          setLoanAmount={setLoanAmount}
        />
      )}

      {submitError && (
        <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {submitError}
        </div>
      )}

      {/* Sticky footer */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 px-6 py-3 shadow-[0_-2px_8px_rgba(0,0,0,0.06)] backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center gap-2.5">
          <button
            type="button"
            onClick={() => router.push(queueHref)}
            disabled={submitting}
            className="inline-flex items-center gap-1 rounded-md border bg-card px-3 py-1.5 text-[11px] font-semibold text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            Cancel
          </button>
          {phase === "review" && (
            <button
              type="button"
              onClick={onResetUpload}
              disabled={submitting}
              className="inline-flex items-center gap-1 rounded-md border bg-card px-3 py-1.5 text-[11px] font-semibold text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
            >
              Start Over
            </button>
          )}
          <div className="flex-1 text-center text-[11px]">
            {fileRequiredError && files.length === 0 ? (
              <span className="inline-flex items-center gap-1 font-semibold text-rose-600">
                <AlertTriangle className="h-3 w-3" />
                Please upload a file before creating the loan — manual
                details alone aren&apos;t enough
              </span>
            ) : phase === "empty" ? (
              files.length === 0 ? (
                <span className="text-muted-foreground">
                  Upload a file to continue — manual details are optional
                </span>
              ) : manualOpen ? (
                <span className="text-muted-foreground">
                  {files.length} file{files.length === 1 ? "" : "s"} ready —
                  Create will open Review before the pipeline starts
                </span>
              ) : (
                <span className="text-muted-foreground">
                  {files.length} file{files.length === 1 ? "" : "s"} ready —
                  Create to start the pipeline
                </span>
              )
            ) : !investor ? (
              <span className="inline-flex items-center gap-1 font-semibold text-[#7A5000]">
                <AlertTriangle className="h-3 w-3" />1 field still needs your
                input — Investor Overlay
              </span>
            ) : (
              <span className="text-muted-foreground">
                All required fields populated — ready to create
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onCreate}
            disabled={submitting || !currentOrgId}
            className="inline-flex items-center gap-1.5 rounded-md bg-gradient-to-br from-[#01BAED] to-[#0098C2] px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:brightness-105 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <FilePlus className="h-3.5 w-3.5" />
            )}
            {submitting ? "Creating…" : "Create File & Start Pipeline"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── EMPTY STATE ──────────────────────────────────────────────────────

interface EmptyStateProps {
  files: File[];
  onFiles: (files: FileList | null) => void;
  onClearFiles: () => void;
  manualOpen: boolean;
  toggleManual: () => void;
  borrowerName: string;
  setBorrowerName: (v: string) => void;
  program: LoanProgram;
  setProgram: (p: LoanProgram) => void;
  investor: string;
  setInvestor: (v: string) => void;
  propertyAddress: string;
  setPropertyAddress: (v: string) => void;
  loanAmount: string;
  setLoanAmount: (v: string) => void;
}

function EmptyState({
  files,
  onFiles,
  onClearFiles,
  manualOpen,
  toggleManual,
  borrowerName,
  setBorrowerName,
  program,
  setProgram,
  investor,
  setInvestor,
  propertyAddress,
  setPropertyAddress,
  loanAmount,
  setLoanAmount,
}: EmptyStateProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  return (
    <>
      {/* Big upload zone */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          onFiles(e.dataTransfer.files);
        }}
        className="group cursor-pointer rounded-2xl border-2 border-dashed border-brand-teal bg-gradient-to-br from-[#EBF9FF] to-[#F0FDF4] px-8 py-10 text-center transition hover:border-solid hover:bg-[#D6F5FD]"
      >
        <div
          className="mx-auto mb-4 flex items-center justify-center rounded-full bg-brand-teal"
          style={{ width: 60, height: 60 }}
        >
          <Cloud className="h-7 w-7 text-[#1A1A2E]" />
        </div>
        <p className="text-lg font-extrabold tracking-tight text-[#1A1A2E]">
          Drop a file to get started
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
          Logikality extracts borrower, loan, and program details
          automatically.
          <br />
          You review and confirm — then the pipeline starts.
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
          {FILE_TYPE_TAGS.map((t) => (
            <span
              key={t}
              className="inline-flex items-center rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-medium text-muted-foreground ring-1 ring-border"
            >
              {t}
            </span>
          ))}
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            fileInputRef.current?.click();
          }}
          className="mt-5 inline-flex items-center gap-1.5 rounded-md bg-gradient-to-br from-[#01BAED] to-[#0098C2] px-7 py-2.5 text-[13px] font-bold text-white shadow-sm transition hover:brightness-105 hover:shadow-md"
        >
          <FolderOpen className="h-3.5 w-3.5" />
          Browse Files
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(e) => onFiles(e.target.files)}
        />
        <p className="mt-2.5 text-[11px] text-muted-foreground">
          PDF, JPEG, PNG, TIFF · Multiple files · Max 50MB per file
        </p>
      </div>

      {/* Uploaded-files banner (only when at least one file has been picked). */}
      {files.length > 0 && (
        <div className="mt-3 flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
          <div className="min-w-0 flex-1">
            <p className="text-[12px] font-bold text-emerald-800">
              {files.length} file{files.length === 1 ? "" : "s"} uploaded
            </p>
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {files.map((f) => f.name).join(" · ")}
            </p>
          </div>
          <button
            type="button"
            onClick={onClearFiles}
            className="inline-flex items-center gap-1 rounded-md border bg-card px-2.5 py-1 text-[11px] font-semibold text-rose-600 hover:bg-rose-50"
          >
            <X className="h-3 w-3" />
            Remove
          </button>
        </div>
      )}

      {/* What gets extracted */}
      <div className="mt-5">
        <p className="mb-2.5 flex items-center gap-2 text-[12px] font-bold text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-brand-teal" />
          What Logikality auto-extracts from your file
        </p>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          {CAPABILITIES.map(({ Icon, title, source }) => (
            <div
              key={title}
              className="flex items-start gap-2.5 rounded-md border border-brand-teal/15 bg-white/60 px-2.5 py-2"
            >
              <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-teal" />
              <div>
                <p className="text-[12px] font-bold text-foreground">{title}</p>
                <p className="text-[10px] text-muted-foreground">{source}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Manual fallback toggle */}
      <div className="mt-5 text-center">
        <button
          type="button"
          onClick={toggleManual}
          className="text-[12px] font-semibold text-brand-teal underline underline-offset-2 hover:text-[#0098C2]"
        >
          {manualOpen
            ? "Hide manual form ↑"
            : "Prefer to type details instead? Enter manually ↓"}
        </button>
      </div>

      {manualOpen && (
        <ManualForm
          borrowerName={borrowerName}
          setBorrowerName={setBorrowerName}
          program={program}
          setProgram={setProgram}
          investor={investor}
          setInvestor={setInvestor}
          propertyAddress={propertyAddress}
          setPropertyAddress={setPropertyAddress}
          loanAmount={loanAmount}
          setLoanAmount={setLoanAmount}
        />
      )}
    </>
  );
}

interface ManualFormProps {
  borrowerName: string;
  setBorrowerName: (v: string) => void;
  program: LoanProgram;
  setProgram: (p: LoanProgram) => void;
  investor: string;
  setInvestor: (v: string) => void;
  propertyAddress: string;
  setPropertyAddress: (v: string) => void;
  loanAmount: string;
  setLoanAmount: (v: string) => void;
}

function ManualForm({
  borrowerName,
  setBorrowerName,
  program,
  setProgram,
  investor,
  setInvestor,
  propertyAddress,
  setPropertyAddress,
  loanAmount,
  setLoanAmount,
}: ManualFormProps) {
  return (
    <div className="mt-4 rounded-xl border bg-card p-5">
      <p className="mb-3.5 text-[13px] font-bold text-foreground">
        Enter details manually — all fields optional if uploading later
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <FieldLbl>Primary Borrower</FieldLbl>
          <ManualInput
            placeholder="Full name"
            value={borrowerName}
            onChange={(e) => setBorrowerName(e.target.value)}
          />
        </div>
        <div>
          <FieldLbl>Co-Borrower</FieldLbl>
          <ManualInput placeholder="Full name (optional)" />
        </div>
        <div>
          <FieldLbl>Loan Program</FieldLbl>
          <ManualSelect
            value={program}
            onChange={(e) => setProgram(e.target.value as LoanProgram)}
          >
            {PROGRAMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </ManualSelect>
        </div>
        <div>
          <FieldLbl>Investor Overlay</FieldLbl>
          <ManualSelect
            value={investor}
            onChange={(e) => setInvestor(e.target.value)}
          >
            <option value="">— Select if known —</option>
            {INVESTORS.map((i) => (
              <option key={i} value={i}>
                {i}
              </option>
            ))}
          </ManualSelect>
        </div>
        <div>
          <FieldLbl>Property Address</FieldLbl>
          <ManualInput
            placeholder="Street, City, State ZIP (optional)"
            value={propertyAddress}
            onChange={(e) => setPropertyAddress(e.target.value)}
          />
        </div>
        <div>
          <FieldLbl>Loan Amount</FieldLbl>
          <ManualInput
            placeholder="$ (optional)"
            value={loanAmount}
            onChange={(e) => setLoanAmount(e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}

function FieldLbl({ children }: { children: React.ReactNode }) {
  return (
    <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
      {children}
    </span>
  );
}

function ManualInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="h-9 w-full rounded-md border border-border bg-card px-2.5 text-[12px] focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
    />
  );
}

function ManualSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className="h-9 w-full rounded-md border border-border bg-card px-2 text-[12px] focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
    >
      {props.children}
    </select>
  );
}

// ─── REVIEW STATE ─────────────────────────────────────────────────────

type FieldKind = "auto" | "low" | "gen" | "missing";

interface ReviewProps {
  files: File[];
  onAddFiles: (files: FileList | null) => void;
  onResetUpload: () => void;
  borrowerName: string;
  setBorrowerName: (v: string) => void;
  program: LoanProgram;
  setProgram: (p: LoanProgram) => void;
  investor: string;
  setInvestor: (v: string) => void;
  propertyAddress: string;
  setPropertyAddress: (v: string) => void;
  loanAmount: string;
  setLoanAmount: (v: string) => void;
}

function ReviewState({
  files,
  onAddFiles,
  onResetUpload,
  borrowerName,
  setBorrowerName,
  program,
  setProgram,
  investor,
  setInvestor,
  propertyAddress,
  setPropertyAddress,
  loanAmount,
  setLoanAmount,
}: ReviewProps) {
  const addFilesRef = useRef<HTMLInputElement | null>(null);
  const fileNames =
    files.length > 0
      ? files.map((f) => f.name).join(" · ")
      : "1003_Application.pdf · Initial_Docs_Package.pdf";
  const fileCountLabel =
    files.length > 0
      ? `${files.length} file${files.length === 1 ? "" : "s"} uploaded — extraction complete`
      : "2 files uploaded — extraction complete";
  return (
    <>
      {/* Upload status banner */}
      <div className="mb-4 flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3">
        <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-bold text-emerald-800">
            {fileCountLabel}
          </p>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {fileNames}
          </p>
        </div>
        <button
          type="button"
          onClick={() => addFilesRef.current?.click()}
          className="inline-flex items-center gap-1 rounded-md border bg-card px-2.5 py-1 text-[11px] font-semibold text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Plus className="h-3 w-3" />
          Add More Files
        </button>
        <input
          ref={addFilesRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(e) => onAddFiles(e.target.files)}
        />
        <button
          type="button"
          onClick={onResetUpload}
          className="inline-flex items-center gap-1 rounded-md border bg-card px-2.5 py-1 text-[11px] font-semibold text-rose-600 hover:bg-rose-50"
        >
          <X className="h-3 w-3" />
          Remove
        </button>
      </div>

      {/* Extraction summary stat tiles */}
      <div className="mb-4 grid grid-cols-3 gap-2.5">
        <SummaryTile
          tone="pass"
          Icon={Sparkles}
          value="8 fields"
          label="Auto-extracted — no action needed"
        />
        <SummaryTile
          tone="warn"
          Icon={AlertTriangle}
          value="2 fields"
          label="Low confidence — please verify"
        />
        <SummaryTile
          tone="fail"
          Icon={CircleDashed}
          value="1 field"
          label="Not found — your input needed"
        />
      </div>

      {/* Borrower Information */}
      <Card title="Borrower Information">
        <ExField
          label="Primary Borrower"
          value={borrowerName}
          onChange={setBorrowerName}
          kind="auto"
          source="1003 — 97%"
          highlight
        />
        <ExField
          label="Co-Borrower"
          defaultValue="Tom Mitchell"
          kind="auto"
          source="1003 — 94%"
        />
        <ExField
          label="Primary SSN — Last 4"
          defaultValue="4521"
          kind="auto"
          source="1003 — 92%"
        />
        <ExField
          label="Co-Borrower SSN — Last 4"
          defaultValue="3309"
          kind="auto"
          source="1003 — 89%"
        />
      </Card>

      {/* Loan Details */}
      <Card title="Loan Details">
        <ExField label="Loan Number" defaultValue="LGK-2026-0871" kind="gen" />
        <ExField
          label="Loan Purpose"
          defaultValue="Purchase"
          kind="auto"
          source="1003 Section 1 — 99%"
          highlight
        />
        <ExField
          label="Property Address"
          value={propertyAddress}
          onChange={setPropertyAddress}
          kind="auto"
          source="1003 Section 2 — 94%"
          highlight
        />
        <ExField
          label="Property Type"
          defaultValue="Single Family Residence"
          kind="auto"
          source="1003 — 91%"
          highlight
        />
        <ExField
          label="Occupancy"
          defaultValue="Primary Residence"
          kind="auto"
          source="1003 — 97%"
          highlight
        />
        <ExField
          label="Purchase Price"
          defaultValue="$480,000"
          kind="low"
          source="1003 vs. Purchase Agmt differ — verify"
          highlight
        />
        <ExField
          label="Loan Amount"
          value={loanAmount}
          onChange={setLoanAmount}
          kind="low"
          source="1003 vs. AUS differ by $3,000 — verify"
          highlight
        />
        <ExField
          label="Expected Close Date"
          defaultValue="June 30, 2026"
          kind="auto"
          source="Purchase Agreement — 96%"
        />
      </Card>

      {/* Program & Investor */}
      <Card title="Program & Investor">
        <ExSelect
          label="Loan Program"
          value={program}
          onChange={(v) => setProgram(v as LoanProgram)}
          options={PROGRAMS}
          kind="auto"
          source="AUS Findings — DU Approve/Eligible"
          highlight
        />
        <ExSelect
          label="Investor Overlay"
          value={investor}
          onChange={setInvestor}
          options={INVESTORS}
          placeholder="— Not detected — please select —"
          kind="missing"
          required
        />
        <ExField
          label="AUS System"
          defaultValue="Fannie Mae DU"
          kind="auto"
          source="AUS Findings — DU Approve/Eligible 97%"
          highlight
        />
        <div className="mt-2 rounded-md border border-brand-teal/25 bg-gradient-to-br from-[#EBF9FF] to-[#F0FDF4] px-3 py-2.5">
          <p className="mb-1 flex items-center gap-1.5 text-[11px] font-bold text-muted-foreground">
            <Sparkles className="h-3 w-3 text-brand-teal" />
            Once you select Investor, requirements preview will appear here
          </p>
          <p className="text-[11px] text-muted-foreground">
            {program} + {investor || "selected investor"} → 13 documents
            required · 24 rules active · Est. STP: 78%
          </p>
        </div>
      </Card>

      {/* What happens next */}
      <div className="mt-3 rounded-lg border bg-muted/30 px-4 py-3">
        <p className="mb-2 flex items-center gap-1.5 text-[12px] font-bold text-foreground">
          <ArrowRight className="h-3 w-3 text-brand-teal" />
          Creating this file will
        </p>
        <ul className="space-y-1.5">
          {NEXT_STEPS.map(({ Icon, t }) => (
            <li
              key={t}
              className="flex items-center gap-2.5 text-[12px] text-muted-foreground"
            >
              <Icon className="h-3.5 w-3.5 shrink-0 text-brand-teal" />
              {t}
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}

function SummaryTile({
  tone,
  Icon,
  value,
  label,
}: {
  tone: "pass" | "warn" | "fail";
  Icon: React.ComponentType<{ className?: string }>;
  value: string;
  label: string;
}) {
  const toneCls = {
    pass: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warn: "border-brand-orange/40 bg-brand-orange/10 text-[#7A5000]",
    fail: "border-rose-200 bg-rose-50 text-rose-700",
  }[tone];
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md border px-3.5 py-2.5",
        toneCls,
      )}
    >
      <Icon className="h-4 w-4" />
      <div>
        <p className="text-[14px] font-extrabold">{value}</p>
        <p className="text-[11px] text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3 rounded-xl border bg-card px-5 py-4">
      <p className="mb-3 text-[12px] font-extrabold tracking-tight text-foreground">
        {title}
      </p>
      {children}
    </div>
  );
}

interface ExFieldProps {
  label: string;
  value?: string;
  defaultValue?: string;
  onChange?: (v: string) => void;
  kind: FieldKind;
  source?: string;
  highlight?: boolean;
}

function KindDot({ kind }: { kind: FieldKind }) {
  const cls = {
    auto: "bg-emerald-500",
    low: "bg-brand-orange",
    gen: "bg-brand-teal",
    missing: "bg-rose-500",
  }[kind];
  return (
    <span
      className={cn("h-2 w-2 shrink-0 rounded-full", cls)}
      aria-hidden
    />
  );
}

function ExField({
  label,
  value,
  defaultValue,
  onChange,
  kind,
  source,
  highlight,
}: ExFieldProps) {
  const controlled = value !== undefined;
  return (
    <div className="flex items-center gap-3 border-b border-border/60 py-2 last:border-0">
      <div className="w-[155px] shrink-0 text-[11px] font-semibold text-muted-foreground">
        {label}
      </div>
      <div className="flex flex-1 items-center gap-2">
        <KindDot kind={kind} />
        <input
          value={controlled ? value : undefined}
          defaultValue={!controlled ? defaultValue : undefined}
          onChange={(e) => onChange?.(e.target.value)}
          className={cn(
            "h-8 flex-1 rounded-md border bg-card px-2.5 text-[12px] focus:outline-none focus:ring-2",
            kind === "low"
              ? "border-brand-orange/60 bg-brand-orange/10 focus:ring-brand-orange/30"
              : "border-border focus:border-brand-teal focus:ring-brand-teal/20",
            highlight && "font-semibold",
          )}
        />
        {source && (
          <span className="hidden text-[10px] text-muted-foreground md:inline">
            {source}
          </span>
        )}
        <Edit3 className="h-3 w-3 cursor-pointer text-muted-foreground hover:text-foreground" />
      </div>
    </div>
  );
}

interface ExSelectProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: readonly string[];
  kind: FieldKind;
  source?: string;
  placeholder?: string;
  highlight?: boolean;
  required?: boolean;
}

function ExSelect({
  label,
  value,
  onChange,
  options,
  kind,
  source,
  placeholder,
  required,
}: ExSelectProps) {
  return (
    <div className="flex items-center gap-3 border-b border-border/60 py-2 last:border-0">
      <div className="w-[155px] shrink-0 text-[11px] font-semibold text-muted-foreground">
        {label} {required && <span className="text-rose-500">*</span>}
      </div>
      <div className="flex flex-1 items-center gap-2">
        <KindDot kind={kind} />
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={cn(
            "h-8 flex-1 rounded-md border bg-card px-2 text-[12px] focus:outline-none focus:ring-2",
            kind === "missing"
              ? "border-rose-300 bg-rose-50 focus:ring-rose-300/40"
              : "border-border focus:border-brand-teal focus:ring-brand-teal/20",
          )}
        >
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
        {required && !value && (
          <span className="text-[10px] font-bold text-rose-500">Required</span>
        )}
        {source && !required && (
          <span className="hidden text-[10px] text-muted-foreground md:inline">
            {source}
          </span>
        )}
      </div>
    </div>
  );
}
