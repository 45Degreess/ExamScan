# `software/` — Backend Design Overview

> Companion to [`DATABASE.md`](DATABASE.md) (MySQL schema and session/booklet
> lifecycle) and [`../docs/authentication.md`](../docs/authentication.md)
> (staff login, sessions, CSRF). This file is about how the FastAPI app itself
> is put together: what each module does, and which HTTP routes exist.

This is the backend for ExamScan: a FastAPI service that turns photos of exam
booklets (captured by a Raspberry Pi rig) into scanned PDFs with OCR'd student
identity fields and an extracted handwritten mark, tracked per scan session in
MySQL. `final-ui` (the operator-facing React app) is its primary client; the
Pi hardware server is a secondary service it talks to over HTTP.

## Module map

| File | Responsibility                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
|---|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `scanner_api.py` | FastAPI app entrypoint. Wires up CORS, `AuthMiddleware`, mounts `auth_router` and `router` (from `routes.py`), and runs `db.init_db()` / `init_auth()` on startup.                                                                                                                                                                                                                                                                                                                   |
| `routes.py` | All non-auth HTTP endpoints — scanning/OCR pipeline, the Pi hardware relay, and session/booklet CRUD. See [Routes](#routes) below. Organized into sections (Shared helpers, Health, Scan/debug pipeline, Runs proxy, Pi hardware relay, Sessions, Booklets, Automatic run collection).                                                                                                                                                                                               |
| `auth.py` | Staff authentication: Argon2 password hashing, session cookies + CSRF tokens, one-time password delivery by email, lockout/rate-limiting, and the `/auth/*` + `/admin/users*` routes. Also defines `AuthMiddleware`, which gates every non-public route behind a valid session cookie.                                                                                                                                                                                               |
| `db.py` | MySQL access layer (SQLAlchemy Core, raw `text()` queries) for `scan_sessions`, `booklets`, and the class-list roster tables. Owns schema creation (`init_db`) and all session/booklet read/write logic that `routes.py` calls via `run_in_threadpool`. Full schema documented in `DATABASE.md`.                                                                                                                                                                                     |
| `detection.py` | Page-boundary detection: `detect_by_colour` (paper vs. coloured background, the default) and `detect_by_corner` (Canny edge + largest quadrilateral, fallback). `detect_document(image, method)` is the shared entrypoint every scan/extract route calls before perspective-transforming a photo.                                                                                                                                                                                    |
| `processing.py` | Everything downstream of detection: `enhance_scan` (CLAHE), the rig-overlay compositing used on raw Pi captures, OCR backends (TrOCR primary, EasyOCR/pytesseract as alternates — lazy-loaded so they don't slow down startup), Emplid digit-splitting, QR-code detection for cover-vs-booklet-spread routing, and the red-pen handwritten-mark extraction pipeline (`_isolate_red_ink` → `_cluster_digits` → `_extract_candidates_from_region` → `extract_handwritten_mark_debug`). |
| `constants.py` | Shared config: A4/A3 pixel dimensions, `RUNS_API_BASE_URL` (the Pi hardware server's base URL), cover-field OCR regions (`COVER_FIELDS`, `MCQ_COVER_FIELDS` — the latter unfinished/placeholder), mark-extraction regions (`MARK_FIELDS`), and the rig-overlay asset path.                                                                                                                                                                                                           |
| `tests/` | `Makefile` for manual curl-based pipeline testing.                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `scripts/` | Standalone operator/dev tooling run outside the API: `fake_pi_server.py` (mocks the Pi hardware server for local dev), `batch_eval_cover_pages.py` + `score_results.py` (offline OCR accuracy evaluation against a labelled batch), `zip_runs_for_fake_pi.py` / `build_contact_sheet.py` (test-data prep), `poll_booklets.py` (curl-based polling helper), `extract_csrf.py`.  `batch_eval_results/` Sample/fixture data and cached output from manual demo runs and the batch-eval scripts                                                                                |
| `assets/` | Static images used by the pipeline itself (e.g. `rig_overlay_v7.png`, composited onto raw Pi captures to hide rig hardware at the frame edges).                                                                                                                                                                                                                                                                                                                                      |
| `demo_images/`, `demo_runs.json` | — not read by the live API except `demo_runs.json` (written/read by the legacy `/runs` endpoints).                                                                                                                                                                                                                                                                                                                                                                                   |
| `.env` / `.env.example` | DB credentials (`DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD`/`DB_NAME`), `RUNS_API_BASE_URL`, `FRONTEND_ORIGINS`, and auth/SMTP settings, loaded via `python-dotenv` in `db.py`.                                                                                                                                                                                                                                                                                                      |

`storage/<session_code>/<emplid>/` (created at runtime, not checked in) holds
each booklet's `combined.pdf` and page images once processing completes.

## Routes

All routes below are mounted with no path prefix (`app.include_router(...)` in
`scanner_api.py`); `final-ui` calls them through its own `/api` proxy. Every
route except `GET /health`, `POST /auth/login`, and `POST /auth/password/request`
requires a valid staff session cookie (`AuthMiddleware`, see `auth.py`).

### Used by `final-ui`

**Auth** (`auth.py`, `auth_router`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | Sign in, sets session cookie + returns CSRF token |
| POST | `/auth/password/request` | Request a one-time login password by email |
| GET | `/auth/me` | Fetch the current signed-in user + a fresh CSRF token |
| POST | `/auth/logout` | Revoke the current session |
| GET | `/admin/users` | List staff accounts (admin only) |
| POST | `/admin/users` | Create a staff account (admin only) |
| PATCH | `/admin/users/{user_id}` | Update a staff account (admin only) |
| POST | `/admin/users/{user_id}/password` | Re-send a login password (admin only) |

**Core app** (`routes.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/pi/health` | Same-origin relay of the Pi hardware server's health, for the UI's status dot |
| GET | `/pi/stream` | Proxies the Pi's MJPEG live camera stream |
| POST | `/pi/debug-run` | Debug page: smoke-tests the Pi capture pipeline end to end (no DB writes) |
| POST | `/detect-preview` | Debug page: returns a photo with the detected page corners drawn on it |
| POST | `/extract-cover` | Debug page: scan a cover photo → OCR identity fields → JSON |
| POST | `/extract-mark` | Debug page: scan a cover photo → extract handwritten mark candidates → JSON |
| POST | `/extract-booklet` | Debug page: run the full cover+mark extraction against a zip of booklet pages or a single photo |
| POST | `/sessions` | Start a new scan session (optionally seeding a class-list roster) |
| GET | `/sessions` | List sessions (Login-page picker) |
| GET | `/sessions/{session_id}` | Fetch one session by numeric id (hard-refresh rehydration) |
| DELETE | `/sessions/{session_code}` | Delete a session and its storage folder |
| POST | `/sessions/{session_code}/class-list` | Upload/re-upload the class-list CSV |
| GET | `/sessions/{session_code}/students` | Roster with derived status (missing/scanned/unexpected/excluded) |
| PUT | `/sessions/{session_code}/students/expected` | Confirm which roster students are expected to sit the exam |
| GET | `/sessions/{session_code}/review` | Combined roster + unmatched-booklet review feed |
| POST | `/sessions/{session_code}/finalize` | Lock in expected flags, mark session finalized, best-effort clear Pi runs |
| POST | `/sessions/{session_code}/capture-run` | Trigger a fresh Pi scan for this session (blocks on capture, processes in background) |
| POST | `/sessions/{session_code}/collect-runs` | Pull in any already-completed Pi runs not yet imported |
| GET | `/sessions/{session_code}/booklets` | List every booklet for the session (any status) — polled to watch processing finish |
| GET | `/sessions/{session_code}/booklets/{booklet_id}/pdf` | Stream a booklet's PDF inline |
| PATCH | `/sessions/{session_code}/booklets/{booklet_id}` | Operator edit of a booklet's OCR'd fields |
| GET | `/sessions/{session_code}/booklets/{booklet_id}/crops` | Field/mark crop images for the edit form |
| DELETE | `/sessions/{session_code}/booklets/{booklet_id}` | Delete a booklet |
| GET | `/sessions/{session_code}/archive` | ZIP of every completed booklet's PDF |
| GET | `/sessions/{session_code}/confirmed/archive` | ZIP of every confirmed student's booklet PDF |
| GET | `/sessions/{session_code}/confirmed/marks.csv` | CSV of `student_id,mark` for confirmed students |

### Internal / legacy-only (not called by `final-ui`)

These exist for manual testing, the older `examscan-ui` prototype, or offline
scripts — kept for now but not part of the live operator flow:

| Method | Path | Used by |
|---|---|---|
| POST | `/scan` | legacy `examscan-ui` only |
| POST | `/split-booklet` | legacy `examscan-ui` only |
| POST | `/process-page` | legacy `examscan-ui` only |
| POST | `/extract-mcq-cover` | legacy `examscan-ui` only (`MCQ_COVER_FIELDS` are unfinished placeholders) |
| POST | `/process-folder` | legacy `examscan-ui` only |
| GET | `/samples`, `/samples/{filename}` | legacy `examscan-ui` only |
| POST | `/runs`, `GET /runs`, `GET /runs/{run_id}/archive` | legacy `examscan-ui` only — superseded by the session-scoped `capture-run`/`collect-runs`/`booklets` flow |
| POST | `/sessions/{session_code}/booklets` (add_booklet) | also used by `tests/Makefile` and pytest fixtures, not by `final-ui` directly |



## GenAI declaration
Claude Sonnet 4.5 was used to assist in the creation of the documentation of this software directory. It was used to list all the files and the usage they provide in the Markdown format.
For scanner_api.py

For routes.py 

For auth.py

For detection.py

for processing.py

for constants.py

