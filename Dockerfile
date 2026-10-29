FROM node:24-alpine AS frontend-builder
WORKDIR /app/frontend

ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ARG VITE_FIREBASE_APP_ID

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN VITE_FIREBASE_API_KEY="$VITE_FIREBASE_API_KEY" \
    VITE_FIREBASE_AUTH_DOMAIN="$VITE_FIREBASE_AUTH_DOMAIN" \
    VITE_FIREBASE_PROJECT_ID="$VITE_FIREBASE_PROJECT_ID" \
    VITE_FIREBASE_APP_ID="$VITE_FIREBASE_APP_ID" \
    npm run build


FROM python:3.12-slim AS backend-builder
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /app/logs /app/.meridian \
    && chown -R app:app /app /home/app

COPY --from=backend-builder /opt/venv /opt/venv
COPY --from=frontend-builder --chown=app:app /app/frontend/dist /app/frontend/dist
COPY --chown=app:app backend/ ./backend/

USER app

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn api.main:app --app-dir backend --host 0.0.0.0 --port \"${PORT:-8080}\""]
