# ======== Stage 1: Python Builder ========
FROM python:3.12-alpine AS python-builder
WORKDIR /AstrBot

# Install build-time dependencies only
RUN apk add --no-cache \
    gcc \
    git \
    musl-dev \
    libffi-dev \
    openssl-dev \
    python3-dev \
    linux-headers \
    rust \
    cargo \
    make

# Install uv and generate + install Python deps
COPY ./AstrBot .
RUN python -m pip install --no-cache-dir uv \
    && echo "3.12" > .python-version \
    && uv add telethon cryptg \
    && uv lock \
    && uv export --format requirements.txt --output-file requirements.txt --frozen \
    && uv pip install -r requirements.txt --no-cache-dir --system \
    && uv pip install socksio pilk --no-cache-dir --system

# ======== Stage 2: Runtime ========
FROM python:3.12-alpine
WORKDIR /AstrBot

# Install runtime-only dependencies
RUN apk add --no-cache \
    ca-certificates \
    bash \
    ffmpeg \
    git \
    nodejs \
    tzdata

# Copy installed Python packages from builder
COPY --from=python-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-builder /usr/local/bin /usr/local/bin

# Copy application source
COPY ./AstrBot /AstrBot/
RUN mkdir -p /AstrBot/data \
    && mv /AstrBot/dashboard/dist /AstrBot/data/dist \
    && mkdir -p /AstrBot/astrbot/dashboard \
    && ln -s /AstrBot/data/dist /AstrBot/astrbot/dashboard/dist

EXPOSE 6185

CMD ["python", "main.py"]
