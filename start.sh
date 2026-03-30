#!/usr/bin/env bash
# Replit startup: runs FastAPI backend + Next.js frontend together
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

PIDS=()
cleanup() {
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  exit 0
}
trap cleanup SIGINT SIGTERM

# Create storage directory if it doesn't exist
mkdir -p "$ROOT_DIR/storage"

# Run database migrations
echo "Running database migrations..."
cd "$BACKEND_DIR"
PYTHONPATH="$BACKEND_DIR" python -m alembic upgrade head 2>&1 || echo "Migration warning (may already be up to date)"

# Seed the database (idempotent)
echo "Seeding database..."
PYTHONPATH="$BACKEND_DIR" python scripts/seed.py 2>&1 || echo "Seed warning (may already be seeded)"

# Start backend API on port 8000
echo "Starting backend on port 8000..."
cd "$BACKEND_DIR"
PYTHONPATH="$BACKEND_DIR" uvicorn app.main:app --host 0.0.0.0 --port 8000 &
PIDS+=($!)

# Start frontend on port 5000
echo "Starting frontend on port 5000..."
cd "$FRONTEND_DIR"
npm run dev &
PIDS+=($!)

echo "Services starting — frontend at :5000, backend at :8000"
wait
