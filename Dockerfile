FROM node:24-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03 AS frontend

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY assets ./assets
COPY templates ./templates
COPY tailwind.config.js vite.config.js ./
RUN npm run build

FROM python:3.12-alpine@sha256:d09d15e60962ca365d1cd544a48773bac9d33f2fb1b00f2aa0deec78ade7dc31

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.lock .
RUN pip install --require-hashes --no-cache-dir -r requirements.lock

RUN addgroup -g 10001 -S app \
    && adduser -u 10001 -S -D -H -G app app \
    && mkdir -p /app/uploads /app/runtime /app/logs \
    && chown -R app:app /app

COPY --chown=app:app . .
COPY --from=frontend --chown=app:app /app/static/dist ./static/dist

USER 10001:10001

EXPOSE 8000

CMD ["python", "app.py"]
