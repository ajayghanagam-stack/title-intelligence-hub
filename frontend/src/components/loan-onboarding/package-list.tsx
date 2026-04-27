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
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = async (
    e: React.MouseEvent,
    pkg: LoanPackageListItem
  ) => {
    e.stopPropagation();
    if (!onDelete || deletingId) return;
    const ok = window.confirm(
      `Delete package "${pkg.name}"? This removes uploaded files, pages, stacks, and reviews. This cannot be undone.`
    );
    if (!ok) return;
    setDeletingId(pkg.id);
    setDeleteError(null);
    try {
      await onDelete(pkg.id);
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete package"
      );
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
      {deleteError && (
        <div
          className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
          data-testid="loan-package-delete-error"
        >
          {deleteError}
        </div>
      )}
      {paged.map((pkg) => (
        <div
          key={pkg.id}
          data-testid={`loan-package-row-${pkg.id}`}
          onClick={() =>
            router.push(orgPath(`/apps/loan-onboarding/packages/${pkg.id}`))
          }
          className="group flex items-center gap-4 card-warm px-5 py-4 cursor-pointer hover:border-primary/20"
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
                {new Date(pkg.updated_at || pkg.created_at).toLocaleDateString()}
              </span>
            </div>
          </div>

          {onDelete && (
            <button
              type="button"
              onClick={(e) => handleDelete(e, pkg)}
              disabled={deletingId === pkg.id}
              aria-label={`Delete ${pkg.name}`}
              data-testid={`loan-package-delete-${pkg.id}`}
              className="shrink-0 rounded-lg p-2 text-muted-foreground/60 hover:bg-red-50 hover:text-red-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}

          <ChevronRight className="h-5 w-5 text-muted-foreground/30 group-hover:text-primary/60 transition-colors shrink-0" />
        </div>
      ))}

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
