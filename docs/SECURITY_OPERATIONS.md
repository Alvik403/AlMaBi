# Безопасная эксплуатация AlMaBi в Docker

Документ для администратора и **службы безопасности (СБ)**. Описывает запуск,
backup, приёмку и rollout. Матрица контролей, чек-лист sign-off СБ и статус
устранения замечений аудита — в `docs/SECURITY_COMPLIANCE.md`.

## Приёмка службой безопасности

Перед первым production rollout и после каждого значимого обновления СБ
выполняет:

1. **Автоматическую приёмку** (на стенде без production-данных):

```powershell
.\scripts\security_acceptance.ps1 -ProductionHost almabi.internal.example
```

Скрипт последовательно запускает:

- `pytest -q` — regression, включая auth, file security, HTTP security;
- `pip-audit -r requirements.lock` — уязвимости Python;
- `npm audit --audit-level=high` — уязвимости frontend;
- `npm run build` — сборка локальных assets;
- `npm run test:browser` — Playwright (визуал, отсутствие внешних CDN);
- `docker compose -f docker-compose.prod.yml config` — валидация prod-стека.

2. **Ручной чек-лист** из раздела 7 `docs/SECURITY_COMPLIANCE.md` (18 пунктов).

3. **Container scan** (рекомендуется Trivy или аналог):

```powershell
docker build -t almabi-web:scan .
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --severity HIGH,CRITICAL almabi-web:scan
```

High/critical находки требуют исправления, понижения образа или **письменного**
решения СБ о принятии риска с указанием срока пересмотра.

4. **Фиксация артефактов приёмки** (хранить не менее 1 года):

- git commit / tag выпуска;
- digest image (`docker inspect --format='{{index .RepoDigests 0}}' ...`);
- лог `security_acceptance.ps1`;
- отчёт container scan;
- заполненный чек-лист СБ с подписями.

## Модель запуска

Production-стек запускается отдельно от `docker-compose.yml`:

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml config
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

`web` не публикует порт на хост и доступен только `nginx` во внутренней сети
`backend`. Оба контейнера работают без root, с read-only root filesystem,
сброшенными capabilities, `no-new-privileges`, лимитами памяти, CPU и PID.
Запись разрешена только в именованные volumes `uploads`, `runtime`, `logs` и
в ограниченный временный `tmpfs`.

Создайте файлы секретов вне системы контроля версий (`ops/secrets/`, каталог в
`.gitignore`):

```text
ops/secrets/session_secret
ops/secrets/data_key
ops/secrets/db_password
ops/secrets/keycloak_client_secret
```

Каждый из `session_secret` и `data_key` — случайная строка не короче 32
символов. Их можно сгенерировать командой
`python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Production-compose отдаёт их контейнеру `web` bind-mount в `/run/secrets`
(`SESSION_SECRET_FILE`, `DATA_KEY_FILE`, пароль Postgres, секрет клиента
Keycloak). Процесс `web` работает от uid `10001`, поэтому эти четыре файла
должны быть читаемы этим пользователем: `chown 10001:10001` и `chmod 400`.
Пароль Postgres для контейнера `db` по-прежнему монтируется как Docker secret:
образ Postgres читает его от root. Не кладите эти значения в `environment` и
не передавайте через Docker build args.

Ротация раз в 60 дней: `scripts/rotate_session_secret.py` (после рестарта все
сессии сбрасываются), `scripts/rotate_data_key.py` (перешифровывает uploads),
смена пароля admin в интерфейсе. TLS-ключ выпускает корпоративный CA;
`/ready` показывает возраст `fullchain.pem` и не останавливает сайт.

Вход всех пользователей: своя страница `/login` → Keycloak 26.5. Локальной формы пароля нет. Иные версии Keycloak не используются. Active Directory и мультифактор подключает ИБ позже. Нужны `KEYCLOAK_ISSUER`, `KEYCLOAK_CLIENT_ID` и файл `ops/secrets/keycloak_client_secret`.

Группы, которые Keycloak кладёт в токен:

| Группа | Кто в ней | Роль в AlMaBi |
|---|---|---|
| `AlMaBi-Admins` | два именных администратора | `admin` |
| `AlMaBi-Uploaders` | сотрудники, которые загружают Excel | `uploader` |
| `AlMaBi-Viewers` | остальные сотрудники | `viewer` |

Человека добавляют в группу. Отдельный локальный пароль в AlMaBi для входа не используется. Секреты сессии и ключа данных лежат в `ops/secrets/session_secret` и `ops/secrets/data_key`, не в `.env.prod`. Без ключа данных production не запускается, файлы открытым текстом не пишутся.

Локальная проверка входа без AD и без второго фактора:

```powershell
docker compose -f docker-compose.test.yml up --build
```

Сайт: http://localhost:18002/login. Keycloak 26.5.7: http://localhost:8088 (админ консоли `admin` / `admin`). Тестовые входы: `test-admin` / `test-admin-pass`, `test-uploader` / `test-uploader-pass`, `test-viewer` / `test-viewer-pass`. Обычный `docker-compose.yml` по-прежнему без входа и нужен для расчётов.

После первого запуска администраторов в локальной базе паролем не создают: два человека должны быть в группе `AlMaBi-Admins`.

Старые UUID-файлы не удаляются автоматически. После backup назначьте их
конкретному пользователю: сначала сохраните dry-run отчёт, затем выполните
копирование с проверкой SHA-256:

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml exec web python scripts/migrate_legacy_uploads.py 1
docker compose --env-file .env.prod -f docker-compose.prod.yml exec web python scripts/migrate_legacy_uploads.py 1 --apply
```

