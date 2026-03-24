"""Lightweight in-process metrics collector.

Provides Prometheus text exposition format without requiring the prometheus_client
package. Tracks request counts, latency, and pipeline statistics.

Usage:
    from app.core.metrics import metrics
    metrics.inc("http_requests_total", labels={"method": "GET", "path": "/health"})
    metrics.observe("http_request_duration_seconds", 0.042, labels={"method": "GET"})
"""

import time
import threading
from collections import defaultdict


class Metrics:
    """Thread-safe metrics collector with Prometheus text output."""

    def __init__(self):
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, value: float, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._histograms[key].append(value)

    def get_counter(self, name: str, labels: dict | None = None) -> float:
        key = self._key(name, labels)
        with self._lock:
            return self._counters.get(key, 0)

    def expose(self) -> str:
        """Return all metrics in Prometheus text exposition format."""
        lines = []
        with self._lock:
            for key, value in sorted(self._counters.items()):
                lines.append(f"{key} {value}")
            for key, values in sorted(self._histograms.items()):
                if values:
                    count = len(values)
                    total = sum(values)
                    avg = total / count
                    lines.append(f"{key}_count {count}")
                    lines.append(f"{key}_sum {total:.6f}")
                    lines.append(f"{key}_avg {avg:.6f}")
        return "\n".join(lines) + "\n"

    def _key(self, name: str, labels: dict | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# Singleton
metrics = Metrics()
