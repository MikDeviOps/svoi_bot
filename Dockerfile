FROM python:3.12-slim AS base

# Переменные окружения
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# Рабочая директория
WORKDIR /app

# Установка системных зависимостей
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
 && rm -rf /var/lib/apt/lists/*

# Копирование requirements.txt отдельно для кэширования
COPY requirements.txt .

# Установка Python-зависимостей
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# Копирование кода приложения
COPY . .

# Создание директории для данных (если нужна)
RUN mkdir -p /data && chown -R nobody:nogroup /data || true

# Команда запуска
CMD ["python", "-m", "app.main"]