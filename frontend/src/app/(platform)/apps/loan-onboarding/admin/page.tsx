"use client";

// Phase 5.3 — LogikIntake Configuration Hub.
//
// Faithful port of the prototype hub: 4 colored-border cards + a 5th
// global-settings row. Counts and status badges are driven off the
// admin config endpoints rather than fixture data.

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  FileText,
  FormInput,
  Layers,
  Lightbulb,
  Settings2,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { cn } from "@/lib/utils";

type Accent = "teal" | "purple" | "orange";

interface HubCard {
  href: string;
  step: number;
  title: string;
  description: string;
  count: number;
  countLabel: string;
  status: "complete" | "pending";
  statusLabel: string;
  Icon: LucideIcon;
  accent: Accent;
}

const ACCENT_BORDER: Record<Accent, string> = {
  teal: "border-t-brand-teal",
  purple: "border-t-brand-purple",
  orange: "border-t-brand-orange",
};
const ACCENT_TEXT: Record<Accent, string> = {
  teal: "text-brand-teal",
  purple: "text-brand-purple",
  orange: "text-[#7A5000]",
};

type Counts = {
  docTypes: number;
  schemasWithFields: number;
  rulesTotal: number;
  rulesActive: number;
  profiles: number;
};

const INITIAL: Counts = {
  docTypes: 0,
  schemasWithFields: 0,
  rulesTotal: 0,
  rulesActive: 0,
  profiles: 0,
};

