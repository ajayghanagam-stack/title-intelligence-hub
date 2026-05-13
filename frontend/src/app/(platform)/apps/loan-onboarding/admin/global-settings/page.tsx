"use client";

// Global Settings — prototype-faithful surface.
//
// 1:1 port of prototype/src/app/logik-intake/admin/global-settings/page.tsx.
// Section titles, labels, descriptions, defaults, options, and ordering are
// stored in the JSONB columns on lo_global_settings (see
// backend/scripts/lo_prototype_data.build_default_global_settings). The
// frontend is a generic renderer keyed by `type` on each setting — so when
// new settings are added on the backend, they show up here without code
// changes (provided the type is one of the known kinds).
//
// PATCH semantics: Save Changes sends only the currently-visible tab's
// section column. Untouched sections are left alone server-side.

import { useEffect, useState } from "react";
import {
  Bell,
  Brain,
  Building2,
  FileBadge,
  Info,
  Lock,
  Plug,
  Save,
  Shield,
  Target,
  Users,
  X,
} from "lucide-react";

import { AdminHeader } from "@/components/loan-onboarding/logik-intake/admin-header";
import { useOrg } from "@/hooks/use-org";
import { cn } from "@/lib/utils";

// ── Type shapes (mirror backend JSONB) ───────────────────────────────────
type SettingType =
  | "percent"
  | "percent_range"
  | "hours"
  | "toggle"
  | "select"
  | "readonly_badge"
  | "text";

type SettingEntry = {
  key: string;
  label: string;
  description?: string;
  type: SettingType;
  value?: string | number | boolean;
  min?: number;
  max?: number;
  options?: string[];
  /** Optional trailing text rendered after the percent input (e.g.
   *  "% (fixed = Review Band lower bound)"). When present, replaces the
   *  default trailing "%" for `percent` entries. */
  suffix?: string;
};

type SettingsGroup = {
  title: string;
  settings: SettingEntry[];
};

type AiThresholdsBlock = { sections: SettingsGroup[] };

type RoleItem = { role: string; description: string; permissions: string };
type RolesBlock = { title: string; items: RoleItem[] };

type NotificationItem = {
  event: string;
  threshold: string;
  channel: string;
  /** Optional — kept for backward compatibility with older seed rows
   *  that still carry a per-event description. The HTML prototype shows
   *  only the threshold, so the renderer ignores this field if absent. */
  description?: string;
};
type NotificationsBlock = { title: string; items: NotificationItem[] };

type IntegrationItem = {
  system: string;
  description: string;
  status: string;
  status_color?: "emerald" | "teal" | "muted";
};
type IntegrationsBlock = { title: string; items: IntegrationItem[] };

type TenantBlock = SettingsGroup & { tenant_slug?: string };

type GlobalSettings = {
  id: string;
  ai_thresholds: AiThresholdsBlock;
  stp_targets: SettingsGroup;
  exception_defaults: SettingsGroup;
  audit: SettingsGroup;
  roles: RolesBlock;
  notifications: NotificationsBlock;
  integrations: IntegrationsBlock;
  tenant: TenantBlock;
};

