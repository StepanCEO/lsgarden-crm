# PlantFlow CRM - Project Handoff

## Short Summary

This is a Django-based CRM for a plant shop, aligned with the Russian technical brief. The project now runs as a Django app with PostgreSQL for production and SQLite for quick local viewing. The UI uses an Apple-inspired visual style from the `apple` folder in the repo.

## Current Stack

- Django 6.x
- PostgreSQL for production
- SQLite fallback for local preview
- Gunicorn for containerized production
- WhiteNoise for static files
- Docker / Docker Compose

## Main Goal

Build a production-ready CRM for:

- clients
- products / inventory
- tasks / tickets
- unified inbox
- knowledge base / training
- analytics
- admin panel

Main external integrations expected from the client:

- 1C
- VK
- Avito
- Telegram
- Email
- website
- S3 for media and backups

## Important Files

- [`config/settings.py`](C:\Users\User\Desktop\Projects\CRM\config\settings.py)
- [`config/urls.py`](C:\Users\User\Desktop\Projects\CRM\config\urls.py)
- [`crm/models.py`](C:\Users\User\Desktop\Projects\CRM\crm\models.py)
- [`crm/views.py`](C:\Users\User\Desktop\Projects\CRM\crm\views.py)
- [`crm/urls.py`](C:\Users\User\Desktop\Projects\CRM\crm\urls.py)
- [`crm/seed.py`](C:\Users\User\Desktop\Projects\CRM\crm\seed.py)
- [`crm/templates/crm/base.html`](C:\Users\User\Desktop\Projects\CRM\crm\templates\crm\base.html)
- [`crm/templates/crm/login.html`](C:\Users\User\Desktop\Projects\CRM\crm\templates\crm\login.html)
- [`crm/templates/crm/dashboard.html`](C:\Users\User\Desktop\Projects\CRM\crm\templates\crm\dashboard.html)
- [`static/crm/styles.css`](C:\Users\User\Desktop\Projects\CRM\static\crm\styles.css)
- [`requirements.txt`](C:\Users\User\Desktop\Projects\CRM\requirements.txt)
- [`Dockerfile`](C:\Users\User\Desktop\Projects\CRM\Dockerfile)
- [`docker-compose.yml`](C:\Users\User\Desktop\Projects\CRM\docker-compose.yml)
- [`entrypoint.sh`](C:\Users\User\Desktop\Projects\CRM\entrypoint.sh)
- [`.env.example`](C:\Users\User\Desktop\Projects\CRM\.env.example)
- [`.env`](C:\Users\User\Desktop\Projects\CRM\.env)
- [`README.md`](C:\Users\User\Desktop\Projects\CRM\README.md)

## What Is Already Implemented

### Authentication

- Login page with admin and employee login flow
- Employee access code check
- Demo users seeded

### CRM Areas

- Dashboard
- Unified inbox
- Clients
- Tasks / tickets
- Products / inventory
- Knowledge base / training
- Analytics shell
- Admin panel

### Models

- `EmployeeProfile`
- `Client`
- `Message`
- `Task`
- `Product`
- `KnowledgeArticle`
- `NewsItem`
- `AuditEntry`

### Business Logic

- create/update client
- create task
- send message
- sync inventory from 1C placeholder
- sync bank placeholder
- toggle user active/inactive
- CSV user import
- auto follow-up task
- quick knowledge test
- simulate incoming message
- audit logging

## Current UX Notes

- Apple-inspired minimal interface
- left black sidebar
- light content area
- compact login page
- pages are section-based
- mobile layout collapses to a single column

## Current Local Run Modes

### SQLite preview

Use this if you only want to inspect the UI quickly.

```powershell
$env:DJANGO_USE_SQLITE="1"
$env:DJANGO_SECRET_KEY="test-secret-key"
$env:DJANGO_DEBUG="1"
python manage.py migrate
python manage.py runserver
```

Open:

- `http://127.0.0.1:8000/login/`

### PostgreSQL mode

Use this for actual production-like behavior.

Required env vars:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=0`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`

Example:

```powershell
$env:DJANGO_DEBUG="0"
$env:DJANGO_USE_SQLITE="0"
$env:DJANGO_SECRET_KEY="replace-with-real-secret"
$env:DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,crm.example.com"
$env:DJANGO_CSRF_TRUSTED_ORIGINS="https://crm.example.com"
$env:POSTGRES_DB="plant_crm"
$env:POSTGRES_USER="plant_crm"
$env:POSTGRES_PASSWORD="plant_crm"
$env:POSTGRES_HOST="127.0.0.1"
$env:POSTGRES_PORT="5433"
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

## Docker

The current Docker setup uses:

- `db` service for PostgreSQL
- `web` service with `gunicorn`
- entrypoint that runs migrations and `collectstatic`

Typical command:

```bash
docker compose up --build
```

## Demo Data

Seed command:

```bash
python manage.py seed_demo
```

Important seeded users:

- `admin / admin123`
- `front / front123 / 246810`
- `hybrid / hybrid123 / 246810`
- `back / back123 / 246810`
- `content / content123 / 246810`
- `locomotive / drive123 / 246810`

## Knowledge Base Notes

The knowledge section is intentionally a lightweight internal support area, not a full LMS.

It currently supports:

- role-based articles
- news items
- a quick knowledge test
- auto scripts for standard replies

The test accepts normal human answers for the "out of stock" scenario, not only one exact phrase.

## Important UX Fixes Already Done

- Removed demo credentials from the login page
- Kept only the short text:
  - "Единое окно для входящих сообщений, клиентов, склада, скриптов, обучения и аналитики."
- Fixed the black left sidebar background so it continues to the bottom
- Reduced page width issues and horizontal overflow
- Adjusted sections so they do not overlap or push content too wide
- Fixed the tasks page so the filter does not fall under the "New task" card

## Known Limitations / Next Work

### 1C integration

Still not implemented against a real client 1C.
Need client access to determine:

- API
- OData
- XML / CSV exchange
- direct remote desktop based setup

### External integrations

VK, Avito, Telegram, Email, and website integrations are still placeholders / planning items.

### Knowledge base

The knowledge area works, but it can still be improved by:

- separating content by role more clearly
- adding categories
- making the test more realistic
- adding an article detail view

### Analytics

There is a dashboard shell, but no full business intelligence layer yet.

## Client Questions Needed

- What exact 1C setup is used?
- Which integration method is available?
- What data must be synchronized first?
- What are the production server details?
- Which channels must be connected first?
- What is the S3 provider?
- What staff roles and permissions are needed?
- What is the final list of workflows and statuses?

## Useful Commands

### Check project

```bash
python manage.py check
```

### Run migrations

```bash
python manage.py migrate
```

### Load demo data

```bash
python manage.py seed_demo
```

### Start dev server

```bash
python manage.py runserver
```

### Collect static files

```bash
python manage.py collectstatic --noinput
```

## Notes for the Next AI

- Do not remove the SQLite fallback unless explicitly asked.
- Do not revert the Apple-style interface unless requested.
- The project is meant to stay Django-first.
- Preserve the current file structure unless there is a strong reason to refactor.
- If changing templates, always check for horizontal overflow and broken sidebar/sidebar-footer behavior.
- If adding new context variables, avoid names that collide with Django built-in `messages`.
- If extending the training section, keep the content practical and role-oriented.

