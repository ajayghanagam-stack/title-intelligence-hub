"use client";

/**
 * Loan-context form — captures the inputs the compliance engine needs to
 * decide which rules apply (program, purpose, occupancy, state, AUS engine,
 * scenario flags, AUS waivers, loan amount, property value).
 *
 * Used in two places:
 *   1. The new-package form (`packages/new/page.tsx`) as an opt-in section.
 *   2. The compliance page (`packages/[id]/compliance/page.tsx`) as an
 *      "Edit Context" modal so reviewers can correct values without re-upload.
 *
 * Pure presentation — parents own state and submission.
 */
import { useMemo } from "react";
import { Check } from "lucide-react";
import {
  AUS_ENGINES,
  AUS_WAIVER_OPTIONS,
  LOAN_PROGRAMS,
  LOAN_PURPOSES,
  OCCUPANCY_TYPES,
  SCENARIO_FLAGS,
  US_STATES,
} from "@/lib/loan-onboarding/loan-context";
import type { LoanContextInput } from "@/lib/loan-onboarding/types";
import { cn } from "@/lib/utils";

interface Props {
  value: LoanContextInput;
  onChange: (next: LoanContextInput) => void;
  /** When true, render in a denser layout (used inside the modal). */
  compact?: boolean;
}

export function LoanContextForm({ value, onChange, compact = false }: Props) {
  const programsByGroup = useMemo(() => {
    const groups = new Map<string, typeof LOAN_PROGRAMS>();
    for (const p of LOAN_PROGRAMS) {
      const g = p.group ?? "Other";
      const list = groups.get(g) ?? [];
      list.push(p);
      groups.set(g, list);
    }
    return Array.from(groups.entries());
  }, []);

  const set = <K extends keyof LoanContextInput>(
    key: K,
    next: LoanContextInput[K]
  ) => onChange({ ...value, [key]: next });

  const toggleArrayItem = (key: "scenarioFlags" | "ausWaivers", id: string) => {
    const current = value[key];
    const next = current.includes(id)
      ? current.filter((x) => x !== id)
      : [...current, id];
    set(key, next);
  };

  const gridCols = compact
    ? "grid-cols-1 sm:grid-cols-2"
    : "grid-cols-1 md:grid-cols-2";

  return (
    <div className="space-y-5" data-testid="loan-context-form">
      {/* Top-row primary selects */}
      <div className={cn("grid gap-4", gridCols)}>
        <Field label="Loan program">
          <select
            value={value.program}
            onChange={(e) => set("program", e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            data-testid="loan-context-program"
          >
            {programsByGroup.map(([group, items]) => (
              <optgroup key={group} label={group}>
                {items.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </Field>

        <Field label="Loan purpose">
          <select
            value={value.purpose}
            onChange={(e) => set("purpose", e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            data-testid="loan-context-purpose"
          >
            {LOAN_PURPOSES.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Occupancy">
          <select
            value={value.occupancy}
            onChange={(e) => set("occupancy", e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            data-testid="loan-context-occupancy"
          >
            {OCCUPANCY_TYPES.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Subject state">
          <select
            value={value.state}
            onChange={(e) => set("state", e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            data-testid="loan-context-state"
          >
            {US_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>

        <Field label="AUS engine">
          <select
            value={value.ausEngine}
            onChange={(e) => set("ausEngine", e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            data-testid="loan-context-aus-engine"
          >
            {AUS_ENGINES.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Loan amount (USD)">
          <input
            type="number"
            inputMode="decimal"
            min={0}
            step={1000}
            value={value.loanAmount ?? ""}
            placeholder="e.g. 425000"
            onChange={(e) =>
              set("loanAmount", e.target.value === "" ? null : Number(e.target.value))
            }
            className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            data-testid="loan-context-loan-amount"
          />
        </Field>

        <Field label="Property value (USD)">
          <input
            type="number"
            inputMode="decimal"
            min={0}
            step={1000}
            value={value.propertyValue ?? ""}
            placeholder="e.g. 530000"
            onChange={(e) =>
              set(
                "propertyValue",
                e.target.value === "" ? null : Number(e.target.value)
              )
            }
            className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            data-testid="loan-context-property-value"
          />
        </Field>
      </div>

      {/* Multi-select chip groups */}
      <ChipGroup
        label="Scenario flags"
        helper="Toggle every situation that applies — they unlock additional checks."
        options={SCENARIO_FLAGS}
        selected={value.scenarioFlags}
        onToggle={(id) => toggleArrayItem("scenarioFlags", id)}
        testId="loan-context-scenario-flags"
      />

      <ChipGroup
        label="AUS waivers"
        helper="Document the waivers granted by the AUS so the engine doesn't flag missing items."
        options={AUS_WAIVER_OPTIONS}
        selected={value.ausWaivers}
        onToggle={(id) => toggleArrayItem("ausWaivers", id)}
        testId="loan-context-aus-waivers"
      />
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium text-foreground/90">{label}</span>
      {children}
    </label>
  );
}

function ChipGroup({
  label,
  helper,
  options,
  selected,
  onToggle,
  testId,
}: {
  label: string;
  helper?: string;
  options: { id: string; label: string }[];
  selected: string[];
  onToggle: (id: string) => void;
  testId: string;
}) {
  return (
    <div className="space-y-2" data-testid={testId}>
      <div>
        <div className="text-sm font-medium text-foreground/90">{label}</div>
        {helper && (
          <div className="text-xs text-muted-foreground mt-0.5">{helper}</div>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const active = selected.includes(opt.id);
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => onToggle(opt.id)}
              aria-pressed={active}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-stone-300 bg-background text-foreground/80 hover:bg-stone-50"
              )}
            >
              {active && <Check className="h-3 w-3" />}
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
