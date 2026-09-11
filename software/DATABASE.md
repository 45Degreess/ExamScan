# Scan Sessions & Booklet Storage — MySQL Guide

> The FastAPI endpoints in this guide now require a staff session. Sign in and
> retain the cookie before using them manually; state-changing requests also
> require the returned `X-CSRF-Token`. See
> [`../docs/authentication.md`](../docs/authentication.md#manual-api-debugging).

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

### Expected-student roster (class list)

A session can carry a **class list**: the students expected to sit the exam.
It's imported from a CSV (`Name, Pronouns, UserName, Email, Role,
LastAccessed`) — either at session creation (`class_list` file field on
`POST /sessions`) or later via `POST /sessions/{session_code}/class-list`.
Only `Role == Student` rows are kept, and only **Name**, **UserName** and
**Role** are stored, one row per student in `session_students` with
`expected = 1`.

`UserName` is the student/Emplid number. When a booklet is scanned, its
OCR'd `Emplid` is matched (case-insensitive) against `session_students.username`
for that session:

- **Match** → `booklets.student_id` is set and the roster row is marked
  `scanned = 1` (with `booklet_id` and `scanned_at`).
- **No match** → the booklet is still stored, `student_id` stays `NULL`, and
  it shows up in the review queue (`unmatched_booklets`). No roster row is
  auto-created.

Re-importing the CSV is safe: rows are upserted by `(session_id, username)`,
names/roles are refreshed and `expected` re-set to `1`, but `scanned` state
is untouched. Any already-scanned booklets that weren't matched before are
re-checked against the new roster.

Before scanning starts, the operator confirms who's actually sitting the exam
via `PUT /sessions/{session_code}/students/expected` (repeatable `excluded`
form field of usernames). It marks every roster row `expected = 1`, then the
excluded ones `expected = 0` — a deselected student is no longer chased as
`missing`.

Status per roster row is *derived*, never stored:

| `expected` | `scanned` | meaning                                          |
|-----------:|----------:|-------------------------------------------------|
| 1          | 0         | `missing` — expected to sit, not yet scanned    |
| 1          | 1         | `scanned` — accounted for                       |
| 0          | 1         | `unexpected` — scanned, not expected            |
| 0          | 0         | `excluded` — deselected, not being chased       |

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

CREATE TABLE session_students (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    session_id  INT NOT NULL,
    name        VARCHAR(255) NOT NULL,
    username    VARCHAR(128) NOT NULL,   -- student/Emplid number; match key
    role        VARCHAR(64)  NOT NULL DEFAULT 'Student',
    expected    BOOLEAN      NOT NULL DEFAULT TRUE,   -- came from the class list
    scanned     BOOLEAN      NOT NULL DEFAULT FALSE,  -- a booklet matched
    booklet_id  INT          NULL,                    -- the matched booklet
    scanned_at  DATETIME     NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES scan_sessions(id),
    UNIQUE KEY uq_session_student (session_id, username)
);

CREATE TABLE booklets (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    session_id            INT NOT NULL,
    emplid                VARCHAR(64)  NOT NULL,
    student_id            INT          NULL,   -- session_students.id, once matched
    course_code_scanned   VARCHAR(64)  NULL,
    course_code_verified  BOOLEAN      NOT NULL DEFAULT FALSE,
    num_pages             INT          NULL,
    pdf_path              VARCHAR(512) NOT NULL,
    created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES scan_sessions(id),
    UNIQUE KEY uq_session_emplid (session_id, emplid),
    KEY idx_booklets_student (student_id)
);
```

`session_students.booklet_id` and `booklets.student_id` point at each other
but are kept as plain nullable `INT`s (no cross `FOREIGN KEY`) to avoid a
circular table-creation dependency. `init_db()` also runs a one-off
`ALTER TABLE booklets ADD COLUMN student_id` for databases created before
this column existed.

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

Start a session (optionally seeding the expected-student roster):

```bash
curl -X POST localhost:8000/sessions \
  -F session_code=S1 \
  -F operator_name=Devak \
  -F test_date=2026-08-18 \
  -F course_code=CS101 \
  -F class_list=@class_list.csv          # optional
```

Import / re-import the class list later:

```bash
curl -X POST localhost:8000/sessions/S1/class-list -F class_list=@class_list.csv
```

Confirm who's sitting the exam (deselect two students):

```bash
curl -X PUT localhost:8000/sessions/S1/students/expected \
  -F excluded=MSTDEV001 -F excluded=DOEJAN002
```

Check who's expected vs. scanned:

```bash
curl localhost:8000/sessions/S1/students          # full roster + derived status
curl localhost:8000/sessions/S1/reconciliation    # counts + missing + unmatched
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
