# DOM Processing Service
# Python 3.13 + Redis (in-container) for SOAP multiprocessing
#
# Build:
#   docker build -t dom-processor:1.0.0 .
#
# Run:
#   docker run --rm --env-file .env dom-processor:1.0.0 python soap_multiprocess.py --run --type domain --day today

FROM python:3.13-slim AS base

LABEL maintainer="caionorder"
LABEL description="DOM SOAP multiprocess processor with embedded Redis"
LABEL version="1.0.0"

# Prevent Python from writing .pyc and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install redis-server and lxml runtime deps, clean up apt cache
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        redis-server \
        libxml2 \
        libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Install Python dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY client/ ./client/
COPY config/ ./config/
COPY core/ ./core/
COPY credentials/ ./credentials/
COPY DTO/ ./DTO/
COPY helpers/ ./helpers/
COPY repositories/ ./repositories/
COPY services/ ./services/
COPY utils/ ./utils/
COPY soap_multiprocess.py .
COPY list_records.py .
COPY .env .

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create directories Redis needs and grant ownership
RUN mkdir -p /var/run/redis /var/log/redis /data && \
    chown -R appuser:appuser /var/run/redis /var/log/redis /data /app

# Configure Redis in app dir (appuser has full access)
RUN echo "bind 127.0.0.1" > /app/redis.conf && \
    echo "port 6379" >> /app/redis.conf && \
    echo "daemonize no" >> /app/redis.conf && \
    echo "dir /data" >> /app/redis.conf && \
    echo "logfile /var/log/redis/redis.log" >> /app/redis.conf && \
    echo "save \"\"" >> /app/redis.conf && \
    echo "appendonly no" >> /app/redis.conf && \
    chown appuser:appuser /app/redis.conf

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD redis-cli -h 127.0.0.1 ping | grep -q PONG || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "soap_multiprocess.py", "--run", "--type", "domain", "--day", "today"]
