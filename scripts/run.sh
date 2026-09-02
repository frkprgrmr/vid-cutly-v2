#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Dependency belum siap. Jalankan ./scripts/setup.sh terlebih dahulu."
  exit 1
fi

set -a
if [[ -f .env ]]; then
  source .env
fi
set +a

host="${APP_HOST:-127.0.0.1}"
port="${APP_PORT:-8000}"
export PATH="$project_dir/.venv/bin:$PATH"
exec .venv/bin/uvicorn backend.main:app --host "$host" --port "$port"

