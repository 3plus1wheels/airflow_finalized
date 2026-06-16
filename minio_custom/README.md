# MinIO S3 Wrapper

Two-folder scaffold:

- `backend/`: Django REST API with JWT auth and MinIO-backed bucket/object endpoints.
- `frontend/`: Vite React shell for later screenshot-driven UI work.

## Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

Run tests:

```bash
cd backend
.venv/bin/python manage.py test
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

## Docker Compose

Run backend, frontend, PostgreSQL 17, and MinIO:

```bash
cp .env.example .env
docker compose -f compose.yml up --build
```

Open:

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000/api
- MinIO console: http://localhost:9001
- PostgreSQL: localhost:5432

Compose binds MinIO and PostgreSQL host ports to `127.0.0.1` by default. For production, keep those ports private and expose user traffic through a TLS reverse proxy or firewall-controlled network path.

Create the first root app user after the stack is running:

```bash
docker compose -f compose.yml exec storage-backend python manage.py createsuperuser
```

This command is the preferred first-launch setup path. It writes the superuser to PostgreSQL through Django; do not create the first app user manually with SQL.

For non-interactive setup, use a one-off shell command and replace the placeholder values before running:

```bash
docker compose -f compose.yml exec storage-backend python manage.py shell -c "from django.contrib.auth import get_user_model; from storage_api.models import UserProfile; User=get_user_model(); u,_=User.objects.get_or_create(username='CHANGE_ME_USERNAME'); u.is_superuser=True; u.is_staff=True; u.is_active=True; u.set_password('CHANGE_ME_STRONG_PASSWORD'); u.save(); UserProfile.objects.update_or_create(user=u, defaults={'role': UserProfile.ROLE_ADMIN}); print('superuser ready')"
```

Log in to the frontend with the superuser account. Open the `Admin` tab to create normal users, groups, and visibility grants.

App roles:

- `superuser`: full root access, including admins and all storage.
- `admin`: manages editor/viewer users and visibility grants; cannot manage superusers.
- `editor`: reads and writes only granted buckets or prefixes.
- `viewer`: reads only granted buckets or prefixes.

Visibility grants:

- Target can be a role or a specific user.
- Target can also be an admin-created group of editor/viewer users.
- Blank prefix means the whole bucket.
- `write` implies `read`.
- Editor/viewer accounts see no buckets until an admin or superuser grants access.
- New buckets default to open access for all viewers/editors. Pick a group in the Create Bucket dialog to restrict the new bucket to that group instead.

MinIO login:

- Username: value of `MINIO_ROOT_USER` in `.env`
- Password: value of `MINIO_ROOT_PASSWORD` in `.env`

PostgreSQL login:

- Host: `localhost`
- Port: value of `POSTGRES_HOST_PORT` in `.env`, default `5432`
- Maintenance database: value of `POSTGRES_DB` in `.env`, default `minio_custom`
- Username: value of `POSTGRES_USER` in `.env`
- Password: value of `POSTGRES_PASSWORD` in `.env`

pgAdmin 4 setup:

1. Right-click `Servers`.
2. Select `Register` > `Server...`.
3. On `General`, set `Name` to `minio_custom`.
4. On `Connection`, set:
   - `Host name/address`: `localhost`
   - `Port`: value of `POSTGRES_HOST_PORT` in `.env`
   - `Maintenance database`: value of `POSTGRES_DB` in `.env`
   - `Username`: value of `POSTGRES_USER` in `.env`
   - `Password`: value of `POSTGRES_PASSWORD` in `.env`
5. Click `Save`.
6. Expand `Servers > minio_custom > Databases > minio_custom > Schemas > public > Tables`.

If local PostgreSQL already uses port `5432`, set `POSTGRES_HOST_PORT=5433` in `.env` and use port `5433` in pgAdmin. Red X icons on other pgAdmin databases usually mean stale or disconnected entries; they are unrelated to this Docker database.

Frontend authentication uses httpOnly JWT cookies. In production, serve the frontend/API over HTTPS and set:

```env
JWT_COOKIE_SECURE=true
DJANGO_CORS_ALLOWED_ORIGINS=https://app.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.com
VITE_API_BASE_URL=/api
```

The frontend nginx container proxies `/api/` to the `storage-backend` container. This lets a single public frontend URL, including a Cloudflare Tunnel pointed only at the frontend service, serve both the SPA and API from the same origin. For a temporary trycloudflare URL, include the tunnel host in Django host/CSRF settings:

```env
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,storage-backend,trading-profession-homework-distributed.trycloudflare.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://trading-profession-homework-distributed.trycloudflare.com
JWT_COOKIE_SECURE=true
VITE_API_BASE_URL=/api
```

Share links use `MINIO_PUBLIC_ENDPOINT` from `.env`. For local development this can be `http://localhost:9000`. For deployment, set it to the public MinIO API origin users can reach, for example:

```env
MINIO_PUBLIC_ENDPOINT=https://minio.example.com
```

Do not commit `.env`. It contains the MinIO root credentials and Django signing key.

Compose stores generated data in Docker named volumes:

- `MINIO_DATA_DIR` (default `./minio-data`): object data mounted into MinIO at `/data`
- `postgres_data`: PostgreSQL database cluster

The backend now uses PostgreSQL only. The Compose stack creates the database and user from the `POSTGRES_*` environment values on first startup, then `backend/entrypoint.sh` runs Django migrations.

For production on a dedicated server, set `MINIO_DATA_DIR` to a stable host path such as `/srv/minio/data` or `/mnt/minio-data`. The local `minio-data/` folder is ignored by git. Docker pulls the MinIO image locally; image layers stay outside the repository.

Windows Server production example:

```env
MINIO_DATA_DIR=D:/minio/data
```

Create the folder before starting Compose:

```powershell
mkdir D:\minio\data
docker compose -f compose.yml up -d --build
```

Back up the `D:\minio\data` folder. Avoid using `./minio-data` in production because the project folder can move or be replaced during deploys.
