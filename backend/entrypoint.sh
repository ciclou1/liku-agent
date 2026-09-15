#!/bin/sh
set -eu

attempt=1
until python -m alembic upgrade head; do
  if [ "$attempt" -ge 30 ]; then
    echo "database migration failed after ${attempt} attempts" >&2
    exit 1
  fi
  echo "database is not accepting connections; retrying migration (${attempt}/30)" >&2
  attempt=$((attempt + 1))
  sleep 2
done
exec "$@"
