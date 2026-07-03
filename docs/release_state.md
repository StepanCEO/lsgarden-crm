# Состояние версии после отката

Дата проверки: 2026-07-02

## Текущий прод

Сервер `crm.lsgarden.ru` работает после отката на преддеплойную копию.

Контейнеры:

- `plantflow-crm-web-1` - запущен
- `plantflow-crm-backup-1` - запущен
- `plantflow-crm-db-1` - запущен, `healthy`
- `plantflow-crm-caddy-1` - запущен

Страхующие архивы на сервере:

- `/opt/deploy-backups/plantflow-crm_predeploy_20260702_1717.tar.gz`
- `/opt/deploy-backups/plantflow-crm_postrollback_safety_20260702_172510.tar.gz`

Каталог версии, снятой с прода при откате:

- `/opt/plantflow-crm.rollback_20260702_172510`

## Что отличается от локальной версии

После локальной доработки отличаются:

- `crm/views.py`
- `crm/templates/crm/dashboard.html`
- `crm/tests.py`
- `docs/release_state.md`

Совпадают локально и на проде:

- `docs/telegram_avito_setup.md`
- `docs/site_forms_integration.md`
- `requirements.txt`
- `docker-compose.prod.yml`

## Что входит в следующий безопасный деплой

- Единый стандарт телефонов в тестах: `+7...`
- Регрессионные тесты для запрета чужих разделов и запрещенных действий
- Проверка обновления матрицы прав администратором
- Матрица прав в админке
- Расширенная аналитика по каналам, задачам, складу и среднему времени ответа

## Проверка перед выкладкой

```powershell
docker compose up -d db
$env:DJANGO_SECRET_KEY="test-secret-key"
$env:DJANGO_DEBUG="1"
python manage.py check
python manage.py test crm --verbosity 1
```

Ожидаемо:

- `System check identified no issues`
- все тесты проходят

## После выкладки

1. Пересобрать `web`.
2. Применить миграции через entrypoint.
3. Проверить `/login/`.
4. Проверить вход администратора.
5. Открыть `?page=admin` и убедиться, что видна матрица прав.
6. Открыть `?page=analytics` и убедиться, что видны KPI и таблица каналов.
7. Если всё стабильно, удалить временный каталог `/opt/plantflow-crm.rollback_20260702_172510`.
