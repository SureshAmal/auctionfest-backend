# ==============================================================
# AuctionFest Backend — Production Dockerfile
# Build context: backend/ directory
# ==============================================================

# ---- Stage 1: Build dependencies ----
FROM python:3.12-slim AS builder

# Install uv for fast, deterministic installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files (relative to backend/ context)
COPY pyproject.toml uv.lock ./

# Install production dependencies only
RUN uv sync --frozen --no-dev --no-install-project


# ---- Stage 2: Production image ----
FROM python:3.12-slim AS runtime

# System dependencies for asyncpg, opencv, and tesseract
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Ensure the venv is on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy all files from backend/ into /app
# (Context is backend/, so ./ is correct)
COPY --chown=appuser:appuser ./ /app/

# Environment variables
ENV SEED_CSV_PATH="/app/PLANOMIC PLOT DETAILS (2).csv"
ENV PORT=8000
EXPOSE 8000

# Make the startup script executable
RUN chmod +x /app/start.sh

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", 8000)}/api/admin/state')" || exit 1

# Start via entrypoint script
CMD ["bash", "/app/start.sh"]
