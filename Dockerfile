# Build context: backend/ directory
# ==============================================================

# ---- Stage 1: Build dependencies ----
FROM python:3.12-slim AS builder

# Install uv for fast, deterministic installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first (relative to backend/ context)
COPY pyproject.toml uv.lock ./

# Install production dependencies only (skip dev/test deps)
RUN uv sync --frozen --no-dev --no-install-project


# ---- Stage 2: Production image ----
FROM python:3.12-slim AS runtime

# System dependencies required at runtime
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

# Copy application source code with correct ownership
# Context is backend/, so copy everything into /app
COPY --chown=appuser:appuser ./ /app/

ENV SEED_CSV_PATH="/app/PLANOMIC PLOT DETAILS (2).csv"

# Make the startup script executable
RUN chmod +x /app/start.sh

# Railway provides PORT env var
ENV PORT=8000
EXPOSE 8000

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", 8000)}/api/admin/state')" || exit 1

# Start via entrypoint script
CMD ["bash", "/app/start.sh"]

