"use client";

import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
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
      const files = Array.from(e.dataTransfer.files).filter((f) =>
        f.name.toLowerCase().endsWith(".pdf")
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
      className={`rounded-xl border-2 border-dashed p-10 text-center transition-all cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/40 ${
        dragActive
          ? "border-primary bg-primary/5 scale-[1.01]"
          : "border-muted-foreground/20 hover:border-primary/30"
      }`}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 mx-auto">
        <FileUp className="h-7 w-7 text-primary" />
      </div>
      <p className="mt-4 text-sm font-medium">
        Drag & drop PDF files here
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        or click to browse from your computer
      </p>
      <label htmlFor="file-upload" className="sr-only">Upload PDF files</label>
      <input
        type="file"
        accept=".pdf"
        multiple
        onChange={handleFileInput}
        className="hidden"
        id="file-upload"
        disabled={uploading}
      />
      <Button
        variant="outline"
        className="mt-4"
        onClick={() => document.getElementById("file-upload")?.click()}
        disabled={uploading}
      >
        <Upload className="mr-2 h-4 w-4" />
        {uploading ? "Uploading..." : "Select Files"}
      </Button>
    </div>
  );
}
