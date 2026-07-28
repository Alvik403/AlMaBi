# 04. API и маршруты

## 4.1. Общие правила доступа

| Условие | Поведение |
|---------|-----------|
| Аутентификация | **Не реализована** — все маршруты доступны без логина |
| OpenAPI | `/api/docs`, `/api/redoc`, `/api/openapi.json` — **всегда включены** |
| Сессия | Signed cookie (`SESSION_SECRET`) для привязки загруженных файлов |

> Для эксплуатации во внутренней сети обязательны организационные меры: VPN/firewall и ideally reverse proxy + auth (см. документ 07).

## 4.2. Публичные эндпоинты (мониторинг)

| Метод | Путь | Ответ |
|-------|------|-------|
| GET | `/health` | `{"status":"ok"}` — liveness |
| GET | `/ready` | 200 `ready` / 503 `not_ready` — наличие каталогов uploads / logs / runtime |

## 4.3. JSON API загрузки и данных

### Основной набор выгрузок

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/api/almabi/data-source` | Статус загруженных файлов сессии |
| POST | `/api/almabi/files/upload` | Загрузка одного `.xlsx` с автоопределением типа |
| POST | `/api/almabi/files/upload-set` | Пакет: `buh_file`, `realization_file`, `cost_file`, `plan_forecast_file` |

**Ограничения upload (текущие):**

- только `.xlsx`;
- структурная валидация заголовков выгрузки;
- отдельного `MAX_UPLOAD_BYTES` / rate limit в коде **нет** (остаточный риск — см. 07).

### KPI-отчёты (шаблон для каждого)

| Метод | Путь | Примеры slug |
|-------|------|--------------|
| GET | `/dashboard/almabi-{slug}-report` | HTML-страница |
| POST | `/api/almabi-{slug}-report/upload` | Локальная загрузка для отчёта |
| GET | `/api/almabi-{slug}-report/data` | JSON payload |

Slugs: `revenue`, `cost`, `other-income`, `other-expense`, `commercial-expense`, `management-expense`, `operating-profit`, `profit-before-tax`, `taxes`, `net-profit`.

### Тест Excel (PQ-таблицы)

| Метод | Путь |
|-------|------|
| GET | `/dashboard/almabi-test-excel` |
| POST | `/api/almabi-test-excel/{revenue\|cost\|buh\|projects}/upload` |
| GET | `/api/almabi-test-excel/{revenue\|cost\|buh\|projects}/data` |

## 4.4. HTML-страницы

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/` | Редирект 307 → `/dashboard/almabi-test` |
| GET | `/dashboard/almabi` | Редирект → Тест BI |
| GET | `/dashboard/almabi-test` | Основной дашборд P&L |
| GET | `/dashboard/almabi-charts` | Графики БДР |
| GET | `/dashboard/almabi-test-excel` | Просмотр PQ-таблиц |
| GET | `/dashboard/almabi-*-report` | KPI-отчёты |

## 4.5. Статика

| Путь | Содержимое |
|------|------------|
| `/static/*` | Статика, включая `/static/dist/*` (Vite build) |

## 4.6. Пример проверки API

```bash
# мониторинг
curl -s http://127.0.0.1:18001/health
curl -s http://127.0.0.1:18001/ready

# статус источников
curl -s -c cookies.txt -b cookies.txt http://127.0.0.1:18001/api/almabi/data-source

# пакетная загрузка
curl -s -c cookies.txt -b cookies.txt \
  -F "buh_file=@./buh.xlsx" \
  -F "realization_file=@./realization.xlsx" \
  -F "cost_file=@./cost.xlsx" \
  http://127.0.0.1:18001/api/almabi/files/upload-set
```

Swagger UI: `http://127.0.0.1:18001/api/docs`.
