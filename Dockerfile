FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SENSOR_CONFIG=/app/config/default.yaml \
    SENSOR_STORAGE__PATH=/data/sensormon.db

WORKDIR /app

RUN mkdir -p /data && chmod 777 /data

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir .

EXPOSE 8000

ENTRYPOINT ["sensormon"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
