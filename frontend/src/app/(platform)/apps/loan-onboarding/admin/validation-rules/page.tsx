"use client";

// Phase 5.3 — Validation Rules admin.
//
// Backend-driven CRUD against /api/v1/apps/loan-onboarding/admin/config/validation-rules.
// Mirrors the LogikIntake prototype's two-tab UI (Document Rules / Data
// Validation Rules), info banner about Hard Stops vs Soft Flags, brand-purple
// "Add Rule" button, and per-row Actions dropdown (Edit / Duplicate).
// Edit and Add both swap to a full-page RuleEditor view. Active toggle is
// wired to PATCH active=true|false directly from the list row.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeftRight,
  Copy,
  Edit3,
  FileCheck,
  Info,
  MoreHorizontal,
  Plus,
} from "lucide-react";

import { AdminHeader } from "@/components/loan-onboarding/logik-intake/admin-header";
import { useOrg } from "@/hooks/use-org";
import { cn } from "@/lib/utils";

import { RuleEditor, type RulePayload } from "./rule-editor";

type RuleRow = {
  id: string;
  scope: "doc" | "data" | string;
  rule: string;
  description: string;
  applies_to: string;
  condition: string;
  preset_id: string | null;
  severity: "hard" | "soft" | string;
  active: boolean;
};

type EditorState = { mode: "add" } | { mode: "edit"; id: string };

