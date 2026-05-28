#!/bin/bash
set -e
echo "=== Starting app ==="
echo "Python: $(python3 --version 2>&1)"
echo "PWD: $(pwd)"
echo "PORT: $PORT"
echo "APP_ENV: $APP_ENV"
echo "=== Testing imports ==="
python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from app.main import app
    print('Import OK')
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
" 2>&1
echo "=== Starting uvicorn ==="
uvicorn app.main:app --host 0.0.0.0 --port $PORT
