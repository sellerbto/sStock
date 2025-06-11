FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .

# Install Python dependencies
RUN pip install --no-cache-dir -e .

COPY README.md .
COPY api/ ./api/

# Expose port
EXPOSE 8000
