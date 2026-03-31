"use client";

import { useState, useRef, useEffect, useCallback } from "react";

interface FlagNoteInputProps {
  flagId: string;
  initialNote: string | null;
  onSave: (flagId: string, note: string | null) => Promise<void>;
}

export function FlagNoteInput({ flagId, initialNote, onSave }: FlagNoteInputProps) {
  const [value, setValue] = useState(initialNote ?? "");
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSaved = useRef(initialNote ?? "");

  // Sync if parent provides a new initialNote (e.g. after refetch)
  useEffect(() => {
    const incoming = initialNote ?? "";
    if (incoming !== lastSaved.current) {
      setValue(incoming);
      lastSaved.current = incoming;
    }
  }, [initialNote]);

  const save = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      const noteValue = trimmed || null;
      if (trimmed === (lastSaved.current ?? "").trim()) return;

      setStatus("saving");
      try {
        await onSave(flagId, noteValue);
        lastSaved.current = trimmed;
        setStatus("saved");
        setTimeout(() => setStatus("idle"), 2000);
      } catch {
        setStatus("idle");
      }
    },
    [flagId, onSave],
  );

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    setValue(newValue);
    setStatus("idle");

    // Auto-save after 1s of inactivity
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => save(newValue), 1000);
  };

  const handleBlur = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    save(value);
  };

  return (
    <div className="flex flex-col gap-1">
      <textarea
        className={`w-full rounded-md border px-2.5 py-1.5 text-sm leading-snug resize-y min-h-[36px] outline-none transition-colors
          ${value ? "border-indigo-200 bg-white" : "border-slate-200 bg-slate-50"}
          focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:bg-white`}
        rows={2}
        placeholder="Add a note..."
        value={value}
        onChange={handleChange}
        onBlur={handleBlur}
      />
      <div className="h-4 text-xs">
        {status === "saving" && <span className="text-slate-400">Saving...</span>}
        {status === "saved" && <span className="text-green-600">Saved</span>}
      </div>
    </div>
  );
}
