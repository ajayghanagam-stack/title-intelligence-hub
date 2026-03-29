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
    city: "",
    zip_code: "",
    county: "",
    state_code: "",
    borrower_name: "",
    parcel_number: "",
    search_scope: "full",
    search_years: 60,
    order_reference: "",
    effective_date: new Date().toISOString().split("T")[0],
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
        city: form.city || undefined,
        zip_code: form.zip_code || undefined,
        borrower_name: form.borrower_name || undefined,
        parcel_number: form.parcel_number || undefined,
        order_reference: form.order_reference || undefined,
        effective_date: form.effective_date || undefined,
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
    <div className="mx-auto max-w-2xl space-y-8" data-testid="new-order-page">
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

      {/* Property Information */}
      <div className="section-card space-y-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Property Information</h2>

        <div className="space-y-2">
          <label htmlFor="ts-borrower" className="text-sm font-semibold">Borrower / Current Owner</label>
          <Input
            id="ts-borrower"
            value={form.borrower_name}
            onChange={(e) => setForm({ ...form, borrower_name: e.target.value })}
            placeholder="Jane Doe"
            className="h-11"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="ts-property-address" className="text-sm font-semibold">Property Address *</label>
          <Input
            id="ts-property-address"
            value={form.property_address}
            onChange={(e) => setForm({ ...form, property_address: e.target.value })}
            placeholder="4471 Sherman Hills Pkwy"
            className="h-11"
          />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-2">
            <label htmlFor="ts-city" className="text-sm font-semibold">City / Municipality</label>
            <Input
              id="ts-city"
              value={form.city}
              onChange={(e) => setForm({ ...form, city: e.target.value })}
              placeholder="Jacksonville"
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
          <div className="space-y-2">
            <label htmlFor="ts-zip" className="text-sm font-semibold">ZIP Code</label>
            <Input
              id="ts-zip"
              value={form.zip_code}
              onChange={(e) => setForm({ ...form, zip_code: e.target.value })}
              placeholder="32210"
              className="h-11"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label htmlFor="ts-county" className="text-sm font-semibold">County *</label>
            <Input
              id="ts-county"
              value={form.county}
              onChange={(e) => setForm({ ...form, county: e.target.value })}
              placeholder="Duval"
              className="h-11"
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="ts-parcel" className="text-sm font-semibold">Parcel Number</label>
            <Input
              id="ts-parcel"
              value={form.parcel_number}
              onChange={(e) => setForm({ ...form, parcel_number: e.target.value })}
              placeholder="012875-1145"
              className="h-11"
            />
          </div>
        </div>
      </div>

      {/* Search Parameters */}
      <div className="section-card space-y-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Search Parameters</h2>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label htmlFor="ts-scope" className="text-sm font-semibold">Product Type</label>
            <select
              id="ts-scope"
              value={form.search_scope}
              onChange={(e) => setForm({ ...form, search_scope: e.target.value })}
              className="h-11 w-full rounded-md border border-input bg-background px-3"
            >
              <option value="full">Full Search</option>
              <option value="current_owner">Current Owner Search</option>
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

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label htmlFor="ts-effective-date" className="text-sm font-semibold">Effective Date</label>
            <Input
              id="ts-effective-date"
              type="date"
              value={form.effective_date}
              onChange={(e) => setForm({ ...form, effective_date: e.target.value })}
              className="h-11"
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="ts-order-ref" className="text-sm font-semibold">Order / Loan #</label>
            <Input
              id="ts-order-ref"
              value={form.order_reference}
              onChange={(e) => setForm({ ...form, order_reference: e.target.value })}
              placeholder="Client reference number"
              className="h-11"
            />
          </div>
        </div>
      </div>

      {/* Submit */}
      <div className="section-card">
        <button
          onClick={handleCreate}
          disabled={!form.property_address || !form.county || !form.state_code || creating}
          className="w-full btn-cta gap-2 py-3"
          data-testid="create-order-button"
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
