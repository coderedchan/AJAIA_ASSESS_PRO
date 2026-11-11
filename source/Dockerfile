FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY relay ./relay

# SQLite lives in /data. Mount a persistent volume here to keep documents across restarts.
ENV RELAY_DATA_DIR=/data \
    PORT=8000 \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data

EXPOSE 8000
# --preload creates and seeds the database once, before the workers start.
CMD gunicorn --preload --workers 2 --bind 0.0.0.0:${PORT} "relay:create_app()"
