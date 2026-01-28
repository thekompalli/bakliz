#!/usr/bin/env sh
set -eu

if [ -n "${DATABASE_URL:-}" ]; then
  echo "Waiting for database..."
  python - <<'PY'
import os
import time
from sqlalchemy import create_engine

url = os.getenv("DATABASE_URL")
engine = create_engine(url, pool_pre_ping=True)

for i in range(60):
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        print("Database is ready")
        break
    except Exception as e:
        time.sleep(1)
else:
    raise SystemExit("Database did not become ready in time")
PY

  echo "Running migrations..."
  alembic -c /app/migrations/alembic.ini upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
