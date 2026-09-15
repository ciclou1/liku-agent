FROM python:3.13-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend /app/backend
COPY tests /app/tests
COPY alembic.ini /app/alembic.ini
COPY backend/entrypoint.sh /app/backend/entrypoint.sh
RUN chmod +x /app/backend/entrypoint.sh
ENTRYPOINT ["/app/backend/entrypoint.sh"]
