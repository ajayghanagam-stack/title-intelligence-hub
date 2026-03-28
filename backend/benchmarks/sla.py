"""SLA threshold definitions and checking for the TI pipeline.

Defines expected performance budgets for different document sizes and
provides functions to check pipeline runs against those budgets.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SLAThreshold:
    """Performance budget for a given document size."""

    page_count: int
    max_pipeline_seconds: float
    max_examine_seconds: float
    max_tokens: int


# Linear SLA: 100pp/60s throughput target
SLA_THRESHOLDS: list[SLAThreshold] = [
    SLAThreshold(page_count=25,  max_pipeline_seconds=15,  max_examine_seconds=10,  max_tokens=15_000),
    SLAThreshold(page_count=50,  max_pipeline_seconds=30,  max_examine_seconds=20,  max_tokens=25_000),
    SLAThreshold(page_count=100, max_pipeline_seconds=60,  max_examine_seconds=40,  max_tokens=50_000),
    SLAThreshold(page_count=200, max_pipeline_seconds=120, max_examine_seconds=80,  max_tokens=100_000),
    SLAThreshold(page_count=300, max_pipeline_seconds=180, max_examine_seconds=120, max_tokens=150_000),
    SLAThreshold(page_count=400, max_pipeline_seconds=240, max_examine_seconds=160, max_tokens=200_000),
    SLAThreshold(page_count=500, max_pipeline_seconds=300, max_examine_seconds=200, max_tokens=250_000),
]


def get_sla_for_page_count(n: int) -> SLAThreshold:
    """Return the matching or linearly-interpolated SLA threshold for *n* pages.

    - If *n* is below the smallest defined threshold, the smallest is returned.
    - If *n* is above the largest defined threshold, the largest is returned.
    - Otherwise, linear interpolation between the two nearest thresholds.
    """
    if n <= SLA_THRESHOLDS[0].page_count:
        return SLA_THRESHOLDS[0]
    if n >= SLA_THRESHOLDS[-1].page_count:
        return SLA_THRESHOLDS[-1]

    # Find bounding thresholds
    for i in range(len(SLA_THRESHOLDS) - 1):
        lo = SLA_THRESHOLDS[i]
        hi = SLA_THRESHOLDS[i + 1]
        if lo.page_count <= n <= hi.page_count:
            ratio = (n - lo.page_count) / (hi.page_count - lo.page_count)
            return SLAThreshold(
                page_count=n,
                max_pipeline_seconds=lo.max_pipeline_seconds + ratio * (hi.max_pipeline_seconds - lo.max_pipeline_seconds),
                max_examine_seconds=lo.max_examine_seconds + ratio * (hi.max_examine_seconds - lo.max_examine_seconds),
                max_tokens=int(lo.max_tokens + ratio * (hi.max_tokens - lo.max_tokens)),
            )

    # Fallback (should not be reached)
    return SLA_THRESHOLDS[-1]


@dataclass
class SLAViolation:
    """A single SLA violation."""

    metric: str
    actual: float
    limit: float
    message: str


@dataclass
class SLAResult:
    """Outcome of an SLA check."""

    passed: bool
    page_count: int
    threshold: SLAThreshold
    violations: list[SLAViolation] = field(default_factory=list)


def check_sla(
    stage_timings: dict[str, float],
    total_tokens: int,
    page_count: int,
    *,
    threshold: SLAThreshold | None = None,
) -> SLAResult:
    """Check pipeline metrics against the SLA for *page_count* pages.

    Args:
        stage_timings: ``{"ingest": 1.2, "render": 0.5, "examine": 8.3, "complete": 0.4}``
        total_tokens: Total token usage (input + output).
        page_count: Number of pages in the document.
        threshold: Optional explicit threshold (defaults to ``get_sla_for_page_count``).

    Returns:
        SLAResult with pass/fail and any violations.
    """
    if threshold is None:
        threshold = get_sla_for_page_count(page_count)

    violations: list[SLAViolation] = []

    # Total pipeline time
    total_seconds = sum(stage_timings.values())
    if total_seconds > threshold.max_pipeline_seconds:
        violations.append(SLAViolation(
            metric="total_pipeline_seconds",
            actual=total_seconds,
            limit=threshold.max_pipeline_seconds,
            message=f"Pipeline took {total_seconds:.1f}s (limit {threshold.max_pipeline_seconds:.0f}s)",
        ))

    # Examine stage time
    examine_seconds = stage_timings.get("examine", 0.0)
    if examine_seconds > threshold.max_examine_seconds:
        violations.append(SLAViolation(
            metric="examine_seconds",
            actual=examine_seconds,
            limit=threshold.max_examine_seconds,
            message=f"Examine stage took {examine_seconds:.1f}s (limit {threshold.max_examine_seconds:.0f}s)",
        ))

    # Token budget
    if total_tokens > threshold.max_tokens:
        violations.append(SLAViolation(
            metric="total_tokens",
            actual=float(total_tokens),
            limit=float(threshold.max_tokens),
            message=f"Used {total_tokens:,} tokens (limit {threshold.max_tokens:,})",
        ))

    return SLAResult(
        passed=len(violations) == 0,
        page_count=page_count,
        threshold=threshold,
        violations=violations,
    )
