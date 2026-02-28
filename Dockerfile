# Email-Buddy Dockerfile — Multi-stage build

# Stage 1: Install Python dependencies
FROM python:3.11-slim AS builder

COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Stage 2: Runtime image
FROM python:3.11-slim

ARG BUILD_VERSION=dev
ENV APP_VERSION=${BUILD_VERSION}
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create non-root user with UID/GID 1000 to match host user
RUN groupadd -r emailbuddy --gid=1000 && useradd -r -g emailbuddy --uid=1000 emailbuddy

WORKDIR /app

# Copy source code
COPY src/ ./src/

# Create logs and data directories
RUN mkdir -p /app/logs /app/data && chown -R emailbuddy:emailbuddy /app

USER emailbuddy

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

LABEL org.opencontainers.image.source="https://github.com/nutellinoit/email-buddy"
LABEL org.opencontainers.image.description="Email-Buddy — AI email classifier backend"

ENTRYPOINT ["python", "-m", "src.main"]
