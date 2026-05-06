# ─── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Copy metadata first so the dep-install layer is cached independently of source changes.
COPY pyproject.toml README.md* ./

# Install all dependencies (setuptools finds no packages yet — that's fine; deps still resolve).
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[dev,security]"

# Copy source and link the editable install without re-downloading deps.
COPY . .
RUN pip install --no-cache-dir --no-deps -e .

# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# System deps for FAISS + sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build /app

# Create storage directories
RUN mkdir -p .cognirepo/memory .cognirepo/graph .cognirepo/index \
             .cognirepo/sessions .cognirepo/archive vector_db

# Non-root user for security
RUN useradd -m -u 1001 cognirepo && chown -R cognirepo:cognirepo /app
USER cognirepo

# Environment defaults (override via docker-compose or -e flags)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Default: run init then start MCP server
CMD ["sh", "-c", "cognirepo init --non-interactive && cognirepo serve"]

# Health check (simplified: check if process is alive via status)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD pgrep -f "cognirepo serve" || exit 1
