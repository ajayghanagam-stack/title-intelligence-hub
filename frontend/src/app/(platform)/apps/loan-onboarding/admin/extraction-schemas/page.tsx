"use client";

// Phase 5.3 — Extraction Schemas admin.
//
// Backend-driven CRUD against /api/v1/apps/loan-onboarding/admin/config/extraction-schemas.
// Mirrors prototype: doc-type sidebar with pending indicators, header
// with schema-status badge, Duplicate button, Add Field button, per-row
// Edit, footer Add Field. Backend stores `fields` as a free-form JSONB
// list — each field is { key, type, required, min_confidence }.

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Edit, Plus, X } from "lucide-react";

import { AdminHeader } from "@/components/loan-onboarding/logik-intake/admin-header";
import { useOrg } from "@/hooks/use-org";
import { cn } from "@/lib/utils";

type DocType = {
  id: string;
  key: string;
  name: string;
  active: boolean;
};

type SchemaField = {
  key: string;
  type: "string" | "number" | "date" | "boolean" | string;
  required: boolean;
  min_confidence: number;
};

// Suggested fields per doc-type key. When a doc type has no schema row (or
// the row has zero fields), the admin UI renders these as a read-only
// preview so the operator can see what the canonical schema would look like
// before committing it. All suggested fields are rendered with the Required
// toggle disabled (uneditable) — they aren't persisted, so toggling a value
// that doesn't exist in the DB would be misleading.
//
// Mirrors `backend/scripts/lo_prototype_data.py` (the seed). Keep the two
// in sync when adding new doc types.
const f = (
  key: string,
  type: SchemaField["type"],
  min_confidence: number,
): SchemaField => ({ key, type, required: false, min_confidence });

