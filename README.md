# Study Quest — Docker Compose application

A study-goal tracker: add quests, list them, and mark them complete. The Python
backend reads and writes PostgreSQL data; the browser page uses the same JSON API.

## Start

Start Docker Desktop (Linux containers) and open a terminal **in the inner
`Webproject` folder containing `compose.yaml`**.

On a fresh checkout, create your local configuration (CMD or PowerShell):

```cmd
copy .env.example .env
```

Edit `.env` and replace `POSTGRES_PASSWORD` with your own random password.
The local `.env` is ignored by Git and excluded from the Docker build context.
If a locally generated `.env` already exists, keep it instead of overwriting it.

```cmd
docker compose up
```

Open http://localhost:8080. Compose builds the backend automatically on first use.
For background mode use `docker compose up -d --build`; after code changes rebuild
with that command. If port 8080 is occupied, change `APP_PORT` in `.env`.

## Services and configuration

| Component | Configuration |
| --- | --- |
| `backend` | Custom Python 3.12 image, non-root user, HTTP port 8080 |
| `db` | PostgreSQL 17, internal port 5432, no host port published |
| Network | Both services join `app-network`; backend connects to hostname `db` |
| Startup | Database healthcheck must pass before backend starts; table is created automatically |
| Storage | Named volume `postgres-data` mounted at `/var/lib/postgresql/data` |
| Health | `/health` runs `SELECT 1`; backend image healthcheck calls this endpoint |

Compose reads `.env`: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`APP_PORT`, `APP_NAME`, and `APP_MESSAGE`. It passes database settings to the
backend as `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`.
Required database settings have no fallback credentials. Never commit `.env`.
PostgreSQL initialization variables apply to a **new, empty volume**; changing
these later does not update existing database accounts.

## API examples (PowerShell)

```powershell
# Write a study goal to PostgreSQL (HTTP 201).
$quest = Invoke-RestMethod http://localhost:8080/api/quests -Method Post -ContentType 'application/json' -Body '{"title":"Learn Docker Compose","subject":"DevOps"}'

# Read stored goals (HTTP 200).
Invoke-RestMethod http://localhost:8080/api/quests | ConvertTo-Json -Depth 5

# Update the saved goal (HTTP 200).
Invoke-RestMethod "http://localhost:8080/api/quests/$($quest.id)" -Method Patch -ContentType 'application/json' -Body '{"completed":true}'

Invoke-RestMethod http://localhost:8080/health
```

`POST /api/quests` requires a nonblank `title` (up to 120 characters) and
`subject` (up to 60). `PATCH /api/quests/{id}` requires a boolean `completed`.
Invalid input returns 400, missing routes/quests 404, and database failures 503.
SQL uses bound parameters. `/api/info` exposes the application name and message.

## Verify persistence

After adding a quest, run:

```cmd
docker compose down
docker compose up -d
```

Refresh the page or repeat `GET /api/quests`: the same quest and completion state
remain. `down` removes containers and the network while retaining the named volume.
`docker compose stop` also retains data; resume with `docker compose up -d`.
**Do not use `docker compose down -v` unless you intend to delete the database.**

## Check and stop

To repeat the API and persistence checks in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\verify.ps1
```

The script creates one demonstration quest, checks invalid inputs, recreates the
containers with `down` / `up`, and verifies the saved quest. It leaves the app running.

```cmd
docker compose ps
docker compose logs backend
docker compose logs db
docker compose down
```

Configuration reference: [Compose startup order and database readiness](https://docs.docker.com/compose/how-tos/startup-order/).
Database adapter: [Psycopg on PyPI](https://pypi.org/project/psycopg/).