export default function ValidationRulesAdminPage() {
  const { orgFetch, currentOrgId } = useOrg();
  const [rows, setRows] = useState<RuleRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"doc" | "data">("doc");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [saving, setSaving] = useState(false);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!currentOrgId) return;
    let cancelled = false;
    setLoading(true);
    orgFetch<RuleRow[]>(
      "/api/v1/apps/loan-onboarding/admin/config/validation-rules"
    )
      .then((data) => {
        if (!cancelled) {
          setRows(data);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message ?? "Failed to load rules");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentOrgId, orgFetch]);

  // Dismiss row-action dropdown on outside click / Escape.
  useEffect(() => {
    if (!menuOpenId) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenId(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpenId(null);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpenId]);

  const docCount = rows.filter((r) => r.scope === "doc").length;
  const dataCount = rows.filter((r) => r.scope === "data").length;
  const filtered = useMemo(
    () => rows.filter((r) => r.scope === tab),
    [rows, tab]
  );

  const editingRow: RuleRow | undefined =
    editor?.mode === "edit" ? rows.find((r) => r.id === editor.id) : undefined;

  async function toggleActive(row: RuleRow) {
    const next = !row.active;
    setRows((rs) =>
      rs.map((r) => (r.id === row.id ? { ...r, active: next } : r))
    );
    try {
      await orgFetch(
        `/api/v1/apps/loan-onboarding/admin/config/validation-rules/${row.id}`,
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

  // Create or update — full-page editor delegates here.
  const saveRule = useCallback(
    async (payload: RulePayload) => {
      if (!editor) return;
      setSaving(true);
      try {
        if (editor.mode === "edit") {
          // `scope` is immutable backend-side — omit from PATCH body.
          const { scope: _scope, ...patch } = payload;
          void _scope;
          const updated = await orgFetch<RuleRow>(
            `/api/v1/apps/loan-onboarding/admin/config/validation-rules/${editor.id}`,
            {
              method: "PATCH",
              body: JSON.stringify(patch),
            }
          );
          setRows((rs) => rs.map((r) => (r.id === editor.id ? updated : r)));
          // Jump to the rule's scope tab on return so the operator sees it.
          if (updated.scope === "doc" || updated.scope === "data") {
            setTab(updated.scope);
          }
        } else {
          const created = await orgFetch<RuleRow>(
            "/api/v1/apps/loan-onboarding/admin/config/validation-rules",
            {
              method: "POST",
              body: JSON.stringify(payload),
            }
          );
          setRows((rs) => [...rs, created]);
          if (created.scope === "doc" || created.scope === "data") {
            setTab(created.scope);
          }
        }
        setEditor(null);
        setError(null);
      } catch (e) {
        // Re-throw so the editor can surface the inline error.
        throw e;
      } finally {
        setSaving(false);
      }
    },
    [editor, orgFetch]
  );

  // Duplicate — POSTs a copy with the next "{name} - N" suffix that
  // doesn't already collide with another rule's name.
  const duplicateRule = useCallback(
    async (row: RuleRow) => {
      setMenuOpenId(null);
      const baseName = row.rule.replace(/\s-\s\d+$/, "");
      const existing = new Set(rows.map((r) => r.rule));
      let n = 2;
      let nextName = `${baseName} - ${n}`;
      while (existing.has(nextName)) {
        n += 1;
        nextName = `${baseName} - ${n}`;
      }
      try {
        const created = await orgFetch<RuleRow>(
          "/api/v1/apps/loan-onboarding/admin/config/validation-rules",
          {
            method: "POST",
            body: JSON.stringify({
              scope: row.scope,
              rule: nextName,
              description: row.description,
              applies_to: row.applies_to,
              condition: row.condition,
              severity: row.severity,
              preset_id: row.preset_id,
            }),
          }
        );
        setRows((rs) => {
          // Insert the duplicate immediately after the source so it
          // surfaces in the same tab right next to the original.
          const idx = rs.findIndex((r) => r.id === row.id);
          if (idx === -1) return [...rs, created];
          const next = [...rs];
          next.splice(idx + 1, 0, created);
          return next;
        });
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [rows, orgFetch]
  );

  // Editor mode short-circuits the list render.
  if (editor) {
    return (
      <RuleEditor
        mode={editor.mode}
        source={
          editor.mode === "edit" && editingRow
            ? {
                id: editingRow.id,
                scope:
                  editingRow.scope === "data"
                    ? "data"
                    : ("doc" as const),
                rule: editingRow.rule,
                description: editingRow.description,
                applies_to: editingRow.applies_to,
                condition: editingRow.condition,
                severity:
                  editingRow.severity === "soft"
                    ? "soft"
                    : ("hard" as const),
                preset_id: editingRow.preset_id,
                active: editingRow.active,
              }
            : undefined
        }
        defaultScope={tab}
        onCancel={() => setEditor(null)}
        onSave={saveRule}
        saving={saving}
      />
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-2 py-2">
      <AdminHeader
        title="Validation Rules"
        subtitle="Global rule library · Program Profiles can tighten thresholds per program or investor. Changes apply to new files immediately."
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border bg-card p-0.5 text-xs">
          <button
            type="button"
            onClick={() => setTab("doc")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1.5 font-medium transition",
              tab === "doc"
                ? "bg-brand-teal/10 text-brand-teal"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <FileCheck className="h-3.5 w-3.5" />
            Document Rules ({docCount})
          </button>
          <button
            type="button"
            onClick={() => setTab("data")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1.5 font-medium transition",
              tab === "data"
                ? "bg-brand-teal/10 text-brand-teal"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <ArrowLeftRight className="h-3.5 w-3.5" />
            Data Validation Rules ({dataCount})
          </button>
        </div>
        <button
          type="button"
          onClick={() => setEditor({ mode: "add" })}
          className="ml-auto inline-flex items-center gap-1 rounded-md bg-brand-purple px-3 py-2 text-xs font-bold uppercase tracking-wider text-white hover:opacity-90"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Rule
        </button>
      </div>

      <div className="flex items-start gap-2 rounded-md border border-brand-teal/30 bg-brand-teal/5 px-3 py-2 text-[11px]">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-teal" />
        <span>
          <strong>Hard Stops</strong> block file advancement — must be resolved
          explicitly. <strong>Soft Flags</strong> are advisory — operators can
          acknowledge and continue. Program Profiles can tighten these
          thresholds but cannot loosen them.
        </span>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      <div className="card-warm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Rule</th>
              <th className="px-4 py-3">Applies To</th>
              <th className="px-4 py-3">Condition</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Active</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {loading ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-6 text-center text-xs text-muted-foreground"
                >
                  Loading…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-6 text-center text-xs text-muted-foreground"
                >
                  No rules in this scope yet. Click Add Rule to create one.
                </td>
              </tr>
            ) : (
              filtered.map((r) => (
                <tr key={r.id} className="hover:bg-muted/30">
                  <td className="px-4 py-3">
                    <div className="text-xs font-bold">{r.rule}</div>
                    {r.description && (
                      <div className="mt-0.5 text-[10px] text-muted-foreground">
                        {r.description}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {r.applies_to ? (
                      <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                        {r.applies_to}
                      </span>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">
                        —
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px] text-muted-foreground">
                    {r.condition || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider ring-1",
                        r.severity === "hard"
                          ? "bg-destructive/10 text-destructive ring-destructive/30"
                          : "bg-brand-orange/15 text-[#7A5000] ring-brand-orange/40"
                      )}
                    >
                      {r.severity === "hard" ? "Hard Stop" : "Soft Flag"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => toggleActive(r)}
                      aria-pressed={r.active}
                      className={cn(
                        "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
                        r.active ? "bg-brand-teal" : "bg-muted"
                      )}
                    >
                      <span
                        className={cn(
                          "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
                          r.active ? "left-[18px]" : "left-0.5"
                        )}
                      />
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div
                      className="relative inline-block"
                      ref={menuOpenId === r.id ? menuRef : undefined}
                    >
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuOpenId((cur) =>
                            cur === r.id ? null : r.id
                          );
                        }}
                        className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[11px] font-semibold text-muted-foreground transition hover:border-brand-teal hover:bg-brand-teal/5 hover:text-brand-teal"
                        aria-haspopup="menu"
                        aria-expanded={menuOpenId === r.id}
                        aria-label={`Actions for ${r.rule}`}
                      >
                        <MoreHorizontal className="h-3.5 w-3.5" />
                      </button>
                      {menuOpenId === r.id && (
                        <div
                          role="menu"
                          className="absolute right-0 top-[calc(100%+4px)] z-20 min-w-[140px] overflow-hidden rounded-md border border-border bg-card shadow-md"
                        >
                          <button
                            type="button"
                            role="menuitem"
                            onClick={() => {
                              setEditor({ mode: "edit", id: r.id });
                              setMenuOpenId(null);
                            }}
                            className="flex w-full items-center gap-2 px-3.5 py-2 text-left text-[12px] font-medium text-foreground transition hover:bg-muted/60"
                          >
                            <Edit3 className="h-3.5 w-3.5 text-muted-foreground" />
                            Edit
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            onClick={() => duplicateRule(r)}
                            className="flex w-full items-center gap-2 px-3.5 py-2 text-left text-[12px] font-medium text-foreground transition hover:bg-muted/60"
                          >
                            <Copy className="h-3.5 w-3.5 text-muted-foreground" />
                            Duplicate
                          </button>
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
