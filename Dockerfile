# ==============================================================
# AuctionFest Backend — Production Dockerfile
# Multi-stage build using uv for fast dependency resolution
# Optimized for Render deployment with managed PostgreSQL
#
# Build context: repository root (set in docker-compose.yml and render.yaml)
# ==============================================================

# ---- Stage 1: Build dependencies ----
FROM python:3.12-slim AS builder

# Install uv for fast, deterministic installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first for layer caching
COPY backend/pyproject.toml backend/uv.lock ./

# Install production dependencies only (skip dev/test deps)
RUN uv sync --frozen --no-dev --no-install-project


# ---- Stage 2: Production image ----
FROM python:3.12-slim AS runtime

# System dependencies required at runtime:
#   - libpq5: PostgreSQL client library (asyncpg)
#   - tesseract-ocr: OCR engine (pytesseract)
#   - libgl1: OpenGL support (opencv-python-headless)
#   - libglib2.0-0: GLib (opencv dependency)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Ensure the venv is on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy application source code (the CSV seed file is inside backend/ now)
COPY backend/ /app/

# Set seed CSV path (CSV is copied with the backend source above)
ENV SEED_CSV_PATH="/app/PLANOMIC PLOT DETAILS (2).csv"

# Expose the backend port
EXPOSE 8000

# Switch to non-root user
USER appuser

# Health check — hit the admin state endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/admin/state')" || exit 1

# Start uvicorn with single worker (required for Socket.IO without Redis)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]
