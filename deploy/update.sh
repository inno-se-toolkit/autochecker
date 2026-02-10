#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== Pulling latest changes ==="
git pull

echo ""
echo "=== Running pre-deploy verification ==="
# Run verify.py inside a temporary container to check imports, structure, etc.
docker build -f deploy/Dockerfile -t autochecker-verify . --quiet
docker run --rm autochecker-verify python verify.py
echo ""

echo "=== Migrating results volume (old path -> new path) ==="
# One-time migration: if results exist at the old path, copy them to the new one.
# The volume is the same, only the mount point changed:
#   old: /app/autochecker/results -> new: /app/results
# This is idempotent — if already migrated, cp will just overwrite with identical files.
RESULTS_VOL="deploy_autochecker-results"
if docker volume inspect "$RESULTS_VOL" >/dev/null 2>&1; then
    docker run --rm \
        -v "$RESULTS_VOL":/vol \
        alpine sh -c '
            if [ -d /vol/autochecker/results ] && [ "$(ls -A /vol/autochecker/results 2>/dev/null)" ]; then
                echo "  Moving data from old mount path..."
                cp -a /vol/autochecker/results/* /vol/ 2>/dev/null || true
                echo "  Done."
            else
                echo "  No migration needed."
            fi
        '
fi

echo ""
echo "=== Rebuilding and restarting containers ==="
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d

echo ""
echo "=== Checking containers ==="
sleep 3
docker compose -f deploy/docker-compose.yml ps

echo ""
echo "Done."
