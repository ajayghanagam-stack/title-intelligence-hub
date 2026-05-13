"use client";

// Full-page Validation Rule editor — mirrors the LogikIntake prototype
// (prototype/src/app/logik-intake/admin/validation-rules/rule-editor.tsx)
// but wired to the LO admin config API instead of in-memory fixtures.
//
// Used by validation-rules/page.tsx in both add and edit modes. The
// list page swaps to this view when the operator picks Edit or Add Rule;
// onCancel/onSave return them to the list.

import { ArrowLeft, Check } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useOrg } from "@/hooks/use-org";
import { cn } from "@/lib/utils";

export type RulePayload = {
  scope: "doc" | "data";
  rule: string;
  description: string;
  applies_to: string;
  condition: string;
  severity: "hard" | "soft";
  preset_id: string | null;
  active: boolean;
};

export type EditableRule = RulePayload & { id?: string };

const APPLIES_TO_PRESETS = [
  "W-2 Wage & Tax",
  "Pay Stub / Paycheck",
  "IRS 1040 Tax Return",
  "Bank Statement",
  "VOE",
] as const;

const SCOPE_OPTIONS: { value: "doc" | "data"; label: string }[] = [
  { value: "doc", label: "Document Rule" },
  { value: "data", label: "Data Validation Rule" },
];

type DocTypeOption = {
  id: string;
  name: string;
  category: string;
  active: boolean;
};

type Draft = {
  rule: string;
  description: string;
  scope: "doc" | "data";
  severity: "hard" | "soft";
  appliesToChips: string[];
  appliesToExtra: string;
  condition: string;
  active: boolean;
};

function splitAppliesTo(raw: string): { chips: string[]; extra: string } {
  const tokens = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const chips: string[] = [];
  const extras: string[] = [];
  for (const t of tokens) {
    if ((APPLIES_TO_PRESETS as readonly string[]).includes(t)) chips.push(t);
    else extras.push(t);
  }
  return { chips, extra: extras.join(", ") };
}

function joinAppliesTo(chips: string[], extra: string): string {
  const extras = extra
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return [...chips, ...extras].join(", ");
}

