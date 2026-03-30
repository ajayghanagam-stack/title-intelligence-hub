#!/bin/bash
# =============================================================================
# HOT-PATCH: Push local file changes to running ECS container (~30 sec)
# =============================================================================
# Usage:
#   ./scripts/hot-patch.sh <local-file> [<local-file2> ...]
#
# Examples:
#   ./scripts/hot-patch.sh backend/app/micro_apps/title_search/pipeline/orchestrator.py
#   ./scripts/hot-patch.sh backend/app/ai/base_service.py backend/app/config.py
#
# What it does:
#   1. Base64-encodes each local file
#   2. Writes it into the running ECS backend container via SSM exec
#   3. Sends SIGHUP to gunicorn (PID 1) to gracefully reload workers
#
# Prerequisites:
#   - AWS CLI configured with correct credentials
#   - session-manager-plugin installed (brew install --cask session-manager-plugin)
#   - ECS exec enabled on the service (already done)
#
# NOTE: Changes are EPHEMERAL — they survive until the next ECS deployment.
#       Always commit and push to git so the next docker build includes your fix.
# =============================================================================

set -euo pipefail

CLUSTER="title-intelligence-cluster"
SERVICE="title-intelligence-service"
CONTAINER="backend"

if [ $# -eq 0 ]; then
    echo "Usage: $0 <local-file> [<local-file2> ...]"
    echo ""
    echo "Example: $0 backend/app/micro_apps/title_search/pipeline/orchestrator.py"
    exit 1
fi

# Get the running task ARN
echo "Finding running task..."
TASK_ARN=$(aws ecs list-tasks \
    --cluster "$CLUSTER" \
    --service-name "$SERVICE" \
    --query 'taskArns[0]' \
    --output text 2>/dev/null)

if [ "$TASK_ARN" = "None" ] || [ -z "$TASK_ARN" ]; then
    echo "ERROR: No running task found in $CLUSTER/$SERVICE"
    exit 1
fi
echo "Task: ${TASK_ARN##*/}"

# Patch each file
for LOCAL_FILE in "$@"; do
    if [ ! -f "$LOCAL_FILE" ]; then
        echo "ERROR: File not found: $LOCAL_FILE"
        exit 1
    fi

    # Convert local path to container path
    # backend/app/foo.py -> app/foo.py (strip "backend/" prefix)
    CONTAINER_PATH="${LOCAL_FILE#backend/}"

    FILE_SIZE=$(wc -c < "$LOCAL_FILE" | tr -d ' ')
    echo ""
    echo "Patching: $CONTAINER_PATH ($FILE_SIZE bytes)"

    # Base64 encode the file and write it in the container
    B64=$(base64 < "$LOCAL_FILE")

    aws ecs execute-command \
        --cluster "$CLUSTER" \
        --task "$TASK_ARN" \
        --container "$CONTAINER" \
        --interactive \
        --command "python3 -c \"
import base64, pathlib, sys
data = base64.b64decode('''$B64''')
p = pathlib.Path('$CONTAINER_PATH')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(data)
print(f'OK: {len(data)} bytes -> $CONTAINER_PATH')
\"" 2>&1 | grep -E "^OK:|^ERROR" || true
done

# Clear bytecode cache and force full gunicorn restart (SIGUSR2 re-execs master)
echo ""
echo "Clearing pycache and restarting gunicorn..."
aws ecs execute-command \
    --cluster "$CLUSTER" \
    --task "$TASK_ARN" \
    --container "$CONTAINER" \
    --interactive \
    --command "python3 -c \"
import os, signal, glob, shutil
for d in glob.glob('**/__pycache__', recursive=True):
    shutil.rmtree(d, ignore_errors=True)
os.kill(1, signal.SIGUSR2)
print('Restarted')
\"" 2>&1 | grep -E "^Restarted|^ERROR" || true

# Wait for workers to come back up
echo "Waiting for health check..."
sleep 8
for i in 1 2 3 4 5; do
    if curl -sf http://title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com/api/v1/health > /dev/null 2>&1; then
        echo "Healthy!"
        break
    fi
    sleep 3
done

echo ""
echo "Done! Changes are live. Test at:"
echo "  http://title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com"
echo ""
echo "REMINDER: Commit and push to git so the next docker build includes your fix."
