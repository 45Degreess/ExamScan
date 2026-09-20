# Scan Sessions & Booklet Storage — MySQL Guide

> The FastAPI endpoints in this guide now require a staff session. Sign in and
> retain the cookie before using them manually; state-changing requests also
> require the returned `X-CSRF-Token`. See
> [`../docs/authentication.md`](../docs/authentication.md#manual-api-debugging).

This covers the MySQL-backed session/booklet storage. 
how the tables fit together, how to run MySQL
locally via Docker, and how to inspect the data yourself.


## How it works

A **scan session** represents one exam sitting: a course code, a test date,
an operator name, a session code you choose, and the exam's `test_total`.
You start it once via `POST /sessions`, and it stays `open` until explicitly finalised.

Each **booklet** is one student's scanned pages. There are two ways one gets
created:

- **Pi-driven capture** (the normal path): `POST /sessions/{code}/capture-run`
  triggers a fresh scan on the Pi hardware server and blocks until it
  finishes; `POST /sessions/{code}/collect-runs` instead pulls in whatever
  completed runs are already sitting on the Pi. 
- Either way, a placeholder booklet row is inserted immediately with `status = 'processing'`, and the
  actual OCR/scan work happens in a background task — the frontend polls
  `GET /sessions/{code}/booklets` to watch it turn into `'complete'` (or
  `'error'`, with `error_message` set, if processing failed).


Once OCR finishes:

1. Compare the OCR'd `Course Code` against the session's declared
   `course_code` (case-insensitive, trimmed) → `course_code_verified`.
2. Extract the handwritten mark from the cover's red-pen regions and resolve
   it against `test_total` (`_resolve_mark` in `routes.py`): the higher of
   the two pooled candidates is expected to equal `test_total`; if it
   doesn't, the mark is stored as `NULL` and flagged `mark_needs_review = 1`
   for manual entry. Field/mark crop images are stored alongside so an
   operator can visually confirm from the UI without re-scanning.
3. Write a row to MySQL and move the PDF + pages into `software/storage/<session_code>/<emplid>/`.

**Mismatches are never rejected outright.** A course-code mismatch just sets
`course_code_verified = 0` for later review. 
What *is* rejected (HTTP 409) is a duplicate Emplid within the same session,
or that same Emplid resubmitted with an identical `checksum` (SHA-256 of the
PDF's bytes) — same student, same file content already recorded for this
session — since that's assumed to be a re-submission rather than a second
legitimate booklet. 

When an operator is scanning, `POST /sessions/{code}/finalize` applies the final `expected` flags and marks the
session `status = 'finalized'`. It also best-effort clears the Pi's stored runs so scan
data doesn't linger on the hardware.

### Expected-student roster (class list)

A session can carry a **class list**: the students expected to sit the exam.
It's imported from a CSV (`Name, Pronouns, UserName, Email, Role,
LastAccessed`).
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


Before scanning starts, the operator confirms who's actually sitting the exam
via `PUT /sessions/{session_code}/students/expected` (repeatable `excluded`
form field of usernames). It marks every roster row `expected = 1`, then the
excluded ones `expected = 0` — a deselected student is no longer chased as
`missing`.

Status per roster row is *derived*, never stored:

| `expected` | `scanned` | meaning                                      |
|-----------:|----------:|----------------------------------------------|
| 1          | 0         | `missing` - expected to sit, not yet scanned |
| 1          | 1         | `scanned` - accounted for                    |
| 0          | 1         | `unexpected` - scanned, not expected         |
| 0          | 0         | `excluded` - deselected, not being chased    |

## Schema

```sql
CREATE TABLE scan_sessions (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    session_code  VARCHAR(64)  NOT NULL UNIQUE,
    operator_name VARCHAR(128) NOT NULL,
    test_date     DATE         NOT NULL,
    course_code   VARCHAR(64)  NOT NULL,
    status        VARCHAR(32)  NOT NULL DEFAULT 'open',   -- 'open' | 'finalized'
    finalized_at  DATETIME     NULL,
    test_total    INT          NULL,   -- exam's max mark, used to verify the scanned mark
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
    confidence            FLOAT        NULL,   -- OCR confidence for the cover fields
    pdf_path              VARCHAR(512) NOT NULL,
    run_id                VARCHAR(64)  NULL,   -- Pi run this booklet came from, if any
    status                VARCHAR(32)  NOT NULL DEFAULT 'complete',  -- 'processing' | 'complete' | 'error'
    error_message         VARCHAR(512) NULL,
    checksum              VARCHAR(64)  NULL,   -- SHA-256 of the PDF bytes; dedups re-submissions
    mark                  INT          NULL,   -- resolved handwritten mark (NULL if flagged for review)
    mark_confidence       FLOAT        NULL,
    mark_candidates       VARCHAR(64)  NULL,   -- top-2 candidates, comma-joined
    mark_needs_review     BOOLEAN      NOT NULL DEFAULT FALSE,
    emplid_crop           TEXT         NULL,   -- base64 PNG crops for manual review, no data-URI prefix
    course_code_crop      TEXT         NULL,
    mark_crop_1           TEXT         NULL,
    mark_crop_2           TEXT         NULL,
    created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES scan_sessions(id),
    UNIQUE KEY uq_session_emplid (session_id, emplid),
    UNIQUE KEY uq_session_checksum (session_id, emplid, checksum),
    KEY idx_booklets_student (student_id),
    KEY idx_booklets_run (session_id, run_id)
);
```

`session_students.booklet_id` and `booklets.student_id` point at each other
but are kept as plain nullable `INT`s (no cross `FOREIGN KEY`) to avoid a
circular table-creation dependency.

Why `VARCHAR` and not fixed-width `CHAR`: OCR output isn't guaranteed to
match a fixed length or format, this keeps the DB from rejecting an unexpected value which has not yet been confirmed by a human.

Tables are created automatically on app startup (`db.init_db()` in
`scanner_api.py`) via `CREATE TABLE IF NOT EXISTS` with this full schema
already in place — there's no separate migration step to run, and (schema
now treated as final) no backfill logic for older databases either.

## Running MySQL locally (Docker)

**One-time setup:**

```bash
cd software
cp .env.example .env      # edit for different credentials
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

## AI Decleration for database
The Database schema was designed by Devak Mistry, Design choices were made to describe the booklets and the sessions aswell as how to resolve dupelicates and missing students/scripts. Claude Sonnet 3.5 and Claude Code was used to assist with the implemntation of the MySql framework and to setup the docker application for hosting. 

