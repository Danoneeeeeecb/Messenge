# Разработка

## Локальная среда

Основной режим разработки — локальные процессы без Docker и отдельного сервера БД. Требуются Python 3.12+ и Node.js 22+; локальный SQLite работает через `aiosqlite`. Настройки Backend находятся в `backend/.env.local.example`: скопируйте его в `backend/.env` и замените JWT secret. Файл `messenger.db` создаётся в `backend/` автоматически. Для тестов используется отдельный файл `messenger_test.db`, поскольку fixture удаляет и пересоздаёт таблицы в тестовой базе.

Backend: из `backend/` создайте virtualenv, установите `python -m pip install -e '.[dev]'`, примените `alembic upgrade head` и запустите `uvicorn app.main:app --reload --ws-max-size 16384`. Вложения хранятся в `backend/uploads/` (или в каталоге `ATTACHMENT_STORAGE_PATH`), максимальный размер по умолчанию — 10 MiB. Frontend запускается отдельно: `npm ci`, затем `npm run dev` из `frontend/`. Запуск обоих сервисов и PostgreSQL через Docker Compose остаётся необязательным вариантом.

## Этапность

Сверяйтесь со списком этапов в `SPEC.md`. Каждый этап должен обновлять API/архитектурную документацию и добавлять проверки своей функциональности. Integration-тесты локально используют отдельный SQLite файл; CI дополнительно проверяет сценарии на PostgreSQL 16.

## Текущий набор проверок

Проверка сборки Frontend — `npm run build`; форматирование Python — `ruff format --check app migrations tests`; линтинг — `ruff check app migrations tests`; типы — `mypy app`; полный набор тестов из `backend/` — `TEST_DATABASE_URL=sqlite+aiosqlite:///./messenger_test.db pytest`.

GitHub Actions выполняет эти проверки на push и pull request, используя PostgreSQL 16 и отдельную базу `messenger_test`. После integration-тестов workflow применяет миграции Alembic к этой базе.
