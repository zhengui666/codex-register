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

ENV APP_DATA_DIR=/app/data
ENV APP_LOGS_DIR=/app/logs

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/run-with-warp.sh
RUN mkdir -p data logs

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["/app/run-with-warp.sh"]
