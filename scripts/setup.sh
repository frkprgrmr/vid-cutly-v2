#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "File .env dibuat. Isi GEMINI_API_KEY sebelum menjalankan app."
fi

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'

cd frontend
npm install
npm run build

echo "Setup selesai. Jalankan: ./scripts/run.sh"
