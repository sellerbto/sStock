FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# Сначала копируем только файлы зависимостей
COPY requirements.txt .
COPY pyproject.toml .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Создаем необходимые директории
RUN mkdir -p /app/api/migrations/versions

# Копируем скрипты инициализации
COPY api/scripts/init_db.py /app/api/scripts/
COPY api/scripts/create_admin.py /app/api/scripts/

# Копируем entrypoint скрипт
COPY api/docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Копируем код приложения
COPY api/ ./api/

# Устанавливаем PYTHONPATH
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Use entrypoint script
ENTRYPOINT ["/app/docker-entrypoint.sh"]
