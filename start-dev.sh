#!/usr/bin/env bash
#
# Start the full Title Intelligence Hub dev stack.
# Supports both Title Intelligence (TI) and Title Search & Abstracting (TSA).
#
# Infrastructure (Postgres + Temporal) runs in Docker.
# Backend, Temporal worker, and frontend run locally for fast reloads.
#
# Usage:  ./start-dev.sh
# Stop:   Ctrl+C (kills all child processes)

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Track child PIDs for cleanup
PIDS=()
cleanup() {
  echo ""
  echo -e "${YELLOW}Shutting down...${NC}"
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  docker compose -f "$ROOT_DIR/docker-compose.yml" stop db temporal temporal-ui 2>/dev/null || true
  echo -e "${GREEN}All stopped.${NC}"
  exit 0
}
trap cleanup SIGINT SIGTERM

# ------------------------------------------------------------------
# 0. Kill stale processes, clear caches, terminate orphan workflows
# ------------------------------------------------------------------
echo -e "${CYAN}[0/5] Cleaning up stale state...${NC}"

# Kill any orphaned Temporal worker processes from previous sessions
STALE_PIDS=$(pgrep -f "temporal_worker" 2>/dev/null || true)
if [ -n "$STALE_PIDS" ]; then
  echo -e "${YELLOW}       Killing stale Temporal worker(s): $STALE_PIDS${NC}"
  echo "$STALE_PIDS" | xargs kill 2>/dev/null || true
  sleep 2
  # Force-kill any that didn't exit gracefully
  REMAINING=$(pgrep -f "temporal_worker" 2>/dev/null || true)
  if [ -n "$REMAINING" ]; then
    echo -e "${YELLOW}       Force-killing stubborn worker(s): $REMAINING${NC}"
    echo "$REMAINING" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
fi

# Kill any orphaned uvicorn processes on port 8000
STALE_UVICORN=$(lsof -ti :8000 2>/dev/null || true)
if [ -n "$STALE_UVICORN" ]; then
  echo -e "${YELLOW}       Killing stale process(es) on port 8000: $STALE_UVICORN${NC}"
  echo "$STALE_UVICORN" | xargs kill 2>/dev/null || true
  sleep 1
fi

# Clear Python bytecode caches to ensure fresh imports
echo -e "${CYAN}       Clearing __pycache__...${NC}"
find "$BACKEND_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo -e "${GREEN}       Cleanup complete${NC}"

# ------------------------------------------------------------------
# 1. Start infrastructure (Postgres + Temporal) in Docker
# ------------------------------------------------------------------
echo -e "${CYAN}[1/5] Starting Postgres + Temporal (Docker)...${NC}"
docker compose -f "$ROOT_DIR/docker-compose.yml" up -d db temporal temporal-ui

# Wait for Postgres
echo -e "${CYAN}       Waiting for Postgres...${NC}"
until docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T db pg_isready -U postgres > /dev/null 2>&1; do
  sleep 1
done
echo -e "${GREEN}       Postgres ready on localhost:5436${NC}"

# Wait for Temporal (check from host side — port 7233 must be reachable)
echo -e "${CYAN}       Waiting for Temporal on localhost:7233...${NC}"
for i in $(seq 1 90); do
  if nc -z localhost 7233 2>/dev/null; then
    # Port open — give Temporal a few more seconds to fully initialize
    sleep 3
    echo -e "${GREEN}       Temporal ready on localhost:7233${NC}"
    break
  fi
  if [ "$i" -eq 90 ]; then
    echo -e "${YELLOW}       WARNING: Temporal may not be ready yet (timed out)${NC}"
  fi
  sleep 2
done

# Terminate any orphaned Temporal workflows (now that Temporal is up)
echo -e "${CYAN}       Terminating stale Temporal workflows...${NC}"
cd "$BACKEND_DIR"
PYTHONPATH="$BACKEND_DIR" python -c "
import asyncio
from temporalio.client import Client

async def cleanup():
    client = await Client.connect('localhost:7233', namespace='default')
    count = 0
    async for wf in client.list_workflows(query=\"ExecutionStatus='Running'\"):
        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
        await handle.terminate(reason='Stale workflow terminated by start-dev.sh')
        count += 1
    if count:
        print(f'       Terminated {count} stale workflow(s)')
    else:
        print('       No stale workflows found')

asyncio.run(cleanup())
" 2>/dev/null || echo -e "${YELLOW}       Could not check Temporal workflows (non-fatal)${NC}"

# ------------------------------------------------------------------
# 2. Seed the database
# ------------------------------------------------------------------
echo -e "${CYAN}[2/5] Seeding database...${NC}"
cd "$BACKEND_DIR"
PYTHONPATH="$BACKEND_DIR" python scripts/seed.py
echo -e "${GREEN}       Seed complete${NC}"

# ------------------------------------------------------------------
# 3. Start backend (uvicorn with hot-reload)
# ------------------------------------------------------------------
echo -e "${CYAN}[3/5] Starting backend on http://localhost:8000 ...${NC}"
cd "$BACKEND_DIR"
PYTHONPATH="$BACKEND_DIR" uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
PIDS+=($!)

# ------------------------------------------------------------------
# 4. Start Temporal worker
# ------------------------------------------------------------------
echo -e "${CYAN}[4/5] Starting Temporal worker...${NC}"
cd "$BACKEND_DIR"
PYTHONPATH="$BACKEND_DIR" python -m app.micro_apps.title_intelligence.pipeline.temporal_worker &
PIDS+=($!)

# ------------------------------------------------------------------
# 5. Start frontend (Next.js dev server)
# ------------------------------------------------------------------
echo -e "${CYAN}[5/5] Starting frontend on http://localhost:3000 ...${NC}"
cd "$FRONTEND_DIR"
# Clean stale .next cache to prevent MODULE_NOT_FOUND errors
if [ -d ".next" ]; then
  echo -e "${YELLOW}       Clearing .next cache...${NC}"
  rm -rf .next
fi
npm run dev &
PIDS+=($!)

# ------------------------------------------------------------------
echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN} All services running!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo -e "  UI:          ${CYAN}http://localhost:3000${NC}"
echo -e "  API:         ${CYAN}http://localhost:8000${NC}"
echo -e "  API Docs:    ${CYAN}http://localhost:8000/docs${NC}"
echo -e "  Temporal UI: ${CYAN}http://localhost:8085${NC}"
echo -e "  DB:          ${CYAN}localhost:5436${NC}"
echo ""
echo -e "  Login:       admin@logikality.com / admin123"
echo ""
echo -e "  Apps:"
echo -e "    Title Intelligence:          ${CYAN}http://localhost:3000/apps/title-intelligence${NC}"
echo -e "    Title Search & Abstracting:  ${CYAN}http://localhost:3000/apps/title-search${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"

# Wait for any child to exit
wait