const TABS = [
  { key: "ai", label: "AI Thresholds", Icon: Brain },
  { key: "stp", label: "STP Targets", Icon: Target },
  { key: "exception", label: "Exception Defaults", Icon: Shield },
  { key: "audit", label: "Audit & Compliance", Icon: FileBadge },
  { key: "roles", label: "User Roles", Icon: Users },
  { key: "notify", label: "Notifications", Icon: Bell },
  { key: "integrations", label: "Integrations", Icon: Plug },
  { key: "tenant", label: "Tenant Settings", Icon: Building2 },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const ENDPOINT = "/api/v1/apps/loan-onboarding/admin/config/global-settings";

export default function GlobalSettingsAdminPage() {
  const { orgFetch, currentOrgId } = useOrg();
  const [tab, setTab] = useState<TabKey>("ai");
  const [settings, setSettings] = useState<GlobalSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!currentOrgId) return;
    let cancelled = false;
    setLoading(true);
    orgFetch<GlobalSettings>(ENDPOINT)
      .then((data) => {
        if (!cancelled) {
          setSettings(data);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled)
          setError(e?.message ?? "Failed to load global settings");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentOrgId, orgFetch]);

  async function handleSave() {
    if (!settings) return;
    const patch: Partial<GlobalSettings> = {};
    if (tab === "ai") patch.ai_thresholds = settings.ai_thresholds;
    if (tab === "stp") patch.stp_targets = settings.stp_targets;
    if (tab === "exception")
      patch.exception_defaults = settings.exception_defaults;
    if (tab === "audit") patch.audit = settings.audit;
    if (tab === "roles") patch.roles = settings.roles;
    if (tab === "notify") patch.notifications = settings.notifications;
    if (tab === "integrations") patch.integrations = settings.integrations;
    if (tab === "tenant") patch.tenant = settings.tenant;

    setSaving(true);
    setSaveMessage(null);
    try {
      const updated = await orgFetch<GlobalSettings>(ENDPOINT, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setSettings(updated);
      setSaveMessage("Saved.");
    } catch (e) {
      const msg = (e as Error)?.message ?? "Save failed";
      setSaveMessage(`Save failed: ${msg}`);
    } finally {
      setSaving(false);
      window.setTimeout(() => setSaveMessage(null), 3500);
    }
  }

  // updateSettingValue patches a single entry within a SettingsGroup by key.
  function patchGroup(
    group: SettingsGroup,
    key: string,
    updates: Partial<SettingEntry>,
  ): SettingsGroup {
    return {
      ...group,
      settings: group.settings.map((s) =>
        s.key === key ? { ...s, ...updates } : s,
      ),
    };
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-2 py-2">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <AdminHeader
          title="Global Settings"
          subtitle="System-wide configuration. Applies to all files and all profiles unless overridden at profile level."
        />
        <button
          type="button"
          onClick={handleSave}
          disabled={!settings || saving}
          className="inline-flex items-center gap-1 rounded-md bg-brand-purple px-3 py-2 text-xs font-bold uppercase tracking-wider text-white hover:opacity-90 disabled:opacity-50"
        >
          <Save className="h-3.5 w-3.5" />
          {saving ? "Saving…" : "Save Changes"}
        </button>
      </div>

      {(saveMessage || error) && (
        <div className="flex items-start gap-2 rounded-md border border-brand-orange/40 bg-brand-orange/10 px-3 py-2 text-[11px] text-[#7A5000]">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {error ?? saveMessage}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
        <aside className="card-warm p-2">
          {TABS.map((t) => {
            const active = t.key === tab;
            const Icon = t.Icon;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs transition",
                  active
                    ? "bg-brand-purple/10 font-bold text-brand-purple"
                    : "text-muted-foreground hover:bg-muted",
                )}
              >
                <Icon className="h-3.5 w-3.5 opacity-80" />
                {t.label}
              </button>
            );
          })}
        </aside>

        <section className="card-warm p-5">
          {loading || !settings ? (
            <div className="text-sm text-muted-foreground">Loading…</div>
          ) : (
            <>
              {tab === "ai" &&
                settings.ai_thresholds.sections.map((section, sectionIdx) => (
                  <SettingsGroupBlock
                    key={section.title}
                    group={section}
                    addDividerAfter={
                      sectionIdx <
                      settings.ai_thresholds.sections.length - 1
                    }
                    onChange={(patched) => {
                      const next = [...settings.ai_thresholds.sections];
                      next[sectionIdx] = patched;
                      setSettings({
                        ...settings,
                        ai_thresholds: { sections: next },
                      });
                    }}
                  />
                ))}

              {tab === "stp" && (
                <SettingsGroupBlock
                  group={settings.stp_targets}
                  onChange={(g) =>
                    setSettings({ ...settings, stp_targets: g })
                  }
                />
              )}

              {tab === "exception" && (
                <SettingsGroupBlock
                  group={settings.exception_defaults}
                  onChange={(g) =>
                    setSettings({ ...settings, exception_defaults: g })
                  }
                />
              )}

              {tab === "audit" && (
                <SettingsGroupBlock
                  group={settings.audit}
                  onChange={(g) => setSettings({ ...settings, audit: g })}
                />
              )}

              {tab === "roles" && <RolesPanel block={settings.roles} />}

              {tab === "notify" && (
                <NotificationsPanel block={settings.notifications} />
              )}

              {tab === "integrations" && (
                <IntegrationsPanel
                  block={settings.integrations}
                  onChange={(next) =>
                    setSettings({ ...settings, integrations: next })
                  }
                />
              )}

              {tab === "tenant" && (
                <SettingsGroupBlock
                  group={settings.tenant}
                  onChange={(g) =>
                    setSettings({
                      ...settings,
                      tenant: { ...settings.tenant, ...g },
                    })
                  }
                />
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );

  // ── Inner renderers ──────────────────────────────────────────────────

  function SettingsGroupBlock({
    group,
    onChange,
    addDividerAfter = false,
  }: {
    group: SettingsGroup;
    onChange: (next: SettingsGroup) => void;
    addDividerAfter?: boolean;
  }) {
    return (
      <>
        <SectionHeading>{group.title}</SectionHeading>
        {group.settings.map((entry) => (
          <SettingRow
            key={entry.key}
            label={entry.label}
            description={entry.description}
          >
            <SettingControl
              entry={entry}
              onChange={(updates) =>
                onChange(patchGroup(group, entry.key, updates))
              }
            />
          </SettingRow>
        ))}
        {addDividerAfter && <div className="my-5 border-t" />}
      </>
    );
  }
}

// ── Section heading + row ────────────────────────────────────────────────

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
      {children}
    </p>
  );
}

function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 border-t py-3 first:border-t-0 first:pt-0">
      <div className="flex-1 min-w-[260px]">
        <p className="text-sm font-bold tracking-tight">{label}</p>
        {description && (
          <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

// ── Generic control dispatcher ───────────────────────────────────────────

function SettingControl({
  entry,
  onChange,
}: {
  entry: SettingEntry;
  onChange: (updates: Partial<SettingEntry>) => void;
}) {
  switch (entry.type) {
    case "percent":
      return (
        <>
          <NumInput
            value={String(entry.value ?? "")}
            onChange={(v) => onChange({ value: Number(v) })}
          />
          <span className="text-xs text-muted-foreground">
            {entry.suffix ?? "%"}
          </span>
        </>
      );
    case "percent_range":
      return (
        <>
          <NumInput
            value={String(entry.min ?? "")}
            w={60}
            onChange={(v) => onChange({ min: Number(v) })}
          />
          <span className="text-xs text-muted-foreground">% to</span>
          <NumInput
            value={String(entry.max ?? "")}
            w={60}
            onChange={(v) => onChange({ max: Number(v) })}
          />
          <span className="text-xs text-muted-foreground">%</span>
        </>
      );
    case "hours":
      return (
        <>
          <NumInput
            value={String(entry.value ?? "")}
            onChange={(v) => onChange({ value: Number(v) })}
          />
          <span className="text-xs text-muted-foreground">hours</span>
        </>
      );
    case "toggle":
      return (
        <Toggle
          on={Boolean(entry.value)}
          onChange={(v) => onChange({ value: v })}
        />
      );
    case "select":
      return (
        <Select
          options={entry.options ?? []}
          value={String(entry.value ?? "")}
          onChange={(v) => onChange({ value: v })}
        />
      );
    case "readonly_badge":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-700 ring-1 ring-emerald-200">
          <Lock className="h-2.5 w-2.5" />
          {String(entry.value ?? "")}
        </span>
      );
    case "text":
      return (
        <input
          value={String(entry.value ?? "")}
          onChange={(e) => onChange({ value: e.target.value })}
          className="w-72 rounded-md border bg-card px-2 py-1 text-xs focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
        />
      );
    default:
      return null;
  }
}

// ── Basic form primitives (prototype look-alikes) ────────────────────────

function NumInput({
  value,
  w = 70,
  onChange,
}: {
  value: string;
  w?: number;
  onChange: (v: string) => void;
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{ width: w }}
      className="rounded-md border bg-card px-2 py-1 text-center text-xs focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
    />
  );
}

function Toggle({
  on,
  onChange,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!on)}
      className={cn(
        "relative h-5 w-9 rounded-full transition",
        on ? "bg-brand-teal" : "bg-muted",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition",
          on ? "left-[18px]" : "left-0.5",
        )}
      />
    </button>
  );
}

