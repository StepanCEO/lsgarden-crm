# PlantFlow CRM

CRM на Django + PostgreSQL по ТЗ для магазина растений.

## Документация

- [Продуктовая и техническая спецификация](docs/product_technical_spec.md)
- [Вопросы к заказчику](docs/customer_questions.md)

## Запуск локально

1. Скопируйте `.env.example` в `.env` и при необходимости поправьте значения.

2. Поднимите PostgreSQL:

```bash
docker compose up -d db
```

3. Примените миграции:

```bash
python manage.py migrate
```

4. Запустите сервер:

```bash
python manage.py runserver
```

Чтобы загрузить демо-данные:

```bash
python manage.py seed_demo
```

Откройте `http://127.0.0.1:8000`.

## Запуск через Docker

```bash
docker compose up --build
```

После старта откройте `http://127.0.0.1:8000`.

## Production-настройки

- `DEBUG=0`
- `DJANGO_SECRET_KEY` обязателен
- `ALLOWED_HOSTS` и `CSRF_TRUSTED_ORIGINS` должны быть заполнены под домен заказчика
- статические файлы собираются через `collectstatic`
- веб-сервер запускается через `gunicorn`

## Демо-доступы

- `admin / admin123`
- `front / front123 / 246810`
- `hybrid / hybrid123 / 246810`
- `back / back123 / 246810`
- `content / content123 / 246810`
- `locomotive / drive123 / 246810`

## Что есть

- Авторизация с кодом для сотрудников
- Дашборд, единое окно, клиенты, тикеты, склад, знания, аналитика и админка
- Модели и данные в PostgreSQL
- Docker-деплой
- Логирование действий, антифрод и базовая автоматизация
