"use client";

import { useMemo, useState } from "react";
import {
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Plus,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import {
  SUGGESTED_DOC_TYPES,
  TOTAL_DOC_TYPE_COUNT,
  getFieldHintsForDocType,
} from "@/lib/loan-onboarding/constants";
import {
  EMPTY_DOC_VALIDATIONS,
  type DocValidations,
  type LoanDocTypeSpec,
} from "@/lib/loan-onboarding/types";

interface Props {
  value: LoanDocTypeSpec[];
  onChange: (next: LoanDocTypeSpec[]) => void;
  /**
   * Per-doc-type validation toggles. The picker renders an inline panel under
   * each selected row so the LO can choose which structural checks run for
   * that doc type, plus the required-fields chip editor when "Missing Fields"
   * is enabled.
   */
  validations: Record<string, DocValidations>;
  onValidationsChange: (next: Record<string, DocValidations>) => void;
}

const VALIDATION_PRESETS: Array<{
  id: keyof Pick<
    DocValidations,
    "missing_pages" | "missing_signatures" | "date_consistency" | "missing_fields"
  >;
  label: string;
  description: string;
}> = [
  {
    id: "missing_pages",
    label: "Missing Pages",
    description: "Detect gaps in page numbering",
  },
  {
    id: "missing_signatures",
    label: "Missing Signatures",
    description: "All signature fields must be signed",
  },
  {
    id: "date_consistency",
    label: "Date Consistency",
    description: "Dates across documents must be within expected windows",
  },
  {
    id: "missing_fields",
    label: "Missing Fields",
    description: "Required form fields must be populated",
  },
];

const PAGE_SIZE = 5;

const isLocked = (spec: { key: string; locked?: boolean }): boolean => {
  if (spec.locked) return true;
  const suggested = SUGGESTED_DOC_TYPES.find((d) => d.key === spec.key);
  return !!suggested?.locked;
};

function slugifyKey(input: string): string {
  return input
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function matchesQuery(spec: LoanDocTypeSpec, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    spec.label.toLowerCase().includes(q) ||
    spec.key.toLowerCase().includes(q) ||
    (spec.description?.toLowerCase().includes(q) ?? false)
  );
}

export function DocTypeSelector({
  value,
  onChange,
  validations,
  onValidationsChange,
}: Props) {
  const [customLabel, setCustomLabel] = useState("");
  const [customDesc, setCustomDesc] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  // Custom-added doc types live alongside catalog items in the paginated list.
  // They are real doc type specs — added to `value` on creation and sent to
  // the backend classifier like any catalog entry.
  const [customSpecs, setCustomSpecs] = useState<LoanDocTypeSpec[]>([]);

  const selectedKeys = useMemo(
    () => new Set(value.map((d) => d.key)),
    [value]
  );
  const customKeys = useMemo(
    () => new Set(customSpecs.map((s) => s.key)),
    [customSpecs]
  );

  const selectedCount = value.filter((d) => !isLocked(d)).length;

  // Combined list: catalog first, then customs. Filtered by search.
  const allSpecs = useMemo(
    () => [...SUGGESTED_DOC_TYPES, ...customSpecs],
    [customSpecs]
  );
  const filtered = useMemo(
    () => allSpecs.filter((s) => matchesQuery(s, query)),
    [allSpecs, query]
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  // Clamp current page to valid range whenever filter shrinks the list.
  const clampedPage = Math.min(page, totalPages);
  const startIdx = (clampedPage - 1) * PAGE_SIZE;
  const pageItems = filtered.slice(startIdx, startIdx + PAGE_SIZE);

  const ensureValidationsFor = (key: string) => {
    if (validations[key]) return;
    onValidationsChange({ ...validations, [key]: { ...EMPTY_DOC_VALIDATIONS } });
  };

  const dropValidationsFor = (key: string) => {
    if (!validations[key]) return;
    const next = { ...validations };
    delete next[key];
    onValidationsChange(next);
  };

  const updateValidations = (key: string, patch: Partial<DocValidations>) => {
    const current = validations[key] ?? { ...EMPTY_DOC_VALIDATIONS };
    onValidationsChange({ ...validations, [key]: { ...current, ...patch } });
  };

  const toggle = (spec: LoanDocTypeSpec) => {
    if (isLocked(spec)) return;
    if (selectedKeys.has(spec.key)) {
      onChange(value.filter((d) => d.key !== spec.key));
      dropValidationsFor(spec.key);
    } else {
      onChange([...value, spec]);
      ensureValidationsFor(spec.key);
    }
  };

  const selectAll = () => {
    const next = [...value];
    const nextValidations = { ...validations };
    for (const spec of allSpecs) {
      if (!next.some((d) => d.key === spec.key)) next.push(spec);
      if (!nextValidations[spec.key]) {
        nextValidations[spec.key] = { ...EMPTY_DOC_VALIDATIONS };
      }
    }
    onChange(next);
    onValidationsChange(nextValidations);
  };

  const clearAll = () => {
    const lockedKeys = new Set(value.filter(isLocked).map((d) => d.key));
    const nextValidations: Record<string, DocValidations> = {};
    for (const k of Object.keys(validations)) {
      if (lockedKeys.has(k)) nextValidations[k] = validations[k];
    }
    onChange(value.filter((d) => isLocked(d)));
    onValidationsChange(nextValidations);
  };

  const addCustom = () => {
    const label = customLabel.trim();
    if (!label) return;
    const key = slugifyKey(label);
    if (!key) {
      setCustomLabel("");
      setCustomDesc("");
      return;
    }
    const catalogKeys = new Set(SUGGESTED_DOC_TYPES.map((s) => s.key));
    if (catalogKeys.has(key) || customKeys.has(key)) {
      setCustomLabel("");
      setCustomDesc("");
      return;
    }
    const description = customDesc.trim() || undefined;
    const spec: LoanDocTypeSpec = { key, label, description, required: false };
    setCustomSpecs((prev) => [...prev, spec]);
    onChange([...value, spec]);
    onValidationsChange({
      ...validations,
      [spec.key]: { ...EMPTY_DOC_VALIDATIONS },
    });
    setCustomLabel("");
    setCustomDesc("");
    // Jump to the last page so the newly added row is visible.
    const newTotal = filtered.length + 1;
    setPage(Math.max(1, Math.ceil(newTotal / PAGE_SIZE)));
  };

  const removeCustomSpec = (key: string) => {
    setCustomSpecs((prev) => prev.filter((s) => s.key !== key));
    onChange(value.filter((d) => d.key !== key));
    dropValidationsFor(key);
  };

  return (
    <div className="space-y-5">
      {/* Search + selected counter + bulk actions */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search documents (e.g. appraisal, VOE, 1099)…"
            className="h-10 pl-9"
            data-testid="doc-type-search"
          />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium",
              selectedCount > 0
                ? "bg-[oklch(0.750_0.170_65)]/10 text-[oklch(0.750_0.170_65)] ring-1 ring-[oklch(0.750_0.170_65)]/30"
                : "bg-muted text-muted-foreground ring-1 ring-border"
            )}
            data-testid="doc-type-selected-count"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            {selectedCount} / {TOTAL_DOC_TYPE_COUNT + customSpecs.length} selected
          </span>
          <button
            type="button"
            onClick={selectAll}
            className="text-xs font-medium text-[oklch(0.750_0.170_65)] hover:underline"
            data-testid="doc-type-select-all"
          >
            Select all
          </button>
          {selectedCount > 0 && (
            <button
              type="button"
              onClick={clearAll}
              className="text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              data-testid="doc-type-clear-all"
            >
              Clear all
            </button>
          )}
        </div>
      </div>

      {/* Paginated flat list */}
      <div className="rounded-xl border border-border/60 bg-card/30 overflow-hidden">
        {pageItems.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            {query ? (
              <>
                No documents match{" "}
                <span className="font-medium">&ldquo;{query}&rdquo;</span>.
              </>
            ) : (
              <>No documents.</>
            )}
          </div>
        ) : (
          <div>
            {pageItems.map((spec, i) => {
              const active = selectedKeys.has(spec.key);
              const custom = customKeys.has(spec.key);
              return (
                <div
                  key={spec.key}
                  className={cn(
                    "transition-colors",
                    i > 0 && "border-t border-border/60",
                    active ? "bg-[oklch(0.750_0.170_65)]/5" : ""
                  )}
                >
                <div
                  role="button"
                  tabIndex={0}
                  aria-pressed={active}
                  onClick={() => toggle(spec)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggle(spec);
                    }
                  }}
                  className={cn(
                    "flex items-center gap-4 px-5 py-3.5 cursor-pointer transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.750_0.170_65)]/40",
                    !active && "hover:bg-muted/40"
                  )}
                  data-testid={`doc-type-row-${spec.key}`}
                >
                  {/* Checkbox */}
                  <div
                    className={cn(
                      "flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-all",
                      active
                        ? "bg-[oklch(0.750_0.170_65)] border-[oklch(0.750_0.170_65)]"
                        : "bg-background border-input"
                    )}
                  >
                    {active && (
                      <Check
                        className="h-3 w-3 text-white"
                        strokeWidth={3}
                      />
                    )}
                  </div>

                  {/* Label + description */}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {custom && (
                        <Sparkles className="h-3.5 w-3.5 shrink-0 text-violet-500" />
                      )}
                      <span className="text-sm font-medium text-foreground truncate">
                        {spec.label}
                      </span>
                      {custom && (
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-violet-600 bg-violet-50 ring-1 ring-violet-200 rounded px-1.5 py-0.5">
                          Custom
                        </span>
                      )}
                    </div>
                    {spec.description && (
                      <div className="text-xs text-muted-foreground mt-0.5 truncate">
                        {spec.description}
                      </div>
                    )}
                  </div>

                  {/* Remove custom */}
                  {custom && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeCustomSpec(spec.key);
                      }}
                      aria-label={`Remove custom document ${spec.label}`}
                      className="shrink-0 rounded-md p-1.5 text-muted-foreground/60 hover:text-red-600 hover:bg-red-50 transition-colors"
                      data-testid={`doc-type-custom-remove-${spec.key}`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                {active && !isLocked(spec) && (
                  <DocValidationsPanel
                    docKey={spec.key}
                    docLabel={spec.label}
                    validations={validations[spec.key] ?? EMPTY_DOC_VALIDATIONS}
                    onChange={(patch) => updateValidations(spec.key, patch)}
                  />
                )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Pagination */}
      {filtered.length > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs">
          <div className="text-muted-foreground">
            Showing{" "}
            <span className="font-medium tabular-nums">
              {startIdx + 1}–{Math.min(startIdx + PAGE_SIZE, filtered.length)}
            </span>{" "}
            of{" "}
            <span className="font-medium tabular-nums">{filtered.length}</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={clampedPage <= 1}
              className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="doc-type-page-prev"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Prev
            </button>
            {/* Window of 5 page numbers — Prev/Next sit immediately on either
                side of the visible window so we don't render all 13 pages
                inline. Window slides by 5: 1–5, 6–10, 11–13, etc. */}
            {(() => {
              const WINDOW = 5;
              const windowStart =
                Math.floor((clampedPage - 1) / WINDOW) * WINDOW + 1;
              const windowEnd = Math.min(windowStart + WINDOW - 1, totalPages);
              const pages: number[] = [];
              for (let p = windowStart; p <= windowEnd; p++) pages.push(p);
              return pages.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPage(p)}
                  className={cn(
                    "rounded-md px-2.5 py-1.5 text-xs font-medium tabular-nums transition-colors",
                    p === clampedPage
                      ? "bg-[oklch(0.750_0.170_65)] text-white"
                      : "hover:bg-muted text-foreground/70"
                  )}
                  data-testid={`doc-type-page-${p}`}
                >
                  {p}
                </button>
              ));
            })()}
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={clampedPage >= totalPages}
              className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="doc-type-page-next"
            >
              Next
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Add custom document */}
      <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-3">
        <div className="flex items-start gap-2">
          <Sparkles className="h-4 w-4 mt-0.5 shrink-0 text-[oklch(0.750_0.170_65)]" />
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              Add a new document type
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Appears in the list as a selectable row and is sent to the
              classifier for this package.
            </p>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2">
          <Input
            value={customLabel}
            onChange={(e) => setCustomLabel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustom();
              }
            }}
            placeholder="Name (e.g. IRS Transcript)"
            className="h-10"
            data-testid="doc-type-custom-input"
          />
          <Input
            value={customDesc}
            onChange={(e) => setCustomDesc(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustom();
              }
            }}
            placeholder="Description (optional)"
            className="h-10"
            data-testid="doc-type-custom-desc"
          />
          <button
            type="button"
            onClick={addCustom}
            disabled={!customLabel.trim()}
            className="inline-flex items-center justify-center gap-1.5 rounded-md px-4 text-sm font-medium bg-[oklch(0.750_0.170_65)] text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed h-10"
            data-testid="doc-type-custom-add"
          >
            <Plus className="h-4 w-4" />
            Add
          </button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          New document types appear in the list above with the same
          per-document validation toggles (Missing Pages, Missing Signatures,
          Date Consistency, Missing Fields).
        </p>
      </div>
    </div>
  );
}

