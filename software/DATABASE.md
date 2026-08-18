# Scan Sessions & Booklet Storage — MySQL Guide

This covers the MySQL-backed session/booklet storage added on top of the
existing scan pipeline: how the two tables fit together, how to run MySQL
locally via Docker, and how to inspect the data yourself.

## How it works

A **scan session** represents one exam sitting: a course code, a test date,
an operator name, and a session code you choose. You start it once via
`POST /sessions`, and it stays open for the lifetime of the run — every
booklet scanned afterwards is submitted against that session code.

Each **booklet** is one student's scanned pages, submitted via
`POST /sessions/{session_code}/booklets`. That endpoint:

1. Runs the existing `_process_exam_folder` pipeline over the folder of
   images you point it at (same OCR/scan logic as `/process-folder`),
   producing a `combined.pdf` and a `student_info` dict (Emplid, Course Code,
   number of pages).
2. Compares the OCR'd `Course Code` against the session's declared
   `course_code` (case-insensitive, trimmed).
3. Writes a row to MySQL and moves the PDF + pages into
   `software/storage/<session_code>/<emplid>/`.

**Mismatches are never rejected.** If the OCR'd course code doesn't match
the session's, the booklet is still stored — `course_code_verified` is just
set to `0` so it can be pulled up for manual review later. The only thing
that *is* rejected is a duplicate Emplid within the same session (HTTP 409)
— it's assumed to be a re-submission, not a legitimate second booklet.

## Schema

```sql
CREATE TABLE scan_sessions (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    session_code  VARCHAR(64)  NOT NULL UNIQUE,
    operator_name VARCHAR(128) NOT NULL,
    test_date     DATE         NOT NULL,
    course_code   VARCHAR(64)  NOT NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE booklets (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    session_id            INT NOT NULL,
    emplid                VARCHAR(64)  NOT NULL,
    course_code_scanned   VARCHAR(64)  NULL,
    course_code_verified  BOOLEAN      NOT NULL DEFAULT FALSE,
    num_pages             INT          NULL,
    pdf_path              VARCHAR(512) NOT NULL,
    created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES scan_sessions(id),
    UNIQUE KEY uq_session_emplid (session_id, emplid)
);
```

Why `VARCHAR` and not fixed-width `CHAR`: OCR output isn't guaranteed to
match a fixed length or format — a misread can produce a `"?"` in place of
an unreadable digit, or an `"[OCR error: ...]"` string. Fixed-width columns
would silently truncate or reject exactly the malformed data this system
needs to keep for review, so `emplid`/`course_code_scanned` stay generous
and nullable-friendly.

Tables are created automatically on app startup (`db.init_db()` in
`scanner_api.py`) via `CREATE TABLE IF NOT EXISTS` — there's no separate
migration step to run.

## Running MySQL locally (Docker)

**One-time setup:**

```bash
cd software
cp .env.example .env      # edit if you want different credentials
```

**Start Docker Desktop** (or your Docker daemon) if it isn't already
running, then:

```bash
cd software
docker compose up -d
```

This starts a single `mysql:8` container, exposed on `localhost:3306`, with
data persisted in a named volume (`examscan_mysql_data`) — stopping the
container does **not** delete your data.

Start the API as usual (e.g. `uvicorn scanner_api:app --reload --port 8000`).
On startup it reads `software/.env` for `DB_HOST`/`DB_PORT`/`DB_USER`/
`DB_PASSWORD`/`DB_NAME` and creates the tables if they don't exist yet.

**Stopping:**

```bash
docker compose down        # stops the container, keeps the data volume
docker compose down -v     # stops the container AND wipes the data volume
```

## Using the endpoints

Start a session:

```bash
curl -X POST localhost:8000/sessions \
  -F session_code=S1 \
  -F operator_name=Devak \
  -F test_date=2026-08-18 \
  -F course_code=CS101
```

Submit a booklet (one folder = one student's cover + spread images):

```bash
curl -X POST localhost:8000/sessions/S1/booklets \
  -F folder_path=/absolute/path/to/one/booklets/images \
  -F method=colour
```

Response includes `verified` (course code match), `booklet_id`, and the
OCR'd `student_info`.

## Inspecting the data yourself

Connect to the running container:

```bash
docker exec -it software-mysql-1 mysql -u examscan -pexamscan examscan
```

(If the container name differs, check with `docker compose ps` or `docker ps`.)

Useful queries once connected:

```sql
SHOW TABLES;
DESCRIBE scan_sessions;
DESCRIBE booklets;

SELECT * FROM scan_sessions\G
SELECT * FROM booklets\G

-- side-by-side session vs. scanned course code, to see what got flagged
SELECT b.id, b.emplid, b.course_code_scanned, s.course_code AS session_course_code,
       b.course_code_verified
FROM booklets b
JOIN scan_sessions s ON b.session_id = s.id;

-- everything flagged for manual review
SELECT * FROM booklets WHERE course_code_verified = 0\G
```

Exit with `exit;` or `\q`.

Confirm the PDF landed on disk (path should match `booklets.pdf_path`):

```bash
find software/storage -type f
```

## Troubleshooting

- **App can't connect to MySQL on startup** — make sure `docker compose up -d`
  finished starting the container (`docker compose ps` should show it
  healthy) before starting the API, and that `software/.env` matches the
  credentials in `docker-compose.yml`.
- **`409` on `/sessions`** — `session_code` already exists; pick a new one
  or reuse the existing session for further booklets.
- **`409` on `/sessions/{code}/booklets`** — that Emplid is already recorded
  for this session (duplicate scan). Check the existing row first if you
  need to decide whether to overwrite it manually.
- **`404` on `/sessions/{code}/booklets`** — no session with that code was
  ever created (or the app was restarted against a different/empty
  database).
