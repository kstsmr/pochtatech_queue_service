FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./
COPY docs/schema.sql /app/docs/schema.sql
COPY config /app/config

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
