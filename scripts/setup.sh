#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
command -v ffmpeg >/dev/null || { echo 'Thiếu FFmpeg: brew install ffmpeg'; exit 1; }
command -v ffprobe >/dev/null || { echo 'Thiếu ffprobe: brew install ffmpeg'; exit 1; }
uv sync --locked
npm --prefix frontend ci
uv run playwright install chromium
npm --prefix frontend run build
PYTHONPATH=backend uv run python -c 'from app.db.session import migrate; migrate()'
