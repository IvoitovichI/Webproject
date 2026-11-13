# Study Quest

REST API and study-goal tracker built with Python 3.12, aiohttp, SQLAlchemy,
and PostgreSQL 17. Courses contain quests; quests contain steps. The existing
browser page creates, lists, and completes quests.

## Run with Docker

Start Docker Desktop using Linux containers. From this directory:

```powershell
Copy-Item .env.example .env
```

If `.env` already exists, keep it. Set your own `POSTGRES_PASSWORD`, then run:

```powershell
docker compose up -d --build --wait
```

Open http://localhost:8080. If that port is occupied, change `APP_PORT` in `.env`
and use the same port in Postman's `baseUrl`.

Compose runs the backend and PostgreSQL on a private network. PostgreSQL is
available to the backend as `db:5432`; it does not publish a host port. Tables
are created automatically. Existing quests are retained and receive a nullable
`course_id` column. Database data is stored in the `postgres-data` named volume.

```powershell
docker compose ps
docker compose logs backend
docker compose down
```

`down` preserves the database. `down -v` deletes it. Existing database credentials
are stored in the volume; editing `.env` does not change those accounts.

## Run locally without Docker

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

With no database environment variables, this uses SQLite at
`instance/study_quest.db`. SQLite is relational and enforces foreign keys.
Set `DATABASE_URL` to a SQLAlchemy URL to choose a different database, for example
`postgresql+psycopg://user:password@localhost:5432/study_quest`.
Alternatively set `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`,
as Compose does. `HOST` defaults to `0.0.0.0`; `PORT` defaults to `8080`.

## Use the API

Full endpoint, validation, and response reference: [API.md](API.md).

```powershell
$course = Invoke-RestMethod http://localhost:8080/api/courses -Method Post -ContentType application/json -Body '{"name":"Web Development"}'
$quest = Invoke-RestMethod "http://localhost:8080/api/courses/$($course.id)/quests" -Method Post -ContentType application/json -Body '{"title":"Build REST API","subject":"Backend"}'
$step = Invoke-RestMethod "http://localhost:8080/api/quests/$($quest.id)/steps" -Method Post -ContentType application/json -Body '{"title":"Document endpoints"}'
Invoke-RestMethod "http://localhost:8080/api/steps/$($step.id)" -Method Patch -ContentType application/json -Body '{"completed":true}'
Invoke-RestMethod "http://localhost:8080/api/courses/$($course.id)/quests"
```

Delete steps before their quest, and quests before their course. Deleting a
parent with dependent records returns `409`. A quest may have no course, allowing
the existing page to work. Quest and step completion are independent flags.

## Postman and tests

Import both files into Postman:

- [StudyQuest.postman_collection.json](postman/StudyQuest.postman_collection.json)
- [StudyQuest.local.postman_environment.json](postman/StudyQuest.local.postman_environment.json)

Select **Study Quest - Local**, then run the entire collection in order using
Collection Runner. The collection covers every JSON endpoint, validates related
data and errors, and removes its temporary records in dependency order.

With Node.js installed, the same collection runs from a terminal:

```powershell
npx --yes newman run postman/StudyQuest.postman_collection.json -e postman/StudyQuest.local.postman_environment.json
```

Run HTTP integration tests against isolated temporary SQLite databases:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These tests include relationship constraints, updates, legacy migration, and
persistence after application restart. To verify PostgreSQL persistence by
recreating the Compose containers:

```powershell
powershell -ExecutionPolicy Bypass -File .\verify.ps1
```

That script leaves one demonstration quest in the database. Historical
SpaceBounty files are unrelated to this Study Quest API; use the StudyQuest
collection above.
