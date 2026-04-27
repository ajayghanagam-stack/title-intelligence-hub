"use client";

import { useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  PenLine,
  Plus,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  OTHERS_DOC_TYPE_KEY,
  getFieldHintsForDocType,
} from "@/lib/loan-onboarding/constants";
import type {
  LoanDocTypeSpec,
  LoanPackageRule,
} from "@/lib/loan-onboarding/types";

interface Props {
  value: LoanPackageRule[];
  onChange: (next: LoanPackageRule[]) => void;
  /**
   * Expected doc types selected on this package. The Missing Fields editor
   * scopes its required-field list per doc type, so it needs the full picker
   * state to render the per-doc-type two-pane editor. Optional for backward
   * compatibility — when omitted, the editor falls back to the legacy flat
   * `required_fields` chip list.
   */
  docTypes?: LoanDocTypeSpec[];
}

const FIELD_DOC_PAGE_SIZE = 5;

/**
 * Prototype-matched preset catalog. The four structural checks mirror the
 * Loan Onboarding prototype (Missing Pages, Missing Signatures, Missing
 * Fields, Date Consistency). `rule_id` values align with backend preset IDs
 * in `services/validation_presets.py` for the three that the backend
 * currently implements. `date_consistency` has no backend evaluator yet and
 * is filtered from the submit payload in the new-package form.
 */
export const PROTOTYPE_PRESETS = [
  {
    rule_id: "missing_pages",
    label: "Missing Pages",
    description: "Detect gaps in page numbering",
    type: "structural",
  },
  {
    rule_id: "missing_signatures",
    label: "Missing Signatures",
    description: "All signature fields must be signed",
    type: "structural",
  },
  {
    rule_id: "date_consistency",
    label: "Date Consistency",
    description: "Dates across documents must be within expected windows",
    type: "structural",
  },
  {
    rule_id: "missing_fields",
    label: "Missing Fields",
    description: "Required form fields must be populated",
    type: "structural",
  },
] as const;

/**
 * rule_ids in PROTOTYPE_PRESETS that the backend does NOT implement yet.
 * These are displayed in the UI (to match the prototype) but stripped from
 * the payload on submit so the classifier doesn't receive unknown rules.
 */
export const UNSUPPORTED_PRESET_IDS = new Set<string>(["date_consistency"]);

function slugify(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 48);
}

