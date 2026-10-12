#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
docker compose up -d --build --remove-orphans
docker compose ps