const DEFAULT_FIELDS_BY_KEY: Record<string, SchemaField[]> = {
  w2: [
    f("employer_name", "string", 0.8),
    f("employer_ein", "string", 0.9),
    f("employee_name", "string", 0.85),
    f("employee_ssn_last4", "ssn", 0.95),
    f("employee_address", "address", 0.7),
    f("tax_year", "year", 0.95),
    f("box1_wages_tips", "currency", 0.9),
    f("box2_federal_tax_withheld", "currency", 0.9),
    f("box3_social_security_wages", "currency", 0.85),
    f("box4_social_security_tax_withheld", "currency", 0.85),
    f("box5_medicare_wages", "currency", 0.85),
    f("box12_code_amount", "string", 0.7),
  ],
  f1040: [
    f("tax_year", "year", 0.95),
    f("filing_status", "string", 0.9),
    f("taxpayer_name", "string", 0.85),
    f("taxpayer_ssn_last4", "ssn", 0.95),
    f("spouse_name", "string", 0.8),
    f("spouse_ssn_last4", "ssn", 0.95),
    f("total_income", "currency", 0.9),
    f("adjusted_gross_income", "currency", 0.9),
    f("taxable_income", "currency", 0.88),
  ],
  sch_c: [
    f("business_name", "string", 0.85),
    f("ein_or_ssn", "string", 0.95),
    f("principal_business_activity", "string", 0.75),
    f("accounting_method", "string", 0.7),
    f("gross_receipts", "currency", 0.9),
    f("total_expenses", "currency", 0.88),
    f("net_profit_or_loss", "currency", 0.9),
    f("line_31_net_profit", "currency", 0.85),
  ],
  paystub: [
    f("employer_name", "string", 0.85),
    f("employee_name", "string", 0.85),
    f("pay_period_start", "date", 0.9),
    f("pay_period_end", "date", 0.9),
    f("gross_pay", "currency", 0.9),
    f("net_pay", "currency", 0.88),
    f("ytd_gross", "currency", 0.88),
  ],
  bank_stmt: [
    f("bank_name", "string", 0.85),
    f("account_holder_name", "string", 0.85),
    f("account_number_last4", "string", 0.9),
    f("statement_period_start", "date", 0.9),
    f("statement_period_end", "date", 0.9),
    f("beginning_balance", "currency", 0.88),
    f("ending_balance", "currency", 0.9),
    f("average_daily_balance", "currency", 0.8),
    f("total_deposits", "currency", 0.8),
    f("total_withdrawals", "currency", 0.8),
  ],
  gov_id: [
    f("id_type", "string", 0.9),
    f("id_number_last4", "string", 0.9),
    f("full_name", "string", 0.9),
    f("date_of_birth", "date", 0.9),
    f("expiration_date", "date", 0.95),
    f("issuing_state", "string", 0.85),
  ],
  voe: [
    f("employer_name", "string", 0.9),
    f("employee_name", "string", 0.9),
    f("position_title", "string", 0.8),
    f("hire_date", "date", 0.9),
    f("employment_status", "string", 0.85),
    f("current_salary", "currency", 0.85),
  ],
  purchase_agmt: [
    f("buyer_name", "string", 0.9),
    f("seller_name", "string", 0.9),
    f("property_address", "address", 0.85),
    f("purchase_price", "currency", 0.95),
    f("earnest_money", "currency", 0.85),
    f("closing_date", "date", 0.9),
    f("contingencies", "string", 0.7),
    f("signature_buyer", "boolean", 0.85),
    f("signature_seller", "boolean", 0.85),
  ],
  appraisal: [
    f("subject_property_address", "address", 0.9),
    f("appraiser_name", "string", 0.85),
    f("appraiser_license_number", "string", 0.9),
    f("effective_date", "date", 0.9),
    f("appraised_value", "currency", 0.95),
    f("gross_living_area_sqft", "number", 0.85),
    f("year_built", "year", 0.85),
    f("bedroom_count", "number", 0.85),
    f("bathroom_count", "number", 0.85),
    f("comparable_count", "number", 0.75),
    f("appraiser_signed", "boolean", 0.75),
  ],
  hoi: [
    f("insurance_carrier", "string", 0.85),
    f("policy_number", "string", 0.9),
    f("named_insured", "string", 0.85),
    f("property_address", "address", 0.85),
    f("effective_date", "date", 0.9),
    f("expiration_date", "date", 0.9),
    f("dwelling_coverage_amount", "currency", 0.85),
  ],
  title_commit: [
    f("title_company_name", "string", 0.85),
    f("file_number", "string", 0.95),
    f("effective_date", "date", 0.9),
    f("proposed_insured", "string", 0.85),
    f("property_address", "address", 0.9),
    f("legal_description", "string", 0.75),
    f("estate_or_interest", "string", 0.8),
    f("purchase_price", "currency", 0.9),
    f("loan_amount", "currency", 0.9),
    f("current_vesting", "string", 0.8),
  ],
  credit_report: [
    f("borrower_name", "string", 0.9),
    f("borrower_ssn_last4", "ssn", 0.95),
    f("report_date", "date", 0.9),
    f("equifax_score", "number", 0.95),
    f("experian_score", "number", 0.95),
    f("transunion_score", "number", 0.95),
    f("derogatory_count", "number", 0.85),
    f("inquiries_count", "number", 0.85),
  ],
  dd214: [
    f("service_member_name", "string", 0.9),
    f("service_member_ssn_last4", "ssn", 0.95),
    f("date_of_birth", "date", 0.9),
    f("branch_of_service", "string", 0.9),
    f("entry_date", "date", 0.9),
    f("separation_date", "date", 0.9),
    f("character_of_service", "string", 0.85),
    f("rank_at_separation", "string", 0.8),
    f("total_active_service_years", "number", 0.85),
  ],
  gift_letter: [
    f("donor_name", "string", 0.85),
    f("donor_relationship", "string", 0.8),
    f("gift_amount", "currency", 0.95),
    f("gift_date", "date", 0.9),
    f("donor_signature_present", "boolean", 0.8),
  ],
  flood_cert: [
    f("borrower_name", "string", 0.85),
    f("property_address", "address", 0.9),
    f("certificate_number", "string", 0.95),
    f("determination_date", "date", 0.9),
    f("flood_zone", "string", 0.95),
    f("in_special_flood_hazard_area", "boolean", 0.95),
    f("nfip_community_number", "string", 0.85),
    f("nfip_community_name", "string", 0.8),
  ],
  f4506c: [
    f("taxpayer_name", "string", 0.9),
    f("taxpayer_ssn_last4", "ssn", 0.95),
    f("spouse_name", "string", 0.85),
    f("spouse_ssn_last4", "ssn", 0.95),
    f("current_address", "address", 0.85),
    f("previous_address", "address", 0.8),
    f("transcript_type", "string", 0.9),
    f("tax_years_requested", "string", 0.9),
    f("signature_date", "date", 0.9),
  ],
  ss_award: [
    f("recipient_name", "string", 0.85),
    f("recipient_ssn_last4", "ssn", 0.95),
    f("monthly_benefit_amount", "currency", 0.9),
    f("effective_date", "date", 0.85),
  ],
  lease: [
    f("lessor_name", "string", 0.85),
    f("lessee_name", "string", 0.85),
    f("lease_start_date", "date", 0.9),
    f("lease_end_date", "date", 0.9),
    f("monthly_rent", "currency", 0.85),
  ],
  // Doc types added after the original seed — required toggle stays
  // disabled for these on the suggestion preview.
  urla_1003: [
    f("borrower_name", "string", 0.9),
    f("borrower_ssn_last4", "ssn", 0.95),
    f("borrower_date_of_birth", "date", 0.9),
    f("co_borrower_name", "string", 0.85),
    f("co_borrower_ssn_last4", "ssn", 0.95),
    f("subject_property_address", "address", 0.9),
    f("loan_purpose", "string", 0.9),
    f("loan_amount", "currency", 0.95),
    f("loan_term_months", "number", 0.9),
    f("interest_rate", "number", 0.9),
    f("occupancy_type", "string", 0.85),
    f("monthly_income_total", "currency", 0.85),
    f("monthly_housing_expense", "currency", 0.85),
    f("borrower_signature_present", "boolean", 0.85),
    f("borrower_signature_date", "date", 0.9),
  ],
  closing_disclosure: [
    f("borrower_name", "string", 0.9),
    f("co_borrower_name", "string", 0.85),
    f("seller_name", "string", 0.85),
    f("lender_name", "string", 0.9),
    f("loan_term_months", "number", 0.9),
    f("loan_purpose", "string", 0.9),
    f("loan_product", "string", 0.85),
    f("loan_type", "string", 0.85),
    f("loan_amount", "currency", 0.95),
    f("interest_rate", "number", 0.95),
    f("monthly_principal_and_interest", "currency", 0.9),
    f("prepayment_penalty", "boolean", 0.85),
    f("balloon_payment", "boolean", 0.85),
    f("closing_date", "date", 0.9),
    f("disbursement_date", "date", 0.9),
    f("cash_to_close", "currency", 0.9),
    f("subject_property_address", "address", 0.9),
    f("sale_price", "currency", 0.9),
  ],
  mi_certificate: [
    f("mi_company_name", "string", 0.9),
    f("certificate_number", "string", 0.95),
    f("borrower_name", "string", 0.9),
    f("lender_name", "string", 0.85),
    f("loan_number", "string", 0.9),
    f("property_address", "address", 0.9),
    f("loan_amount", "currency", 0.95),
    f("coverage_percent", "number", 0.9),
    f("premium_amount", "currency", 0.85),
    f("premium_plan", "string", 0.8),
    f("effective_date", "date", 0.9),
    f("expiration_date", "date", 0.9),
  ],
  va_coe: [
    f("veteran_name", "string", 0.9),
    f("veteran_ssn_last4", "ssn", 0.95),
    f("veteran_date_of_birth", "date", 0.9),
    f("service_number", "string", 0.9),
    f("branch_of_service", "string", 0.9),
    f("entitlement_code", "string", 0.9),
    f("entitlement_amount", "currency", 0.95),
    f("entitlement_used", "currency", 0.85),
    f("entitlement_available", "currency", 0.9),
    f("funding_fee_status", "string", 0.85),
    f("certificate_date", "date", 0.9),
    f("certificate_number", "string", 0.95),
  ],
};

