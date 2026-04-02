export type FlagSeverity = "critical" | "high" | "medium" | "low";
export type FlagStatus = "open" | "approved" | "rejected" | "escalated";
export type ReviewDecision = "approve" | "reject" | "escalate";

export interface EvidenceRef {
  page_number: number;
  text_snippet: string;
}

export interface Flag {
  id: string;
  flag_type: string;
  severity: FlagSeverity;
  title: string;
  description: string;
  ai_explanation: string;
  evidence_refs: EvidenceRef[];
  status: FlagStatus;
  note: string | null;
}

export interface Review {
  id: string;
  flag_id: string;
  decision: ReviewDecision;
  reason_code: string | null;
  notes: string | null;
  created_at: string;
}

export interface Extraction {
  id: string;
  extraction_type: string;
  label: string;
  value: Record<string, unknown>;
  evidence_refs: EvidenceRef[];
  confidence: number;
}

export interface Section {
  id: string;
  section_type: string;
  title: string;
  start_page: number;
  end_page: number;
}

export interface ChatMessage {
  id: string;
  pack_id: string;
  role: "user" | "assistant";
  content: string;
  citations: EvidenceRef[] | null;
  user_id: string | null;
  created_at: string;
}

export interface PageData {
  id: string;
  page_number: number;
  image_uri: string;
  thumb_uri: string;
  ocr_text: string | null;
  page_type?: string;
}

export interface PackFile {
  id: string;
  filename: string;
  file_size: number;
  page_count: number | null;
  created_at: string;
}

export interface Pack {
  id: string;
  org_id: string;
  name: string;
  status: "uploading" | "processing" | "completed" | "failed";
  current_stage: string | null;
  readiness_summary: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  files?: PackFile[];
  page_count?: number | null;
  title_company?: string | null;
  property_address?: string | null;
}

export interface StageStatus {
  stage: string;
  status: "pending" | "running" | "completed" | "failed";
}

export interface TIPipelineStatus {
  pack_id: string;
  status: string;
  current_stage: string | null;
  stages: StageStatus[];
  examine_progress: string | null;
  error_message: string | null;
}

export interface FlagListResponse {
  flags: Flag[];
  counts: Record<string, number>;
  total: number;
  limit: number;
  offset: number;
}

export interface ReportException {
  number: number | string;
  title: string;
  description: string;
  severity: string;
  status?: string;
  page_ref: string;
  note?: string | null;
}

export interface ReportRequirement {
  number: number | string;
  title: string;
  description: string;
  priority: string;
  status: string;
  page_ref: string;
  note?: string | null;
}

export interface ReportWarning {
  title: string;
  explanation: string;
  flag_type: string;
  severity: string;
}

export interface ReportChecklistItem {
  number: number;
  action: string;
  priority: string;
  checked: boolean;
  note?: string | null;
}

export interface ReportData {
  subtitle: string;
  property_address: string;
  county: string;
  state: string;
  legal_description: string;
  interest_type: string;
  commitment_number: string;
  faf_file_number: string;
  effective_date: string;
  issued_date: string;
  owners_policy: string;
  lenders_policy: string;
  policy_amount: string;
  buyer_borrower: string;
  seller: string;
  lender: string;
  title_company: string;
  underwriter: string;
  generated_at: string;
  flags_by_severity: Record<string, unknown[]>;
  total_open: number;
  risk_assessment: string;
  standard_exceptions: ReportException[];
  specific_exceptions: ReportException[];
  requirements: ReportRequirement[];
  warnings: ReportWarning[];
  checklist_items: ReportChecklistItem[];
}

export interface Recommendation {
  decision: string;
  reasoning: string;
  confidence: number;
}
