# ══════════════════════════════════════════════════════════════
#  Clinical GraphRAG Pro — Backend (CPU-only build)
#  No CUDA / NVIDIA drivers pulled in.
# ══════════════════════════════════════════════════════════════

# ── Stage 1: dependency builder ───────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Build tools needed to compile some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install setuptools so legacy packages (setup.py) build
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .

# ── Install ALL packages into /install with CPU-only torch ─────
# Install torch FIRST (still into /install) so sentence-transformers
# uses the 186 MB CPU wheel instead of the 3 GB CUDA variant.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    --default-timeout=600 \
    --retries=5 \
    --prefix=/install \
    torch==2.2.2+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Install the rest of requirements, also into /install.
# torch is now "satisfied" FROM /install, so pip won't re-add CUDA build.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    --default-timeout=600 \
    --retries=5 \
    --prefix=/install \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# ── Stage 2: lean production image ────────────────────────────
FROM python:3.12-slim AS production

WORKDIR /app

# Copy only the installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Runtime directories + non-root user
RUN mkdir -p uploads data/vector_store data/adapters \
    && adduser --disabled-password --no-create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
