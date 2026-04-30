/**
 * Loan-context vocabularies — mirrors backend
 * `app/micro_apps/loan_onboarding/services/compliance_rules.py` (LOAN_PROGRAMS,
 * LOAN_PURPOSES, OCCUPANCY_TYPES, SCENARIO_FLAGS, AUS_ENGINES,
 * AUS_WAIVER_OPTIONS, US_STATES). Kept client-side because:
 *   1. The lists are small + stable (regulator-defined enums).
 *   2. The new-package form needs them at first paint with no extra round-trip.
 *   3. The backend re-validates on every write (security boundary), so a stale
 *      client copy degrades to a 422, not silent corruption.
 *
 * If you add or rename any entry here, update the matching constant in
 * compliance_rules.py — the hashes/IDs must agree.
 */
import type { LoanContextInput } from "./types";

export interface OptionItem {
  id: string;
  label: string;
  group?: string;
}

export const LOAN_PROGRAMS: OptionItem[] = [
  { id: "conv",       label: "Conventional Conforming",     group: "Conventional" },
  { id: "conv_hb",    label: "Conventional High-Balance",   group: "Conventional" },
  { id: "fha",        label: "FHA 203(b)",                  group: "Government" },
  { id: "fha_203k",   label: "FHA 203(k) Renovation",       group: "Government" },
  { id: "fha_stream", label: "FHA Streamline Refinance",    group: "Government" },
  { id: "va_pur",     label: "VA Purchase / Cash-Out",      group: "Government" },
  { id: "va_irrrl",   label: "VA IRRRL (Streamline)",       group: "Government" },
  { id: "usda",       label: "USDA Section 502 Guaranteed", group: "Government" },
  { id: "jumbo",      label: "Jumbo Prime",                 group: "Jumbo" },
  { id: "nonqm_bs",   label: "Non-QM Bank Statement",       group: "Non-QM" },
  { id: "nonqm_dscr", label: "Non-QM DSCR (Investment)",    group: "Non-QM" },
];

export const LOAN_PURPOSES: OptionItem[] = [
  { id: "purchase", label: "Purchase" },
  { id: "rt_refi",  label: "Rate-and-Term Refinance" },
  { id: "co_refi",  label: "Cash-Out Refinance" },
  { id: "c2p",      label: "Construction-to-Perm" },
];

export const OCCUPANCY_TYPES: OptionItem[] = [
  { id: "primary",    label: "Primary residence" },
  { id: "second",     label: "Second home" },
  { id: "investment", label: "Investment property" },
];

export const SCENARIO_FLAGS: OptionItem[] = [
  { id: "self_employed", label: "Self-employed" },
  { id: "gift_funds",    label: "Gift funds" },
  { id: "rental_income", label: "Rental income used to qualify" },
  { id: "co_borrower",   label: "Co-borrower on loan" },
  { id: "first_time",    label: "First-time homebuyer" },
  { id: "high_cost",     label: "High-cost APR (HOEPA \u00a732 territory)" },
];

export const AUS_ENGINES: OptionItem[] = [
  { id: "du",     label: "Fannie Mae DU" },
  { id: "lpa",    label: "Freddie Mac LPA" },
  { id: "gus",    label: "USDA GUS" },
  { id: "manual", label: "Manual underwrite" },
];

export const AUS_WAIVER_OPTIONS: OptionItem[] = [
  { id: "piw",     label: "PIW / Appraisal waiver" },
  { id: "no_ftax", label: "Tax transcript (4506-C) waiver" },
  { id: "asset_v", label: "Asset verification waiver" },
];

export const US_STATES: string[] = [
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
  "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
  "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
  "VA","WA","WV","WI","WY",
];

/** Default seed for the form — matches backend `LoanContext` defaults. */
export const DEFAULT_LOAN_CONTEXT: LoanContextInput = {
  program: "conv",
  purpose: "purchase",
  occupancy: "primary",
  state: "CT",
  scenarioFlags: [],
  ausEngine: "du",
  ausWaivers: [],
  loanAmount: null,
  propertyValue: null,
};
