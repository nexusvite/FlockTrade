#!/bin/sh

echo "Running database migrations..."
python manage.py migrate --noinput || echo "Migration failed, continuing..."

echo "Creating admin user..."
python manage.py create_admin || true

echo "Starting Daphne server..."
exec daphne -b 0.0.0.0 -p 8080 flocktrade.asgi:application
