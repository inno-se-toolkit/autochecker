#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "Pulling latest changes..."
git pull

echo "Rebuilding and restarting containers..."
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d

echo "Done."
