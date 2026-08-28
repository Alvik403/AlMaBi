# AlMaBi

FastAPI BI-приложение для построения P&L по выгрузкам 1С. Основной экран — `Тест BI` с Power Query-совместимой логикой join, план/прогнозом, налоговыми разрезами, drill-down по KPI и отдельными отчётами.

## Быстрый старт

```bash
docker compose up --build -d
```

Открыть:

- `http://localhost:18001/` — редирект на дашборд.
- `http://localhost:18001/dashboard/almabi-test` — основной дашборд.
- `http://localhost:18001/dashboard/almabi-test-excel` — проверка PQ-таблиц.
- `http://localhost:18001/dashboard/almabi-revenue-report` и другие `/dashboard/almabi-*-report` — отчёты по KPI.
- `http://localhost:18001/api/docs` — Swagger / OpenAPI.
- `http://localhost:18001/health` — liveness.
- `http://localhost:18001/ready` — readiness.

## Конфигурация

Настройки читаются из переменных окружения или `.env` (пример в `.env.example`):

- `DEBUG` — включает debug-режим приложения.
- `APP_HOST`, `APP_PORT` — параметры запуска uvicorn.
- `SESSION_SECRET` — ключ signed-cookie сессий.
- `AUTH_ENABLED` — локальная аутентификация; в production должна быть включена.
- `SESSION_HTTPS_ONLY`, `SESSION_MAX_AGE_SECONDS` — защищённая cookie и срок сессии.
- `AUTH_DB` — SQLite с пользователями и отзывными сессиями.
- `ALLOWED_HOSTS` — допустимые Host-заголовки через запятую.
- `MAX_UPLOAD_BYTES`, `UPLOAD_QUOTA_BYTES` — лимит запроса и пользовательская квота.
- `UPLOADS_DIR` — папка загруженных Excel-файлов AlMaBi.
- `RUNTIME_DIR` — runtime-папка приложения.
- `LOGS_DIR` — JSON-логи приложения и audit.

При `AUTH_ENABLED=true` и `DEBUG=false` приложение не запускается со слабым
`SESSION_SECRET` или без `SESSION_HTTPS_ONLY=true`.

Первый администратор создаётся интерактивно:

```bash
python scripts/manage_users.py bootstrap admin
```

Дальнейшие пользователи управляются на `/admin/users` или командами
`create`, `password`, `disable`, `list` этого скрипта. Роли: `viewer`
(только чтение), `uploader` (чтение и загрузка), `admin` (полный доступ).
Документация для службы безопасности и эксплуатации:

- `docs/SECURITY_COMPLIANCE.md` — контроли, статус аудита, чек-лист sign-off СБ;
- `docs/SECURITY_OPERATIONS.md` — production Docker, backup, rollout, retention.

## Входные файлы

В меню загрузки доступны выгрузки:

- `Бух.регистр` — обязательно;
- `Реализация` — обязательно;
- `Себестоимость` — обязательно;
- `План / прогноз` — опционально.

## Frontend assets

Tailwind и JS собираются локально через Vite:

```bash
npm install
npm run build
```

В Docker сборка выполняется в отдельном frontend-stage. Compose не монтирует весь проект в `/app`, чтобы не затереть собранные `static/dist`.

На Windows для `uploads`, `runtime` и `logs` используются **named volumes** (не `./uploads` с хоста): иначе пользователь `10001` в контейнере не может переименовывать файлы в `.incoming`. Чтобы подложить локальные Excel из `./uploads`:

```bash
docker compose run --rm -v "${PWD}/uploads:/seed:ro" web sh -c "cp -a /seed/. /app/uploads/ 2>/dev/null || true"
```

(или скопируйте файлы через UI загрузки в дашборде.)

## Тесты

Запуск через Docker:

```bash
docker compose build
docker compose run --rm web pytest -q
```

Проверяется:

- парсинг выгрузок 1С;
- Power Query-совместимые таблицы;
- сборка `Тест BI`;
- план/прогноз;
- отчёты по KPI;
- upload API и маршруты AlMaBi.

## Ручной smoke-check

1. Открыть `http://localhost:18001/` и убедиться, что произошёл редирект на `/dashboard/almabi-test`.
2. Загрузить обязательные выгрузки 1С через меню в правом верхнем углу.
3. Проверить сводную таблицу, фильтры, графики и drill-down.
4. Открыть `Тест Excel` и отчёты по KPI.
5. Проверить `/health` и `/ready`.

## Git flow

- `main` — стабильная ветка.
- `develop` — интеграционная ветка разработки.
- `feature/<name>` — задачи.

Пример цикла:

```bash
git switch develop
git switch -c feature/my-task
# изменения...
git add -A
git commit -m "feat: my task"
git switch develop
git merge --no-ff feature/my-task
```
