"use client";

// Phase 5.3 — Program Profiles admin.
//
// Backend-driven CRUD against /api/v1/apps/loan-onboarding/admin/config/profiles.
// Mirrors the prototype: profile sidebar, type badges, "Stacks with"
// indicator, info banner, brand-purple "New Profile" + "Edit Profile"
// buttons + modal.

import { useEffect, useMemo, useState } from "react";
import {
  Edit,
  Info,
  Layers,
  ListChecks,
  Plus,
  Settings2,
  Sliders,
  X,
} from "lucide-react";

import { AdminHeader } from "@/components/loan-onboarding/logik-intake/admin-header";
import { useOrg } from "@/hooks/use-org";
import { cn } from "@/lib/utils";

// ── Backend row shapes ─────────────────────────────────────────────────

type ChecklistEntry = {
  doc_type_key: string;
  required: boolean;
  expected_min_pages?: number | null;
  expected_max_pages?: number | null;
  note?: string | null;
};

type ExtractionOverrideMap = Record<
  string, // doc_type key (e.g. "w2")
  Record<
    string, // field key (e.g. "box1_wages_tips")
    { required?: boolean; min_confidence?: number }
  >
>;

type RuleOverride = {
  scope: string;
  rule: string;
  condition: string;
  preset_id: string | null;
  severity: "hard" | "soft";
};

type ProfileRow = {
  id: string;
  name: string;
  type: "loan_program" | "investor_overlay";
  stacks_with: string | null;
  checklist: ChecklistEntry[];
  extraction_overrides: ExtractionOverrideMap;
  rule_overrides: RuleOverride[];
  active: boolean;
};

type DocTypeRow = { id: string; key: string; name: string };

type ExtractionField = {
  key: string;
  type: string;
  required: boolean;
  min_confidence: number;
};
type ExtractionSchemaRow = {
  id: string;
  doc_type_id: string;
  fields: ExtractionField[];
};

type OrgValidationRuleRow = {
  id: string;
  scope: string;
  rule: string;
  condition: string;
  preset_id: string | null;
  severity: "hard" | "soft";
  active: boolean;
};

const TYPE_LABEL: Record<string, string> = {
  loan_program: "Loan Program",
  investor_overlay: "Investor Overlay",
};

const TYPE_BADGE: Record<string, string> = {
  loan_program: "bg-brand-teal/10 text-brand-teal ring-brand-teal/30",
  investor_overlay:
    "bg-brand-purple/10 text-brand-purple ring-brand-purple/30",
};

const REQ_BADGE: Record<string, string> = {
  Required: "bg-brand-teal/10 text-brand-teal ring-brand-teal/30",
  Optional: "bg-muted text-muted-foreground ring-border",
  Conditional: "bg-brand-orange/15 text-[#7A5000] ring-brand-orange/40",
};

type ProfileTab = "checklist" | "ext-overrides" | "rule-overrides";