export function RuleBuilder({ value, onChange, docTypes }: Props) {
  const [customDraft, setCustomDraft] = useState("");
  const [fieldDraft, setFieldDraft] = useState("");
  const [activeDocKey, setActiveDocKey] = useState<string | null>(null);
  const [fieldDocPage, setFieldDocPage] = useState(0);

  const presetEnabled = (ruleId: string) =>
    value.some((r) => r.rule_source === "preset" && r.rule_id === ruleId);

  const getPresetConfig = (ruleId: string): Record<string, unknown> => {
    const rule = value.find(
      (r) => r.rule_source === "preset" && r.rule_id === ruleId
    );
    return rule?.config ?? {};
  };

  const updatePresetConfig = (
    ruleId: string,
    patch: Record<string, unknown>
  ) => {
    onChange(
      value.map((r) =>
        r.rule_source === "preset" && r.rule_id === ruleId
          ? { ...r, config: { ...r.config, ...patch } }
          : r
      )
    );
  };

  const getRequiredFieldsByDoc = (
    ruleId: string
  ): Record<string, string[]> => {
    const cfg = getPresetConfig(ruleId);
    const raw = cfg.required_fields_by_doc;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    const out: Record<string, string[]> = {};
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      if (Array.isArray(v)) out[k] = v.map(String);
    }
    return out;
  };

  const setRequiredFieldsByDoc = (
    ruleId: string,
    next: Record<string, string[]>
  ) => {
    // Drop empty entries to keep the payload tidy.
    const cleaned: Record<string, string[]> = {};
    for (const [k, v] of Object.entries(next)) {
      if (v && v.length > 0) cleaned[k] = v;
    }
    updatePresetConfig(ruleId, { required_fields_by_doc: cleaned });
  };

  const addRequiredField = (ruleId: string, docKey: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed || !docKey) return;
    const map = getRequiredFieldsByDoc(ruleId);
    const existing = map[docKey] ?? [];
    if (existing.includes(trimmed)) return;
    setRequiredFieldsByDoc(ruleId, {
      ...map,
      [docKey]: [...existing, trimmed],
    });
  };

  const removeRequiredField = (
    ruleId: string,
    docKey: string,
    name: string
  ) => {
    const map = getRequiredFieldsByDoc(ruleId);
    const existing = map[docKey] ?? [];
    setRequiredFieldsByDoc(ruleId, {
      ...map,
      [docKey]: existing.filter((f) => f !== name),
    });
  };

  const togglePreset = (preset: (typeof PROTOTYPE_PRESETS)[number]) => {
    if (presetEnabled(preset.rule_id)) {
      onChange(
        value.filter(
          (r) => !(r.rule_source === "preset" && r.rule_id === preset.rule_id)
        )
      );
    } else {
      onChange([
        ...value,
        {
          rule_source: "preset",
          rule_id: preset.rule_id,
          description: preset.description,
          config: {},
        },
      ]);
    }
  };

  const customRules = value.filter((r) => r.rule_source === "custom");

  const addCustomRule = () => {
    const text = customDraft.trim();
    if (!text) return;
    const slug = slugify(text) || `custom_${value.length + 1}`;
    let unique = slug;
    let suffix = 2;
    while (
      value.some((r) => r.rule_source === "custom" && r.rule_id === unique)
    ) {
      unique = `${slug}_${suffix++}`;
    }
    onChange([
      ...value,
      {
        rule_source: "custom",
        rule_id: unique,
        description: text,
        config: { text },
      },
    ]);
    setCustomDraft("");
  };

  const removeCustomRule = (ruleId: string) => {
    onChange(
      value.filter(
        (r) => !(r.rule_source === "custom" && r.rule_id === ruleId)
      )
    );
  };

  const activeCount =
    value.filter((r) => r.rule_source === "preset").length +
    customRules.length;

  return (
    <div className="space-y-8">
      {/* Structural Checks */}
      <div>
        <div className="flex items-center gap-3 mb-4">
          <div className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground uppercase">
            Structural Checks
          </div>
          <div className="h-px flex-1 bg-border/60" />
        </div>
        <div className="rounded-lg border border-border/60 bg-background overflow-hidden">
          {PROTOTYPE_PRESETS.map((preset, i) => {
            const enabled = presetEnabled(preset.rule_id);
            const showFieldsEditor =
              preset.rule_id === "missing_fields" && enabled;
            return (
              <div
                key={preset.rule_id}
                className={cn(
                  "p-4",
                  i > 0 && "border-t border-border/60"
                )}
                data-testid={`rule-preset-${preset.rule_id}`}
              >
                <div className="flex items-start gap-4">
                  <div className="pt-0.5">
                    <Toggle
                      value={enabled}
                      onChange={() => togglePreset(preset)}
                      ariaLabel={`Toggle ${preset.label}`}
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground">
                      {preset.label}
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {preset.description}
                    </div>
                  </div>
                  <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase px-2 py-0.5 bg-muted/60 rounded shrink-0">
                    {preset.type}
                  </div>
                </div>
                {showFieldsEditor && (
                  <div className="mt-3 pl-[52px]">
                    <MissingFieldsEditor
                      ruleId={preset.rule_id}
                      docTypes={docTypes ?? []}
                      map={getRequiredFieldsByDoc(preset.rule_id)}
                      activeDocKey={activeDocKey}
                      setActiveDocKey={setActiveDocKey}
                      fieldDocPage={fieldDocPage}
                      setFieldDocPage={setFieldDocPage}
                      fieldDraft={fieldDraft}
                      setFieldDraft={setFieldDraft}
                      onAdd={addRequiredField}
                      onRemove={removeRequiredField}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Custom NL rules */}
      <div>
        <div className="flex items-center gap-3 mb-4">
          <div className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground uppercase">
            Custom Rules · Natural Language
          </div>
          <div className="h-px flex-1 bg-border/60" />
          <Sparkles className="h-3 w-3 text-[oklch(0.750_0.170_65)]" />
        </div>

        {customRules.length > 0 && (
          <div className="rounded-lg border border-border/60 bg-background overflow-hidden mb-3">
            {customRules.map((rule, i) => (
              <div
                key={rule.rule_id}
                className={cn(
                  "flex items-start gap-4 p-4",
                  i > 0 && "border-t border-border/60"
                )}
                data-testid={`custom-rule-${rule.rule_id}`}
              >
                <div className="pt-0.5">
                  <Toggle
                    value
                    onChange={() => removeCustomRule(rule.rule_id)}
                    ariaLabel={`Disable custom rule`}
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-foreground italic">
                    &ldquo;{rule.description}&rdquo;
                  </div>
                  <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase mt-2">
                    Interpreted as: Cross-document field comparison
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => removeCustomRule(rule.rule_id)}
                  className="shrink-0 rounded p-1.5 text-muted-foreground/70 hover:text-red-600 hover:bg-red-50 transition-colors"
                  aria-label="Remove rule"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Add new rule panel (dashed border to match prototype) */}
        <div className="rounded-lg border border-dashed border-border/80 bg-muted/30 p-4">
          <div className="flex items-center gap-2 mb-3">
            <PenLine className="h-3.5 w-3.5 text-[oklch(0.750_0.170_65)]" />
            <div className="font-mono text-[10px] tracking-[0.15em] text-muted-foreground uppercase">
              Describe a new rule in plain English
            </div>
          </div>
          <textarea
            value={customDraft}
            onChange={(e) => setCustomDraft(e.target.value)}
            placeholder="e.g., 'The property address on the appraisal must match the purchase agreement exactly'"
            rows={2}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm italic resize-none focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            data-testid="rule-custom-draft"
          />
          <div className="flex items-center justify-between mt-3">
            <div className="text-[10px] text-muted-foreground">
              System will interpret and convert to executable validation.
            </div>
            <button
              type="button"
              onClick={addCustomRule}
              disabled={!customDraft.trim()}
              className="inline-flex items-center gap-1.5 rounded-md px-4 py-1.5 text-xs font-medium bg-[oklch(0.750_0.170_65)] text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="rule-custom-add"
            >
              <Plus className="h-3.5 w-3.5" />
              Add rule
            </button>
          </div>
        </div>
      </div>

      {/* Footer stat */}
      <div className="font-mono text-[10px] text-muted-foreground">
        {activeCount} rule{activeCount === 1 ? "" : "s"} active
      </div>
    </div>
  );
}

interface MissingFieldsEditorProps {
  ruleId: string;
  docTypes: LoanDocTypeSpec[];
  map: Record<string, string[]>;
  activeDocKey: string | null;
  setActiveDocKey: (key: string) => void;
  fieldDocPage: number;
  setFieldDocPage: (n: number) => void;
  fieldDraft: string;
  setFieldDraft: (s: string) => void;
  onAdd: (ruleId: string, docKey: string, name: string) => void;
  onRemove: (ruleId: string, docKey: string, name: string) => void;
}

function MissingFieldsEditor({
  ruleId,
  docTypes,
  map,
  activeDocKey,
  setActiveDocKey,
  fieldDocPage,
  setFieldDocPage,
  fieldDraft,
  setFieldDraft,
  onAdd,
  onRemove,
}: MissingFieldsEditorProps) {
  // Doc options come from selected doc types (excluding the reserved Others
  // bucket). Plus any keys already in `map` that may not be in the current
  // selection (e.g. user removed a doc type after configuring its fields) —
  // surface them so users can clear them rather than silently leaking.
  const fromSpecs = docTypes.filter((d) => d.key !== OTHERS_DOC_TYPE_KEY);
  const labelByKey = new Map(fromSpecs.map((d) => [d.key, d.label]));
  const orphanKeys = Object.keys(map).filter(
    (k) => !labelByKey.has(k) && k !== OTHERS_DOC_TYPE_KEY
  );
  type Opt = { key: string; label: string; orphan: boolean };
  const docOptions: Opt[] = [
    ...fromSpecs.map((d) => ({ key: d.key, label: d.label, orphan: false })),
    ...orphanKeys.map((k) => ({ key: k, label: k, orphan: true })),
  ];

  const totalFields = Object.values(map).reduce(
    (sum, arr) => sum + (arr ? arr.length : 0),
    0
  );
  const docsConfigured = Object.entries(map).filter(
    ([, arr]) => arr && arr.length > 0
  ).length;

  const totalPages = Math.max(
    1,
    Math.ceil(docOptions.length / FIELD_DOC_PAGE_SIZE)
  );
  const safePage = Math.min(Math.max(0, fieldDocPage), totalPages - 1);
  const pageStart = safePage * FIELD_DOC_PAGE_SIZE;
  const pageDocs = docOptions.slice(pageStart, pageStart + FIELD_DOC_PAGE_SIZE);

  const currentKey =
    activeDocKey && docOptions.some((o) => o.key === activeDocKey)
      ? activeDocKey
      : docOptions[0]?.key ?? "";
  const currentLabel =
    docOptions.find((o) => o.key === currentKey)?.label ?? currentKey;
  const fields = (currentKey && map[currentKey]) || [];

  if (docOptions.length === 0) {
    return (
      <div
        className="rounded-md border border-dashed border-border/60 bg-muted/30 p-4 text-[11px] text-muted-foreground italic"
        data-testid="missing-fields-editor"
      >
        Select document types in the panel above to configure their required
        fields per type.
      </div>
    );
  }

  return (
    <div data-testid="missing-fields-editor">
      <div className="flex items-center justify-between mb-2">
        <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase">
          Required fields by document type
        </div>
        <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase">
          {totalFields} field{totalFields === 1 ? "" : "s"} · {docsConfigured}/
          {docOptions.length} doc type{docOptions.length === 1 ? "" : "s"}{" "}
          configured
        </div>
      </div>
      <div className="grid grid-cols-[220px_1fr] gap-0 bg-background border border-border/60 rounded-md overflow-hidden">
        {/* Left: doc type list (paginated) */}
        <div className="border-r border-border/60 flex flex-col">
          <div className="px-3 py-2 bg-muted/40 border-b border-border/60 flex items-center justify-between">
            <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase">
              Doc types
            </div>
            <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground tabular-nums">
              {pageStart + 1}–
              {Math.min(pageStart + FIELD_DOC_PAGE_SIZE, docOptions.length)} of{" "}
              {docOptions.length}
            </div>
          </div>
          <div className="flex-1">
            {pageDocs.map((opt) => {
              const count = (map[opt.key] || []).length;
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
                  data-testid={`missing-fields-doc-${opt.key}`}
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
              length: Math.max(0, FIELD_DOC_PAGE_SIZE - pageDocs.length),
            }).map((_, idx) => (
              <div
                key={`filler-${idx}`}
                className="px-3 py-2 border-b border-border/60 border-l-2 border-l-transparent"
              >
                <span className="text-xs text-transparent select-none">·</span>
              </div>
            ))}
          </div>
          {totalPages > 1 && (
            <div className="px-2 py-1.5 border-t border-border/60 bg-muted/40 flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setFieldDocPage(Math.max(0, safePage - 1))}
                disabled={safePage === 0}
                className="px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                aria-label="Previous page"
                data-testid="missing-fields-page-prev"
              >
                <ChevronLeft className="h-3 w-3" /> Prev
              </button>
              <span className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase tabular-nums">
                {safePage + 1} / {totalPages}
              </span>
              <button
                type="button"
                onClick={() =>
                  setFieldDocPage(Math.min(totalPages - 1, safePage + 1))
                }
                disabled={safePage >= totalPages - 1}
                className="px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                aria-label="Next page"
                data-testid="missing-fields-page-next"
              >
                Next <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          )}
        </div>

        {/* Right: chip editor for active doc */}
        <div className="p-3">
          <div className="flex items-baseline justify-between mb-2">
            <div className="text-sm text-foreground">{currentLabel}</div>
            <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase">
              {fields.length} field{fields.length === 1 ? "" : "s"}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5 mb-3 min-h-[28px]">
            {fields.map((f) => (
              <span
                key={f}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-muted/60 border border-border/60 rounded-full text-xs font-mono"
                data-testid={`required-field-${currentKey}-${f}`}
              >
                {f}
                <button
                  type="button"
                  onClick={() => onRemove(ruleId, currentKey, f)}
                  className="text-muted-foreground/70 hover:text-red-600 transition-colors"
                  aria-label={`Remove ${f}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            {fields.length === 0 && (
              <span className="text-[11px] text-muted-foreground italic self-center">
                No required fields configured for {currentLabel} yet.
              </span>
            )}
          </div>
          {currentKey &&
            (() => {
              const allHints = getFieldHintsForDocType(currentKey);
              const remaining = allHints.filter((h) => !fields.includes(h));
              if (remaining.length === 0) return null;
              return (
                <div
                  className="mb-3"
                  data-testid={`field-hints-${currentKey}`}
                >
                  <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase mb-1.5">
                    Suggestions for {currentLabel}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {remaining.map((hint) => (
                      <button
                        key={hint}
                        type="button"
                        onClick={() => onAdd(ruleId, currentKey, hint)}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono border border-dashed border-border/70 bg-background text-muted-foreground hover:text-foreground hover:border-[oklch(0.750_0.170_65)] hover:bg-[oklch(0.750_0.170_65)]/10 transition-colors"
                        data-testid={`field-hint-${currentKey}-${hint}`}
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
                  if (currentKey) {
                    onAdd(ruleId, currentKey, fieldDraft);
                    setFieldDraft("");
                  }
                }
              }}
              placeholder={`Add a required field for ${currentLabel} · press Enter`}
              className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs font-mono focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              data-testid="required-field-input"
            />
            <button
              type="button"
              onClick={() => {
                if (!currentKey) return;
                onAdd(ruleId, currentKey, fieldDraft);
                setFieldDraft("");
              }}
              disabled={!fieldDraft.trim() || !currentKey}
              className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium border border-border/60 bg-background hover:bg-muted/60 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="required-field-add"
            >
              <Plus className="h-3 w-3" />
              Add
            </button>
          </div>
        </div>
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
