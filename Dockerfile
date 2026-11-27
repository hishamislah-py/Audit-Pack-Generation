# Production image: the consolidated UC-042 application (Smart Parser + analyst web application + UC-042 engine).
# Same architecture as before: one container, nginx on :80 in front of the Python application server on loopback.
#
# Stage 1 does not produce the UI: it REBUILDS the React analyst app from source and fails the build unless the result
# is byte-identical to the committed, validated bundle (app/smartparser/webapp/analyst), which the server serves.
FROM node:24-slim AS ui-check
WORKDIR /ui/ringfence-analyst-app
COPY app/ringfence-analyst-app/package.json app/ringfence-analyst-app/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/ringfence-analyst-app/ ./
COPY app/smartparser/webapp/analyst/ /ui/committed/
RUN npx vite build --mode backend --outDir /ui/built --emptyOutDir \
    && diff -r /ui/built /ui/committed \
    && echo "analyst UI: rebuilt bundle identical to the committed bundle" > /ui/ui-check.ok

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default
WORKDIR /app/src
# Engine runtime (pinned): API/AI stack + PDF reading/rendering + time zones; the application adds charset-normalizer.
COPY uc042/requirements-api.txt uc042/requirements-ai.txt uc042/
RUN pip install -r uc042/requirements-api.txt pypdf==5.9.0 reportlab==4.4.10 tzdata==2026.6 "charset-normalizer>=3.3"
COPY . /app/src
COPY --from=ui-check /ui/ui-check.ok /app/ui-check.ok
COPY deploy/nginx.conf /etc/nginx/conf.d/app.conf
ENV UC042_DATA_DIR=/data
EXPOSE 80
CMD ["sh", "/app/src/deploy/start.sh"]
