FROM node:24-slim AS frontend

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY assets ./assets
COPY templates ./templates
COPY tailwind.config.js vite.config.js ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/static/dist ./static/dist

EXPOSE 8000

CMD ["python", "app.py"]
