from pydantic import BaseModel


class ChecklistItem(BaseModel):
    category: str
    label: str
    status: str  # "done", "pending", "blocked", "needs_review"
    severity: str | None = None  # for flag-related items


class CategoryScore(BaseModel):
    category: str
    weight: float
    score: int  # 0-100 percentage within this category
    max_score: int  # always 100 (for frontend display)
    satisfied: int
    total: int
    details: str


class ReadinessResponse(BaseModel):
    score: int  # 0-100
    status: str  # "ready", "at_risk", "not_ready"
    summary: str | None
    categories: list[CategoryScore]
    checklist: list[ChecklistItem]
    estimated_days: int
