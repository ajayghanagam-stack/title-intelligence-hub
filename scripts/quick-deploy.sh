#!/usr/bin/env bash
set -euo pipefail

# Quick deploy: push code, rebuild on server, skip CI/CD pipeline
# Usage: ./scripts/quick-deploy.sh [commit message]

SERVER="deploy@37.27.210.85"
APP_DIR="/opt/title-intelligence-hub"

MSG="${1:-Quick deploy}"

echo "==> Committing..."
git add -A
git commit -m "$MSG [skip ci]" || echo "Nothing to commit"

echo "==> Pushing to GitHub (CI skipped)..."
git push origin main

echo "==> Syncing files to server..."
rsync -avz --exclude='node_modules' --exclude='.next' --exclude='__pycache__' --exclude='.venv' --exclude='storage' \
    docker-compose.prod.yml Caddyfile scripts/deploy.sh \
    "$SERVER:$APP_DIR/"

echo "==> Rebuilding and restarting on server..."
ssh "$SERVER" "cd $APP_DIR && docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d --remove-orphans"

echo "==> Done!"
