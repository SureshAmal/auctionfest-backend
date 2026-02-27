#!/bin/bash
# ==============================================================
# AuctionFest — Docker Entrypoint
# Starts uvicorn server.
# ==============================================================

echo "=== System Info ==="
echo "User: $(whoami)"
echo "Working directory: $(pwd)"
echo "Files in /app:"
ls -F /app

echo "Starting uvicorn server on port ${PORT:-8000}..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --log-level info