interface DocValidationsPanelProps {
  docKey: string;
  docLabel: string;
  validations: DocValidations;
  onChange: (patch: Partial<DocValidations>) => void;
}

function DocValidationsPanel({
  docKey,
  docLabel,
  validations,
  onChange,
}: DocValidationsPanelProps) {
  const [fieldDraft, setFieldDraft] = useState("");
  const fields = validations.required_fields;

  const addRequiredField = (name: string) => {
    const trimmed = name.trim();
    if (!trimmed || fields.includes(trimmed)) return;
    onChange({ required_fields: [...fields, trimmed] });
  };

  const removeRequiredField = (name: string) => {
    onChange({ required_fields: fields.filter((f) => f !== name) });
  };

  const hints = useMemo(() => {
    const all = getFieldHintsForDocType(docKey);
    return all.filter((h) => !fields.includes(h));
  }, [docKey, fields]);

  return (
    <div
      className="px-5 pb-4 pt-1 pl-12 space-y-3 border-t border-border/30"
      data-testid={`doc-type-validations-${docKey}`}
    >
      <div className="font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground">
        Validations for {docLabel}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {VALIDATION_PRESETS.map((preset) => {
          const enabled = validations[preset.id];
          const inputId = `doc-type-validation-${docKey}-${preset.id}-input`;
          return (
            <label
              key={preset.id}
              htmlFor={inputId}
              aria-label={preset.label}
              className={cn(
                "flex items-start gap-2.5 rounded-md border px-3 py-2 cursor-pointer transition-colors",
                enabled
                  ? "border-[oklch(0.750_0.170_65)]/40 bg-[oklch(0.750_0.170_65)]/5"
                  : "border-border/60 bg-background hover:bg-muted/40"
              )}
              data-testid={`doc-type-validation-${docKey}-${preset.id}`}
            >
              <input
                id={inputId}
                type="checkbox"
                checked={enabled}
                onChange={(e) => onChange({ [preset.id]: e.target.checked })}
                className="mt-0.5 h-4 w-4 rounded border-input"
              />
              <div className="min-w-0">
                <div className="text-xs font-medium text-foreground">
                  {preset.label}
                </div>
                <div className="text-[11px] text-muted-foreground mt-0.5">
                  {preset.description}
                </div>
              </div>
            </label>
          );
        })}
      </div>

      {validations.missing_fields && (
        <div
          className="rounded-md border border-border/60 bg-background p-3 space-y-2"
          data-testid={`doc-type-required-fields-${docKey}`}
        >
          <div className="flex items-baseline justify-between">
            <div className="font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground">
              Required fields
            </div>
            <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase">
              {fields.length} field{fields.length === 1 ? "" : "s"}
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5 min-h-[24px]">
            {fields.map((f) => (
              <span
                key={f}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-muted/60 border border-border/60 rounded-full text-xs font-mono"
                data-testid={`required-field-${docKey}-${f}`}
              >
                {f}
                <button
                  type="button"
                  onClick={() => removeRequiredField(f)}
                  className="text-muted-foreground/70 hover:text-red-600 transition-colors"
                  aria-label={`Remove ${f}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            {fields.length === 0 && (
              <span className="text-[11px] text-muted-foreground italic self-center">
                No required fields configured for {docLabel} yet.
              </span>
            )}
          </div>

          {hints.length > 0 && (
            <div data-testid={`field-hints-${docKey}`}>
              <div className="font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground mb-1.5">
                Suggestions for {docLabel}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {hints.map((hint) => (
                  <button
                    key={hint}
                    type="button"
                    onClick={() => addRequiredField(hint)}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono border border-dashed border-border/70 bg-background text-muted-foreground hover:text-foreground hover:border-[oklch(0.750_0.170_65)] hover:bg-[oklch(0.750_0.170_65)]/10 transition-colors"
                    data-testid={`field-hint-${docKey}-${hint}`}
                    aria-label={`Add suggested field ${hint}`}
                  >
                    <Plus className="h-2.5 w-2.5" />
                    {hint}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex gap-2">
            <input
              type="text"
              value={fieldDraft}
              onChange={(e) => setFieldDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addRequiredField(fieldDraft);
                  setFieldDraft("");
                }
              }}
              placeholder={`Add a required field for ${docLabel} · press Enter`}
              className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs font-mono focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              data-testid={`required-field-input-${docKey}`}
            />
            <button
              type="button"
              onClick={() => {
                addRequiredField(fieldDraft);
                setFieldDraft("");
              }}
              disabled={!fieldDraft.trim()}
              className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium border border-border/60 bg-background hover:bg-muted/60 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid={`required-field-add-${docKey}`}
            >
              <Plus className="h-3 w-3" />
              Add
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
