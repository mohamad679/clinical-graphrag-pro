"""
Prometheus metrics helpers and lightweight instrumentation.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from statistics import fmean
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter as _PromCounter, Gauge as _PromGauge, Histogram as _PromHistogram, REGISTRY, generate_latest
    Counter: Any = _PromCounter
    Gauge: Any = _PromGauge
    Histogram: Any = _PromHistogram
except Exception:  # pragma: no cover - dependency availability varies
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _FallbackMetric:
        def __init__(self, name: str, documentation: str, labelnames: tuple[str, ...] = ()):
            self.name = name
            self.documentation = documentation
            self.labelnames = labelnames
            self.samples: dict[tuple[str, ...], float] = {}

        def inc(self, amount: float = 1.0):
            handle = self.labels()
            handle.inc(amount)

        def observe(self, value: float):
            handle = self.labels()
            handle.observe(value)

        def labels(self, *label_values):
            key = tuple(str(value) for value in label_values)
            self.samples.setdefault(key, 0.0)
            return _FallbackMetricHandle(self, key)

    class _FallbackMetricHandle:
        def __init__(self, metric: "_FallbackMetric", key: tuple[str, ...]):
            self.metric = metric
            self.key = key

        def inc(self, amount: float = 1.0):
            self.metric.samples[self.key] = self.metric.samples.get(self.key, 0.0) + amount

        def observe(self, value: float):
            self.metric.samples[self.key] = self.metric.samples.get(self.key, 0.0) + value

        def set(self, value: float):
            self.metric.samples[self.key] = value

    class _FallbackRegistry:
        def __init__(self):
            self._names_to_collectors: dict[str, _FallbackMetric] = {}

    REGISTRY: Any = _FallbackRegistry()

    def _fallback_counter(name: str, documentation: str, labelnames: tuple[str, ...] = ()) -> _FallbackMetric:
        metric = _FallbackMetric(name, documentation, labelnames)
        REGISTRY._names_to_collectors[name] = metric
        return metric

    def _fallback_histogram(name: str, documentation: str, labelnames: tuple[str, ...] = ()) -> _FallbackMetric:
        metric = _FallbackMetric(name, documentation, labelnames)
        REGISTRY._names_to_collectors[name] = metric
        return metric

    def _fallback_gauge(name: str, documentation: str, labelnames: tuple[str, ...] = ()) -> _FallbackMetric:
        metric = _FallbackMetric(name, documentation, labelnames)
        REGISTRY._names_to_collectors[name] = metric
        return metric

    Counter: Any = _fallback_counter
    Histogram: Any = _fallback_histogram
    Gauge: Any = _fallback_gauge

    def generate_latest(registry) -> bytes:
        lines: list[str] = []
        for metric in registry._names_to_collectors.values():
            lines.append(f"# HELP {metric.name} {metric.documentation}")
            lines.append(f"# TYPE {metric.name} gauge")
            if not metric.samples:
                lines.append(f"{metric.name} 0")
                continue
            for labels, value in metric.samples.items():
                if metric.labelnames:
                    rendered_labels = ",".join(
                        f'{name}="{label}"'
                        for name, label in zip(metric.labelnames, labels)
                    )
                    lines.append(f"{metric.name}{{{rendered_labels}}} {value}")
                else:
                    lines.append(f"{metric.name} {value}")
        return ("\n".join(lines) + "\n").encode("utf-8")

try:
    from prometheus_fastapi_instrumentator import Instrumentator
except Exception:  # pragma: no cover - optional runtime enhancement
    Instrumentator = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _existing_metric(name: str):
    return getattr(REGISTRY, "_names_to_collectors", {}).get(name)


def _counter(name: str, documentation: str, labelnames: tuple[str, ...] = ()):
    existing = _existing_metric(name)
    if existing is not None:
        return existing
    return Counter(name, documentation, labelnames=labelnames)


def _histogram(name: str, documentation: str, labelnames: tuple[str, ...] = ()):
    existing = _existing_metric(name)
    if existing is not None:
        return existing
    return Histogram(name, documentation, labelnames=labelnames)


def _gauge(name: str, documentation: str, labelnames: tuple[str, ...] = ()):
    existing = _existing_metric(name)
    if existing is not None:
        return existing
    return Gauge(name, documentation, labelnames=labelnames)


HTTP_REQUEST_DURATION = _histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    labelnames=("method", "path", "status"),
)
CHAT_REQUESTS_TOTAL = _counter("chat_requests_total", "Total number of chat requests.")
DOCUMENT_UPLOADS_TOTAL = _counter("document_uploads_total", "Total number of document uploads.")
AGENT_RUNS_TOTAL = _counter("agent_runs_total", "Total number of agent workflow runs.")
RAG_RETRIEVAL_LATENCY = _histogram(
    "rag_retrieval_latency_seconds",
    "Latency of the retrieval pipeline in seconds.",
)
CHAT_LATENCY = _histogram(
    "chat_latency_seconds",
    "End-to-end chat orchestration latency in seconds.",
    labelnames=("mode",),
)
LLM_CALL_LATENCY = _histogram(
    "llm_call_latency_seconds",
    "Latency of outbound LLM provider calls in seconds.",
    labelnames=("provider", "outcome"),
)
LLM_FAILURES_TOTAL = _counter(
    "llm_failures_total",
    "Total number of failed LLM provider calls.",
    labelnames=("provider",),
)
DOCUMENT_PROCESSING_LATENCY = _histogram(
    "document_processing_latency_seconds",
    "Latency of document processing runs in seconds.",
    labelnames=("outcome",),
)
DOCUMENT_PROCESSING_FAILURES_TOTAL = _counter(
    "document_processing_failures_total",
    "Total number of failed document processing runs.",
)
IMAGE_ANALYSIS_TOTAL = _counter(
    "image_analysis_total",
    "Total number of image analysis runs by outcome.",
    labelnames=("outcome",),
)
IMAGE_ANALYSIS_LATENCY = _histogram(
    "image_analysis_latency_seconds",
    "Latency of image analysis runs in seconds.",
    labelnames=("outcome",),
)
WORKER_QUEUE_DEPTH = _gauge(
    "worker_queue_depth",
    "Active queued/dispatched/running background jobs by task type.",
    labelnames=("task_type",),
)
DB_QUERY_LATENCY = _histogram(
    "db_query_latency_seconds",
    "SQL query latency in seconds.",
    labelnames=("statement_type",),
)
REDIS_OPERATION_LATENCY = _histogram(
    "redis_operation_latency_seconds",
    "Redis operation latency in seconds.",
    labelnames=("command", "outcome"),
)
CACHE_HIT_TOTAL = _counter("cache_hit_total", "Total cache hits.", labelnames=("backend",))
CACHE_MISS_TOTAL = _counter("cache_miss_total", "Total cache misses.", labelnames=("backend",))
CACHE_SET_TOTAL = _counter("cache_set_total", "Total cache set operations.", labelnames=("backend",))
CACHE_DELETE_TOTAL = _counter("cache_delete_total", "Total cache delete operations.", labelnames=("backend",))
CACHE_BACKEND_ERROR_TOTAL = _counter(
    "cache_backend_error_total",
    "Total cache backend errors.",
    labelnames=("backend", "operation"),
)
CACHE_FALLBACK_TOTAL = _counter(
    "cache_fallback_total",
    "Total cache fallback events.",
    labelnames=("from_backend", "to_backend"),
)
CACHE_LATENCY_MS = _histogram(
    "cache_latency_ms",
    "Cache operation latency in milliseconds.",
    labelnames=("backend", "operation"),
)
AUTH_LEGACY_HASH_UPGRADE_TOTAL = _counter(
    "auth_legacy_hash_upgrade_total",
    "Total successful legacy password hash upgrades.",
    labelnames=("from_scheme", "to_scheme"),
)
CELERY_TASK_LATENCY = _histogram(
    "celery_task_latency_seconds",
    "Background task execution latency in seconds.",
    labelnames=("task_type", "outcome"),
)
VECTOR_SEARCH_LATENCY = _histogram(
    "vector_search_latency_seconds",
    "Vector store search latency in seconds.",
    labelnames=("backend",),
)

DENSE_SEARCH_LATENCY = _histogram("dense_search_latency_ms", "FAISS dense search latency in ms.")
SPARSE_SEARCH_LATENCY = _histogram("sparse_search_latency_ms", "BM25 sparse search latency in ms.")
RERANKER_LATENCY = _histogram("reranker_latency_ms", "Cross-Encoder reranker latency in ms.")
GRAPH_QUERY_LATENCY = _histogram("graph_query_latency_ms", "Neo4j/Graph lookup latency in ms.")
LLM_LATENCY = _histogram("llm_latency_ms", "LLM call execution latency in ms.")
RETRIEVED_CHUNKS = _counter("retrieved_chunks_total", "Total number of retrieved chunks.")
CITATIONS_TOTAL = _counter("citations_total", "Total number of citation tags emitted.")
ABSTENTION_TOTAL = _counter("abstention_total", "Total number of agent/RAG abstentions.")
GROUNDING_VALIDATION_TOTAL = _counter(
    "grounding_validation_total",
    "Total number of grounding validation outcomes.",
    labelnames=("outcome",),
)
RAG_REGENERATIONS_TOTAL = _counter(
    "rag_regenerations_total",
    "Total number of RAG regenerations after grounding validation failure.",
)
CITATION_FAILURES_TOTAL = _counter(
    "citation_failures_total",
    "Total number of citation grounding validation failures.",
)
UNSAFE_STREAM_ATTEMPTS_TOTAL = _counter(
    "unsafe_stream_attempts_total",
    "Total number of blocked unsafe streaming attempts.",
)
NO_CONTEXT_TOTAL = _counter("no_context_total", "Total number of queries with empty/insufficient context.")
EVALUATOR_REJECTIONS = _counter("evaluator_rejections_total", "Total number of critic evaluation rejections.")
AGENT_RETRIES = _counter("agent_retries_total", "Total number of agent execution loop retries.")
PROVIDER_ERRORS = _counter("provider_errors_total", "Total number of LLM provider level errors.")
TOKEN_USAGE = _counter("token_usage_total", "Total token usage count by type.", labelnames=("type", "model"))
ESTIMATED_COST = _counter("estimated_cost_usd_total", "Total estimated LLM API cost in USD.")


class OperationalMetricsWindow:
    """Small in-memory rolling window for dashboard summaries."""

    def __init__(self):
        self.chat_latencies = deque(maxlen=500)
        self.retrieval_latencies = deque(maxlen=500)
        self.dense_latencies = deque(maxlen=500)
        self.sparse_latencies = deque(maxlen=500)
        self.rerank_latencies = deque(maxlen=500)
        self.graph_latencies = deque(maxlen=500)
        self.llm_latencies = deque(maxlen=500)
        self.llm_calls = 0
        self.llm_failures = 0
        self.document_runs = 0
        self.document_failures = 0
        self.image_runs = 0
        self.image_successes = 0
        self.queue_depths: dict[str, int] = {}
        self.retrieved_chunks = 0
        self.citations = 0
        self.abstentions = 0
        self.grounding_validation: dict[str, int] = {}
        self.rag_regenerations = 0
        self.citation_failures = 0
        self.unsafe_stream_attempts = 0
        self.no_context_runs = 0
        self.evaluator_rejections = 0
        self.agent_retries = 0
        self.provider_errors = 0
        self.total_tokens: dict[str, int] = {}
        self.estimated_cost_usd = 0.0

    @staticmethod
    def _p95(values: deque[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(int(len(ordered) * 0.95) - 1, 0))
        return float(ordered[index])

    def summary(self) -> dict:
        llm_failure_rate = (self.llm_failures / self.llm_calls) if self.llm_calls else 0.0
        document_failure_rate = (self.document_failures / self.document_runs) if self.document_runs else 0.0
        image_success_rate = (self.image_successes / self.image_runs) if self.image_runs else 0.0
        return {
            "chat_latency_ms_avg": round((fmean(self.chat_latencies) if self.chat_latencies else 0.0) * 1000, 2),
            "chat_latency_ms_p95": round(self._p95(self.chat_latencies) * 1000, 2),
            "retrieval_latency_ms_avg": round((fmean(self.retrieval_latencies) if self.retrieval_latencies else 0.0) * 1000, 2),
            "retrieval_latency_ms_p95": round(self._p95(self.retrieval_latencies) * 1000, 2),
            "dense_search_latency_ms_avg": round(fmean(self.dense_latencies) if self.dense_latencies else 0.0, 2),
            "sparse_search_latency_ms_avg": round(fmean(self.sparse_latencies) if self.sparse_latencies else 0.0, 2),
            "rerank_latency_ms_avg": round(fmean(self.rerank_latencies) if self.rerank_latencies else 0.0, 2),
            "graph_query_latency_ms_avg": round(fmean(self.graph_latencies) if self.graph_latencies else 0.0, 2),
            "llm_latency_ms_avg": round(fmean(self.llm_latencies) if self.llm_latencies else 0.0, 2),
            "llm_failure_rate": round(llm_failure_rate, 4),
            "document_processing_failure_rate": round(document_failure_rate, 4),
            "image_analysis_success_rate": round(image_success_rate, 4),
            "worker_queue_depth": dict(sorted(self.queue_depths.items())),
            "retrieved_chunks_total": self.retrieved_chunks,
            "citations_total": self.citations,
            "abstention_total": self.abstentions,
            "grounding_validation": dict(sorted(self.grounding_validation.items())),
            "rag_regeneration_total": self.rag_regenerations,
            "citation_failure_total": self.citation_failures,
            "unsafe_stream_attempt_total": self.unsafe_stream_attempts,
            "no_context_total": self.no_context_runs,
            "evaluator_rejection_total": self.evaluator_rejections,
            "agent_retry_total": self.agent_retries,
            "provider_error_total": self.provider_errors,
            "token_usage": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
        }


operational_metrics = OperationalMetricsWindow()


def observe_dense_search(duration_ms: float) -> None:
    value = max(duration_ms, 0.0)
    DENSE_SEARCH_LATENCY.observe(value)
    operational_metrics.dense_latencies.append(value)


def observe_sparse_search(duration_ms: float) -> None:
    value = max(duration_ms, 0.0)
    SPARSE_SEARCH_LATENCY.observe(value)
    operational_metrics.sparse_latencies.append(value)


def observe_reranker(duration_ms: float) -> None:
    value = max(duration_ms, 0.0)
    RERANKER_LATENCY.observe(value)
    operational_metrics.rerank_latencies.append(value)


def observe_graph_query(duration_ms: float) -> None:
    value = max(duration_ms, 0.0)
    GRAPH_QUERY_LATENCY.observe(value)
    operational_metrics.graph_latencies.append(value)


def observe_llm_latency(duration_ms: float) -> None:
    value = max(duration_ms, 0.0)
    LLM_LATENCY.observe(value)
    operational_metrics.llm_latencies.append(value)


def record_retrieved_chunks(count: int) -> None:
    RETRIEVED_CHUNKS.inc(count)
    operational_metrics.retrieved_chunks += count


def record_citations(count: int) -> None:
    CITATIONS_TOTAL.inc(count)
    operational_metrics.citations += count


def record_abstention() -> None:
    ABSTENTION_TOTAL.inc()
    operational_metrics.abstentions += 1


def record_grounding_validation(passed: bool) -> None:
    outcome = "passed" if passed else "failed"
    GROUNDING_VALIDATION_TOTAL.labels(outcome).inc()
    operational_metrics.grounding_validation.setdefault(outcome, 0)
    operational_metrics.grounding_validation[outcome] += 1


def record_rag_regeneration() -> None:
    RAG_REGENERATIONS_TOTAL.inc()
    operational_metrics.rag_regenerations += 1


def record_citation_failure(count: int = 1) -> None:
    amount = max(int(count), 1)
    CITATION_FAILURES_TOTAL.inc(amount)
    operational_metrics.citation_failures += amount


def record_blocked_unsafe_stream_attempt() -> None:
    UNSAFE_STREAM_ATTEMPTS_TOTAL.inc()
    operational_metrics.unsafe_stream_attempts += 1


def record_no_context() -> None:
    NO_CONTEXT_TOTAL.inc()
    operational_metrics.no_context_runs += 1


def record_evaluator_rejection() -> None:
    EVALUATOR_REJECTIONS.inc()
    operational_metrics.evaluator_rejections += 1


def record_agent_retry() -> None:
    AGENT_RETRIES.inc()
    operational_metrics.agent_retries += 1


def record_provider_error() -> None:
    PROVIDER_ERRORS.inc()
    operational_metrics.provider_errors += 1


def record_token_usage(prompt_tokens: int, completion_tokens: int, model: str = "unknown") -> None:
    TOKEN_USAGE.labels("prompt", model).inc(prompt_tokens)
    TOKEN_USAGE.labels("completion", model).inc(completion_tokens)
    
    operational_metrics.total_tokens.setdefault("prompt", 0)
    operational_metrics.total_tokens["prompt"] += prompt_tokens
    operational_metrics.total_tokens.setdefault("completion", 0)
    operational_metrics.total_tokens["completion"] += completion_tokens
    
    from app.services.cost_estimator import calculate_llm_cost
    provider = "groq"
    if "gemini" in model.lower() or "google" in model.lower():
        provider = "gemini"
    elif "ollama" in model.lower() or "local" in model.lower() or "llama_cpp" in model.lower():
        provider = "ollama"
        
    cost_val = calculate_llm_cost(provider, model, prompt_tokens, completion_tokens)
    cost = cost_val if isinstance(cost_val, float) else 0.0
    
    ESTIMATED_COST.inc(cost)
    operational_metrics.estimated_cost_usd += cost



def mark_chat_request() -> None:
    CHAT_REQUESTS_TOTAL.inc()


def observe_chat_latency(duration_seconds: float, *, mode: str = "sync") -> None:
    value = max(duration_seconds, 0.0)
    CHAT_LATENCY.labels(mode).observe(value)
    operational_metrics.chat_latencies.append(value)


def mark_document_upload() -> None:
    DOCUMENT_UPLOADS_TOTAL.inc()


def mark_agent_run() -> None:
    AGENT_RUNS_TOTAL.inc()


def observe_rag_retrieval(duration_seconds: float) -> None:
    value = max(duration_seconds, 0.0)
    RAG_RETRIEVAL_LATENCY.observe(value)
    operational_metrics.retrieval_latencies.append(value)


def observe_llm_call(provider: str, duration_seconds: float, *, success: bool) -> None:
    outcome = "success" if success else "failure"
    duration = max(duration_seconds, 0.0)
    LLM_CALL_LATENCY.labels(provider, outcome).observe(duration)
    operational_metrics.llm_calls += 1
    if not success:
        LLM_FAILURES_TOTAL.labels(provider).inc()
        operational_metrics.llm_failures += 1


def observe_document_processing(duration_seconds: float, *, success: bool) -> None:
    outcome = "success" if success else "failure"
    duration = max(duration_seconds, 0.0)
    DOCUMENT_PROCESSING_LATENCY.labels(outcome).observe(duration)
    operational_metrics.document_runs += 1
    if not success:
        DOCUMENT_PROCESSING_FAILURES_TOTAL.inc()
        operational_metrics.document_failures += 1


def observe_image_analysis(duration_seconds: float, *, success: bool) -> None:
    outcome = "success" if success else "failure"
    duration = max(duration_seconds, 0.0)
    IMAGE_ANALYSIS_TOTAL.labels(outcome).inc()
    IMAGE_ANALYSIS_LATENCY.labels(outcome).observe(duration)
    operational_metrics.image_runs += 1
    if success:
        operational_metrics.image_successes += 1


def observe_db_query(duration_seconds: float, *, statement_type: str) -> None:
    DB_QUERY_LATENCY.labels(statement_type).observe(max(duration_seconds, 0.0))


def observe_redis_operation(duration_seconds: float, *, command: str, success: bool) -> None:
    REDIS_OPERATION_LATENCY.labels(command.upper(), "success" if success else "failure").observe(
        max(duration_seconds, 0.0)
    )


def observe_cache_operation(
    duration_ms: float,
    *,
    backend: str,
    operation: str,
    outcome: str | None = None,
) -> None:
    CACHE_LATENCY_MS.labels(backend, operation).observe(max(duration_ms, 0.0))
    if outcome == "hit":
        CACHE_HIT_TOTAL.labels(backend).inc()
    elif outcome == "miss":
        CACHE_MISS_TOTAL.labels(backend).inc()
    elif outcome == "set":
        CACHE_SET_TOTAL.labels(backend).inc()
    elif outcome == "delete":
        CACHE_DELETE_TOTAL.labels(backend).inc()


def record_cache_backend_error(*, backend: str, operation: str) -> None:
    CACHE_BACKEND_ERROR_TOTAL.labels(backend, operation).inc()


def record_cache_fallback(*, from_backend: str, to_backend: str) -> None:
    CACHE_FALLBACK_TOTAL.labels(from_backend, to_backend).inc()


def record_auth_legacy_hash_upgrade(*, from_scheme: str, to_scheme: str) -> None:
    AUTH_LEGACY_HASH_UPGRADE_TOTAL.labels(from_scheme, to_scheme).inc()


def observe_celery_task(duration_seconds: float, *, task_type: str, success: bool) -> None:
    CELERY_TASK_LATENCY.labels(task_type, "success" if success else "failure").observe(
        max(duration_seconds, 0.0)
    )


def observe_vector_search(duration_seconds: float, *, backend: str) -> None:
    VECTOR_SEARCH_LATENCY.labels(backend).observe(max(duration_seconds, 0.0))


def set_worker_queue_depth(task_type: str, depth: int) -> None:
    WORKER_QUEUE_DEPTH.labels(task_type).set(max(depth, 0))
    operational_metrics.queue_depths[task_type] = max(depth, 0)


async def refresh_worker_queue_depths() -> dict[str, int]:
    from sqlalchemy import func, select

    from app.core.database import async_session_factory
    from app.models.persistence import JobRun

    depths: dict[str, int] = {}
    try:
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(JobRun.job_type, func.count(JobRun.id))
                    .where(JobRun.status.in_(("queued", "dispatched", "running", "retry_scheduled", "cancelling")))
                    .group_by(JobRun.job_type)
                )
            ).all()
        for job_type, count in rows:
            depths[str(job_type)] = int(count)
    except Exception as exc:  # pragma: no cover - depends on runtime DB availability
        logger.debug("Unable to refresh worker queue depths: %s", exc)

    for task_type in ("document_processing", "image_analysis", "audio_transcription", "evaluation_run", "retention_purge"):
        set_worker_queue_depth(task_type, depths.get(task_type, 0))
    return dict(sorted(depths.items()))


async def collect_operational_metrics_summary() -> dict:
    await refresh_worker_queue_depths()
    return operational_metrics.summary()


async def metrics_response() -> Response:
    await refresh_worker_queue_depths()
    payload = generate_latest(REGISTRY)
    return PlainTextResponse(payload.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


def _normalize_path(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if route_path:
        return str(route_path)
    return request.url.path


def configure_metrics(app: FastAPI) -> None:
    """Attach metrics middleware and the /metrics endpoint once."""
    if getattr(app.state, "metrics_configured", False):
        return

    if Instrumentator is not None:
        try:
            Instrumentator(
                should_group_status_codes=False,
                should_ignore_untemplated=True,
                should_respect_env_var=False,
            ).instrument(app)
        except Exception as exc:  # pragma: no cover - optional enhancement only
            logger.warning("Prometheus instrumentator unavailable: %s", exc)

    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next: Callable):
        started = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - started
        HTTP_REQUEST_DURATION.labels(
            request.method,
            _normalize_path(request),
            str(response.status_code),
        ).observe(duration)
        return response

    app.add_api_route("/metrics", metrics_response, methods=["GET"], include_in_schema=False)
    app.state.metrics_configured = True