function Select({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border bg-card px-2 py-1 text-xs focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
    >
      {options.map((o) => (
        <option key={o}>{o}</option>
      ))}
    </select>
  );
}

// ── List-shaped panels (Roles, Notifications, Integrations) ──────────────

function RolesPanel({ block }: { block: RolesBlock }) {
  return (
    <>
      <SectionHeading>{block.title}</SectionHeading>
      {block.items.map((r) => (
        <div
          key={r.role}
          className="flex flex-wrap items-start gap-4 border-t py-3 first:border-t-0 first:pt-0"
        >
          <div className="flex-1 min-w-[260px]">
            <p className="text-sm font-bold tracking-tight">{r.role}</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
              {r.description}
            </p>
            <span className="mt-1 inline-block rounded-full bg-muted px-2 py-0.5 text-[9px] font-medium text-muted-foreground">
              {r.permissions}
            </span>
          </div>
          <button
            type="button"
            className="rounded-md border bg-card px-2.5 py-1 text-[11px] font-medium hover:bg-muted"
          >
            Edit
          </button>
        </div>
      ))}
    </>
  );
}

function NotificationsPanel({ block }: { block: NotificationsBlock }) {
  return (
    <>
      <SectionHeading>{block.title}</SectionHeading>
      {block.items.map((e) => (
        <SettingRow
          key={e.event}
          label={e.event}
          description={
            <>
              Threshold: <strong>{e.threshold}</strong>
            </>
          }
        >
          <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            {e.channel}
          </span>
          <button
            type="button"
            className="rounded-md border bg-card px-2.5 py-1 text-[11px] font-medium hover:bg-muted"
          >
            Edit
          </button>
        </SettingRow>
      ))}
    </>
  );
}

