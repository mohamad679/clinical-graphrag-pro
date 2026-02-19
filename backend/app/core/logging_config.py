"""
Structured JSON Logging with Request Tracing.
Production-ready logging configuration.
"""

import json
import logging
import sys
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request context if available
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if hasattr(record, "method"):
            log_entry["method"] = record.method
        if hasattr(record, "path"):
            log_entry["path"] = record.path
        if hasattr(record, "status_code"):
            log_entry["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if hasattr(record, "client_ip"):
            log_entry["client_ip"] = record.client_ip

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


class RequestMetrics:
    """Track request metrics for the admin dashboard."""

    def __init__(self):
        self.total_requests: int = 0
        self.total_errors: int = 0
        self.status_counts: dict[int, int] = {}
        self.latencies: list[float] = []  # Last 1000 latencies in ms
        self.endpoint_counts: dict[str, int] = {}

    def record(self, path: str, status_code: int, duration_ms: float):
        self.total_requests += 1
        if status_code >= 400:
            self.total_errors += 1
        self.status_counts[status_code] = self.status_counts.get(status_code, 0) + 1
        self.endpoint_counts[path] = self.endpoint_counts.get(path, 0) + 1
        self.latencies.append(duration_ms)
        if len(self.latencies) > 1000:
            self.latencies = self.latencies[-1000:]

    def get_summary(self) -> dict:
        avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0
        p95_latency = sorted(self.latencies)[int(len(self.latencies) * 0.95)] if len(self.latencies) > 10 else avg_latency
        error_rate = (self.total_errors / self.total_requests * 100) if self.total_requests > 0 else 0

        return {
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate_pct": round(error_rate, 2),
            "avg_latency_ms": round(avg_latency, 1),
            "p95_latency_ms": round(p95_latency, 1),
            "status_counts": dict(sorted(self.status_counts.items())),
            "top_endpoints": dict(
                sorted(self.endpoint_counts.items(), key=lambda x: -x[1])[:10]
            ),
        }


# Module-level singleton
request_metrics = RequestMetrics()


def setup_logging(json_output: bool = False):
    """Configure application logging."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Clear existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
        )

    root.addHandler(handler)

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with timing and capture metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())[:8]
        client_ip = request.client.host if request.client else "unknown"
        start = time.monotonic()

        # Attach request_id to request state for downstream use
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000
            request_metrics.record(request.url.path, 500, duration_ms)
            raise

        duration_ms = (time.monotonic() - start) * 1000

        # Record metrics
        request_metrics.record(request.url.path, response.status_code, duration_ms)

        # Log request (skip health checks for noise reduction)
        if not request.url.path.endswith("/health"):
            logger = logging.getLogger("http")
            logger.info(
                f"{request.method} {request.url.path} → {response.status_code} ({duration_ms:.0f}ms)",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 1),
                    "client_ip": client_ip,
                },
            )

        # Add headers
        response.headers["X-Request-ID"] = request_id
        return response
