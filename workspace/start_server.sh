#!/bin/zsh
cd /Users/naman.agarwal/dev2/crux-2
exec backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
