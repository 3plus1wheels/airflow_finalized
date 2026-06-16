# AGENTS.md

## Purpose

This file is operational guidance for AI coding agents working in this repository. It describes the project shape, expected workflows, safety rules, storage model, verification commands, and implementation conventions. Follow this file before changing code.

This repository is a MinIO-backed object storage wrapper with:

- `backend/`: Django REST API using JWT authentication and boto3-compatible MinIO calls.
- `frontend/`: Vite + React object browser UI.
- `compose.yml`: local and production-oriented Docker Compose stack for frontend, backend, and MinIO.

The core product goal is a usable object browser: authenticate, create buckets, browse object paths, upload files/folders, inspect object details, and perform object actions.

## Current Architecture

### Services

Compose starts three services:

- `minio`: `minio/minio:latest`, S3-compatible object storage.
- `backend`: Django app served by the backend image.
- `frontend`: Vite-built React app served by nginx.

Ports:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000/api`
- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`

### Data Storage

MinIO stores object data at `/data` inside the MinIO container.

Compose mounts `/data` from:

```yaml
${MINIO_DATA_DIR:-./minio-data}:/data
```

Local default:

```text
./minio-data
```

Production should set `MINIO_DATA_DIR` to a stable host path:

Linux examples:

```env
MINIO_DATA_DIR=/srv/minio/data
MINIO_DATA_DIR=/mnt/minio-data
```

Windows Server example:

```env
MINIO_DATA_DIR=D:/minio/data
```

Do not manually edit MinIO internal object files. Inspect objects through the MinIO console, S3 API, or application API. Back up the host path used by `MINIO_DATA_DIR`.

Backend SQLite data in Compose is stored in Docker named volume `backend_data`, mounted to `/app/data`.

### Authentication

The backend uses Django REST Framework with SimpleJWT.

Relevant frontend storage:

- `localStorage.accessToken`
- `localStorage.refreshToken`

The app currently removes tokens on sign-out and auth expiry.

### API Layer

Frontend API helpers live in:

```text
frontend/src/api.js
```

Backend views live in:

```text
backend/storage_api/views.py
```

Backend URL routes live in:

```text
backend/storage_api/urls.py
```

## Important Files

Root:

- `compose.yml`: service wiring, ports, storage mount.
- `.env.example`: safe template for Compose settings.
- `.gitignore`: ignores local secrets and generated data.
- `README.md`: human setup instructions.
- `AGENTS.md`: this file.

Backend:

- `backend/config/settings.py`: Django config, env handling, MinIO settings.
- `backend/storage_api/views.py`: REST endpoint behavior.
- `backend/storage_api/serializers.py`: request validation.
- `backend/storage_api/minio_client.py`: boto3 S3 client factory.
- `backend/storage_api/tests.py`: backend API tests with mocked S3 client.
- `backend/entrypoint.sh`: container startup behavior.
- `backend/Dockerfile`: backend image.

Frontend:

- `frontend/src/main.jsx`: main React app and object browser.
- `frontend/src/api.js`: API helpers.
- `frontend/src/styles.css`: all current UI styling.
- `frontend/package.json`: frontend scripts.
- `frontend/Dockerfile`: frontend build and nginx image.
- `frontend/nginx.conf`: nginx config for SPA routing.

## Working Rules

### Do Not Commit Secrets

Never commit:

- `.env`
- `backend/.env`
- any access keys
- JWT signing secrets
- real MinIO credentials
- local object data under `minio-data/`

Use `.env.example` for safe templates.

### Preserve User Data

Object data lives under `MINIO_DATA_DIR`. Treat it as user data.

Do not delete or overwrite:

- `minio-data/`
- production `MINIO_DATA_DIR`
- Docker volumes
- uploaded object directories

If a migration or storage layout change is needed, copy data first and explain the migration path.

### Avoid Unrelated Refactors

Keep changes scoped to the requested behavior. This app is small, but large incidental rewrites can easily break auth, upload, path handling, or object action flows.

### Prefer Existing Patterns

Use current patterns unless there is a clear reason to change:

- React function components and hooks in `frontend/src/main.jsx`.
- Plain CSS in `frontend/src/styles.css`.
- API helper functions in `frontend/src/api.js`.
- DRF `APIView` classes in `backend/storage_api/views.py`.
- boto3 S3 client from `get_s3_client()`.

## Development Commands

### Full Stack With Docker

Start or rebuild all services:

```bash
docker compose -f compose.yml up --build -d
```

Show service status:

```bash
docker compose -f compose.yml ps
```

Stop services:

```bash
docker compose -f compose.yml down
```

View logs:

