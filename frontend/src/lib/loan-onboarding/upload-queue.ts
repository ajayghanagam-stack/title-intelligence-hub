/**
 * Tiny in-memory queue used to hand the user-selected `File` objects from
 * the new-package form to the /processing page so we can navigate
 * immediately after the package row is created (instead of blocking on
 * upload + pipeline-trigger inside the form's submit handler).
 *
 * Lives in module scope on purpose — `File` objects can't be serialized
 * through router state or sessionStorage, and the lifetime we need is
 * "until the next route mounts", which is exactly what a module-level
 * Map gives us. If the user closes the tab or hard-reloads before upload
 * finishes the entry is lost; that's the same failure mode as the
 * pre-existing in-form upload and is acceptable for a transient queue.
 */
export interface QueuedUpload {
  files: File[];
  orgId: string;
}

const queue = new Map<string, QueuedUpload>();

export function enqueueUpload(packageId: string, payload: QueuedUpload): void {
  queue.set(packageId, payload);
}

/** Take-and-clear: returns the queued payload (if any) and removes it. */
export function dequeueUpload(packageId: string): QueuedUpload | null {
  const payload = queue.get(packageId);
  if (!payload) return null;
  queue.delete(packageId);
  return payload;
}
