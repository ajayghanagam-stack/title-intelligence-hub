export const ORDER_STATUS_COLORS: Record<string, string> = {
  pending: "bg-stone-100 text-stone-600 ring-1 ring-stone-200",
  processing: "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  awaiting_abstractor: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  review_required: "bg-orange-50 text-orange-700 ring-1 ring-orange-200",
  completed: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  failed: "bg-red-50 text-red-700 ring-1 ring-red-200",
};

export const ORDER_STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  processing: "Processing",
  awaiting_abstractor: "Awaiting Abstractor",
  review_required: "Review Required",
  completed: "Completed",
  failed: "Failed",
};

export const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border-red-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-yellow-100 text-yellow-800 border-yellow-200",
  low: "bg-blue-100 text-blue-800 border-blue-200",
};

export const STATUS_COLORS: Record<string, string> = {
  open: "bg-muted text-muted-foreground",
  approved: "bg-green-100 text-green-800 border-green-200",
  rejected: "bg-red-100 text-red-800 border-red-200",
};

export const DOC_TYPE_LABELS: Record<string, string> = {
  deed: "Deed",
  mortgage: "Mortgage",
  lien: "Lien",
  judgment: "Judgment",
  easement: "Easement",
  satisfaction: "Satisfaction",
  release: "Release",
  assignment: "Assignment",
  other: "Other",
};

export const STAGE_LABELS: Record<string, string> = {
  order: "Order Created",
  retrieve: "Record Retrieval",
  parse: "Document Parsing",
  chain: "Chain Building",
  package: "Package Assembly",
  complete: "Finalization",
};