```bash
docker compose -f compose.yml logs
docker compose -f compose.yml logs storage-backend
docker compose -f compose.yml logs frontend
docker compose -f compose.yml logs minio
```

Run backend tests in container:

```bash
docker compose -f compose.yml exec storage-backend python manage.py test storage_api
```

### Backend Locally

From repository root:

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
.venv/bin/python manage.py test storage_api
```

From repo root, if root virtualenv exists:

```bash
./.venv/bin/python backend/manage.py test storage_api
```

Note: `backend/manage.py test` without the app label may report zero tests depending on working directory and discovery context. Prefer:

```bash
./.venv/bin/python backend/manage.py test storage_api
```

### Frontend Locally

```bash
cd frontend
npm install
npm run dev
```

Build:

```bash
cd frontend
npm run build
```

Preview production build:

```bash
cd frontend
npm run preview
```

## Verification Checklist

For frontend changes:

```bash
cd frontend
npm run build
```

For backend API changes:

```bash
./.venv/bin/python backend/manage.py test storage_api
```

For container-level changes:

```bash
docker compose -f compose.yml up --build -d
docker compose -f compose.yml ps
docker compose -f compose.yml exec storage-backend python manage.py test storage_api
```

Smoke checks:

```bash
curl -sS -I http://localhost:5173/
curl -sS -I http://localhost:8000/api/buckets/
curl -sS -I http://localhost:9001/
```

Expected:

- Frontend returns `200`.
- Backend `/api/buckets/` returns `401` without token. That is correct.
- MinIO console returns `200`.

## Backend Behavior

### Bucket Endpoints

Current bucket behavior:

- List buckets: `GET /api/buckets/`
- Create bucket: `POST /api/buckets/`
- Delete bucket: `DELETE /api/buckets/<bucket>/`

Bucket names are validated by `BucketSerializer` with S3-like naming constraints.

### Object Endpoints

Current object behavior:

- List objects: `GET /api/buckets/<bucket>/objects/`
- Upload object: `POST /api/buckets/<bucket>/objects/`
- Delete object: `DELETE /api/buckets/<bucket>/objects/?key=<key>`
- Download object: `GET /api/buckets/<bucket>/objects/download/?key=<key>`
- Share object: `GET /api/buckets/<bucket>/objects/share/?key=<key>`
- Get object tags: `GET /api/buckets/<bucket>/objects/tags/?key=<key>`
- Save object tags: `PUT /api/buckets/<bucket>/objects/tags/?key=<key>`
- List object versions: `GET /api/buckets/<bucket>/objects/versions/?key=<key>`

Object list returns:

- `key`
- `size`
- `last_modified`
- `etag`
- `content_type`
- `metadata`

Listing currently calls `head_object` for each listed object to fetch content type and user metadata. This is acceptable for the current app size, but it can become expensive on large buckets. If object counts grow, consider paginating and fetching details only for selected objects.

### Upload Key Rules

Frontend upload key construction:

```text
currentPrefix + file.webkitRelativePath || file.name
```

Important:

- File upload uses current path prefix.
- Folder upload uses `webkitRelativePath` and preserves folder structure.
- Path creation creates a pending folder-like prefix in the frontend. In S3/MinIO, folders are key prefixes, not real directories, unless marker objects are added.

### Content Type

The backend preserves browser-provided MIME type:

```python
ExtraArgs={"ContentType": uploaded_file.content_type}
```

If content type is missing, UI falls back to:

```text
binary/octet-stream
```

### Share and Preview

Share returns a presigned URL. The frontend sends an `expires_in` query value in seconds. The backend clamps expiry between 60 seconds and 7 days.

Generated URLs use `MINIO_PUBLIC_ENDPOINT`, not the internal Compose endpoint. Set `MINIO_PUBLIC_ENDPOINT` to the public MinIO API origin for deployment.

Preview uses the same share URL and opens it in a new tab.

### Tags

Tags are stored through S3 object tagging, not custom metadata.

Frontend tag editor uses one `key=value` pair per line.

### Versions

`Display Object Versions` calls `list_object_versions`. It reports the count in status. Buckets must have versioning enabled in MinIO for useful results.

## Frontend Behavior

### Routing

Routing is client-side:

- `/login`
- `/browser`
- `/browser/<bucket>`

`getRoute()` parses `window.location.pathname`. `pushRoute()` updates history and dispatches `popstate`.

### Object Browser State

Important state in `ObjectBrowser`:

- `buckets`
- `selectedBucket`
- `objects`
- `currentPrefix`
- `pendingFolders`
- `selectedObject`
- `objectFilter`
- `status`
- modal flags

When changing upload, folder, path, or object details behavior, check interactions with:

- `buildObjectEntries()`
- `getParentPrefix()`
- `normalizeFolderPath()`
- `getObjectDisplayName()`
- `selectedObject` refresh logic

### White Screen Pitfall

The UI previously crashed after upload when `selectedObject` was refreshed from raw API data without a `name` property. Be careful not to assume object entries always have UI-only fields.

Backend objects have:

```text
key, size, last_modified, etag, content_type, metadata
```

UI object entries add:

```text
type, name
```

Use null-safe helpers for display name and file extension.

### Buttons and Tooltips

Buttons should have:

- clear visible text or icon
- `title` tooltip
- `aria-label` when icon-only
- hover/focus behavior from CSS

Disabled buttons should not animate like active controls.

### Object Details Panel

Clicking a file row opens the right details panel.

The details panel includes:

- object header
- actions
- delete button
- object info
- metadata

Folder rows navigate into the folder prefix instead of opening details.

### Object Actions

Current UI behavior:

- Download: fetch blob, create temporary object URL, click temporary anchor.
- Share: fetch presigned URL, copy to clipboard if possible.
- Preview: fetch presigned URL, open new tab.
- Tags: open modal, load tags, save tags.
- Display Object Versions: request version list and show count.
- Delete: confirm with `window.confirm`, then delete and clear selection.

### Styling

All styling currently lives in:

```text
frontend/src/styles.css
```

Use existing design language:

- square-ish 4px radius controls
- restrained borders
- MinIO-inspired dark navy and red accents
- lucide icons for actions
- dense operational layout, not marketing layout

Avoid:

- decorative blobs or gradient-only ornament
- nested cards
- oversized hero styling in tool surfaces
- negative letter spacing
- viewport-scaled font sizes
- hidden overflow that truncates critical action text without tooltip

For responsive changes, test narrow layouts mentally and via browser when possible. Current mobile behavior hides some path-row buttons under `max-width: 900px`; update that media rule if adding important path actions.

## Docker and Storage Operations

### Inspect MinIO Data

Use MinIO console:

```text
http://localhost:9001
```

Or inspect mounted host folder:

```text
./minio-data
```

Inside container:

```bash
docker exec minio_custom-minio-1 sh -c 'ls -la /data'
```

Verify bind mount:

```bash
docker inspect minio_custom-minio-1 --format '{{json .Mounts}}'
```

Expected local mount:

```text
Source: /Users/vova_nguyen/Documents/minio_custom/minio-data
Destination: /data
Type: bind
```

### Preserve Data When Changing Mounts

If changing from Docker volume to bind mount or from one host path to another:

1. Stop and understand current mount.
2. Copy existing data before recreating containers.
3. Verify buckets appear after restart.
4. Do not remove old volume until user confirms migration succeeded.

Useful copy command:

```bash
docker cp minio_custom-minio-1:/data ./minio-data
```

### Production Storage Guidance

For dedicated Linux server:

```env
MINIO_DATA_DIR=/srv/minio/data
```

For Windows Server:

```env
MINIO_DATA_DIR=D:/minio/data
```

Create path before Compose starts.

Back up the data path. Do not store production data in the repo folder.

## API Error Handling

Frontend `apiRequest()`:

- sets `Authorization` header if token exists
- sets `Content-Type: application/json` for non-FormData bodies
- parses error JSON when possible
- attaches `status` to thrown error

When adding API helpers:

- use `encodeURIComponent(bucket)` for bucket path segment
- use `encodeURIComponent(key)` for object query param
- preserve the `status` property on thrown errors
- handle `401` in the calling component by invoking `onAuthExpired()`

Backend `error_response()`:

- extracts boto3 `ClientError` messages
- returns DRF `Response({"detail": ...})`

When adding backend endpoints:

- require `key` query param for object-specific operations
- return `400` for missing/invalid parameters
- return `404` only when object-specific fetch truly misses object
- keep response JSON small and explicit

## Testing Guidance

### Backend Tests

Tests mock `storage_api.views.get_s3_client`. When adding S3 calls, update mocks with concrete return values. Do not leave `Mock()` values inside API responses, because DRF rendering can hang or produce invalid output.

Good:

```python
s3.head_object.return_value = {
    "ContentType": "text/plain",
    "Metadata": {},
}
```

Bad:

```python
s3.head_object.return_value = Mock()
```

Use targeted command:

```bash
./.venv/bin/python backend/manage.py test storage_api
```

Container equivalent:

```bash
docker compose -f compose.yml exec storage-backend python manage.py test storage_api
```

### Frontend Build

Always run:

```bash
cd frontend
npm run build
```

There are no frontend unit tests at the moment. Build is the minimum verification for frontend changes.

### Manual UI Flows To Check

After frontend/object changes, test these flows:

1. Login.
2. Select a bucket.
3. Upload a file.
4. Upload a folder.
5. Create a path.
6. Navigate into a folder row.
7. Navigate back with path back button.
8. Click file row and verify details panel opens.
9. Copy path.
10. Download object.
11. Share object and confirm status.
12. Preview object.
13. Edit tags.
14. Display versions.
15. Delete object.

## Environment Variables

Root `.env` for Compose:

```env
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_DATA_DIR=./minio-data
MINIO_PUBLIC_ENDPOINT=http://localhost:9000
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,storage-backend
DJANGO_CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
JWT_ACCESS_TOKEN_MINUTES=720
JWT_REFRESH_TOKEN_DAYS=14
VITE_API_BASE_URL=http://localhost:8000/api
```

Backend service receives:

```env
MINIO_ENDPOINT=http://minio:9000
MINIO_ACCESS_KEY=${MINIO_ROOT_USER}
MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD}
MINIO_SECURE=false
```

Local non-Compose backend reads `backend/.env`.

## Security Notes

This project is currently suitable for development and small controlled deployments, but production hardening needs attention.

Important production items:

- Use strong Django `DJANGO_SECRET_KEY`.
- Use strong MinIO credentials.
- Do not use root MinIO credentials for routine application access if separate users/policies are introduced.
- Enable TLS for public deployments.
- Restrict allowed hosts and CORS origins.
- Use HTTPS-only frontend/backend access.
- Back up MinIO data path.
- Monitor disk usage.
- Consider object versioning and lifecycle policies if deletion safety matters.
- Keep presigned URL expiry short enough for the use case.

## Known Limitations

Current limitations:

- Object listing does not paginate yet.
- Object listing fetches `head_object` for each object.
- Folder creation is frontend-pending until a file is uploaded into that prefix.
- Version display shows count/status, not a full versions table.
- Delete uses browser `window.confirm`, not a custom modal.
- Tags modal accepts simple `key=value` lines only.
- No frontend unit tests yet.
- No role-based access model beyond Django authentication.
- No refresh-token rotation flow in frontend beyond storing refresh token.

When improving these, keep backward compatibility with existing buckets and object keys.

## Code Quality Expectations

### Backend

- Validate request data with serializers when shape is non-trivial.
- Keep S3 exception handling explicit.
- Avoid leaking raw credentials or internal paths in API responses.
- Keep endpoint responses predictable and documented by tests.
- Add or update tests for new backend behavior.
- Prefer small helper functions over repeated S3 response shaping.

### Frontend

- Keep object/key path handling robust.
- Use stable display names for objects.
- Avoid assuming backend objects have UI-only fields.
- Keep every interactive button accessible.
- Add status messages for meaningful actions.
- Keep layout stable at desktop and mobile widths.
- Use existing lucide icon set.
- Prefer focused helper functions over inline complex transformations.

### Docker

- Keep Compose environment-driven.
- Do not hardcode local absolute paths in `compose.yml`.
- Use `.env.example` for defaults.
- Keep production storage path configurable through `MINIO_DATA_DIR`.

## Git Hygiene

Before reporting completion, check:

```bash
git status --short
```

Expected generated/local paths ignored:

- `.env`
- `minio-data/`
- virtualenvs
- `node_modules/`
- `dist/`

Do not revert user changes. If files are already dirty, work with them and keep edits scoped.

## Recommended Change Flow

Use this order for most tasks:

1. Inspect relevant files with `rg`, `sed`, and targeted reads.
2. Identify existing patterns.
3. Make minimal scoped edits.
4. Run relevant build/tests.
5. If Docker or storage changed, rebuild/recreate stack and verify mounts.
6. Summarize exactly what changed and how it was verified.

For object upload/storage work, add one more step:

7. Confirm data path and existing buckets are preserved.

## Quick Reference

Build frontend:

```bash
cd frontend && npm run build
```

Run backend tests:

```bash
./.venv/bin/python backend/manage.py test storage_api
```

Rebuild stack:

```bash
docker compose -f compose.yml up --build -d
```

Show stack:

```bash
docker compose -f compose.yml ps
```

Inspect MinIO mount:

```bash
docker inspect minio_custom-minio-1 --format '{{json .Mounts}}'
```

List local MinIO data:

```bash
ls -la minio-data
```

Open app:

```text
http://localhost:5173
```

Open MinIO console:

```text
http://localhost:9001
```
