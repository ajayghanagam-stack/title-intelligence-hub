from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    """Kept for backward compatibility — fields are optional since the
    download endpoint no longer requires audience/format selection."""
    audience: str | None = Field(default=None, pattern="^(attorney|lender|buyer|underwriter)$")
    format: str | None = Field(default=None, pattern="^(text|markdown|pdf|json)$")


class ReportResponse(BaseModel):
    audience: str
    format: str
    content: str
    uri: str | None = None
