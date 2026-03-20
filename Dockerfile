FROM python:3.10-slim

# Install system dependencies for the app and lightweight JS runtime
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 容器运行时使用固定的数据和日志目录
ENV APP_DATA_DIR=/app/data
ENV APP_LOGS_DIR=/app/logs

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p data logs

# Expose port
EXPOSE 8000

# Environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "webui.py"]