## TLS-сертификаты

Создайте локальный каталог `ops/tls`:

```text
ops/tls/fullchain.pem
ops/tls/privkey.pem
```

Закрытый ключ должен читаться UID 101 внутри контейнера nginx и никем лишним.
На Linux задайте владельца/ACL и права не шире `0640`; не делайте ключ
общедоступным только ради запуска контейнера. На Windows используйте ACL NTFS,
ограничив доступ учетной записью оператора и Administrators. После замены
сертификата выполните:

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml exec nginx nginx -t
docker compose --env-file .env.prod -f docker-compose.prod.yml restart nginx
```

Для публичного DNS используйте сертификат доверенного CA (например,
ACME/Let's Encrypt). Для закрытой LAN — сертификат внутреннего CA; добавьте CA
в доверенные хранилища клиентов. SAN сертификата обязан содержать именно DNS-имя
или IP, по которому пользователи открывают сервис. Самоподписанный сертификат
подходит только для теста. HSTS включен на год: сначала проверяйте сертификат и
DNS на тестовом имени, иначе браузеры будут упорно требовать HTTPS.

## Backup по правилу 3-2-1

Храните три копии данных, на двух разных типах носителей, одну — вне площадки.
Минимально резервируйте `uploads` и `runtime`; `logs` сохраняйте согласно
политике аудита. Отдельно сохраняйте зашифрованные TLS-ключи, `.env.prod`,
использованный image digest и конфигурацию, но не складывайте секреты в один
незашифрованный архив с данными.

Пример остановочного backup именованных volumes (имена проверьте через
`docker volume ls`):

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml stop web
New-Item -ItemType Directory -Force backup | Out-Null
docker run --rm -v almabi-prod_uploads:/source:ro -v "${PWD}\backup:/backup" alpine:3.22 tar -czf /backup/uploads.tgz -C /source .
docker run --rm -v almabi-prod_runtime:/source:ro -v "${PWD}\backup:/backup" alpine:3.22 tar -czf /backup/runtime.tgz -C /source .
docker run --rm -v almabi-prod_logs:/source:ro -v "${PWD}\backup:/backup" alpine:3.22 tar -czf /backup/logs.tgz -C /source .
docker compose --env-file .env.prod -f docker-compose.prod.yml start web
```

Подсчитайте SHA-256 архивов, зашифруйте их, перенесите вторую копию на другой
носитель и третью в off-site хранилище с versioning/immutability. Регулярно
проверяйте срок хранения и возможность чтения, а не только факт создания файла.

## Проверка восстановления

Не восстанавливайте тестовый backup поверх production. Не реже раза в квартал:

1. Создайте отдельные пустые volumes с префиксом `almabi-restore`.
2. Распакуйте архивы временным контейнером `alpine` в эти volumes.
3. Запустите отдельный compose project с override-файлом, который подключает
   восстановленные volumes и публикует другие host ports.
4. Проверьте `/health`, вход, открытие нескольких известных проектов и
   контрольные суммы выбранных загруженных файлов.
5. Зафиксируйте RTO/RPO, длительность и найденные ошибки; затем удалите
   тестовый стек и volumes.

Пример распаковки одного volume:

```powershell
docker volume create almabi-restore_uploads
docker run --rm -v almabi-restore_uploads:/target -v "${PWD}\backup:/backup:ro" alpine:3.22 sh -c "rm -rf /target/* && tar -xzf /backup/uploads.tgz -C /target"
```

До теста восстановления проверьте архив командой `tar -tzf` и SHA-256.

## Retention и очистка данных

Переменные: `UPLOAD_RETENTION_DAYS` (по умолчанию 90),
`LOG_RETENTION_DAYS` (30). Процесс `web` сам запускает очистку не чаще чем
раз в `RETENTION_INTERVAL_DAYS` (10). Первый старт только запоминает дату в
`runtime/retention_state.json` и ничего не удаляет. Журнал удалений —
`logs/retention.jsonl`. Файлы моложе срока хранения остаются на месте.

СБ утверждает сроки и то, что автоматический запуск заменяет ручной скрипт.

## Rollout и rollback

Этапы выпуска нельзя объединять:

1. Тестовый стенд с копией конфигурации без production-данных.
2. `scripts/security_acceptance.ps1` и ручной чек-лист СБ
   (`docs/SECURITY_COMPLIANCE.md`, раздел 7).
3. SCA и container scan; high/critical — исправление или письменное решение СБ.
4. Ограниченная LAN/VVPN-группа (5–10 пользователей), наблюдение минимум один
   рабочий цикл: вход, upload, открытие дашборда, logout.
