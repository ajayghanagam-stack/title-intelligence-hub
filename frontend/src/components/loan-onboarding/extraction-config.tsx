"use client";

import { useState } from "react";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Plus,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  OTHERS_DOC_TYPE_KEY,
  getFieldHintsForDocType,
} from "@/lib/loan-onboarding/constants";
import type { LoanDocTypeSpec } from "@/lib/loan-onboarding/types";

const DOC_PAGE_SIZE = 5;

interface Props {
  /** Full doc-type spec list selected for this package. */
  docTypes: LoanDocTypeSpec[];
  /** Master toggle — when false, the editor is hidden. */
  enabled: boolean;
  onEnabledChange: (next: boolean) => void;
  /** Fields-to-extract map, keyed by doc-type key. */
  fieldsByDoc: Record<string, string[]>;
  onFieldsByDocChange: (next: Record<string, string[]>) => void;
}

/**
 * Section "D · Field Extraction" from the new-package form.
 *
 * Master toggle gates a two-pane editor: paginated doc-type list on the
 * left, chip editor on the right. Independent of the Missing-Fields
 * validation rule — extracted fields drive a downstream LOS feed
 * (JSON / CSV / MISMO XML), not the per-stack validation result.
 *
 * The shape and copy mirror the prototype at localhost:5173 (UploadConfig
 * screen, "D · Field Extraction" panel) so users moving between the two
 * see the same affordances.
 */
