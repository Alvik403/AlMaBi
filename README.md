# Дашборд ОПиОП

FastAPI BI-дашборд для построения витрин по Excel-файлам с листом `Калькуляция`.
Приложение поддерживает историю загруженных `.xlsx`, выбор активного файла в текущей сессии, кеширование данных по `mtime/size`, debug-раздел, health/readiness и автотесты.

## Быстрый старт

```bash
docker compose up --build -d
```

Открыть:

- `http://localhost:18000/` — редирект на дашборд.
- `http://localhost:18000/dashboard` — основной дашборд.
- `http://localhost:18000/dashboard/excel` — Excel-подобный просмотр и редактирование активной книги.
- `http://localhost:18000/api/docs` — Swagger / OpenAPI.
- `http://localhost:18000/health` — liveness.
- `http://localhost:18000/ready` — readiness.

При `DEBUG=true` доступны:

- `http://localhost:18000/debug` — меню debug-инструментов.
- `http://localhost:18000/debug/calculation-services` — тех. страница расчётов.
- `http://localhost:18000/debug/excel` — просмотр листов Excel.

## Конфигурация

Настройки читаются из переменных окружения или `.env` (пример в `.env.example`):

- `DEBUG` — включает `/debug`.
- `APP_HOST`, `APP_PORT` — параметры запуска uvicorn.
- `SESSION_SECRET` — ключ signed-cookie сессий.
- `DATA_DIR` — папка исходного `data.xlsx`.
- `UPLOADS_DIR` — папка загруженных Excel-файлов.
- `DATABASE_PATH` — SQLite metadata.
- `LOGS_DIR` — JSON-логи приложения и ошибок.
- `ACTIVE_DEFAULT_FILE` — имя файла по умолчанию в `DATA_DIR`.

## Работа с Excel-файлами

В правом верхнем углу дашборда есть шестерёнка:

- показывает историю файлов;
- подсвечивает последний загруженный файл;
- позволяет выбрать файл только для текущей сессии;
- загружает новый `.xlsx` после проверки структуры.

Если пользователь загружает новый валидный файл, он становится активным только у него. У остальных пользователей текущий выбор не меняется, но появляется плашка о новой версии.

Слева в дашборде есть вкладка `Просмотр Excel`. Она открывает активный `.xlsx` в браузерном редакторе на базе Univer: доступны листы книги, сетка ячеек, редактирование и сохранение результата как новой версии. Сохранение проходит ту же серверную проверку структуры, что и обычная загрузка файла. Макросы, внешние ссылки и часть сложного форматирования могут не сохраниться в open-source браузерном импорте/экспорте.

## Frontend assets

Tailwind и JS собираются локально через Vite:

```bash
npm install
npm run build
```

В Docker сборка выполняется в отдельном frontend-stage. Compose не монтирует весь проект в `/app`, чтобы не затереть собранные `static/dist`.

## Тесты

Запуск через Docker:

```bash
docker compose build
docker compose run --rm web pytest -q
```

Проверяется:

- парсинг Excel fixture;
- сборка overview/navigation;
- валидация upload;
- редирект `/` → `/dashboard`;
- debug mode;
- маршруты с `/` внутри имени класса/услуги;
- session-scoped active file;
- страница и API Excel-редактора.

## Ручной smoke-check

1. Открыть `http://localhost:18000/` и убедиться, что произошёл редирект на `/dashboard`.
2. Открыть шестерёнку, увидеть активный файл и latest.
3. Загрузить валидный `.xlsx`; он должен стать активным в текущей сессии.
4. Загрузить невалидный файл; должна появиться понятная ошибка, файл не должен стать доступным.
5. Выбрать прошлый файл из истории; latest не меняется глобально.
6. Открыть `/dashboard/excel`, изменить ячейку и нажать `Сохранить как новую версию`.
7. Вернуться на `/dashboard` и убедиться, что активным стал новый файл.
8. Проверить `/health` и `/ready`.
9. При `DEBUG=true` открыть `/debug`, `/debug/excel`, `/debug/calculation-services`.

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
