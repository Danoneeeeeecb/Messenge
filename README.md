# Realtime Messenger

Учебный full-stack проект: веб-мессенджер на FastAPI, SQLAlchemy и React. Для локальной разработки используется SQLite через `aiosqlite`; CI и необязательный Compose проверяют PostgreSQL 16. Реализованы регистрация/вход, поиск пользователей, личные и групповые чаты, управление участниками, история/поиск сообщений, WebSocket-доставка и браузерный интерфейс. Подробности — в [SPEC.md](SPEC.md) и `docs/`.

## Локальный запуск без Docker

Требуются Python 3.12+ и Node.js 22+. SQLite подключается через Python-библиотеку и не требует отдельного сервера. Скопируйте локальные настройки Backend:

```sh
cp backend/.env.local.example backend/.env
```

Замените `JWT_SECRET_KEY` на секрет длиной не менее 32 символов (например, `openssl rand -hex 32`). Из корня проекта установите и запустите Backend:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload --ws-max-size 16384
```

В отдельном терминале установите и запустите Frontend:

```sh
cd frontend
npm ci
npm run dev
```

Frontend: <http://localhost:5173>. API health: <http://localhost:8000/api/v1/health/live>. OpenAPI: <http://localhost:8000/docs>.

## Запуск через Docker Compose (необязательно)

Для Compose требуются Docker и Docker Compose v2. Скопируйте корневой `.env.example` в `.env`, задайте собственный `JWT_SECRET_KEY` и запускайте:

```sh
cp .env.example .env
docker compose up --build
```

Если меняете `POSTGRES_PASSWORD`, укажите такой же пароль в `DATABASE_URL`. Данные PostgreSQL хранятся в volume `postgres_data`.

Остановить Compose: `docker compose down`.

Compose запускает миграции автоматически. При локальном запуске без Docker их нужно применять командой `alembic upgrade head` после настройки базы.

## Проверки

Backend quality tools и pytest настроены в `backend/pyproject.toml`. Для локального полного набора тестов из `backend/` выполните `TEST_DATABASE_URL=sqlite+aiosqlite:///./messenger_test.db pytest`; тестовая fixture очищает только эту отдельную тестовую БД. CI дополнительно запускает integration-набор и миграции на PostgreSQL 16. Frontend production-сборка: `npm run build` из `frontend/`; проверка advisories: `npm audit --audit-level=high`. GitHub Actions запускает проверки Backend и Frontend на push и pull request.

## План

Реализованы инфраструктура, аутентификация, чаты, сообщения, WebSocket и пользовательский интерфейс. Текущие границы реализации, API, проверки и архитектурные решения описаны в `docs/`.
