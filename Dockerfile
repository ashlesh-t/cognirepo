# ─── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY . .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]" && \
    pip install --no-cache-dir grpcio grpcio-tools

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
ENV COGNIREPO_MULTI_AGENT_ENABLED=false \
    COGNIREPO_GRPC_ENABLED=false \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Ports: 8080 = FastAPI REST, 50051 = gRPC
EXPOSE 8080 50051

# Default: run init then start REST API + MCP server
# Use CMD override for specific services (see docker-compose.yml)
CMD ["sh", "-c", "cognirepo init --password ${COGNIREPO_PASSWORD:-changeme} && uvicorn api.main:app --host 0.0.0.0 --port 8080"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
