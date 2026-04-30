/**
 * Extraction export builders — JSON / CSV / MISMO-flavored XML.
 *
 * Mirrors the prototype's `buildExtractionJSON / CSV / XML` shape exactly so
 * downstream LOS importers that already key off the prototype output keep
 * working. Backend data (`LoanExtractionsResponse`) is mapped onto the same
 * `documents[]` payload first; per-format formatters share that one shape.
 */
import type {
  LoanExtractionField,
  LoanExtractionOverride,
  LoanStackExtraction,
  LoanPackage,
} from "./types";

interface ExportField {
  name: string;
  value: string | null;
  confidence: number | null;
  // "extracted" mirrors the prototype's terminology for downstream parsers.
  status: "extracted" | "missing";
  /** True iff the value was supplied by a reviewer (override). */
  reviewed?: boolean;
}

interface ExportDocument {
  stackId: string;
  documentType: string;
  pageCount: number | null;
  confidence: number | null;
  fields: ExportField[];
}

/**
 * Composite key used by both the dashboard's local `fieldSaved` map and the
 * backend's `lo_extraction_overrides` unique constraint.
 */
function _overrideKey(stackId: string, docType: string, fieldName: string): string {
  return `${stackId}::${docType}::${fieldName}`;
}

function _buildOverrideMap(
  overrides: LoanExtractionOverride[] | undefined
): Map<string, string> {
  const m = new Map<string, string>();
  for (const o of overrides ?? []) {
    m.set(_overrideKey(o.stack_id, o.doc_type, o.field_name), o.value);
  }
  return m;
}

function _toExportField(
  f: LoanExtractionField,
  override: string | undefined
): ExportField {
  // Reviewer-edited values always win and are emitted as extracted with
  // confidence 1.0 — the AI's value/confidence are no longer authoritative.
  if (override !== undefined) {
    return {
      name: f.name,
      value: override,
      confidence: 1,
      status: "extracted",
      reviewed: true,
    };
  }
  const found = f.status === "located" || f.status === "low_confidence";
  return {
    name: f.name,
    value: found ? f.value : null,
    confidence: f.confidence ?? null,
    status: found ? "extracted" : "missing",
  };
}

export function buildExtractionPayload(
  stacks: LoanStackExtraction[],
  overrides?: LoanExtractionOverride[]
): ExportDocument[] {
  const overrideMap = _buildOverrideMap(overrides);
  return stacks
    .filter((s) => s.fields && s.fields.length > 0)
    .map((s) => ({
      stackId: s.stack_id,
      documentType: s.doc_type,
      pageCount: null,
      confidence: null,
      fields: s.fields.map((f) =>
        _toExportField(f, overrideMap.get(_overrideKey(s.stack_id, s.doc_type, f.name)))
      ),
    }));
}

function _loanIdentifier(pkg: LoanPackage | null | undefined): string {
  // Prefer the loan_reference, fall back to package name, then a placeholder.
  return (
    pkg?.loan_reference?.trim() ||
    pkg?.name?.trim() ||
    "LOAN-UNKNOWN"
  );
}

export function buildExtractionJSON(
  stacks: LoanStackExtraction[],
  pkg?: LoanPackage | null,
  overrides?: LoanExtractionOverride[]
): string {
  const payload = {
    schemaVersion: "1.0",
    generatedAt: new Date().toISOString(),
    loanNumber: _loanIdentifier(pkg),
    documents: buildExtractionPayload(stacks, overrides),
  };
  return JSON.stringify(payload, null, 2);
}

