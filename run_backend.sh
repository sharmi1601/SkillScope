#!/usr/bin/env bash
# Boot the FastAPI backend for the hackathon demo.
#   ./run_backend.sh        → port 8000, --reload
#   PORT=9000 ./run_backend.sh
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
exec uvicorn src.api:app --reload --port "$PORT"
