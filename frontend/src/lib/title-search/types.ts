export interface TSOrder {
  id: string;
  org_id: string;
  created_by: string;
  property_address: string;
  city: string | null;
  zip_code: string | null;
  parcel_number: string | null;
  county: string;
  state_code: string;
  borrower_name: string | null;
  legal_description: string | null;
  search_scope: string;
  search_years: number;
  order_reference: string | null;
  effective_date: string | null;
  status: string;
  pipeline_stage: string | null;
  pipeline_error: string | null;
  linked_pack_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TSOrderListItem {
  id: string;
  property_address: string;
  county: string;
  state_code: string;
  borrower_name: string | null;
  status: string;
  pipeline_stage: string | null;
  created_at: string;
}

export interface PipelineStageStatus {
  stage: string;
  status: string;
}

export interface TSPipelineStatus {
  order_id: string;
  status: string;
  pipeline_stage: string | null;
  stages: PipelineStageStatus[];
  pipeline_error: string | null;
}

export interface TSDocument {
  id: string;
  order_id: string;
  doc_type: string;
  recording_date: string | null;
  recording_ref: string | null;
  consideration: number | null;
  grantor: { names: string[]; entity_type?: string } | null;
  grantee: { names: string[]; entity_type?: string } | null;
  summary: string | null;
  confidence: number | null;
  needs_review: boolean;
  created_at: string;
}

export interface ChainLink {
  id: string;
  order_id: string;
  document_id: string | null;
  position: number;
  link_type: string;
  from_party: { names: string[] } | null;
  to_party: { names: string[] } | null;
  effective_date: string | null;
  is_gap: boolean;
  gap_description: string | null;
}

export interface ChainResponse {
  order_id: string;
  chain_links: ChainLink[];
  chain_complete: boolean;
  total_links: number;
  gap_count: number;
}

export interface TSFlag {
  id: string;
  order_id: string;
  flag_type: string;
  severity: string;
  title: string;
  description: string;
  status: string;
  created_at: string;
  reviews: TSReview[];
}

export interface TSReview {
  id: string;
  flag_id: string | null;
  reviewer_id: string;
  decision: string;
  notes: string | null;
  created_at: string;
}

export interface TSFlagList {
  flags: TSFlag[];
  counts: Record<string, number>;
}

export interface TSPackage {
  id: string;
  order_id: string;
  package_number: string;
  status: string;
  search_scope: string | null;
  years_covered: number | null;
  total_documents: number | null;
  chain_complete: boolean;
  open_flags_count: number | null;
  property_summary: Record<string, string> | null;
  issued_by: string | null;
  issued_at: string | null;
  created_at: string;
}

export interface SourceAssignment {
  id: string;
  order_id: string;
  source_type: string;
  availability: string;
  status: string;
  created_at: string;
}
