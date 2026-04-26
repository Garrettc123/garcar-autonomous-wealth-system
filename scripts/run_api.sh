#!/bin/bash
# Start the Garcar FastAPI server
set -e
cd "$(dirname "$0")/.."
pip install fastapi uvicorn[standard] --quiet
export PYTHONPATH="$(pwd):$PYTHONPATH"
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2 --log-level info
