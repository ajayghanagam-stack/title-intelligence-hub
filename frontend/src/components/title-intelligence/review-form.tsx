"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { REASON_CODES } from "@/lib/ti-constants";
import type { ReviewDecision } from "@/lib/ti-types";
import { Check, X, AlertTriangle } from "lucide-react";

export function ReviewForm({
  onSubmit,
  submitting,
}: {
  onSubmit: (decision: ReviewDecision, reasonCode: string | null, notes: string) => void;
  submitting?: boolean;
}) {
  const [reasonCode, setReasonCode] = useState("");
  const [notes, setNotes] = useState("");

  const handleSubmit = (decision: ReviewDecision) => {
    onSubmit(decision, reasonCode || null, notes);
  };

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="review-reason" className="text-sm font-medium">Reason Code</label>
        <select
          id="review-reason"
          className="mt-1.5 w-full rounded-lg border bg-background px-3 py-2 text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-all"
          value={reasonCode}
          onChange={(e) => setReasonCode(e.target.value)}
        >
          <option value="">Select a reason (optional)</option>
          {REASON_CODES.map((rc) => (
            <option key={rc.value} value={rc.value}>
              {rc.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="review-notes" className="text-sm font-medium">Notes</label>
        <textarea
          id="review-notes"
          className="mt-1.5 w-full rounded-lg border bg-background p-3 text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-all"
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional review notes..."
        />
      </div>

      <div className="flex gap-2 pt-1">
        <Button
          onClick={() => handleSubmit("approve")}
          disabled={submitting}
          className="flex-1"
        >
          <Check className="mr-1.5 h-4 w-4" />
          Approve
        </Button>
        <Button
          variant="destructive"
          onClick={() => handleSubmit("reject")}
          disabled={submitting}
          className="flex-1"
        >
          <X className="mr-1.5 h-4 w-4" />
          Reject
        </Button>
        <Button
          variant="secondary"
          onClick={() => handleSubmit("escalate")}
          disabled={submitting}
          className="flex-1"
        >
          <AlertTriangle className="mr-1.5 h-4 w-4" />
          Escalate
        </Button>
      </div>
    </div>
  );
}