type SchemaRow = {
  id: string;
  doc_type_id: string;
  fields: SchemaField[];
  version: number;
  active: boolean;
};

type FieldEditState = {
  field: SchemaField;
  index: number | null; // null = adding new
};

export default function ExtractionSchemasAdminPage() {
  const { orgFetch, currentOrgId } = useOrg();
  const [docTypes, setDocTypes] = useState<DocType[]>([]);
  const [schemas, setSchemas] = useState<SchemaRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDocTypeId, setSelectedDocTypeId] = useState<string | null>(null);
  const [editingField, setEditingField] = useState<FieldEditState | null>(null);

  useEffect(() => {
    if (!currentOrgId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      orgFetch<DocType[]>(
        "/api/v1/apps/loan-onboarding/admin/config/doc-types"
      ),
      orgFetch<SchemaRow[]>(
        "/api/v1/apps/loan-onboarding/admin/config/extraction-schemas"
      ),
    ])
      .then(([dts, sc]) => {
        if (cancelled) return;
        setDocTypes(dts);
        setSchemas(sc);
        setSelectedDocTypeId((cur) => cur ?? dts[0]?.id ?? null);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message ?? "Failed to load schemas");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentOrgId, orgFetch]);

  const selectedDocType = useMemo(
    () => docTypes.find((d) => d.id === selectedDocTypeId) ?? null,
    [docTypes, selectedDocTypeId]
  );
  const selectedSchema = useMemo(
    () => schemas.find((s) => s.doc_type_id === selectedDocTypeId) ?? null,
    [schemas, selectedDocTypeId]
  );

  // Suggested fields per doc-type key from `DEFAULT_FIELDS_BY_KEY`.
  const suggestedAll: SchemaField[] = useMemo(() => {
    if (!selectedDocType) return [];
    return DEFAULT_FIELDS_BY_KEY[selectedDocType.key] ?? [];
  }, [selectedDocType]);

  // Build the row list as `persisted ⊕ missing-suggestions`. Persisted rows
  // render normally (interactive Required toggle + Edit). Suggestion rows
  // render with the toggle in an "off" visual state — clicking it promotes
  // the suggestion into the persisted schema with `required` set to the new
  // value, so the field gets saved on first interaction. This handles three
  // cases with one code path:
  //   (a) zero persisted fields → all rows are suggestions.
  //   (b) partial persistence (e.g. closing_disclosure with 1 field) → the
  //       1 saved field renders interactive, the rest as suggestions.
  //   (c) fully schemed → no suggestion rows.
  type Row = SchemaField & {
    __suggested: boolean;
    /** Index into `selectedSchema.fields` for persisted rows, -1 for suggestions. */
    __persistedIndex: number;
  };
  const rows: Row[] = useMemo(() => {
    const persisted: SchemaField[] = selectedSchema?.fields ?? [];
    const persistedKeys = new Set(persisted.map((f) => f.key));
    const missingSuggestions = suggestedAll.filter(
      (f) => !persistedKeys.has(f.key)
    );
    return [
      ...persisted.map((f, i): Row => ({
        ...f,
        __suggested: false,
        __persistedIndex: i,
      })),
      ...missingSuggestions.map((f): Row => ({
        ...f,
        __suggested: true,
        __persistedIndex: -1,
      })),
    ];
  }, [selectedSchema, suggestedAll]);

  const persistedCount = selectedSchema?.fields.length ?? 0;
  const suggestionCount = rows.filter((r) => r.__suggested).length;
  const hasAnySuggestion = suggestionCount > 0;

  async function persistFields(nextFields: SchemaField[]) {
    if (!selectedDocType) return;
    if (selectedSchema) {
      const updated = await orgFetch<SchemaRow>(
        `/api/v1/apps/loan-onboarding/admin/config/extraction-schemas/${selectedSchema.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ fields: nextFields }),
        }
      );
      setSchemas((rs) => rs.map((s) => (s.id === updated.id ? updated : s)));
    } else {
      const created = await orgFetch<SchemaRow>(
        "/api/v1/apps/loan-onboarding/admin/config/extraction-schemas",
        {
          method: "POST",
          body: JSON.stringify({
            doc_type_id: selectedDocType.id,
            fields: nextFields,
          }),
        }
      );
      setSchemas((rs) => [...rs, created]);
    }
  }

  async function saveField(state: FieldEditState) {
    const existing = selectedSchema?.fields ?? [];
    const next =
      state.index === null
        ? [...existing, state.field]
        : existing.map((f, i) => (i === state.index ? state.field : f));
    await persistFields(next);
  }

  async function toggleRequired(index: number) {
    if (!selectedSchema) return;
    const existing = selectedSchema.fields;
    const target = existing[index];
    if (!target) return;
    const next = existing.map((f, i) =>
      i === index ? { ...f, required: !f.required } : f
    );
    // Optimistic update so the toggle feels instant.
    setSchemas((rs) =>
      rs.map((s) =>
        s.id === selectedSchema.id ? { ...s, fields: next } : s
      )
    );
    try {
      await persistFields(next);
    } catch (e) {
      // Roll back on failure.
      setSchemas((rs) =>
        rs.map((s) =>
          s.id === selectedSchema.id ? { ...s, fields: existing } : s
        )
      );
      setError((e as Error).message);
    }
  }

  /**
   * Promote a suggestion row into the persisted schema with the given
   * `required` value. Used when the operator clicks the Required toggle on
   * a suggestion — the toggle's first click both adds the field and sets
   * the chosen required state, so there's no separate "Add then toggle"
   * dance.
   */
  async function promoteSuggestion(
    suggestion: SchemaField,
    required: boolean
  ) {
    const existing = selectedSchema?.fields ?? [];
    // Guard against double-clicks racing the persist round-trip — if the
    // key is already in the schema, treat it as a regular toggle on the
    // existing row instead of appending a duplicate.
    const existingIdx = existing.findIndex((f) => f.key === suggestion.key);
    if (existingIdx >= 0) {
      await toggleRequired(existingIdx);
      return;
    }
    const next = [...existing, { ...suggestion, required }];
    try {
      await persistFields(next);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-2 py-2">
      <AdminHeader
        title="Extraction Schemas"
        subtitle="Define fields to extract per document type. AI uses these schemas for every document."
      />

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!selectedDocType}
          onClick={() =>
            setEditingField({
              field: {
                key: "",
                type: "string",
                required: true,
                min_confidence: 0.85,
              },
              index: null,
            })
          }
          className="ml-auto inline-flex items-center gap-1 rounded-md bg-brand-purple px-3 py-2 text-xs font-bold uppercase tracking-wider text-white hover:opacity-90 disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Field
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="card-warm p-2">
          <p className="px-2 py-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Document Types
          </p>
          {loading ? (
            <p className="px-2 py-2 text-xs text-muted-foreground">Loading…</p>
          ) : docTypes.length === 0 ? (
            <p className="px-2 py-2 text-xs text-muted-foreground">
              Create doc types first.
            </p>
          ) : (
            <div className="space-y-0.5">
              {docTypes.map((dt) => {
                const schema = schemas.find((s) => s.doc_type_id === dt.id);
                const pending = !schema || schema.fields.length === 0;
                const active = dt.id === selectedDocTypeId;
                return (
                  <button
                    key={dt.id}
                    type="button"
                    onClick={() => setSelectedDocTypeId(dt.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition",
                      active
                        ? "bg-brand-purple/10 font-bold text-brand-purple"
                        : "text-muted-foreground hover:bg-muted"
                    )}
                  >
                    <span className="flex-1 truncate">{dt.name}</span>
                    {pending && (
                      <span className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full bg-brand-orange text-[9px] font-bold text-white">
                        !
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        <section>
          {selectedDocType && (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border bg-card p-3">
                <div>
                  <h2 className="text-base font-bold tracking-tight">
                    {selectedDocType.name}
                  </h2>
                  <p className="text-[11px] text-muted-foreground">
                    Schema {selectedSchema ? `v${selectedSchema.version}` : "not yet created"} ·{" "}
                    {persistedCount} fields
                  </p>
                </div>
                <div className="ml-auto flex items-center gap-2">
                  {persistedCount > 0 && suggestionCount === 0 ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-700 ring-1 ring-emerald-200">
                      <CheckCircle2 className="h-2.5 w-2.5" />
                      Schema complete
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-orange/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[#7A5000] ring-1 ring-brand-orange/40">
                      Schema pending
                    </span>
                  )}
                </div>
              </div>

              {rows.length === 0 ? (
                <div className="rounded-xl border bg-card p-6 text-center text-xs text-muted-foreground">
                  No fields defined yet. Click <strong>Add Field</strong> to start.
                </div>
              ) : (
                <>
                  <div className="overflow-hidden rounded-xl border bg-card">
                    <div className="grid grid-cols-[2fr_1.2fr_0.8fr_1fr_80px] gap-3 bg-muted/40 px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                      <span>Field</span>
                      <span>Type</span>
                      <span className="text-center">Required</span>
                      <span className="text-center">Min Confidence</span>
                      <span></span>
                    </div>
                    <div className="divide-y">
                      {rows.map((r, rowIdx) => {
                        const pct = Math.round((r.min_confidence ?? 0) * 100);
                        const cc =
                          pct >= 85
                            ? "text-emerald-600"
                            : pct >= 70
                              ? "text-[#7A5000]"
                              : "text-rose-600";
                        const bar =
                          pct >= 85
                            ? "bg-emerald-500"
                            : pct >= 70
                              ? "bg-brand-orange"
                              : "bg-rose-500";
                        return (
                          <div
                            key={`${r.key}-${rowIdx}`}
                            className="grid grid-cols-[2fr_1.2fr_0.8fr_1fr_80px] items-center gap-3 px-4 py-2.5 text-xs"
                          >
                            <span className="font-mono font-bold">{r.key}</span>
                            <span>
                              <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                                {r.type}
                              </span>
                            </span>
                            <span className="flex justify-center">
                              <button
                                type="button"
                                onClick={() => {
                                  if (r.__suggested) {
                                    // First click promotes the suggestion
                                    // into the schema with the toggled value.
                                    promoteSuggestion(r, !r.required);
                                  } else {
                                    toggleRequired(r.__persistedIndex);
                                  }
                                }}
                                aria-pressed={r.required}
                                aria-label={
                                  r.required
                                    ? `Mark ${r.key} as optional`
                                    : `Mark ${r.key} as required`
                                }
                                title={
                                  r.__suggested
                                    ? "Toggle to add this suggestion to the schema"
                                    : undefined
                                }
                                className={cn(
                                  "relative block h-4 w-7 rounded-full transition",
                                  r.required ? "bg-brand-teal" : "bg-muted"
                                )}
                              >
                                <span
                                  className={cn(
                                    "absolute top-0.5 h-3 w-3 rounded-full bg-white shadow",
                                    r.required ? "left-[14px]" : "left-0.5"
                                  )}
                                />
                              </button>
                            </span>
                            <span className="flex items-center justify-center gap-2">
                              <span className="block h-1.5 w-12 overflow-hidden rounded-full bg-muted">
                                <span
                                  className={cn("block h-full", bar)}
                                  style={{ width: `${pct}%` }}
                                />
                              </span>
                              <span
                                className={cn(
                                  "font-mono text-[11px] font-bold tabular-nums",
                                  cc
                                )}
                              >
                                {pct}%
                              </span>
                            </span>
                            <span className="flex justify-end">
                              <button
                                type="button"
                                onClick={() =>
                                  setEditingField({
                                    field: {
                                      key: r.key,
                                      type: r.type,
                                      required: r.required,
                                      min_confidence: r.min_confidence,
                                    },
                                    // Suggested rows aren't persisted yet, so
                                    // saving must append rather than mutate.
                                    index: r.__suggested
                                      ? null
                                      : r.__persistedIndex,
                                  })
                                }
                                className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-medium hover:bg-muted"
                              >
                                <Edit className="h-2.5 w-2.5" />
                                {r.__suggested ? "Add" : "Edit"}
                              </button>
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}

              <button
                type="button"
                onClick={() =>
                  setEditingField({
                    field: {
                      key: "",
                      type: "string",
                      required: true,
                      min_confidence: 0.85,
                    },
                    index: null,
                  })
                }
                className="mt-3 inline-flex w-full items-center justify-center gap-1 rounded-md border border-dashed bg-card px-3 py-2 text-xs font-medium text-muted-foreground hover:border-brand-purple hover:bg-brand-purple/5 hover:text-brand-purple"
              >
                <Plus className="h-3 w-3" />
                Add Field to {selectedDocType.name} Schema
              </button>
            </>
          )}
        </section>
      </div>

      {editingField && (
        <FieldModal
          initial={editingField}
          onClose={() => setEditingField(null)}
          onSave={async (state) => {
            await saveField(state);
            setEditingField(null);
          }}
        />
      )}
    </div>
  );
}

function FieldModal({
  initial,
  onClose,
  onSave,
}: {
  initial: FieldEditState;
  onClose: () => void;
  onSave: (state: FieldEditState) => Promise<void>;
}) {
  const [key, setKey] = useState(initial.field.key);
  const [type, setType] = useState(initial.field.type);
  const [required, setRequired] = useState(initial.field.required);
  const [minConf, setMinConf] = useState(
    Math.round((initial.field.min_confidence ?? 0.85) * 100)
  );
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    try {
      await onSave({
        index: initial.index,
        field: {
          key: key.trim(),
          type,
          required,
          min_confidence: Math.max(0, Math.min(100, minConf)) / 100,
        },
      });
    } catch (e) {
      setErr((e as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border bg-card shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b px-5 py-3">
          <h2 className="text-base font-bold tracking-tight">
            {initial.index === null ? "Add Field" : "Edit Field"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <form onSubmit={submit} className="space-y-3 px-5 py-4">
          <label className="block">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Field Key
            </span>
            <input
              required
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="e.g. gross_pay_period"
              className="mt-1 h-9 w-full rounded-md border bg-card px-3 font-mono text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            />
          </label>
          <label className="block">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Type
            </span>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="mt-1 h-9 w-full rounded-md border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            >
              {/* Full set documented in
                  backend/app/micro_apps/loan_onboarding/models/extraction_schema.py
                  — keep this in sync with the model docstring. */}
              <option value="string">string</option>
              <option value="currency">currency</option>
              <option value="number">number</option>
              <option value="date">date</option>
              <option value="year">year</option>
              <option value="boolean">boolean</option>
              <option value="ssn">ssn</option>
              <option value="phone">phone</option>
              <option value="email">email</option>
              <option value="address">address</option>
            </select>
          </label>
          <label className="block">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Min Confidence: {minConf}%
            </span>
            <input
              type="range"
              min={0}
              max={100}
              value={minConf}
              onChange={(e) => setMinConf(Number(e.target.value))}
              className="mt-1 w-full"
            />
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={required}
              onChange={(e) => setRequired(e.target.checked)}
              className="h-4 w-4 rounded border-border text-brand-teal focus:ring-brand-teal/30"
            />
            <span className="text-sm">Required</span>
          </label>

          {err && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {err}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border bg-card px-3 py-1.5 text-xs font-medium hover:bg-muted"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-brand-purple px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-white hover:opacity-90 disabled:opacity-50"
            >
              {submitting ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
