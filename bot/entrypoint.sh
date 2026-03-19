#!/bin/sh

echo "Running database migrations..."
python manage.py migrate --noinput || echo "Migration failed, continuing..."

echo "Creating admin user..."
python manage.py create_admin || true

echo "Starting all services via supervisord..."
exec supervisord -c /app/supervisord.conf
