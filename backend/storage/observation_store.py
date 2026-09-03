"""
Compact Observation Store for CausalGuard.
Maintains rolling windows of normalized metrics, traces, and logs.
Produces lightweight, high-density observation keys (OBSK_*) so agents
consume only relevant signals without context waste.
"""

import time
from collections import defaultdict

from backend.models.schema import LogEntry, MetricSample, ObservationSnapshot, TraceSpan


class ObservationStore:
    def __init__(self):
        self._observations: dict[str, ObservationSnapshot] = {}
        self._metric_history: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self._trace_history: list[TraceSpan] = []
        self._log_history: list[LogEntry] = []
        self._active_risks: dict[str, dict] = {}

    def put_observation(self, obs: ObservationSnapshot) -> None:
        self._observations[obs.id] = obs

    def get_observation(self, obs_id: str) -> ObservationSnapshot | None:
        return self._observations.get(obs_id)

    def list_observations(
        self, category: str | None = None, source: str | None = None, limit: int = 50
    ) -> list[ObservationSnapshot]:
        results = list(self._observations.values())
        if category:
            results = [o for o in results if o.category == category]
        if source:
            results = [o for o in results if o.source == source]
        # Sort by timestamp descending
        results.sort(key=lambda x: x.timestamp, reverse=True)
        return results[:limit]

    def record_metric(self, sample: MetricSample) -> None:
        key = f"{sample.source}:{sample.name}"
        self._metric_history[key].append((sample.timestamp, sample.value))
        # Keep last 1 hour of samples (max 1000 items)
        if len(self._metric_history[key]) > 1000:
            self._metric_history[key] = self._metric_history[key][-1000:]

    def get_metric_series(
        self, source: str, metric_name: str, window_seconds: int = 900
    ) -> list[tuple[float, float]]:
        key = f"{source}:{metric_name}"
        now = time.time()
        cutoff = now - window_seconds
        return [(ts, val) for ts, val in self._metric_history[key] if ts >= cutoff]

    def record_trace(self, span: TraceSpan) -> None:
        self._trace_history.append(span)
        if len(self._trace_history) > 2000:
            self._trace_history = self._trace_history[-2000:]

    def get_traces(
        self, service_name: str | None = None, errors_only: bool = False, limit: int = 100
    ) -> list[TraceSpan]:
        traces = self._trace_history
        if service_name:
            traces = [t for t in traces if t.service_name == service_name]
        if errors_only:
            traces = [t for t in traces if t.error]
        return traces[-limit:]

    def record_log(self, log: LogEntry) -> None:
        self._log_history.append(log)
        if len(self._log_history) > 2000:
            self._log_history = self._log_history[-2000:]

    def get_logs(
        self, service_name: str | None = None, level: str | None = None, limit: int = 100
    ) -> list[LogEntry]:
        logs = self._log_history
        if service_name:
            logs = [entry for entry in logs if entry.service_name == service_name]
        if level:
            logs = [entry for entry in logs if entry.level == level]
        return logs[-limit:]

    def clear(self) -> None:
        self._observations.clear()
        self._metric_history.clear()
        self._trace_history.clear()
        self._log_history.clear()
        self._active_risks.clear()


global_observation_store = ObservationStore()
