#!/bin/sh
set -e

echo ">>> [1/3] Migrations..."
python manage.py migrate --no-input

echo ">>> [2/3] Collectstatic..."
python manage.py collectstatic --no-input

echo ">>> [3/3] Starting gunicorn on port ${PORT:-8000}..."
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers 2 \
    --timeout 120 \
    --log-file - \
    --access-logfile -
