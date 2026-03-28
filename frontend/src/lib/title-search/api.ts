import { apiFetch, apiFetchBlob } from "@/lib/api";
import type {
  TSOrder,
  TSOrderListItem,
  TSPipelineStatus,
  TSDocument,
  ChainResponse,
  TSFlagList,
  TSPackage,
  SourceAssignment,
} from "./types";

const BASE = "/api/v1/apps/title-search";

// Orders
export function createOrder(
  orgId: string,
  data: {
    property_address: string;
    city?: string;
    zip_code?: string;
    county: string;
    state_code: string;
    borrower_name?: string;
    parcel_number?: string;
    legal_description?: string;
    search_scope?: string;
    search_years?: number;
    order_reference?: string;
    effective_date?: string;
    linked_pack_id?: string;
  }
) {
  return apiFetch<TSOrder>(`${BASE}/orders`, {
    method: "POST",
    body: JSON.stringify(data),
    orgId,
  });
}

export function listOrders(orgId: string, status?: string) {
  const params = status ? `?status=${status}` : "";
  return apiFetch<TSOrderListItem[]>(`${BASE}/orders${params}`, { orgId });
}

export function getOrder(orgId: string, orderId: string) {
  return apiFetch<TSOrder>(`${BASE}/orders/${orderId}`, { orgId });
}

export function deleteOrder(orgId: string, orderId: string) {
  return apiFetch<void>(`${BASE}/orders/${orderId}`, {
    method: "DELETE",
    orgId,
  });
}

export function processOrder(orgId: string, orderId: string) {
  return apiFetch<{ message: string; order_id: string }>(
    `${BASE}/orders/${orderId}/process`,
    { method: "POST", orgId }
  );
}

// Pipeline
export function getPipelineStatus(orgId: string, orderId: string) {
  return apiFetch<TSPipelineStatus>(`${BASE}/orders/${orderId}/pipeline`, {
    orgId,
  });
}

// Sources
export function getSources(orgId: string, orderId: string) {
  return apiFetch<SourceAssignment[]>(`${BASE}/orders/${orderId}/sources`, {
    orgId,
  });
}

// Documents
export function getDocuments(
  orgId: string,
  orderId: string,
  filters?: { doc_type?: string; needs_review?: boolean }
) {
  const params = new URLSearchParams();
  if (filters?.doc_type) params.set("doc_type", filters.doc_type);
  if (filters?.needs_review !== undefined)
    params.set("needs_review", String(filters.needs_review));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<TSDocument[]>(`${BASE}/orders/${orderId}/documents${qs}`, {
    orgId,
  });
}

export function downloadDocument(orgId: string, orderId: string, docId: string) {
  return apiFetchBlob(`${BASE}/orders/${orderId}/documents/${docId}/download`, {
    orgId,
  });
}

// Chain
export function getChain(orgId: string, orderId: string) {
  return apiFetch<ChainResponse>(`${BASE}/orders/${orderId}/chain`, { orgId });
}

// Flags
export function getFlags(orgId: string, orderId: string) {
  return apiFetch<TSFlagList>(`${BASE}/orders/${orderId}/flags`, { orgId });
}

export function reviewFlag(
  orgId: string,
  orderId: string,
  flagId: string,
  data: { decision: string; notes?: string }
) {
  return apiFetch(`${BASE}/orders/${orderId}/flags/${flagId}/review`, {
    method: "POST",
    body: JSON.stringify(data),
    orgId,
  });
}

// Package
export function getPackage(orgId: string, orderId: string) {
  return apiFetch<TSPackage>(`${BASE}/orders/${orderId}/package`, { orgId });
}

export function issuePackage(orgId: string, orderId: string) {
  return apiFetch<TSPackage>(`${BASE}/orders/${orderId}/package/issue`, {
    method: "POST",
    orgId,
  });
}

export function downloadPackagePdf(orgId: string, orderId: string) {
  return apiFetchBlob(`${BASE}/orders/${orderId}/package/pdf`, { orgId });
}