5. Полный LAN rollout после **sign-off СБ** и владельца BI.

На каждом этапе сохраняйте image digest, compose config, backup volumes,
результаты тестов и решение продолжить/откатить. Схемы и миграции остаются
additive; legacy-файлы не удаляются до отдельной подтверждённой очистки.

Перед rollout соберите версионный image, проверьте конфигурацию и healthcheck:

```powershell
$env:ALMABI_IMAGE = "almabi-web:2026-08-19.1"
docker compose --env-file .env.prod -f docker-compose.prod.yml build --pull web
docker compose --env-file .env.prod -f docker-compose.prod.yml config
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --no-deps web
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --since 10m web nginx
```

После замены `web` перезапустите nginx, чтобы сбросить старые соединения.
Сохраняйте предыдущий immutable image tag/digest. При ошибке верните прежний
`ALMABI_IMAGE` и выполните `up -d --no-build --no-deps web`, затем перезапустите
nginx и повторите smoke test. Rollback image не откатывает содержимое volumes:
изменения форматов данных требуют заранее документированного обратимого
перехода либо восстановления из проверенного backup.

Проверяйте состояние командой:

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
curl.exe -k https://localhost/health
```

Флаг `-k` допустим только для локальной проверки самоподписанного сертификата.

## Windows и LAN

- Docker Desktop должен использовать Linux containers. Лимиты CPU/памяти
  действуют внутри VM Docker Desktop и не заменяют лимиты самой VM.
- Именованные volumes предпочтительнее bind mounts для рабочих данных:
  Windows ACL и Linux UID/GID отображаются неполно и могут дать неожиданные
  права. Доступ к ним выполняйте через контейнеры backup/restore.
- Откройте в Windows Firewall входящий TCP 443 только для доверенных LAN-профилей и подсетей. Порт 80 не публикуется. Не публикуйте 8000 и 5432.
- `ops/nginx.conf` по умолчанию разрешает только RFC1918/loopback. До rollout
  замените/дополните `allow` фактическими LAN/VPN CIDR; внешние адреса
  корпоративного VPN иначе будут отклонены.
- Используйте статический адрес/DNS-имя хоста и сертификат с соответствующим
  SAN. Доступ по `localhost` с другой машины не работает.
- Порт 443 может быть занят IIS, HTTP.sys, VPN или другим reverse proxy.
  Проверьте занятость до запуска. Если TLS завершается на корпоративном
  балансировщике, согласуйте отдельную схему вместо двойного TLS.
- Docker Desktop не является предпочтительной production-платформой для
  критичного сервиса: автоматические обновления, сон/перезагрузка Windows и
  пользовательская сессия влияют на доступность. Для повышенной надежности
  используйте выделенный Linux-host/VM и внешний мониторинг.

## Мониторинг и SIEM

Журналы будут отправляться в SIEM после подключения. Назначение: `srv-s.alabuga.ru` (`10.50.53.121`), TCP/1514 и TCP/1515. Название системы не фиксируется. Приложение отправку не выполняет. Файлы в томе `logs` зашифрованы; для будущей отправки остаётся открытый JSON в консоли контейнера.

Минимальный набор проверок:

| Что проверять | Где | Периодичность |
|---|---|---|
| Доступность сервиса | `GET https://<host>/health` через TLS | 1–5 мин (внешний probe) |
| Срок TLS-сертификата | `openssl s_client` / мониторинг CA | еженедельно |
| Ошибки 401/403/429/5xx | логи nginx (stdout контейнера) | ежедневно |
| Неудачные входы | журнал Keycloak и JSON-логи приложения | ежедневно |
| Заполнение volumes | `docker system df -v` | еженедельно |
| Актуальность пользователей | Keycloak 26.5, два именных администратора | ежеквартально |
| Retention cleanup | `logs/retention.jsonl` | по регламенту |

Алерты на множественные 401 с одного IP, резкий рост 413 (upload), падение
`/ready` (auth store недоступен).

## Управление учётными записями

Вход идёт через Keycloak 26.5. Сотрудника добавляют в группу `AlMaBi-Admins`, `AlMaBi-Uploaders` или `AlMaBi-Viewers`. Локальный пароль для входа не используется. Active Directory и мультифактор к этим группам подключает ИБ.

## Остаточные ограничения

- Base images используют изменяемые tags. Для воспроизводимости зафиксируйте
  проверенные digest после регулярного vulnerability scan и обновляйте их
  контролируемо.
- `nginx -t` в healthcheck проверяет конфигурацию и ключи, но не делает
  end-to-end HTTPS-запрос. Внешний мониторинг должен проверять `/health` через
  TLS и валидировать срок/цепочку сертификата.
- `restart: unless-stopped` не обеспечивает оркестрацию между несколькими
  хостами, автоматический rollback или high availability.
- Доступ оператора к Docker daemon эквивалентен root-доступу к данным и
  секретам. Ограничьте membership в группе/ACL Docker и ведите аудит.
- Полный перечень остаточных рисков и матрица «принять / доработать» — раздел 8
  `docs/SECURITY_COMPLIANCE.md`.