export function ExtractionConfig({
  docTypes,
  enabled,
  onEnabledChange,
  fieldsByDoc,
  onFieldsByDocChange,
}: Props) {
  const [activeDocKey, setActiveDocKey] = useState<string | null>(null);
  const [docPage, setDocPage] = useState(0);
  const [fieldDraft, setFieldDraft] = useState("");

  // Hide the reserved catch-all bucket from the editor — we don't extract
  // fields from "Others" pages. Surface orphan keys (entries in the map
  // for doc types the user has since removed) so they can be cleared.
  const fromSpecs = docTypes.filter((d) => d.key !== OTHERS_DOC_TYPE_KEY);
  const labelByKey = new Map(fromSpecs.map((d) => [d.key, d.label]));
  const orphanKeys = Object.keys(fieldsByDoc).filter(
    (k) => !labelByKey.has(k) && k !== OTHERS_DOC_TYPE_KEY
  );
  type Opt = { key: string; label: string; orphan: boolean };
  const docOptions: Opt[] = [
    ...fromSpecs.map((d) => ({ key: d.key, label: d.label, orphan: false })),
    ...orphanKeys.map((k) => ({ key: k, label: k, orphan: true })),
  ];

  const totalFields = Object.values(fieldsByDoc).reduce(
    (sum, arr) => sum + (arr ? arr.length : 0),
    0
  );
  const docsConfigured = Object.entries(fieldsByDoc).filter(
    ([, arr]) => arr && arr.length > 0
  ).length;

  const totalPages = Math.max(1, Math.ceil(docOptions.length / DOC_PAGE_SIZE));
  const safePage = Math.min(Math.max(0, docPage), totalPages - 1);
  const pageStart = safePage * DOC_PAGE_SIZE;
  const pageDocs = docOptions.slice(pageStart, pageStart + DOC_PAGE_SIZE);

  const currentKey =
    activeDocKey && docOptions.some((o) => o.key === activeDocKey)
      ? activeDocKey
      : (docOptions[0]?.key ?? "");
  const currentLabel =
    docOptions.find((o) => o.key === currentKey)?.label ?? currentKey;
  const fields = (currentKey && fieldsByDoc[currentKey]) || [];

  const setFieldsForDoc = (docKey: string, next: string[]) => {
    const cleaned: Record<string, string[]> = {};
    for (const [k, v] of Object.entries(fieldsByDoc)) {
      if (k === docKey) continue;
      if (v && v.length > 0) cleaned[k] = v;
    }
    if (next.length > 0) cleaned[docKey] = next;
    onFieldsByDocChange(cleaned);
  };

  const addField = (docKey: string, raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed || !docKey) return;
    const existing = fieldsByDoc[docKey] ?? [];
    if (existing.includes(trimmed)) return;
    setFieldsForDoc(docKey, [...existing, trimmed]);
    setFieldDraft("");
  };

  const removeField = (docKey: string, name: string) => {
    const existing = fieldsByDoc[docKey] ?? [];
    setFieldsForDoc(
      docKey,
      existing.filter((f) => f !== name)
    );
  };

  return (
    <div data-testid="extraction-config">
      <div className="rounded-lg border border-border/60 bg-background overflow-hidden">
        {/* Master toggle row */}
        <div className="flex items-center p-4 border-b border-border/60">
          <Toggle
            value={enabled}
            onChange={() => onEnabledChange(!enabled)}
            ariaLabel="Toggle field extraction"
          />
          <div className="ml-4 flex-1">
            <div className="text-sm font-medium text-foreground">
              Extract structured fields per document
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Independent of validation. The system pulls the listed fields
              out of each document, scores extraction confidence, and emits a
              downloadable feed for downstream LOS systems (JSON, CSV, MISMO
              XML).
            </div>
          </div>
          <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase px-2 py-0.5 bg-muted/60 rounded shrink-0">
            downstream
          </div>
        </div>

        {enabled && (
          <div className="p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase">
                Fields to extract by document type
              </div>
              <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase">
                {totalFields} field{totalFields === 1 ? "" : "s"} ·{" "}
                {docsConfigured}/{docOptions.length} doc type
                {docOptions.length === 1 ? "" : "s"}
              </div>
            </div>

            {docOptions.length === 0 ? (
              <div className="rounded-md border border-dashed border-border/60 bg-muted/30 p-4 text-[11px] text-muted-foreground italic">
                Select document types above to configure fields to extract.
              </div>
            ) : (
              <div className="grid grid-cols-[220px_1fr] gap-0 bg-background border border-border/60 rounded-md overflow-hidden">
                {/* Left: paginated doc list */}
                <div className="border-r border-border/60 flex flex-col">
                  <div className="px-3 py-2 bg-muted/40 border-b border-border/60 flex items-center justify-between">
                    <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase">
                      Doc types
                    </div>
                    <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground tabular-nums">
                      {pageStart + 1}–
                      {Math.min(pageStart + DOC_PAGE_SIZE, docOptions.length)}{" "}
                      of {docOptions.length}
                    </div>
                  </div>
                  <div className="flex-1">
                    {pageDocs.map((opt) => {
                      const count = (fieldsByDoc[opt.key] || []).length;
                      const isActive = opt.key === currentKey;
                      const isEmpty = count === 0;
                      return (
                        <button
                          key={opt.key}
                          type="button"
                          onClick={() => setActiveDocKey(opt.key)}
                          className={cn(
                            "w-full flex items-center justify-between px-3 py-2 text-left border-b border-border/60 transition-colors border-l-2",
                            isActive
                              ? "bg-[oklch(0.750_0.170_65)]/10 border-l-[oklch(0.750_0.170_65)]"
                              : "hover:bg-muted/40 border-l-transparent"
                          )}
                          data-testid={`extraction-doc-${opt.key}`}
                          aria-pressed={isActive}
                        >
                          <span
                            className={cn(
                              "text-xs truncate",
                              isActive
                                ? "text-foreground font-medium"
                                : isEmpty
                                  ? "text-muted-foreground"
                                  : "text-foreground",
                              opt.orphan && "italic"
                            )}
                          >
                            {opt.label}
                            {opt.orphan ? " (removed)" : ""}
                          </span>
                          <span
                            className={cn(
                              "font-mono text-[10px] tabular-nums shrink-0 ml-2",
                              isEmpty
                                ? "text-muted-foreground/60"
                                : "text-muted-foreground"
                            )}
                          >
                            {isEmpty ? "—" : count}
                          </span>
                        </button>
                      );
                    })}
                    {Array.from({
                      length: Math.max(0, DOC_PAGE_SIZE - pageDocs.length),
                    }).map((_, idx) => (
                      <div
                        key={`filler-${idx}`}
                        className="px-3 py-2 border-b border-border/60 border-l-2 border-l-transparent"
                      >
                        <span className="text-xs text-transparent select-none">
                          ·
                        </span>
                      </div>
                    ))}
                  </div>
                  {totalPages > 1 && (
                    <div className="px-2 py-1.5 border-t border-border/60 bg-muted/40 flex items-center justify-between gap-2">
                      <button
                        type="button"
                        onClick={() => setDocPage(Math.max(0, safePage - 1))}
                        disabled={safePage === 0}
                        className="px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                        aria-label="Previous page"
                        data-testid="extraction-page-prev"
                      >
                        <ChevronLeft className="h-3 w-3" /> Prev
                      </button>
                      <span className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase tabular-nums">
                        {safePage + 1} / {totalPages}
                      </span>
                      <button
                        type="button"
                        onClick={() =>
                          setDocPage(Math.min(totalPages - 1, safePage + 1))
                        }
                        disabled={safePage >= totalPages - 1}
                        className="px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                        aria-label="Next page"
                        data-testid="extraction-page-next"
                      >
                        Next <ChevronRight className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                </div>

                {/* Right: chip editor for active doc */}
                <div className="p-3">
                  <div className="flex items-baseline justify-between mb-2">
                    <div className="text-sm text-foreground">
                      {currentLabel}
                    </div>
                    <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase">
                      {fields.length} field{fields.length === 1 ? "" : "s"}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5 mb-3 min-h-[28px]">
                    {fields.map((f) => (
                      <span
                        key={f}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-muted/60 border border-border/60 rounded-full text-xs"
                        data-testid={`extraction-field-${currentKey}-${f}`}
                      >
                        {f}
                        <button
                          type="button"
                          onClick={() => removeField(currentKey, f)}
                          className="text-muted-foreground/70 hover:text-red-600 transition-colors"
                          aria-label={`Remove ${f}`}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                    {fields.length === 0 && (
                      <span className="text-[11px] text-muted-foreground italic self-center">
                        No fields configured for {currentLabel} yet.
                      </span>
                    )}
                  </div>
                  {currentKey &&
                    (() => {
                      const allHints = getFieldHintsForDocType(currentKey);
                      const remaining = allHints.filter(
                        (h) => !fields.includes(h)
                      );
                      if (remaining.length === 0) return null;
                      return (
                        <div
                          className="mb-3"
                          data-testid={`extraction-field-hints-${currentKey}`}
                        >
                          <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase mb-1.5">
                            Suggestions for {currentLabel}
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {remaining.map((hint) => (
                              <button
                                key={hint}
                                type="button"
                                onClick={() => addField(currentKey, hint)}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono border border-dashed border-border/70 bg-background text-muted-foreground hover:text-foreground hover:border-[oklch(0.750_0.170_65)] hover:bg-[oklch(0.750_0.170_65)]/10 transition-colors"
                                data-testid={`extraction-field-hint-${currentKey}-${hint}`}
                                aria-label={`Add suggested field ${hint}`}
                              >
                                <Plus className="h-2.5 w-2.5" />
                                {hint}
                              </button>
                            ))}
                          </div>
                        </div>
                      );
                    })()}
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={fieldDraft}
                      onChange={(e) => setFieldDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          if (currentKey) addField(currentKey, fieldDraft);
                        }
                      }}
                      placeholder={`Add a field to extract from ${currentLabel} · press Enter`}
                      className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                      data-testid="extraction-field-input"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        if (!currentKey) return;
                        addField(currentKey, fieldDraft);
                      }}
                      disabled={!fieldDraft.trim() || !currentKey}
                      className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium bg-[oklch(0.750_0.170_65)] text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
                      data-testid="extraction-field-add"
                    >
                      <Plus className="h-3 w-3" />
                      Add
                    </button>
                  </div>
                </div>
              </div>
            )}

            <div className="mt-3 flex items-center gap-1.5 text-[10px] text-muted-foreground">
              <AlertCircle className="h-3 w-3" />
              During processing the system attempts to extract each configured
              field; missing fields are reported separately from validation
              outcomes.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

interface ToggleProps {
  value: boolean;
  onChange: () => void;
  ariaLabel?: string;
}

function Toggle({ value, onChange, ariaLabel }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={ariaLabel}
      onClick={onChange}
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full border transition-colors",
        value
          ? "bg-[oklch(0.750_0.170_65)] border-[oklch(0.750_0.170_65)]"
          : "bg-background border-input"
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all",
          value ? "left-[18px] bg-white" : "left-0.5 bg-muted-foreground/70"
        )}
      />
    </button>
  );
}