export default function ConfigurationHubPage() {
  const { orgPath } = useOrgSlug();
  const { orgFetch, currentOrgId } = useOrg();
  const [counts, setCounts] = useState<Counts>(INITIAL);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!currentOrgId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      orgFetch<{ active: boolean }[]>(
        "/api/v1/apps/loan-onboarding/admin/config/doc-types"
      ),
      orgFetch<{ fields: unknown[] }[]>(
        "/api/v1/apps/loan-onboarding/admin/config/extraction-schemas"
      ),
      orgFetch<{ active: boolean }[]>(
        "/api/v1/apps/loan-onboarding/admin/config/validation-rules"
      ),
      orgFetch<{ active: boolean }[]>(
        "/api/v1/apps/loan-onboarding/admin/config/profiles"
      ),
    ])
      .then(([dts, schemas, rules, profiles]) => {
        if (cancelled) return;
        setCounts({
          docTypes: dts.length,
          schemasWithFields: schemas.filter(
            (s) => s.fields && s.fields.length > 0
          ).length,
          rulesTotal: rules.length,
          rulesActive: rules.filter((r) => r.active).length,
          profiles: profiles.length,
        });
      })
      .catch(() => {
        /* leave counts at zero; cards render Pending */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentOrgId, orgFetch]);

  const schemasPending = Math.max(
    0,
    counts.docTypes - counts.schemasWithFields
  );

  const cards: HubCard[] = [
    {
      href: orgPath("/apps/loan-onboarding/admin/document-types"),
      step: 1,
      title: "Document Types",
      description:
        "Define every document type the system will recognize. Classification targets for the AI engine.",
      count: counts.docTypes,
      countLabel: "types",
      status: counts.docTypes > 0 ? "complete" : "pending",
      statusLabel: counts.docTypes > 0 ? "Complete" : "Empty",
      Icon: FileText,
      accent: "teal",
    },
    {
      href: orgPath("/apps/loan-onboarding/admin/extraction-schemas"),
      step: 2,
      title: "Extraction Schemas",
      description:
        "Per document type — define fields to extract, data format, and confidence thresholds.",
      count: counts.schemasWithFields,
      countLabel: counts.docTypes > 0 ? `of ${counts.docTypes}` : "schemas",
      status: schemasPending === 0 && counts.docTypes > 0 ? "complete" : "pending",
      statusLabel:
        schemasPending > 0
          ? `${schemasPending} pending`
          : counts.docTypes === 0
            ? "Empty"
            : "Complete",
      Icon: FormInput,
      accent: "purple",
    },
    {
      href: orgPath("/apps/loan-onboarding/admin/validation-rules"),
      step: 3,
      title: "Validation Rules",
      description:
        "Global rule library for document-level and cross-document data checks. Profiles can override thresholds.",
      count: counts.rulesTotal,
      countLabel: "rules",
      status: counts.rulesTotal > 0 ? "complete" : "pending",
      statusLabel: counts.rulesTotal > 0 ? "Complete" : "Empty",
      Icon: ShieldCheck,
      accent: "orange",
    },
    {
      href: orgPath("/apps/loan-onboarding/admin/program-profiles"),
      step: 4,
      title: "Program Profiles",
      description:
        "Loan programs and investor overlays — each defines its own doc checklist, extraction overrides, and rule thresholds. Profiles stack.",
      count: counts.profiles,
      countLabel: "profiles",
      status: counts.profiles > 0 ? "complete" : "pending",
      statusLabel: counts.profiles > 0 ? "Complete" : "Empty",
      Icon: Layers,
      accent: "teal",
    },
  ];

  return (
    <div className="mx-auto max-w-7xl px-2 py-2">
      <header className="mb-5">
        <h1 className="text-xl font-bold tracking-tight">Configuration Hub</h1>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          One-time setup. Complete these areas in sequence and LogikIntake runs
          automatically for every loan file.
        </p>
      </header>

      <div className="mb-6 flex items-start gap-3 rounded-xl border border-brand-teal/30 bg-brand-teal/5 px-4 py-3 text-xs text-foreground">
        <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-brand-teal" />
        <p>
          <strong>Setup once, run forever.</strong> Global settings apply
          system-wide. Program Profiles let you define different rules per loan
          program and investor overlay.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {cards.map((c) => {
          const Icon = c.Icon;
          return (
            <Link
              key={c.href}
              href={c.href}
              className={cn(
                "group rounded-xl border border-t-4 bg-card p-5 transition hover:shadow-md",
                ACCENT_BORDER[c.accent]
              )}
            >
              <Icon className={cn("h-7 w-7", ACCENT_TEXT[c.accent])} />
              <h3 className="mt-3 text-base font-bold tracking-tight">
                {c.step}. {c.title}
              </h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                {c.description}
              </p>
              <div className="mt-4 flex items-end gap-2">
                <span
                  className={cn(
                    "font-mono text-2xl font-bold tabular-nums leading-none",
                    ACCENT_TEXT[c.accent]
                  )}
                >
                  {loading ? "…" : c.count}
                </span>
                <span className="mb-0.5 text-[11px] text-muted-foreground">
                  {c.countLabel}
                </span>
                <span
                  className={cn(
                    "ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                    c.status === "complete"
                      ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                      : "bg-brand-orange/15 text-[#7A5000] ring-1 ring-brand-orange/40"
                  )}
                >
                  {c.status === "complete" ? (
                    <CheckCircle2 className="h-2.5 w-2.5" />
                  ) : (
                    <Clock className="h-2.5 w-2.5" />
                  )}
                  {c.statusLabel}
                </span>
              </div>
            </Link>
          );
        })}
      </div>

      <Link
        href={orgPath("/apps/loan-onboarding/admin/global-settings")}
        className="mt-4 flex items-center gap-3 rounded-xl border border-t-4 border-t-brand-purple bg-card p-4 transition hover:shadow-md"
      >
        <Settings2 className="h-6 w-6 text-brand-purple" />
        <div className="flex-1">
          <p className="text-sm font-bold tracking-tight">5. Global Settings</p>
          <p className="text-xs text-muted-foreground">
            AI thresholds · STP targets · Audit retention · User roles ·
            Notifications · Integrations · Tenant settings
          </p>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-700 ring-1 ring-emerald-200">
          <CheckCircle2 className="h-2.5 w-2.5" />
          Configured
        </span>
        <span className="inline-flex items-center gap-1 rounded-md bg-brand-purple px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-white">
          Open
          <ArrowRight className="h-3 w-3" />
        </span>
      </Link>
    </div>
  );
}
