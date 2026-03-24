"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/input";
import { useOrg } from "@/hooks/use-org";
import { createOrder, processOrder } from "@/lib/title-search/api";
import { ArrowRight } from "lucide-react";

const US_STATES = [
  "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
  "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
  "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
  "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
  "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
];

export default function NewOrderPage() {
  const router = useRouter();
  const { currentOrgId } = useOrg();
  const [form, setForm] = useState({
    property_address: "",
    county: "",
    state_code: "",
    parcel_number: "",
    search_scope: "full",
    search_years: 60,
  });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!form.property_address || !form.county || !form.state_code || !currentOrgId) return;

    setCreating(true);
    setError(null);
    try {
      const order = await createOrder(currentOrgId, {
        ...form,
        parcel_number: form.parcel_number || undefined,
      });
      await processOrder(currentOrgId, order.id);
      router.push(`/apps/title-search/orders/${order.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create order");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Create New Search Order</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Enter property details to initiate a title search
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="section-card space-y-6">
        <div className="space-y-2">
          <label htmlFor="ts-property-address" className="text-sm font-semibold">Property Address *</label>
          <Input
            id="ts-property-address"
            value={form.property_address}
            onChange={(e) => setForm({ ...form, property_address: e.target.value })}
            placeholder="123 Main St, Springfield, IL 62701"
            className="h-11"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label htmlFor="ts-county" className="text-sm font-semibold">County *</label>
            <Input
              id="ts-county"
              value={form.county}
              onChange={(e) => setForm({ ...form, county: e.target.value })}
              placeholder="Sangamon"
              className="h-11"
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="ts-state" className="text-sm font-semibold">State *</label>
            <select
              id="ts-state"
              value={form.state_code}
              onChange={(e) => setForm({ ...form, state_code: e.target.value })}
              className="h-11 w-full rounded-md border border-input bg-background px-3"
            >
              <option value="">Select state</option>
              {US_STATES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="space-y-2">
          <label htmlFor="ts-parcel" className="text-sm font-semibold">Parcel Number (optional)</label>
          <Input
            id="ts-parcel"
            value={form.parcel_number}
            onChange={(e) => setForm({ ...form, parcel_number: e.target.value })}
            placeholder="12-34-567-890"
            className="h-11"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label htmlFor="ts-scope" className="text-sm font-semibold">Search Scope</label>
            <select
              id="ts-scope"
              value={form.search_scope}
              onChange={(e) => setForm({ ...form, search_scope: e.target.value })}
              className="h-11 w-full rounded-md border border-input bg-background px-3"
            >
              <option value="full">Full Search</option>
              <option value="current_owner">Current Owner</option>
              <option value="limited">Limited</option>
            </select>
          </div>
          <div className="space-y-2">
            <label htmlFor="ts-years" className="text-sm font-semibold">Search Years</label>
            <Input
              id="ts-years"
              type="number"
              value={form.search_years}
              onChange={(e) => setForm({ ...form, search_years: parseInt(e.target.value) || 60 })}
              min={1}
              max={200}
              className="h-11"
            />
          </div>
        </div>

        <button
          onClick={handleCreate}
          disabled={!form.property_address || !form.county || !form.state_code || creating}
          className="w-full btn-cta gap-2 py-3"
        >
          {creating ? "Creating order..." : (
            <>
              Create & Process Order
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
      </div>
    </div>
  );
}
