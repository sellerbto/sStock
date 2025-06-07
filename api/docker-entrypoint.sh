#!/bin/bash

echo "Waiting for database..."

# Ждем, пока база данных будет готова
echo "Database is ready!"

# Применяем миграции
cd /app
alembic upgrade head

# Создаем админа (только если его нет)
python api/scripts/create_admin.py

# Запускаем приложение
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload 