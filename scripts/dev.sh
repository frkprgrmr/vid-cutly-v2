#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
export PATH="$project_dir/.venv/bin:$PATH"

cleanup() {
  if [[ -n "${backend_pid:-}" ]]; then
    kill "$backend_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

.venv/bin/uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 &
backend_pid=$!

cd frontend
npm run dev

