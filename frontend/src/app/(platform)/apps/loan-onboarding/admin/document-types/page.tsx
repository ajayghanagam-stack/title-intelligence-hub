"use client";

// Phase 5.3 — Document Types admin.
//
// Faithful port of the prototype's catalog UI. Search + category filter
// + "Add Type" sit inline with the title. Table styling, badges, and
// toggle dimensions match the prototype 1:1. Backend-driven via the
// /admin/config/doc-types CRUD endpoints (toggle = PATCH active=true|false;
// backend has no DELETE — soft-disable is canonical).

import { useEffect, useMemo, useState } from "react";
import { Brain, Minus, Plus, Search, X } from "lucide-react";

import { useOrg } from "@/hooks/use-org";
import { cn } from "@/lib/utils";

type DocTypeRow = {
  id: string;
  key: string;
  name: string;
  category: string;
  auto_classify_enabled: boolean;
  expected_min_pages: number | null;
  expected_max_pages: number | null;
  active: boolean;
  documents_processed: number;
};

const CATEGORIES = [
  "All Categories",
  "Income",
  "Assets",
  "Identity",
  "Property",
  "Insurance",
  "Title",
  "Credit",
  "Employment",
  "VA/Military",
];

const CATEGORY_OPTIONS = CATEGORIES.filter((c) => c !== "All Categories");

export default function DocumentTypesPage() {
  const { orgFetch, currentOrgId } = useOrg();
  const [rows, setRows] = useState<DocTypeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All Categories");
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    if (!currentOrgId) return;
    let cancelled = false;
    setLoading(true);
    orgFetch<DocTypeRow[]>(
      "/api/v1/apps/loan-onboarding/admin/config/doc-types"
    )
      .then((data) => {
        if (!cancelled) {
          setRows(data);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message ?? "Failed to load doc types");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentOrgId, orgFetch]);

  const filtered = useMemo(() => {
    return rows
      .filter((r) => {
        if (category !== "All Categories" && r.category !== category) return false;
        if (search.trim()) {
          const q = search.toLowerCase();
          if (
            !r.name.toLowerCase().includes(q) &&
            !r.key.toLowerCase().includes(q) &&
            !r.category.toLowerCase().includes(q)
          ) {
            return false;
          }
        }
        return true;
      })
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [rows, search, category]);

  const totalActive = useMemo(
    () => rows.filter((r) => r.active).length,
    [rows]
  );

  async function toggleActive(row: DocTypeRow) {
    const next = !row.active;
    setRows((rs) =>
      rs.map((r) => (r.id === row.id ? { ...r, active: next } : r))
    );
    try {
      await orgFetch(
        `/api/v1/apps/loan-onboarding/admin/config/doc-types/${row.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ active: next }),
        }
      );
    } catch (e) {
      setRows((rs) =>
        rs.map((r) => (r.id === row.id ? { ...r, active: !next } : r))
      );
      setError((e as Error).message);
    }
  }

  async function createDocType(
    payload: Omit<DocTypeRow, "id" | "active">
  ) {
    const created = await orgFetch<DocTypeRow>(
      "/api/v1/apps/loan-onboarding/admin/config/doc-types",
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
    setRows((rs) => [...rs, created].sort((a, b) => a.key.localeCompare(b.key)));
  }

  return (
    <div className="mx-auto max-w-7xl px-2 py-2">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Document Types</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {rows.length} types configured · {totalActive} active ·
            Classification targets for the AI engine.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search types…"
              className="h-8 w-44 rounded-md border bg-card pl-8 pr-2 text-xs focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            />
          </div>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="h-8 rounded-md border bg-card px-2 text-xs focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
          >
            {CATEGORIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setShowModal(true)}
            className="inline-flex items-center gap-1 rounded-md bg-brand-purple px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-white hover:opacity-90"
          >
            <Plus className="h-3 w-3" />
            Add Type
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-4 py-2.5 text-left">Document Type</th>
              <th className="px-4 py-2.5 text-left">Category</th>
              <th className="px-4 py-2.5 text-left">Auto-Classify</th>
              <th className="px-4 py-2.5 text-left">Processed</th>
              <th className="px-4 py-2.5 text-left">Active</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-6 text-center text-xs text-muted-foreground"
                >
                  Loading…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-6 text-center text-xs text-muted-foreground"
                >
                  {rows.length === 0
                    ? "No doc types configured yet. Click Add Type to create one."
                    : "No matches for the current filters."}
                </td>
              </tr>
            ) : (
              filtered.map((r) => (
                <tr key={r.id} className="border-t hover:bg-muted/20">
                  <td className="px-4 py-2.5 text-xs font-bold">{r.name}</td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                      {r.category}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                        r.auto_classify_enabled
                          ? "bg-brand-teal/10 text-brand-teal ring-1 ring-brand-teal/30"
                          : "bg-muted text-muted-foreground ring-1 ring-border"
                      )}
                    >
                      {r.auto_classify_enabled ? (
                        <Brain className="h-2.5 w-2.5" />
                      ) : (
                        <Minus className="h-2.5 w-2.5" />
                      )}
                      {r.auto_classify_enabled ? "Enabled" : "Off"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground tabular-nums">
                    {(r.documents_processed ?? 0).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      onClick={() => toggleActive(r)}
                      aria-pressed={r.active}
                      className={cn(
                        "relative h-5 w-9 rounded-full transition",
                        r.active ? "bg-brand-teal" : "bg-muted"
                      )}
                    >
                      <span
                        className={cn(
                          "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition",
                          r.active ? "left-[18px]" : "left-0.5"
                        )}
                      />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {showModal && (
        <AddDocTypeModal
          onClose={() => setShowModal(false)}
          onCreate={async (payload) => {
            await createDocType(payload);
            setShowModal(false);
          }}
        />
      )}
    </div>
  );
}

function AddDocTypeModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (payload: Omit<DocTypeRow, "id" | "active">) => Promise<void>;
}) {
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [cat, setCat] = useState(CATEGORY_OPTIONS[0]);
  const [autoClassify, setAutoClassify] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    try {
      await onCreate({
        key: key.trim(),
        name: name.trim(),
        category: cat,
        auto_classify_enabled: autoClassify,
        expected_min_pages: null,
        expected_max_pages: null,
        documents_processed: 0,
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
            Add Document Type
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
              Key (stable identifier)
            </span>
            <input
              required
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="e.g. Paystub"
              className="mt-1 h-9 w-full rounded-md border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            />
          </label>
          <label className="block">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Display Name
            </span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Paystub"
              className="mt-1 h-9 w-full rounded-md border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            />
          </label>
          <label className="block">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Category
            </span>
            <select
              value={cat}
              onChange={(e) => setCat(e.target.value)}
              className="mt-1 h-9 w-full rounded-md border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
            >
              {CATEGORY_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={autoClassify}
              onChange={(e) => setAutoClassify(e.target.checked)}
              className="h-4 w-4 rounded border-border text-brand-teal focus:ring-brand-teal/30"
            />
            <span className="text-sm">Enable auto-classify</span>
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
              className="inline-flex items-center gap-1 rounded-md bg-brand-purple px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-white hover:opacity-90 disabled:opacity-50"
            >
              <Plus className="h-3 w-3" />
              {submitting ? "Creating…" : "Add Type"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
