#!/bin/sh

echo "Fixing schema for Binance migration..."
python manage.py fix_schema || echo "Schema fix skipped"

echo "Running database migrations..."
python manage.py migrate --noinput || echo "Migration failed, continuing..."

echo "Creating admin user..."
python manage.py create_admin || true

echo "Setting up crypto symbols..."
python manage.py setup_crypto || true

echo "Starting all services via supervisord..."
exec supervisord -c /app/supervisord.conf