function IntegrationsPanel({
  block,
  onChange,
}: {
  block: IntegrationsBlock;
  onChange: (next: IntegrationsBlock) => void;
}) {
  const statusCls: Record<string, string> = {
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    teal: "bg-brand-teal/10 text-brand-teal ring-brand-teal/30",
    muted: "bg-muted text-muted-foreground ring-border",
  };
  const [editingIdx, setEditingIdx] = useState<number | null>(null);

  return (
    <>
      <SectionHeading>{block.title}</SectionHeading>
      {block.items.map((s, idx) => (
        <SettingRow key={s.system} label={s.system} description={s.description}>
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1",
              statusCls[s.status_color ?? "muted"],
            )}
          >
            {s.status}
          </span>
          <button
            type="button"
            onClick={() => setEditingIdx(idx)}
            className="rounded-md border bg-card px-2.5 py-1 text-[11px] font-medium hover:bg-muted"
          >
            Configure
          </button>
        </SettingRow>
      ))}

      {editingIdx !== null && (
        <IntegrationConfigureModal
          item={block.items[editingIdx]}
          onClose={() => setEditingIdx(null)}
          onSave={(patched) => {
            const nextItems = block.items.map((it, i) =>
              i === editingIdx ? patched : it,
            );
            onChange({ ...block, items: nextItems });
            setEditingIdx(null);
          }}
        />
      )}
    </>
  );
}

function IntegrationConfigureModal({
  item,
  onClose,
  onSave,
}: {
  item: IntegrationItem;
  onClose: () => void;
  onSave: (next: IntegrationItem) => void;
}) {
  const [status, setStatus] = useState(item.status);
  const [statusColor, setStatusColor] = useState<
    NonNullable<IntegrationItem["status_color"]>
  >(item.status_color ?? "muted");

  const STATUS_PRESETS: Array<{
    label: string;
    color: NonNullable<IntegrationItem["status_color"]>;
  }> = [
    { label: "Connected", color: "emerald" },
    { label: "Active", color: "teal" },
    { label: "Pending", color: "teal" },
    { label: "Not Connected", color: "muted" },
    { label: "Disconnected", color: "muted" },
  ];

  function submit(e: React.FormEvent) {
    e.preventDefault();
    onSave({
      ...item,
      status: status.trim() || item.status,
      status_color: statusColor,
    });
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
            Configure {item.system}
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
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            {item.description}
          </p>
          <label className="block">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Status Label
            </span>
            <input
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="mt-1 h-9 w-full rounded-md border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {STATUS_PRESETS.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => {
                    setStatus(p.label);
                    setStatusColor(p.color);
                  }}
                  className="rounded-full border bg-card px-2 py-0.5 text-[10px] font-medium hover:bg-muted"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </label>
          <label className="block">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Status Color
            </span>
            <select
              value={statusColor}
              onChange={(e) =>
                setStatusColor(
                  e.target.value as NonNullable<IntegrationItem["status_color"]>,
                )
              }
              className="mt-1 h-9 w-full rounded-md border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            >
              <option value="emerald">Green (Connected)</option>
              <option value="teal">Teal (Active / Pending)</option>
              <option value="muted">Grey (Inactive)</option>
            </select>
          </label>
          <p className="rounded-md border border-brand-orange/30 bg-brand-orange/5 px-3 py-2 text-[11px] text-[#7A5000]">
            Click <strong>Save Changes</strong> on the main page to persist.
          </p>
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
              className="rounded-md bg-brand-purple px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-white hover:opacity-90"
            >
              Apply
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
