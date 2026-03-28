"""Benchmark metrics collection and reporting.

Extracts timing and token-usage data from PipelineRun records and
formats human-readable pass/fail reports against SLA thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from benchmarks.sla import SLAResult, SLAThreshold, check_sla


@dataclass
class BenchmarkMetrics:
    """Metrics collected from a single pipeline run."""

    page_count: int
    stage_timings: dict[str, float] = field(default_factory=dict)
    total_seconds: float = 0.0
    examine_seconds: float = 0.0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    batch_count: int = 0
    rate_limit_hits: int = 0


def collect_metrics_from_version_metadata(
    version_metadata: dict[str, Any] | None,
    page_count: int,
) -> BenchmarkMetrics:
    """Build ``BenchmarkMetrics`` from a PipelineRun's ``version_metadata``.

    This is the primary way to extract metrics — it reads the
    ``stage_timings``, ``total_elapsed_seconds``, and batch-level
    token counts that the orchestrator writes into ``version_metadata``.
    """
    meta = version_metadata or {}
    stage_timings = meta.get("stage_timings", {})

    # Aggregate token usage from batch results stored in metadata
    batch_results = meta.get("batch_results", [])
    input_tokens = sum(b.get("input_tokens", 0) for b in batch_results)
    output_tokens = sum(b.get("output_tokens", 0) for b in batch_results)
    total_tokens = meta.get("total_tokens", input_tokens + output_tokens)
    rate_limit_hits = meta.get("rate_limit_hits", 0)

    return BenchmarkMetrics(
        page_count=page_count,
        stage_timings=stage_timings,
        total_seconds=meta.get("total_elapsed_seconds", sum(stage_timings.values())),
        examine_seconds=stage_timings.get("examine", 0.0),
        total_tokens=total_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        batch_count=len(batch_results),
        rate_limit_hits=rate_limit_hits,
    )


def check_metrics(metrics: BenchmarkMetrics, threshold: SLAThreshold | None = None) -> SLAResult:
    """Run SLA check on collected metrics."""
    return check_sla(
        stage_timings=metrics.stage_timings,
        total_tokens=metrics.total_tokens,
        page_count=metrics.page_count,
        threshold=threshold,
    )


def format_report(metrics: BenchmarkMetrics, sla_result: SLAResult) -> str:
    """Format a human-readable benchmark report."""
    lines: list[str] = []
    status = "PASS" if sla_result.passed else "FAIL"
    lines.append(f"=== Benchmark Report ({metrics.page_count} pages) — {status} ===")
    lines.append("")

    # Timing breakdown
    lines.append("Stage timings:")
    for stage, elapsed in metrics.stage_timings.items():
        lines.append(f"  {stage:>10s}: {elapsed:6.2f}s")
    lines.append(f"  {'TOTAL':>10s}: {metrics.total_seconds:6.2f}s  (limit {sla_result.threshold.max_pipeline_seconds:.0f}s)")
    lines.append("")

    # Token usage
    lines.append("Token usage:")
    lines.append(f"  Input:  {metrics.input_tokens:>8,}")
    lines.append(f"  Output: {metrics.output_tokens:>8,}")
    lines.append(f"  Total:  {metrics.total_tokens:>8,}  (limit {sla_result.threshold.max_tokens:,})")
    lines.append("")

    # Batch info
    if metrics.batch_count:
        lines.append(f"Batches: {metrics.batch_count}  |  Rate-limit hits: {metrics.rate_limit_hits}")
        lines.append("")

    # Violations
    if sla_result.violations:
        lines.append("VIOLATIONS:")
        for v in sla_result.violations:
            lines.append(f"  - {v.message}")
        lines.append("")

    return "\n".join(lines)
