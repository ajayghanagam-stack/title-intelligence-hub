"use client";

import { useCallback, useState } from "react";
import { Upload, FileUp } from "lucide-react";

export function UploadDropzone({
  onFilesSelected,
  uploading,
}: {
  onFilesSelected: (files: File[]) => void;
  uploading: boolean;
}) {
  const [dragActive, setDragActive] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      const allowed = [".pdf", ".png", ".jpg", ".jpeg"];
      const files = Array.from(e.dataTransfer.files).filter((f) =>
        allowed.some((ext) => f.name.toLowerCase().endsWith(ext))
      );
      if (files.length) onFilesSelected(files);
    },
    [onFilesSelected]
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length) onFilesSelected(files);
    },
    [onFilesSelected]
  );

  return (
    <div
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          document.getElementById("file-upload")?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={handleDrop}
      className={`rounded-xl border-2 border-dashed p-10 text-center transition-all cursor-pointer focus:outline-none focus:ring-2 focus:ring-brand-amber/40 ${
        dragActive
          ? "border-brand-amber bg-brand-amber/5 scale-[1.01]"
          : "border-muted-foreground/20 hover:border-brand-amber/30"
      }`}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-sky-100 mx-auto">
        <FileUp className="h-7 w-7 text-sky-500" />
      </div>
      <p className="mt-4 text-sm font-semibold">
        Upload a Title Search Package
      </p>
      <p className="mt-1.5 text-xs text-muted-foreground">
        Supports PDF, PNG, and JPEG files. Upload all documents for a single package together.
      </p>
      <label htmlFor="file-upload" className="sr-only">Upload files</label>
      <input
        type="file"
        accept=".pdf,.png,.jpg,.jpeg"
        multiple
        onChange={handleFileInput}
        className="hidden"
        id="file-upload"
        disabled={uploading}
      />
      <button
        className="mt-4 btn-cta gap-2 px-6"
        onClick={() => document.getElementById("file-upload")?.click()}
        disabled={uploading}
      >
        {uploading ? "Uploading..." : "Select Files"}
      </button>
    </div>
  );
}