export default function ProgramProfilesAdminPage() {
  const { orgFetch, currentOrgId } = useOrg();
  const [rows, setRows] = useState<ProfileRow[]>([]);
  // Supporting catalogs let us resolve doc-type keys to human names,
  // compute "vs global" deltas for extraction overrides, and map rule
  // overrides back to their org-level baseline condition.
  const [docTypes, setDocTypes] = useState<DocTypeRow[]>([]);
  const [extractionSchemas, setExtractionSchemas] = useState<
    ExtractionSchemaRow[]
  >([]);
  const [orgRules, setOrgRules] = useState<OrgValidationRuleRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<ProfileTab>("checklist");
  const [showNewModal, setShowNewModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);

  useEffect(() => {
    if (!currentOrgId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      orgFetch<ProfileRow[]>(
        "/api/v1/apps/loan-onboarding/admin/config/profiles"
      ),
      orgFetch<DocTypeRow[]>(
        "/api/v1/apps/loan-onboarding/admin/config/doc-types"
      ),
      orgFetch<ExtractionSchemaRow[]>(
        "/api/v1/apps/loan-onboarding/admin/config/extraction-schemas"
      ),
      orgFetch<OrgValidationRuleRow[]>(
        "/api/v1/apps/loan-onboarding/admin/config/validation-rules"
      ),
    ])
      .then(([profiles, dts, schemas, rules]) => {
        if (cancelled) return;
        setRows(profiles);
        setSelectedId((cur) => cur ?? profiles[0]?.id ?? null);
        setDocTypes(dts);
        setExtractionSchemas(schemas);
        setOrgRules(rules);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message ?? "Failed to load profiles");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentOrgId, orgFetch]);

  // ── Lookups derived from the catalogs ────────────────────────────────

  const docTypeNameByKey = useMemo(() => {
    const m: Record<string, string> = {};
    for (const dt of docTypes) m[dt.key] = dt.name;
    return m;
  }, [docTypes]);

  // doc_type_id → doc_type_key (extraction-schemas FK by id, not key).
  const docTypeKeyById = useMemo(() => {
    const m: Record<string, string> = {};
    for (const dt of docTypes) m[dt.id] = dt.key;
    return m;
  }, [docTypes]);

  // Global field metadata: docTypeKey → fieldKey → { required, min_confidence }.
  const globalFields = useMemo(() => {
    const m: Record<
      string,
      Record<string, { required: boolean; min_confidence: number }>
    > = {};
    for (const schema of extractionSchemas) {
      const dtKey = docTypeKeyById[schema.doc_type_id];
      if (!dtKey) continue;
      m[dtKey] = {};
      for (const f of schema.fields ?? []) {
        m[dtKey][f.key] = {
          required: !!f.required,
          min_confidence: f.min_confidence,
        };
      }
    }
    return m;
  }, [extractionSchemas, docTypeKeyById]);

  // Org rule library by rule name (case-insensitive on name only).
  const orgRuleByName = useMemo(() => {
    const m: Record<string, OrgValidationRuleRow> = {};
    for (const r of orgRules) m[r.rule.toLowerCase()] = r;
    return m;
  }, [orgRules]);

  const profile = useMemo(
    () => rows.find((p) => p.id === selectedId) ?? rows[0] ?? null,
    [rows, selectedId]
  );

  const stacksWithName = useMemo(() => {
    if (!profile?.stacks_with) return null;
    return rows.find((p) => p.id === profile.stacks_with)?.name ?? null;
  }, [profile, rows]);

  async function createProfile(payload: {
    name: string;
    type: "loan_program" | "investor_overlay";
    stacks_with: string | null;
  }) {
    const created = await orgFetch<ProfileRow>(
      "/api/v1/apps/loan-onboarding/admin/config/profiles",
      {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          checklist: [],
          extraction_overrides: {},
          rule_overrides: [],
        }),
      }
    );
    setRows((rs) => [...rs, created]);
    setSelectedId(created.id);
  }

  async function updateProfile(
    id: string,
    patch: { name?: string; stacks_with?: string | null; active?: boolean }
  ) {
    const updated = await orgFetch<ProfileRow>(
      `/api/v1/apps/loan-onboarding/admin/config/profiles/${id}`,
      {
        method: "PATCH",
        body: JSON.stringify(patch),
      }
    );
    setRows((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-2 py-2">
      <AdminHeader
        title="Program Profiles"
        subtitle="Each profile is a named ruleset — loan program or investor overlay. Profiles stack: a file can use a Loan Program plus an Investor Overlay simultaneously."
      />

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setShowNewModal(true)}
          className="ml-auto inline-flex items-center gap-1 rounded-md bg-brand-purple px-3 py-2 text-xs font-bold uppercase tracking-wider text-white hover:opacity-90"
        >
          <Plus className="h-3.5 w-3.5" />
          New Profile
        </button>
      </div>

      <div className="flex items-start gap-2 rounded-md border border-brand-teal/30 bg-brand-teal/5 px-3 py-2 text-[11px]">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-teal" />
        <span>
          <strong>How stacking works:</strong> Global rules are the base. Loan
          Program profiles apply next. Investor Overlays apply last and can only
          tighten — never loosen — what&apos;s below them.
        </span>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="card-warm divide-y">
          <p className="px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Profiles ({rows.length})
          </p>
          {loading ? (
            <p className="px-4 py-3 text-xs text-muted-foreground">Loading…</p>
          ) : rows.length === 0 ? (
            <p className="px-4 py-3 text-xs text-muted-foreground">
              No profiles yet. Click New Profile to create one.
            </p>
          ) : (
            rows.map((p) => {
              const active = p.id === profile?.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setSelectedId(p.id)}
                  className={cn(
                    "w-full px-4 py-3 text-left text-sm transition",
                    active
                      ? "bg-brand-purple/10"
                      : "hover:bg-muted/30"
                  )}
                >
                  <p
                    className={cn(
                      "font-bold",
                      active ? "text-brand-purple" : "text-foreground"
                    )}
                  >
                    {p.name}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ring-1",
                        TYPE_BADGE[p.type]
                      )}
                    >
                      {TYPE_LABEL[p.type] ?? p.type}
                    </span>
                    {!p.active && (
                      <span className="inline-flex items-center rounded-full bg-muted px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-muted-foreground ring-1 ring-border">
                        Inactive
                      </span>
                    )}
                  </div>
                </button>
              );
            })
          )}
        </aside>

        <section>
          {profile && (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border bg-card p-3">
                <div>
                  <h2 className="text-base font-bold tracking-tight">
                    {profile.name}
                  </h2>
                  <p className="text-[11px] text-muted-foreground">
                    {TYPE_LABEL[profile.type] ?? profile.type} ·{" "}
                    {profile.checklist.length} checklist entries ·{" "}
                    {profile.active ? "Active" : "Inactive"}
                  </p>
                </div>
                <div className="ml-auto flex flex-wrap items-center gap-2">
                  {stacksWithName && (
                    <>
                      <span className="text-[11px] text-muted-foreground">
                        Stacks with investor:
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-full bg-brand-purple/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-brand-purple ring-1 ring-brand-purple/30">
                        <Layers className="h-2.5 w-2.5" />
                        {stacksWithName}
                      </span>
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => setShowEditModal(true)}
                    className="inline-flex items-center gap-1 rounded-md border bg-card px-2.5 py-1 text-[11px] font-medium hover:bg-muted"
                  >
                    <Edit className="h-3 w-3" />
                    Edit Profile
                  </button>
                </div>
              </div>

              <div className="mb-3 inline-flex rounded-md border bg-card p-0.5 text-xs">
                <TabBtn
                  active={tab === "checklist"}
                  onClick={() => setTab("checklist")}
                  Icon={ListChecks}
                  label={`Doc Checklist (${profile.checklist.length})`}
                />
                <TabBtn
                  active={tab === "ext-overrides"}
                  onClick={() => setTab("ext-overrides")}
                  Icon={Settings2}
                  label={`Extraction Overrides (${countExtractionOverrides(
                    profile.extraction_overrides
                  )})`}
                />
                <TabBtn
                  active={tab === "rule-overrides"}
                  onClick={() => setTab("rule-overrides")}
                  Icon={Sliders}
                  label={`Rule Overrides (${profile.rule_overrides.length})`}
                />
              </div>

              {tab === "checklist" && (
                <ChecklistTable
                  entries={profile.checklist}
                  docTypeNameByKey={docTypeNameByKey}
                />
              )}
              {tab === "ext-overrides" && (
                <ExtractionOverridesTable
                  overrides={profile.extraction_overrides}
                  docTypeNameByKey={docTypeNameByKey}
                  globalFields={globalFields}
                />
              )}
              {tab === "rule-overrides" && (
                <RuleOverridesTable
                  overrides={profile.rule_overrides}
                  orgRuleByName={orgRuleByName}
                />
              )}
            </>
          )}
        </section>
      </div>

      {showNewModal && (
        <ProfileModal
          title="New Profile"
          submitLabel="Create"
          profiles={rows}
          onClose={() => setShowNewModal(false)}
          onSubmit={async (data) => {
            await createProfile(data);
            setShowNewModal(false);
          }}
        />
      )}
      {showEditModal && profile && (
        <ProfileModal
          title="Edit Profile"
          submitLabel="Save"
          profiles={rows.filter((p) => p.id !== profile.id)}
          initial={{
            name: profile.name,
            type: profile.type,
            stacks_with: profile.stacks_with,
            active: profile.active,
          }}
          editing
          onClose={() => setShowEditModal(false)}
          onSubmit={async (data) => {
            await updateProfile(profile.id, {
              name: data.name,
              stacks_with: data.stacks_with,
              active: data.active,
            });
            setShowEditModal(false);
          }}
        />
      )}
    </div>
  );
}

