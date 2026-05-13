// In-memory handoff queue between the "New Loan File" modal and the loan
// overview page that drives the upload + process call.
//
// The previous architecture did `create → upload → process → navigate`
// inside the modal. That blocked the modal for 10–30s on large PDFs with
// no visible progress, so the operator saw the modal hang and then
// suddenly land on a loan page mid-pipeline — a jarring "crazy"
// experience.
//
// The fix is to navigate immediately after `create()` and let the
// destination page run the upload. That requires handing over the
// in-memory `File` objects (which can't go through the router) — this
// module is the bridge.
//
// **Why not sessionStorage / cancelled flags?**
//   - `File` is not JSON-serialisable.
//   - React 18 StrictMode double-invokes effects in dev. A `cancelled`
//     flag in the dequeue effect would cancel the upload mid-flight, and
//     `processPackage` would never fire. Module-level `Map.delete`
//     guarantees the second invocation gets `null` and silently skips —
//     no race, no need for a cleanup flag.

export interface QueuedUpload {
  files: File[];
  orgId: string;
}

const queue = new Map<string, QueuedUpload>();

export function enqueueUpload(packageId: string, payload: QueuedUpload): void {
  queue.set(packageId, payload);
}

export function dequeueUpload(packageId: string): QueuedUpload | null {
  const entry = queue.get(packageId);
  if (!entry) return null;
  queue.delete(packageId);
  return entry;
}

export function hasQueuedUpload(packageId: string): boolean {
  return queue.has(packageId);
}
