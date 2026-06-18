FROM python:3.13-slim

# Metadaten
LABEL maintainer="firma_website"
LABEL description="Django Web Platform"

WORKDIR /app

# Systemabhängigkeiten (PostgreSQL-Client für psycopg2-binary)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python-Umgebung
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Abhängigkeiten zuerst (Layer-Caching)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Projektcode
COPY . .

# Static Files sammeln
RUN python manage.py collectstatic --no-input --settings=config.settings || true

EXPOSE 8000

CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "2", "--log-file", "-", "--access-logfile", "-"]