function ProfileModal({
  title,
  submitLabel,
  profiles,
  initial,
  editing,
  onClose,
  onSubmit,
}: {
  title: string;
  submitLabel: string;
  profiles: ProfileRow[];
  initial?: {
    name: string;
    type: "loan_program" | "investor_overlay";
    stacks_with: string | null;
    active: boolean;
  };
  editing?: boolean;
  onClose: () => void;
  onSubmit: (data: {
    name: string;
    type: "loan_program" | "investor_overlay";
    stacks_with: string | null;
    active: boolean;
  }) => Promise<void>;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [type, setType] = useState<"loan_program" | "investor_overlay">(
    initial?.type ?? "loan_program"
  );
  const [stacksWith, setStacksWith] = useState<string | null>(
    initial?.stacks_with ?? null
  );
  const [active, setActive] = useState(initial?.active ?? true);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const loanProgramOptions = profiles.filter((p) => p.type === "loan_program");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    try {
      await onSubmit({
        name: name.trim(),
        type,
        stacks_with: type === "investor_overlay" ? stacksWith : null,
        active,
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
          <h2 className="text-base font-bold tracking-tight">{title}</h2>
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
              Name
            </span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Conventional 30yr"
              className="mt-1 h-9 w-full rounded-md border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            />
          </label>
          <label className="block">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Type {editing && "(immutable)"}
            </span>
            <select
              value={type}
              onChange={(e) =>
                setType(e.target.value as "loan_program" | "investor_overlay")
              }
              disabled={editing}
              className="mt-1 h-9 w-full rounded-md border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20 disabled:bg-muted"
            >
              <option value="loan_program">Loan Program</option>
              <option value="investor_overlay">Investor Overlay</option>
            </select>
          </label>
          {type === "investor_overlay" && (
            <label className="block">
              <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                Stacks With (Loan Program)
              </span>
              <select
                required
                value={stacksWith ?? ""}
                onChange={(e) => setStacksWith(e.target.value || null)}
                className="mt-1 h-9 w-full rounded-md border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
              >
                <option value="">Select a loan program…</option>
                {loanProgramOptions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {editing && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={active}
                onChange={(e) => setActive(e.target.checked)}
                className="h-4 w-4 rounded border-border text-brand-teal focus:ring-brand-teal/30"
              />
              <span className="text-sm">Active</span>
            </label>
          )}

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
              {submitting ? "Saving…" : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Tab button (matches prototype: icon + label) ─────────────────────

function TabBtn({
  active,
  onClick,
  Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  Icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1.5 font-medium transition",
        active
          ? "bg-brand-teal/10 text-brand-teal"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────

// The extraction_overrides JSONB is doc_type_key → field_key → overrides.
// We count the inner fields, not the outer doc-types, so the tab label
// shows the same number of rows that the table will render.
function countExtractionOverrides(map: ExtractionOverrideMap): number {
  let n = 0;
  for (const k of Object.keys(map)) {
    n += Object.keys(map[k] ?? {}).length;
  }
  return n;
}

// Derive a human "Required | Optional | Conditional" label from the
// backend's `{required, note}` shape. A non-required entry with a note
// is treated as conditional (the note is the trigger condition).
function requirementLabel(entry: ChecklistEntry): {
  label: "Required" | "Optional" | "Conditional";
  condition: string;
} {
  if (entry.required) {
    return { label: "Required", condition: entry.note?.trim() || "" };
  }
  if (entry.note && entry.note.trim()) {
    return { label: "Conditional", condition: entry.note.trim() };
  }
  return { label: "Optional", condition: "" };
}

// ── Checklist table ──────────────────────────────────────────────────

function ChecklistTable({
  entries,
  docTypeNameByKey,
}: {
  entries: ChecklistEntry[];
  docTypeNameByKey: Record<string, string>;
}) {
  if (entries.length === 0) {
    return (
      <div className="overflow-hidden rounded-xl border bg-card">
        <p className="px-4 py-6 text-center text-xs text-muted-foreground">
          Inherits from global checklist.
        </p>
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-4 py-2.5 text-left">Document Type</th>
            <th className="px-4 py-2.5 text-left">Requirement</th>
            <th className="px-4 py-2.5 text-left">Condition</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((c, i) => {
            const { label, condition } = requirementLabel(c);
            const name =
              docTypeNameByKey[c.doc_type_key] ?? c.doc_type_key;
            return (
              <tr key={`${c.doc_type_key}-${i}`} className="border-t">
                <td className="px-4 py-2.5 text-xs font-bold">{name}</td>
                <td className="px-4 py-2.5">
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1",
                      REQ_BADGE[label]
                    )}
                  >
                    {label}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-[11px] text-muted-foreground">
                  {condition || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Extraction overrides table ───────────────────────────────────────

function ExtractionOverridesTable({
  overrides,
  docTypeNameByKey,
  globalFields,
}: {
  overrides: ExtractionOverrideMap;
  docTypeNameByKey: Record<string, string>;
  globalFields: Record<
    string,
    Record<string, { required: boolean; min_confidence: number }>
  >;
}) {
  // Flatten the doc_type → field → overrides map into table rows. Compute
  // a short "vs global" delta string for each (required / min_confidence).
  const rows: Array<{
    docTypeKey: string;
    docTypeName: string;
    fieldKey: string;
    overrideDescription: string;
    overrideMinConfidence: number | null;
  }> = [];
  for (const [dtKey, fields] of Object.entries(overrides)) {
    const dtName = docTypeNameByKey[dtKey] ?? dtKey;
    for (const [fieldKey, ovr] of Object.entries(fields ?? {})) {
      const globalFor = globalFields[dtKey]?.[fieldKey];
      const parts: string[] = [];
      if (
        ovr.required !== undefined &&
        (!globalFor || ovr.required !== globalFor.required)
      ) {
        parts.push(
          `required: ${globalFor ? globalFor.required : "—"} → ${ovr.required}`
        );
      }
      if (
        ovr.min_confidence !== undefined &&
        (!globalFor || ovr.min_confidence !== globalFor.min_confidence)
      ) {
        parts.push(
          `min_confidence: ${
            globalFor ? globalFor.min_confidence.toFixed(2) : "—"
          } → ${ovr.min_confidence.toFixed(2)}`
        );
      }
      rows.push({
        docTypeKey: dtKey,
        docTypeName: dtName,
        fieldKey,
        overrideDescription: parts.length > 0 ? parts.join(" · ") : "no change",
        overrideMinConfidence: ovr.min_confidence ?? null,
      });
    }
  }

  if (rows.length === 0) {
    return (
      <div className="overflow-hidden rounded-xl border bg-card">
        <p className="px-4 py-6 text-center text-xs text-muted-foreground">
          No extraction overrides for this profile. Uses global thresholds.
        </p>
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-4 py-2.5 text-left">Document Type</th>
            <th className="px-4 py-2.5 text-left">Field</th>
            <th className="px-4 py-2.5 text-left">Override vs. Global</th>
            <th className="px-4 py-2.5 text-left">Min Confidence</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.docTypeKey}-${r.fieldKey}-${i}`} className="border-t">
              <td className="px-4 py-2.5 text-xs font-bold">{r.docTypeName}</td>
              <td className="px-4 py-2.5 font-mono text-xs">{r.fieldKey}</td>
              <td className="px-4 py-2.5">
                <span className="inline-block rounded bg-brand-orange/15 px-2 py-1 text-[10px] font-medium leading-tight text-[#7A5000] ring-1 ring-brand-orange/40">
                  {r.overrideDescription}
                </span>
              </td>
              <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">
                {r.overrideMinConfidence !== null
                  ? r.overrideMinConfidence.toFixed(2)
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Rule overrides table ─────────────────────────────────────────────

function RuleOverridesTable({
  overrides,
  orgRuleByName,
}: {
  overrides: RuleOverride[];
  orgRuleByName: Record<string, OrgValidationRuleRow>;
}) {
  if (overrides.length === 0) {
    return (
      <div className="overflow-hidden rounded-xl border bg-card">
        <p className="px-4 py-6 text-center text-xs text-muted-foreground">
          No rule overrides for this profile. Uses global thresholds.
        </p>
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-4 py-2.5 text-left">Rule</th>
            <th className="px-4 py-2.5 text-left">Global Threshold</th>
            <th className="px-4 py-2.5 text-left">Profile Override</th>
          </tr>
        </thead>
        <tbody>
          {overrides.map((r, i) => {
            // Match an org-level rule by case-insensitive name so we can
            // display the global baseline next to the override. Falls back
            // to "—" if the override introduces a brand-new rule.
            const global = orgRuleByName[r.rule.toLowerCase()];
            const changed = !global || global.condition !== r.condition;
            return (
              <tr key={`${r.rule}-${i}`} className="border-t">
                <td className="px-4 py-2.5 text-xs font-bold">{r.rule}</td>
                <td className="px-4 py-2.5 text-[11px] text-muted-foreground">
                  {global?.condition ?? "—"}
                </td>
                <td className="px-4 py-2.5">
                  {changed ? (
                    <span className="inline-block rounded bg-brand-orange/15 px-2 py-1 text-[10px] font-medium text-[#7A5000] ring-1 ring-brand-orange/40">
                      {r.condition}
                    </span>
                  ) : (
                    <span className="text-[11px] text-muted-foreground">
                      {r.condition}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
