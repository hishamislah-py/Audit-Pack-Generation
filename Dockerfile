# Production image: Vite frontend (uc042/frontend) built in stage 1; FastAPI backend + nginx in stage 2.
FROM node:22-slim AS web
WORKDIR /web
COPY uc042/frontend/package.json uc042/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY uc042/frontend/ ./
# "/" makes the client use same-origin relative /api/v1/... paths (see src api client).
ENV VITE_API_BASE_URL=/
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default
WORKDIR /app/src
COPY uc042/requirements-api.txt uc042/requirements-ai.txt uc042/
RUN pip install -r uc042/requirements-api.txt pypdf==5.9.0 reportlab==4.4.10 tzdata==2026.6
COPY . /app/src
COPY --from=web /web/dist /app/web
COPY deploy/nginx.conf /etc/nginx/conf.d/app.conf
ENV UC042_APP_STATE_DIR=/data/app_state UC042_DOCUMENT_STORE=/data/document_store
EXPOSE 80
CMD ["sh", "/app/src/deploy/start.sh"]
