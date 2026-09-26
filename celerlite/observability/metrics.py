"""In-memory metrics counters for throughput and latency tracking."""

import time
from collections import deque
from threading import Lock
from typing import Deque


class MetricsCollector:
    """Thread-safe in-memory metrics for the CelerLite system."""

    def __init__(self, window_seconds: int = 300):
        self._lock = Lock()
        self._window = window_seconds
        # Each entry is (timestamp, duration_ms)
        self._completed: Deque[tuple[float, float]] = deque()
        self._failed: Deque[float] = deque()
        self._submitted_total: int = 0
        self._completed_total: int = 0
        self._failed_total: int = 0
        self._dead_lettered_total: int = 0
        self._start_time: float = time.time()

    def record_submitted(self) -> None:
        with self._lock:
            self._submitted_total += 1

    def record_completed(self, duration_ms: float) -> None:
        with self._lock:
            now = time.time()
            self._completed.append((now, duration_ms))
            self._completed_total += 1
            self._evict(now)

    def record_failed(self) -> None:
        with self._lock:
            now = time.time()
            self._failed.append(now)
            self._failed_total += 1
            self._evict(now)

    def record_dead_lettered(self) -> None:
        with self._lock:
            self._dead_lettered_total += 1

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        while self._completed and self._completed[0][0] < cutoff:
            self._completed.popleft()
        while self._failed and self._failed[0] < cutoff:
            self._failed.popleft()

    def get_snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            self._evict(now)

            durations = [d for _, d in self._completed]
            window_completed = len(durations)
            throughput = window_completed / self._window if self._window > 0 else 0

            avg_latency = sum(durations) / len(durations) if durations else 0.0
            p99_latency = 0.0
            if durations:
                sorted_d = sorted(durations)
                idx = max(0, int(len(sorted_d) * 0.99) - 1)
                p99_latency = sorted_d[idx]

            return {
                "submitted_total": self._submitted_total,
                "completed_total": self._completed_total,
                "failed_total": self._failed_total,
                "dead_lettered_total": self._dead_lettered_total,
                "throughput_per_sec": round(throughput, 2),
                "avg_latency_ms": round(avg_latency, 2),
                "p99_latency_ms": round(p99_latency, 2),
                "uptime_seconds": int(now - self._start_time),
            }


# Global singleton
metrics = MetricsCollector()
