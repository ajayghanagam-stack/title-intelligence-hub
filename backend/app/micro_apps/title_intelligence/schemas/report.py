from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    audience: str = Field(..., pattern="^(attorney|lender|buyer|underwriter)$")
    format: str = Field(default="text", pattern="^(text|markdown|pdf|json)$")


class ReportResponse(BaseModel):
    audience: str
    format: str
    content: str  # Text/markdown content, or URI for pdf/json downloads
    uri: str | None = None  # Storage URI for downloadable reports
