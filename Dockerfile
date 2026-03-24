FROM python:3.10-slim

RUN apt-get update && apt-get install -y curl ca-certificates build-essential python3-dev gnupg && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    mkdir -p /usr/share/keyrings; \
    curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg; \
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ bullseye main" > /etc/apt/sources.list.d/cloudflare-client.list; \
    apt-get update; \
    apt-get install -y cloudflare-warp; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    LOG_LEVEL=info \
    DEBUG=0 \
    APP_DATA_DIR=/app/data \
    APP_LOGS_DIR=/app/logs

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/run-with-warp.sh
RUN mkdir -p data logs

EXPOSE 8000

CMD ["/app/run-with-warp.sh"]
