#!/bin/bash
set -e

exec /app/.venv/bin/tiktok-live-recorder -no-update-check "$@"
