"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { UploadDropzone } from "@/components/title-intelligence/upload-dropzone";
import { useOrg } from "@/hooks/use-org";
import { uploadFiles } from "@/lib/api";
import { X, FileText, ArrowRight } from "lucide-react";
import type { Pack } from "@/lib/ti-types";

export default function NewPackPage() {
  const router = useRouter();
  const { currentOrgId, orgFetch } = useOrg();
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!name.trim() || files.length === 0 || !currentOrgId) return;

    setCreating(true);
    setError(null);
    try {
      const pack = await orgFetch<Pack>("/api/v1/apps/title-intelligence/packs", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
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

      router.push(`/apps/title-intelligence/packs/${pack.id}`);
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
        <h1 className="text-2xl font-bold tracking-tight">Create New Pack</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Upload title commitment PDFs for AI-powered analysis
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="section-card space-y-6">
        <div className="space-y-2">
          <label htmlFor="pack-name" className="text-sm font-semibold">Pack Name</label>
          <Input
            id="pack-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g., 123 Main Street Title Commitment"
            className="h-11"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="file-upload" className="text-sm font-semibold">Upload PDFs</label>
          <UploadDropzone
            onFilesSelected={(selected) =>
              setFiles((prev) => [...prev, ...selected])
            }
            uploading={uploading}
          />
          {files.length > 0 && (
            <div className="mt-3 space-y-2">
              {files.map((f, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-lg bg-muted/40 px-4 py-2.5 text-sm group"
                >
                  <div className="flex items-center gap-2.5">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    <span className="truncate font-medium">{f.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {(f.size / 1024 / 1024).toFixed(1)} MB
                    </span>
                  </div>
                  <button
                    onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                    aria-label={`Remove ${f.name}`}
                    className="rounded-full p-1.5 text-muted-foreground hover:bg-background hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
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
          disabled={!name.trim() || files.length === 0 || creating}
          className="w-full btn-cta gap-2 py-3"
        >
          {creating
            ? uploading
              ? "Uploading files..."
              : "Creating pack..."
            : (
              <>
                Create & Process Pack
                <ArrowRight className="h-4 w-4" />
              </>
            )
          }
        </button>
      </div>
    </div>
  );
}
