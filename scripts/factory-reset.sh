#!/usr/bin/env bash
set -euo pipefail

echo "========================================="
echo "  FACTORY RESET — Production"
echo "========================================="
echo ""
echo "This will:"
echo "  1. Truncate ALL database tables (cascade)"
echo "  2. Delete ALL storage files"
echo "  3. Re-seed admin user + micro apps"
echo ""
read -p "Type 'RESET' to confirm: " confirm
if [ "$confirm" != "RESET" ]; then
    echo "Aborted."
    exit 1
fi

COMPOSE_FILE="docker-compose.prod.yml"

echo ""
echo "==> Stopping backend to prevent writes..."
docker compose -f "$COMPOSE_FILE" stop backend frontend 2>/dev/null || true

echo "==> Truncating all tables..."
docker compose -f "$COMPOSE_FILE" exec -T db psql \
    -U "${POSTGRES_USER:-postgres}" \
    -d "${POSTGRES_DB:-title_intelligence_hub}" \
    -c "
DO \$\$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        AND tablename != 'alembic_version'
    ) LOOP
        EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END \$\$;
"
echo "    Done."

echo "==> Clearing storage volume..."
docker compose -f "$COMPOSE_FILE" run --rm --entrypoint="" backend sh -c "rm -rf /app/storage/*"
echo "    Done."

echo "==> Re-seeding database..."
docker compose -f "$COMPOSE_FILE" run --rm backend python -m scripts.seed
echo "    Done."

echo "==> Restarting services..."
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

echo "==> Waiting for backend health..."
for i in $(seq 1 30); do
    if curl -sf http://localhost/api/v1/health > /dev/null 2>&1; then
        echo "    Backend healthy after ${i} checks"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "    ERROR: Backend failed health check"
        docker compose -f "$COMPOSE_FILE" logs --tail=20 backend
        exit 1
    fi
    sleep 2
done

echo ""
echo "========================================="
echo "  Factory reset complete!"
echo "  Admin: admin@logikality.com / admin123"
echo "========================================="
