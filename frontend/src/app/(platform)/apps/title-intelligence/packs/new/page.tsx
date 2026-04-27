"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { UploadDropzone } from "@/components/title-intelligence/upload-dropzone";
import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { uploadFiles } from "@/lib/api";
import { X, FileText } from "lucide-react";
import type { Pack } from "@/lib/ti-types";

export default function NewPackPage() {
  const router = useRouter();
  const { currentOrgId, orgFetch } = useOrg();
  const { orgPath } = useOrgSlug();
  const [files, setFiles] = useState<File[]>([]);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (files.length === 0 || !currentOrgId) return;

    // Auto-generate pack name from first file (strip extension)
    const autoName = files[0].name.replace(/\.[^.]+$/, "");

    setCreating(true);
    setError(null);
    try {
      const pack = await orgFetch<Pack>("/api/v1/apps/title-intelligence/packs", {
        method: "POST",
        body: JSON.stringify({ name: autoName }),
      });

      setUploading(true);
      await uploadFiles(
        `/api/v1/apps/title-intelligence/packs/${pack.id}/files`,
        files,
        { orgId: currentOrgId }
      );

      await orgFetch<unknown>(
        `/api/v1/apps/title-intelligence/packs/${pack.id}/process`,
        { method: "POST" }
      );

      // Dispatch event to refresh sidebar
      window.dispatchEvent(new CustomEvent("pack-uploaded"));

      router.push(orgPath(`/apps/title-intelligence/packs/${pack.id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create pack");
    } finally {
      setCreating(false);
      setUploading(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Upload Documents</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Upload your title commitment package file for analysis.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="section-card space-y-6">
        <UploadDropzone
          onFilesSelected={(selected) =>
            setFiles((prev) => [...prev, ...selected])
          }
          uploading={uploading}
        />
        {files.length > 0 && (
          <div className="space-y-2">
            {files.map((f, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded-lg bg-muted/40 px-4 py-2.5 text-sm"
              >
                <div className="flex items-center gap-2.5">
                  <FileText className="h-4 w-4 text-muted-foreground" />
                  <span className="truncate font-medium">{f.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {(f.size / 1024 / 1024).toFixed(1)} MB
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                  aria-label={`Remove ${f.name}`}
                  className="rounded-full p-1.5 text-muted-foreground hover:bg-background hover:text-red-500 transition-colors"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <button
        onClick={handleCreate}
        disabled={files.length === 0 || creating}
        className="w-full btn-cta py-3.5"
      >
        {creating
          ? uploading
            ? "Uploading files..."
            : "Creating pack..."
          : "Analyze Package"
        }
      </button>
    </div>
  );
}
