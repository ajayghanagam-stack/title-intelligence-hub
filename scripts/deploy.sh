#!/usr/bin/env bash
set -euo pipefail

echo "==> Deploying with IMAGE_TAG=${IMAGE_TAG:-latest}"

# Pull new images
echo "==> Pulling images..."
docker compose -f docker-compose.prod.yml pull

# Run database migrations
echo "==> Running migrations..."
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head

# Restart services
echo "==> Starting services..."
docker compose -f docker-compose.prod.yml up -d --remove-orphans

# Health check
echo "==> Waiting for backend health..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        echo "==> Backend healthy after ${i} checks"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "==> ERROR: Backend failed health check after 30 attempts"
        docker compose -f docker-compose.prod.yml logs --tail=50 backend
        exit 1
    fi
    sleep 2
done

# Cleanup old images
echo "==> Pruning old images..."
docker image prune -f --filter "until=168h"

echo "==> Deploy complete!"
