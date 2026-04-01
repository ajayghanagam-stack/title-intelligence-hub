"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/hooks/use-org";
import { getPackage, getFlags } from "@/lib/title-search/api";
import { EntitySection } from "@/components/title-search/entity-section";
import { PropertySummaryGrid } from "@/components/title-search/property-summary-grid";
import { RiskSummaryCards } from "@/components/title-search/risk-summary-cards";
import { SourceCitations } from "@/components/title-search/source-citations";
import type { TSPackage, TSFlagList, PropertySummary } from "@/lib/title-search/types";
import {
  Home,
  Ruler,
  MapPin,
  Users,
  FileText,
  Landmark,
  AlertTriangle,
  DollarSign,
  Building2,
  Shield,
  Gavel,
  Hammer,
  Map,
  Scale,
  ListTodo,
  Phone,
  TrendingUp,
} from "lucide-react";

export default function ResultsDashboardPage() {
  const params = useParams();
  const orderId = params.orderId as string;
  const { currentOrgId } = useOrg();
  const [pkg, setPkg] = useState<TSPackage | null>(null);
  const [flagData, setFlagData] = useState<TSFlagList | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!currentOrgId || !orderId) return;
    Promise.all([
      getPackage(currentOrgId, orderId),
      getFlags(currentOrgId, orderId),
    ])
      .then(([p, f]) => {
        setPkg(p);
        setFlagData(f);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [currentOrgId, orderId]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading results...</p>
      </div>
    );
  }

  if (!pkg) {
    return (
      <p className="text-muted-foreground py-10 text-center">
        No results available yet.
      </p>
    );
  }

  const ps: PropertySummary = pkg.property_summary || {};

  const toItems = (obj: Record<string, unknown> | undefined) => {
    if (!obj) return [];
    return Object.entries(obj)
      .filter(([, v]) => v != null && v !== "" && !Array.isArray(v) && typeof v !== "object")
      .map(([k, v]) => ({
        label: k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
        value: v as string | number | boolean | null,
      }));
  };

  return (
    <div className="space-y-6" data-testid="results-dashboard">
      {/* Risk Summary */}
      {flagData && <RiskSummaryCards counts={flagData.counts} />}

      {/* Property Identification */}
      <EntitySection
        title="Property Identification"
        icon={<Home className="h-4 w-4" />}
        defaultOpen
      >
        <PropertySummaryGrid items={toItems(ps.property_identification as Record<string, unknown>)} />
      </EntitySection>

      {/* Physical Attributes */}
      {ps.physical_attributes ? (
        <EntitySection
          title="Physical Attributes"
          icon={<Ruler className="h-4 w-4" />}
        >
          <PropertySummaryGrid items={toItems(ps.physical_attributes as Record<string, unknown>)} />
        </EntitySection>
      ) : null}

      {/* Lot & Land */}
      {ps.lot_and_land ? (
        <EntitySection
          title="Lot & Land / Zoning"
          icon={<MapPin className="h-4 w-4" />}
        >
          <PropertySummaryGrid items={toItems(ps.lot_and_land as Record<string, unknown>)} />
        </EntitySection>
      ) : null}

      {/* Current Ownership */}
      {ps.current_ownership ? (
        <EntitySection
          title="Current Ownership"
          icon={<Users className="h-4 w-4" />}
          defaultOpen
        >
          <PropertySummaryGrid items={toItems(ps.current_ownership as Record<string, unknown>)} />
        </EntitySection>
      ) : null}

      {/* Chain of Title */}
      {ps.chain_of_title && (ps.chain_of_title as unknown[]).length > 0 && (
        <EntitySection
          title="Chain of Title"
          icon={<FileText className="h-4 w-4" />}
          badge={`${(ps.chain_of_title as unknown[]).length} entries`}
        >
          <div className="space-y-3">
            {(ps.chain_of_title as Array<Record<string, unknown>>).map((deed, i) => (
              <div key={i} className="rounded-lg border p-3 bg-amber-50/30 text-sm">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-semibold">{(deed.deed_type as string) || "Deed"}</span>
                  <span className="text-xs text-muted-foreground">{(deed.recording_date as string) || ""}</span>
                </div>
                <p className="text-muted-foreground">
                  {(deed.grantor as string) || "?"} → {(deed.grantee as string) || "?"}
                </p>
                {deed.consideration ? (
                  <p className="text-xs mt-1">Consideration: {deed.consideration as string}</p>
                ) : null}
                {deed.recording_ref ? (
                  <p className="text-xs text-muted-foreground">Ref: {deed.recording_ref as string}</p>
                ) : null}
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Mortgages */}
      {ps.mortgages && (ps.mortgages as unknown[]).length > 0 && (
        <EntitySection
          title="Mortgages"
          icon={<Landmark className="h-4 w-4" />}
          badge={`${(ps.mortgages as unknown[]).length}`}
        >
          <div className="space-y-3">
            {(ps.mortgages as Array<Record<string, unknown>>).map((m, i) => (
              <div key={i} className="rounded-lg border p-3 text-sm">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-semibold">{(m.lender as string) || "Unknown Lender"}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    m.status === "active" ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700"
                  }`}>
                    {(m.status as string) || "unknown"}
                  </span>
                </div>
                <p className="text-muted-foreground">
                  Amount: {(m.amount as string) || "N/A"} | Borrower: {(m.borrower as string) || "N/A"}
                </p>
                {m.recording_date ? (
                  <p className="text-xs text-muted-foreground mt-1">
                    Recorded: {m.recording_date as string} | Ref: {(m.recording_ref as string) || "N/A"}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Liens */}
      {ps.liens && (ps.liens as unknown[]).length > 0 && (
        <EntitySection
          title="Liens & Judgments"
          icon={<AlertTriangle className="h-4 w-4" />}
          badge={`${(ps.liens as unknown[]).length}`}
        >
          <div className="space-y-2">
            {(ps.liens as Array<Record<string, unknown>>).map((l, i) => (
              <div key={i} className="rounded-lg border border-red-200 p-3 bg-red-50/30 text-sm">
                <span className="font-semibold">{(l.lien_type as string) || "Lien"}</span>
                <span className="text-xs ml-2 text-muted-foreground">{(l.recording_date as string) || ""}</span>
                <p className="text-muted-foreground mt-1">
                  {(l.creditor as string) || "?"} — Amount: {(l.amount as string) || "N/A"}
                </p>
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Tax Status */}
      {ps.tax_status ? (
        <EntitySection
          title="Tax Status"
          icon={<DollarSign className="h-4 w-4" />}
        >
          <PropertySummaryGrid items={toItems(ps.tax_status as Record<string, unknown>)} />
        </EntitySection>
      ) : null}

      {/* HOA */}
      {ps.hoa && (ps.hoa as Record<string, unknown>).has_hoa ? (
        <EntitySection title="HOA / Subdivision" icon={<Building2 className="h-4 w-4" />}>
          <PropertySummaryGrid items={toItems(ps.hoa as Record<string, unknown>)} />
        </EntitySection>
      ) : null}

      {/* Easements */}
      {ps.easements && (ps.easements as unknown[]).length > 0 && (
        <EntitySection title="Easements" icon={<Shield className="h-4 w-4" />}>
          <div className="space-y-2">
            {(ps.easements as Array<Record<string, unknown>>).map((e, i) => (
              <div key={i} className="text-sm p-2 border-b last:border-0">
                <span className="font-medium">{(e.easement_type as string) || "Easement"}</span>
                {e.description ? <p className="text-muted-foreground text-xs">{e.description as string}</p> : null}
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Court Proceedings */}
      {ps.court_proceedings && (ps.court_proceedings as unknown[]).length > 0 && (
        <EntitySection title="Court Proceedings" icon={<Gavel className="h-4 w-4" />}>
          <div className="space-y-2">
            {(ps.court_proceedings as Array<Record<string, unknown>>).map((c, i) => (
              <div key={i} className="rounded-lg border border-red-200 p-3 bg-red-50/30 text-sm">
                <span className="font-semibold">{(c.case_type as string) || "Case"}</span>
                <span className="text-xs ml-2">#{(c.case_number as string) || "N/A"}</span>
                <p className="text-muted-foreground mt-1">Status: {(c.status as string) || "N/A"}</p>
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Permits */}
      {ps.permits && (ps.permits as unknown[]).length > 0 && (
        <EntitySection title="Permits / Code Enforcement" icon={<Hammer className="h-4 w-4" />}>
          <div className="space-y-2">
            {(ps.permits as Array<Record<string, unknown>>).map((p, i) => (
              <div key={i} className="text-sm p-2 border-b last:border-0">
                <span className="font-medium">{(p.permit_type as string) || "Permit"} #{(p.permit_number as string) || ""}</span>
                <span className={`text-xs ml-2 ${(p.status as string) === "violation" ? "text-red-600" : "text-muted-foreground"}`}>
                  {(p.status as string) || ""}
                </span>
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Survey & Plat */}
      {ps.survey_plat && (ps.survey_plat as Record<string, unknown>).has_survey ? (
        <EntitySection title="Survey & Plat" icon={<Map className="h-4 w-4" />}>
          <PropertySummaryGrid items={toItems(ps.survey_plat as Record<string, unknown>)} />
        </EntitySection>
      ) : null}

      {/* Title Opinion */}
      {ps.title_opinion_items && ps.title_opinion_items.length > 0 && (
        <EntitySection
          title="Title Opinion Summary"
          icon={<Scale className="h-4 w-4" />}
          badge={`${ps.title_opinion_items.length} items`}
          defaultOpen
        >
          <div className="space-y-2">
            {ps.title_opinion_items.map((item, i) => (
              <div key={i} className={`rounded-lg border p-3 text-sm ${
                item.severity === "critical" ? "border-red-300 bg-red-50/50" :
                item.severity === "high" ? "border-amber-300 bg-amber-50/50" :
                "border-gray-200"
              }`}>
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${
                    item.severity === "critical" ? "bg-red-500" :
                    item.severity === "high" ? "bg-amber-500" :
                    item.severity === "medium" ? "bg-yellow-500" : "bg-blue-500"
                  }`} />
                  <span className="font-medium">{item.item}</span>
                  <span className="text-xs text-muted-foreground ml-auto">{item.status}</span>
                </div>
                {item.recommendation && (
                  <p className="text-xs text-muted-foreground mt-1 ml-4">
                    {item.recommendation}
                  </p>
                )}
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Next Steps */}
      {ps.next_steps && ps.next_steps.length > 0 && (
        <EntitySection
          title="Next Steps / Action Items"
          icon={<ListTodo className="h-4 w-4" />}
          defaultOpen
        >
          <div className="space-y-2">
            {ps.next_steps.map((ns, i) => (
              <div key={i} className="flex items-start gap-3 p-2 rounded-lg hover:bg-muted/50 text-sm">
                <span className={`shrink-0 mt-0.5 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                  ns.priority === "high" ? "bg-red-100 text-red-700" :
                  ns.priority === "medium" ? "bg-amber-100 text-amber-700" :
                  "bg-blue-100 text-blue-700"
                }`}>
                  {ns.priority}
                </span>
                <div>
                  <p className="font-medium">{ns.action}</p>
                  {ns.notes && <p className="text-xs text-muted-foreground mt-0.5">{ns.notes}</p>}
                </div>
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Key Contacts */}
      {ps.key_contacts && ps.key_contacts.length > 0 && (
        <EntitySection title="Key Contacts" icon={<Phone className="h-4 w-4" />}>
          <div className="space-y-2">
            {ps.key_contacts.map((c, i) => (
              <div key={i} className="text-sm p-2 border-b last:border-0">
                <span className="font-medium">{c.name}</span>
                {c.role && <span className="text-muted-foreground ml-2">({c.role})</span>}
                {c.phone && <span className="ml-3 text-xs text-muted-foreground">{c.phone}</span>}
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Comparable Sales */}
      {ps.comparable_sales && (ps.comparable_sales as unknown[]).length > 0 && (
        <EntitySection title="Comparable Sales" icon={<TrendingUp className="h-4 w-4" />}>
          <div className="space-y-2">
            {(ps.comparable_sales as Array<Record<string, unknown>>).map((comp, i) => (
              <div key={i} className="text-sm p-2 border-b last:border-0 flex justify-between">
                <span>{(comp.address as string) || "N/A"}</span>
                <span className="font-medium">{(comp.sale_price as string) || "N/A"}</span>
              </div>
            ))}
          </div>
        </EntitySection>
      )}

      {/* Source Citations */}
      {ps.search_summary?.sources_searched && ps.search_summary.sources_searched.length > 0 && (
        <SourceCitations
          citations={ps.search_summary.sources_searched.map((s) => ({
            url: s,
            title: s,
          }))}
        />
      )}
    </div>
  );
}
