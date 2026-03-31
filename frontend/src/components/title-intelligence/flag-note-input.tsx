"use client";

import { useState, useRef, useEffect } from "react";
import { Check, X } from "lucide-react";

interface FlagNoteInputProps {
  flagId: string;
  initialNote: string | null;
  onSave: (flagId: string, note: string | null) => Promise<void>;
}

export function FlagNoteInput({ flagId, initialNote, onSave }: FlagNoteInputProps) {
  const [value, setValue] = useState(initialNote ?? "");
  const [saving, setSaving] = useState(false);
  const savedValue = useRef(initialNote ?? "");

  // Sync if parent provides a new initialNote (e.g. after refetch)
  useEffect(() => {
    const incoming = initialNote ?? "";
    if (incoming !== savedValue.current) {
      setValue(incoming);
      savedValue.current = incoming;
    }
  }, [initialNote]);

  const isDirty = value.trim() !== savedValue.current.trim();

  const handleSave = async () => {
    const trimmed = value.trim();
    const noteValue = trimmed || null;
    setSaving(true);
    try {
      await onSave(flagId, noteValue);
      savedValue.current = trimmed;
    } catch {
      // keep dirty state so user can retry
    } finally {
      setSaving(false);
    }
  };

  const handleDiscard = () => {
    setValue(savedValue.current);
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
        onChange={(e) => setValue(e.target.value)}
        disabled={saving}
      />
      {isDirty && (
        <div className="flex items-center gap-1">
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center justify-center h-6 w-6 rounded bg-emerald-50 text-emerald-600 hover:bg-emerald-100 border border-emerald-200 transition-colors disabled:opacity-40"
            title="Save note"
          >
            <Check className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={handleDiscard}
            disabled={saving}
            className="inline-flex items-center justify-center h-6 w-6 rounded bg-red-50 text-red-500 hover:bg-red-100 border border-red-200 transition-colors disabled:opacity-40"
            title="Discard changes"
          >
            <X className="h-3.5 w-3.5" />
          </button>
          {saving && <span className="text-xs text-slate-400 ml-1">Saving...</span>}
        </div>
      )}
    </div>
  );
}