function _csvEscape(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "";
  const s = String(v).replace(/"/g, '""');
  return /[",\n]/.test(s) ? `"${s}"` : s;
}

export function buildExtractionCSV(
  stacks: LoanStackExtraction[],
  overrides?: LoanExtractionOverride[]
): string {
  const rows: string[][] = [
    [
      "document_type",
      "stack_id",
      "field_name",
      "field_value",
      "confidence",
      "status",
      "reviewed",
    ],
  ];
  for (const doc of buildExtractionPayload(stacks, overrides)) {
    for (const f of doc.fields) {
      rows.push([
        _csvEscape(doc.documentType),
        _csvEscape(doc.stackId),
        _csvEscape(f.name),
        _csvEscape(f.value),
        f.confidence !== null && f.confidence !== undefined
          ? String(f.confidence)
          : "",
        f.status,
        f.reviewed ? "true" : "false",
      ]);
    }
  }
  return rows.map((r) => r.join(",")).join("\n");
}

function _xmlEscape(s: string | number | null | undefined): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/**
 * MISMO-flavored XML. Not a strict 3.4-conformant schema, but mirrors the
 * shape (LOAN > DOCUMENT > EXTENSION > FIELD) so LOS importers can map
 * fields. Same shape the prototype emits.
 */
export function buildExtractionXML(
  stacks: LoanStackExtraction[],
  pkg?: LoanPackage | null,
  overrides?: LoanExtractionOverride[]
): string {
  const docs = buildExtractionPayload(stacks, overrides);
  const loanId = _loanIdentifier(pkg);
  const lines: string[] = [];
  lines.push('<?xml version="1.0" encoding="UTF-8"?>');
  lines.push(
    '<MESSAGE xmlns="http://www.mismo.org/residential/2009/schemas" MISMOReferenceModelIdentifier="3.4.0">'
  );
  lines.push("  <DEAL_SETS>");
  lines.push("    <DEAL_SET>");
  lines.push("      <DEALS>");
  lines.push("        <DEAL>");
  lines.push("          <LOANS>");
  lines.push("            <LOAN>");
  lines.push("              <LOAN_IDENTIFIERS>");
  lines.push(
    `                <LOAN_IDENTIFIER><LoanIdentifier>${_xmlEscape(loanId)}</LoanIdentifier></LOAN_IDENTIFIER>`
  );
  lines.push("              </LOAN_IDENTIFIERS>");
  lines.push("              <DOCUMENT_SETS><DOCUMENT_SET><DOCUMENTS>");
  for (const d of docs) {
    lines.push("                <DOCUMENT>");
    lines.push(
      `                  <DOCUMENT_CLASSIFICATION><DOCUMENT_CLASS><DocumentTypeOtherDescription>${_xmlEscape(d.documentType)}</DocumentTypeOtherDescription></DOCUMENT_CLASS></DOCUMENT_CLASSIFICATION>`
    );
    if (d.pageCount !== null) {
      lines.push(`                  <PAGES_COUNT>${d.pageCount}</PAGES_COUNT>`);
    }
    lines.push("                  <EXTENSION><OTHER><EXTRACTED_FIELDS>");
    for (const f of d.fields) {
      lines.push("                    <FIELD>");
      lines.push(`                      <Name>${_xmlEscape(f.name)}</Name>`);
      lines.push(`                      <Value>${_xmlEscape(f.value ?? "")}</Value>`);
      lines.push(
        `                      <Confidence>${f.confidence ?? ""}</Confidence>`
      );
      lines.push(`                      <Status>${_xmlEscape(f.status)}</Status>`);
      if (f.reviewed) {
        lines.push("                      <Reviewed>true</Reviewed>");
      }
      lines.push("                    </FIELD>");
    }
    lines.push("                  </EXTRACTED_FIELDS></OTHER></EXTENSION>");
    lines.push("                </DOCUMENT>");
  }
  lines.push("              </DOCUMENTS></DOCUMENT_SET></DOCUMENT_SETS>");
  lines.push("            </LOAN>");
  lines.push("          </LOANS>");
  lines.push("        </DEAL>");
  lines.push("      </DEALS>");
  lines.push("    </DEAL_SET>");
  lines.push("  </DEAL_SETS>");
  lines.push("</MESSAGE>");
  return lines.join("\n");
}

/** Trigger a client-side file download for a generated string payload. */
export function triggerDownload(
  filename: string,
  content: string,
  mime: string
): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Defer revoke so Safari finishes the download first.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