export function RuleEditor({
  mode,
  source,
  defaultScope,
  onCancel,
  onSave,
  saving,
}: {
  mode: "add" | "edit";
  /** Existing rule for edit mode, or undefined for add mode. */
  source?: EditableRule;
  defaultScope?: "doc" | "data";
  onCancel: () => void;
  onSave: (next: RulePayload) => Promise<void> | void;
  saving?: boolean;
}) {
  const { orgFetch } = useOrg();

  // Initial draft snapshot. We rebuild only when `source` changes — the
  // form is otherwise self-contained and persists user edits across
  // re-renders.
  const initial: Draft = useMemo(() => {
    const split = splitAppliesTo(source?.applies_to ?? "");
    return {
      rule: source?.rule ?? "",
      description: source?.description ?? "",
      scope: source?.scope ?? defaultScope ?? "data",
      severity: source?.severity ?? "hard",
      appliesToChips: split.chips,
      appliesToExtra: split.extra,
      condition: source?.condition ?? "",
      active: source?.active ?? true,
    };
  }, [source, defaultScope]);

  const [draft, setDraft] = useState<Draft>(initial);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  // Fetch doc-type catalog so the "Other" datalist surfaces real values.
  // We don't render a dropdown here (prototype uses chip presets +
  // free-text) but still pull the catalog so a future enhancement can
  // dropdown the extras input.
  const [docTypes, setDocTypes] = useState<DocTypeOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    orgFetch<DocTypeOption[]>(
      "/api/v1/apps/loan-onboarding/admin/config/doc-types"
    )
      .then((data) => {
        if (!cancelled) setDocTypes(data.filter((d) => d.active));
      })
      .catch(() => {
        /* dropdown will fall back to existing values + default */
      });
    return () => {
      cancelled = true;
    };
  }, [orgFetch]);

  const docTypeSuggestions = useMemo(() => {
    const cats = Array.from(new Set(docTypes.map((d) => d.category))).sort();
    const names = Array.from(new Set(docTypes.map((d) => d.name))).sort();
    return Array.from(
      new Set([
        "All Documents",
        "Program Checklist",
        ...cats.map((c) => `All ${c} Docs`),
        ...names,
      ])
    );
  }, [docTypes]);

  const update = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const toggleChip = (chip: string) =>
    setDraft((d) => ({
      ...d,
      appliesToChips: d.appliesToChips.includes(chip)
        ? d.appliesToChips.filter((c) => c !== chip)
        : [...d.appliesToChips, chip],
    }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = draft.rule.trim();
    if (!name) return;
    setSubmitErr(null);
    const payload: RulePayload = {
      scope: draft.scope,
      rule: name,
      description: draft.description.trim(),
      applies_to: joinAppliesTo(draft.appliesToChips, draft.appliesToExtra),
      condition: draft.condition.trim(),
      severity: draft.severity,
      preset_id: source?.preset_id ?? null,
      active: draft.active,
    };
    try {
      await onSave(payload);
    } catch (e) {
      setSubmitErr((e as Error).message ?? "Failed to save");
    }
  };

  const scopeLabel =
    SCOPE_OPTIONS.find((o) => o.value === draft.scope)?.label ?? "";
  const typeLabel = draft.severity === "hard" ? "Hard Stop" : "Soft Flag";
  const shortId = source?.id ? source.id.slice(0, 8) : "new";

  return (
    <form onSubmit={submit} className="mx-auto max-w-5xl space-y-5 px-2 py-2">
      {/* Header — back link + title + active toggle */}
      <button
        type="button"
        onClick={onCancel}
        className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3 w-3" />
        Back to Validation Rules
      </button>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            {mode === "edit" ? "Edit Validation Rule" : "Add Validation Rule"}
          </h1>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {mode === "edit" ? (
              <>
                Rule ID: <span className="font-mono">{shortId}</span> ·{" "}
                {scopeLabel} · Currently:{" "}
                <span className="font-semibold">{typeLabel}</span>
              </>
            ) : (
              "Rules apply to new files immediately. Existing in-progress files are not retroactively affected."
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => update("active", !draft.active)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider ring-1 transition",
            draft.active
              ? "bg-brand-teal/10 text-brand-teal ring-brand-teal/40"
              : "bg-muted text-muted-foreground ring-border"
          )}
          aria-pressed={draft.active}
        >
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              draft.active ? "bg-brand-teal" : "bg-muted-foreground/60"
            )}
          />
          {draft.active ? "Active" : "Inactive"}
        </button>
      </header>

      {/* Section 1 — Rule Identity */}
      <section className="card-warm p-5">
        <h2 className="mb-4 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
          Rule Identity
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold text-foreground">
              Rule Name <span className="text-rose-500">*</span>
            </span>
            <input
              type="text"
              required
              value={draft.rule}
              onChange={(e) => update("rule", e.target.value)}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs outline-none focus:border-brand-teal focus:ring-1 focus:ring-brand-teal"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold text-foreground">
              Rule Category
            </span>
            <select
              value={draft.scope}
              onChange={(e) =>
                update("scope", e.target.value as "doc" | "data")
              }
              // Scope is immutable on edit (backend rejects PATCH on scope).
              disabled={mode === "edit"}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs outline-none focus:border-brand-teal focus:ring-1 focus:ring-brand-teal disabled:cursor-not-allowed disabled:opacity-70"
            >
              {SCOPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            {mode === "edit" && (
              <span className="mt-1 block text-[10px] text-muted-foreground">
                Scope is fixed once a rule is created. Duplicate the rule
                into the other scope if you need to migrate it.
              </span>
            )}
          </label>
          <label className="block md:col-span-2">
            <span className="mb-1 block text-[11px] font-semibold text-foreground">
              Description
            </span>
            <textarea
              rows={3}
              value={draft.description}
              onChange={(e) => update("description", e.target.value)}
              placeholder="Plain-English summary of what this rule enforces."
              className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-xs outline-none focus:border-brand-teal focus:ring-1 focus:ring-brand-teal"
            />
          </label>
        </div>
      </section>

      {/* Section 2 — Applies To + Condition */}
      <section className="card-warm p-5">
        <h2 className="mb-1 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
          Applies To
        </h2>
        <p className="mb-3 text-[11px] text-muted-foreground">
          Pick the document types this rule evaluates. Add custom scopes in
          the field below if your scope isn&apos;t one of the presets.
        </p>
        <div className="mb-4 flex flex-wrap gap-2">
          {APPLIES_TO_PRESETS.map((chip) => {
            const selected = draft.appliesToChips.includes(chip);
            return (
              <button
                key={chip}
                type="button"
                onClick={() => toggleChip(chip)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium ring-1 transition",
                  selected
                    ? "bg-brand-teal/10 text-brand-teal ring-brand-teal/40"
                    : "bg-card text-muted-foreground ring-border hover:text-foreground"
                )}
                aria-pressed={selected}
              >
                {selected && <Check className="h-3 w-3" />}
                {chip}
              </button>
            );
          })}
        </div>
        <label className="mb-4 block">
          <span className="mb-1 block text-[11px] font-semibold text-foreground">
            Other (comma-separated)
          </span>
          <input
            type="text"
            value={draft.appliesToExtra}
            onChange={(e) => update("appliesToExtra", e.target.value)}
            placeholder="e.g. All Documents, Program Checklist, Government ID"
            list="lo-rule-applies-to-suggestions"
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs outline-none focus:border-brand-teal focus:ring-1 focus:ring-brand-teal"
          />
          <datalist id="lo-rule-applies-to-suggestions">
            {docTypeSuggestions.map((opt) => (
              <option key={opt} value={opt} />
            ))}
          </datalist>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold text-foreground">
            Condition / Threshold
          </span>
          <input
            type="text"
            value={draft.condition}
            onChange={(e) => update("condition", e.target.value)}
            placeholder="e.g. Variance ≤ 5% · Max age: 60 days · Fuzzy match ≥ 85%"
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs font-mono outline-none focus:border-brand-teal focus:ring-1 focus:ring-brand-teal"
          />
          <span className="mt-1 block text-[10px] text-muted-foreground">
            Auto-acceptable threshold. Program Profiles can override this for
            specific loan programs — they may only tighten, never loosen.
          </span>
        </label>
      </section>

      {/* Section 3 — Exception Type */}
      <section className="rounded-xl border border-brand-orange/40 bg-brand-orange/5 p-5">
        <h2 className="mb-1 text-[11px] font-bold uppercase tracking-wider text-brand-orange">
          Exception Type — What happens when this rule fails?
        </h2>
        <p className="mb-4 text-[11px] text-muted-foreground">
          This is the most important setting for any rule. <strong>Hard Stop</strong>
          : file is blocked until resolved. <strong>Soft Flag</strong>: operator
          is notified — file can continue. Program Profiles can only make this
          stricter — never more lenient.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          {(["hard", "soft"] as const).map((t) => {
            const selected = draft.severity === t;
            const label = t === "hard" ? "Hard Stop" : "Soft Flag";
            const blurb =
              t === "hard"
                ? "File is blocked until an operator explicitly resolves or overrides the exception."
                : "Operator sees an advisory flag but the file can continue advancing through the pipeline.";
            return (
              <button
                key={t}
                type="button"
                onClick={() => update("severity", t)}
                className={cn(
                  "rounded-lg border bg-card p-3.5 text-left transition",
                  selected
                    ? t === "hard"
                      ? "border-rose-300 ring-1 ring-rose-300"
                      : "border-brand-orange/60 ring-1 ring-brand-orange/60"
                    : "border-border hover:border-foreground/30"
                )}
                aria-pressed={selected}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "flex h-3.5 w-3.5 items-center justify-center rounded-full border",
                      selected
                        ? t === "hard"
                          ? "border-rose-500"
                          : "border-brand-orange"
                        : "border-muted-foreground/50"
                    )}
                  >
                    {selected && (
                      <span
                        className={cn(
                          "h-1.5 w-1.5 rounded-full",
                          t === "hard" ? "bg-rose-500" : "bg-brand-orange"
                        )}
                      />
                    )}
                  </span>
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1",
                      t === "hard"
                        ? "bg-rose-50 text-rose-700 ring-rose-200"
                        : "bg-brand-orange/15 text-[#7A5000] ring-brand-orange/40"
                    )}
                  >
                    {label}
                  </span>
                </div>
                <p className="mt-2 text-[11px] text-muted-foreground">{blurb}</p>
              </button>
            );
          })}
        </div>
      </section>

      {submitErr && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {submitErr}
        </div>
      )}

      {/* Footer */}
      <footer className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-border bg-card px-4 py-2 text-xs font-semibold text-muted-foreground transition hover:text-foreground"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-brand-purple px-4 py-2 text-xs font-bold uppercase tracking-wider text-white hover:opacity-90 disabled:opacity-50"
        >
          {saving
            ? "Saving…"
            : mode === "edit"
              ? "Save Rule"
              : "Add Rule"}
        </button>
      </footer>
    </form>
  );
}
