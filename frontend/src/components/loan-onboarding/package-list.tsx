"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  FileStack,
  ChevronRight,
  ChevronLeft,
  Calendar,
  User,
  Plus,
  Trash2,
  Check,
  X,
} from "lucide-react";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { PackageStatusBadge } from "./package-status-badge";
import type { LoanPackageListItem } from "@/lib/loan-onboarding/types";

const PAGE_SIZE = 10;

interface Props {
  packages: LoanPackageListItem[];
  onDelete?: (packageId: string) => Promise<void>;
}

export function PackageList({ packages, onDelete }: Props) {
  const router = useRouter();
  const { orgPath } = useOrgSlug();
  const [page, setPage] = useState(0);
  // Two-step inline confirm — mirrors the TSA orders list (`order-list.tsx`)
  // and the TI packs list so the delete UX is consistent across micro-apps.
  // Click trash → row enters "Delete?" mode with Check/X buttons; click Check
  // commits the delete; click X (or anywhere else) cancels back.
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<Record<string, string>>({});

  const handleDelete = async (pkgId: string) => {
    if (!onDelete || deletingId) return;
    setDeletingId(pkgId);
    setErrorMsg((prev) => {
      const next = { ...prev };
      delete next[pkgId];
      return next;
    });
    try {
      await onDelete(pkgId);
      setConfirmId(null);
      // If we just deleted the last row on the current page, fall back one.
      const newTotal = sorted.length - 1;
      const newTotalPages = Math.max(1, Math.ceil(newTotal / PAGE_SIZE));
      if (page >= newTotalPages) setPage(Math.max(0, newTotalPages - 1));
    } catch (err) {
      setConfirmId(null);
      setErrorMsg((prev) => ({
        ...prev,
        [pkgId]: err instanceof Error ? err.message : "Failed to delete package",
      }));
    } finally {
      setDeletingId(null);
    }
  };

  const sorted = [...packages].sort(
    (a, b) =>
      new Date(b.updated_at || b.created_at).getTime() -
      new Date(a.updated_at || a.created_at).getTime()
  );
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const paged = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  if (packages.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60"
        data-testid="loan-packages-empty"
      >
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50 mb-4">
          <FileStack className="h-7 w-7 text-muted-foreground/60" />
        </div>
        <p className="text-lg font-medium text-foreground/80 mb-1">
          No packages yet
        </p>
        <p className="text-sm text-muted-foreground mb-6">
          Create your first loan onboarding package to get started
        </p>
        <Link
          href={orgPath("/apps/loan-onboarding/packages/new")}
          className="btn-cta gap-2"
        >
          <Plus className="h-4 w-4" />
          New Package
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="loan-package-list">
      {paged.map((pkg) => {
        const isConfirming = confirmId === pkg.id;
        const isDeleting = deletingId === pkg.id;
        const error = errorMsg[pkg.id];
        return (
          <div key={pkg.id} data-testid={`loan-package-row-${pkg.id}`}>
            <div
              onClick={() => {
                if (isConfirming || isDeleting) return;
                router.push(
                  orgPath(`/apps/loan-onboarding/packages/${pkg.id}`)
                );
              }}
              className={`group flex items-center gap-4 card-warm px-5 py-4 cursor-pointer ${
                isConfirming
                  ? "border-red-200 bg-red-50/30"
                  : "hover:border-primary/20"
              }`}
            >
              <div className="shrink-0">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-sky-50 text-sky-600 ring-1 ring-sky-200">
                  <FileStack className="h-5 w-5" />
                </div>
              </div>

              <div className="flex-1 min-w-0">
                <p className="font-semibold text-foreground group-hover:text-primary transition-colors truncate">
                  {pkg.name}
                </p>
                <div className="flex items-center gap-3 mt-1 flex-wrap">
                  <PackageStatusBadge
                    status={pkg.status}
                    stage={pkg.pipeline_stage}
                  />
                  {pkg.borrower_name && (
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <User className="h-3 w-3" />
                      {pkg.borrower_name}
                    </span>
                  )}
                  {pkg.loan_reference && (
                    <span className="text-xs text-muted-foreground">
                      Ref: {pkg.loan_reference}
                    </span>
                  )}
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Calendar className="h-3 w-3" />
                    {new Date(
                      pkg.updated_at || pkg.created_at
                    ).toLocaleDateString()}
                  </span>
                </div>
              </div>

              {/* Right side: trash icon OR inline confirm/cancel */}
              {onDelete &&
                (isConfirming ? (
                  <div
                    className="shrink-0 flex items-center gap-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <span className="text-xs text-red-600 font-medium">
                      {isDeleting ? "Deleting..." : "Delete?"}
                    </span>
                    <button
                      type="button"
                      onClick={() => handleDelete(pkg.id)}
                      disabled={isDeleting}
                      className="p-1.5 rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                      title="Confirm delete"
                      data-testid={`loan-package-delete-confirm-${pkg.id}`}
                    >
                      <Check className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmId(null)}
                      disabled={isDeleting}
                      className="p-1.5 rounded-md text-muted-foreground hover:bg-muted transition-colors"
                      title="Cancel"
                      data-testid={`loan-package-delete-cancel-${pkg.id}`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setErrorMsg((prev) => {
                          const next = { ...prev };
                          delete next[pkg.id];
                          return next;
                        });
                        setConfirmId(pkg.id);
                      }}
                      aria-label={`Delete ${pkg.name}`}
                      data-testid={`loan-package-delete-${pkg.id}`}
                      className="shrink-0 p-2 rounded-lg text-muted-foreground/40 hover:text-red-600 hover:bg-red-50 transition-colors"
                      title="Delete package"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                    <ChevronRight className="h-5 w-5 text-muted-foreground/30 group-hover:text-primary/60 transition-colors shrink-0" />
                  </>
                ))}
              {!onDelete && (
                <ChevronRight className="h-5 w-5 text-muted-foreground/30 group-hover:text-primary/60 transition-colors shrink-0" />
              )}
            </div>

            {/* Per-row error banner — appears under the row when a delete
                fails. Dismissable via the small X. */}
            {error && (
              <div
                className="flex items-center gap-2 px-5 py-2 text-xs text-amber-800 bg-amber-50 border border-t-0 border-amber-200 rounded-b-xl"
                data-testid={`loan-package-delete-error-${pkg.id}`}
              >
                <span className="flex-1">{error}</span>
                <button
                  type="button"
                  onClick={() =>
                    setErrorMsg((prev) => {
                      const next = { ...prev };
                      delete next[pkg.id];
                      return next;
                    })
                  }
                  className="p-0.5 rounded text-amber-400 hover:text-amber-600"
                  title="Dismiss"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>
        );
      })}

      {totalPages > 1 && (
        <div
          className="flex items-center justify-between pt-4 border-t border-border/40"
          data-testid="loan-pagination-controls"
        >
          <span className="text-xs text-muted-foreground">
            Showing {page * PAGE_SIZE + 1}–
            {Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-muted hover:bg-muted/80 text-foreground"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Prev
            </button>
            <span className="text-xs font-medium text-muted-foreground tabular-nums">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() =>
                setPage((p) => Math.min(totalPages - 1, p + 1))
              }
              disabled={page >= totalPages - 1}
              className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-muted hover:bg-muted/80 text-foreground"
            >
              Next
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
