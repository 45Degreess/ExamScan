"""
MySQL access layer for scan sessions and booklets.

Config is read from env vars (DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME),
loaded from a `.env` file if present. Schema is created with a plain
CREATE TABLE IF NOT EXISTS on startup (see init_db()) — no migration
tooling is required for the application's small schema.
"""
from __future__ import annotations

import os
from datetime import date

from dotenv import load_dotenv
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.exc import IntegrityError

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = os.environ.get("DB_PORT", "3306")
DB_USER = os.environ.get("DB_USER", "examscan")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "examscan")
DB_NAME = os.environ.get("DB_NAME", "examscan")

_engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
    pool_pre_ping=True,
)


def get_engine():
    """Return the shared SQLAlchemy engine for adjacent data-access modules."""
    return _engine


class DuplicateSessionError(Exception):
    """Raised when session_code already exists."""


class DuplicateEmplidError(Exception):
    """Raised when (session_id, emplid) already exists."""


class DuplicateChecksumError(Exception):
    """Raised when (session_id, checksum) already exists — the booklet's PDF
    content is identical to one already stored in this session."""


class BookletNotFoundError(Exception):
    """Raised when a booklet id doesn't exist."""


_UNSET = object()  # "field not supplied" sentinel for partial updates


def _add_col_if_missing(conn, table: str, column: str, ddl: str) -> None:
    """Idempotent `ALTER TABLE ... ADD COLUMN` for databases created by an
    earlier schema version — there's no migration tooling. `ddl` is the full
    statement to run when the column is absent."""
    has_col = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = :table
          AND column_name = :column
    """), {"table": table, "column": column}).scalar()
    if not has_col:
        conn.execute(text(ddl))


def init_db() -> None:
    with _engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS scan_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_code VARCHAR(64) NOT NULL UNIQUE,
                operator_name VARCHAR(128) NOT NULL,
                test_date DATE NOT NULL,
                course_code VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'open',
                finalized_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS session_students (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id INT NOT NULL,
                name VARCHAR(255) NOT NULL,
                username VARCHAR(128) NOT NULL,
                role VARCHAR(64) NOT NULL DEFAULT 'Student',
                expected BOOLEAN NOT NULL DEFAULT TRUE,
                scanned BOOLEAN NOT NULL DEFAULT FALSE,
                booklet_id INT NULL,
                scanned_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES scan_sessions(id),
                UNIQUE KEY uq_session_student (session_id, username)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS booklets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id INT NOT NULL,
                emplid VARCHAR(64) NOT NULL,
                student_id INT NULL,
                course_code_scanned VARCHAR(64) NULL,
                course_code_verified BOOLEAN NOT NULL DEFAULT FALSE,
                num_pages INT NULL,
                confidence FLOAT NULL,
                pdf_path VARCHAR(512) NOT NULL,
                run_id VARCHAR(64) NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'complete',
                error_message VARCHAR(512) NULL,
                checksum VARCHAR(64) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES scan_sessions(id),
                UNIQUE KEY uq_session_emplid (session_id, emplid),
                UNIQUE KEY uq_session_checksum (session_id, checksum),
                KEY idx_booklets_student (student_id),
                KEY idx_booklets_run (session_id, run_id)
            )
        """))
        # Columns added after the tables' first release; back-fill in place
        # since there's no migration tooling.
        if not conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'booklets' AND column_name = 'student_id'
        """)).scalar():
            conn.execute(text("ALTER TABLE booklets ADD COLUMN student_id INT NULL"))
            conn.execute(text("ALTER TABLE booklets ADD KEY idx_booklets_student (student_id)"))
        _add_col_if_missing(conn, "booklets", "confidence",
                            "ALTER TABLE booklets ADD COLUMN confidence FLOAT NULL")
        _add_col_if_missing(conn, "booklets", "run_id",
                            "ALTER TABLE booklets ADD COLUMN run_id VARCHAR(64) NULL")
        _add_col_if_missing(conn, "booklets", "status",
                            "ALTER TABLE booklets ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'complete'")
        _add_col_if_missing(conn, "booklets", "error_message",
                            "ALTER TABLE booklets ADD COLUMN error_message VARCHAR(512) NULL")
        _add_col_if_missing(conn, "booklets", "checksum",
                            "ALTER TABLE booklets ADD COLUMN checksum VARCHAR(64) NULL")
        if not conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'booklets' AND index_name = 'idx_booklets_run'
        """)).scalar():
            conn.execute(text("ALTER TABLE booklets ADD KEY idx_booklets_run (session_id, run_id)"))
        if not conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'booklets' AND index_name = 'uq_session_checksum'
        """)).scalar():
            conn.execute(text(
                "ALTER TABLE booklets ADD UNIQUE KEY uq_session_checksum (session_id, checksum)"
            ))
        _add_col_if_missing(conn, "scan_sessions", "status",
                            "ALTER TABLE scan_sessions ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'open'")
        _add_col_if_missing(conn, "scan_sessions", "finalized_at",
                            "ALTER TABLE scan_sessions ADD COLUMN finalized_at DATETIME NULL")


def create_session(session_code: str, operator_name: str, test_date_str: str, course_code: str) -> int:
    try:
        with _engine.begin() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO scan_sessions (session_code, operator_name, test_date, course_code)
                    VALUES (:session_code, :operator_name, :test_date, :course_code)
                """),
                {
                    "session_code": session_code,
                    "operator_name": operator_name,
                    "test_date": date.fromisoformat(test_date_str),
                    "course_code": course_code,
                },
            )
            return result.lastrowid
    except IntegrityError as exc:
        raise DuplicateSessionError(session_code) from exc


def get_session(session_code: str) -> dict | None:
    with _engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM scan_sessions WHERE session_code = :session_code"),
            {"session_code": session_code},
        ).mappings().first()
    return dict(row) if row else None


_SESSION_LIST_SQL = """
    SELECT s.id, s.session_code, s.operator_name, s.test_date, s.course_code,
           s.status, s.created_at, s.finalized_at,
           COUNT(ss.id) AS student_count
    FROM scan_sessions s
    LEFT JOIN session_students ss ON ss.session_id = s.id
    {where}
    GROUP BY s.id, s.session_code, s.operator_name, s.test_date, s.course_code,
             s.status, s.created_at, s.finalized_at
    {order}
"""


def list_sessions() -> list[dict]:
    """Every scan session, newest first, each with its roster size."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text(_SESSION_LIST_SQL.format(where="", order="ORDER BY s.created_at DESC"))
        ).mappings().all()
    return [dict(r) for r in rows]


def get_session_by_id(session_id: int) -> dict | None:
    """A single session by its numeric id, with roster size, or None."""
    with _engine.connect() as conn:
        row = conn.execute(
            text(_SESSION_LIST_SQL.format(where="WHERE s.id = :id", order="")),
            {"id": session_id},
        ).mappings().first()
    return dict(row) if row else None


def _raise_for_booklet_integrity_error(
    exc: IntegrityError, emplid: str, checksum: str | None
) -> None:
    """Distinguish which unique key on `booklets` a failed insert/update
    violated (uq_session_checksum vs uq_session_emplid) and raise the
    matching error."""
    if checksum is not None and "uq_session_checksum" in str(exc.orig):
        raise DuplicateChecksumError(checksum) from exc
    raise DuplicateEmplidError(emplid) from exc


def insert_booklet(
    session_id: int,
    emplid: str,
    course_code_scanned: str,
    verified: bool,
    num_pages: int | None,
    pdf_path: str,
    confidence: float | None = None,
    checksum: str | None = None,
) -> dict:
    """
    Insert a booklet and try to link it to an expected class-list student
    (session_students.username == emplid, case-insensitive). When a match is
    found, booklets.student_id is set and the roster row is marked scanned.

    `confidence` is a 0-1 scalar OCR confidence for the cover fields, or None
    when no cover page was extracted. `checksum` is a SHA-256 hex digest of
    the booklet's PDF content, or None; a booklet whose checksum matches one
    already stored in this session is rejected (DuplicateChecksumError).

    Returns {"booklet_id": int, "student_id": int | None} — student_id is None
    for a booklet whose emplid isn't on the class list (flagged for review).
    """
    try:
        with _engine.begin() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO booklets
                        (session_id, emplid, course_code_scanned, course_code_verified,
                         num_pages, confidence, pdf_path, checksum)
                    VALUES
                        (:session_id, :emplid, :course_code_scanned, :verified,
                         :num_pages, :confidence, :pdf_path, :checksum)
                """),
                {
                    "session_id": session_id,
                    "emplid": emplid,
                    "course_code_scanned": course_code_scanned,
                    "verified": verified,
                    "num_pages": num_pages,
                    "confidence": confidence,
                    "pdf_path": pdf_path,
                    "checksum": checksum,
                },
            )
            booklet_id = result.lastrowid
            student_id = _link_booklet_to_student(conn, session_id, booklet_id, emplid)
            return {"booklet_id": booklet_id, "student_id": student_id}
    except IntegrityError as exc:
        _raise_for_booklet_integrity_error(exc, emplid, checksum)


def _link_booklet_to_student(conn, session_id: int, booklet_id: int, emplid: str) -> int | None:
    """Link one booklet to the expected student whose username matches emplid.
    Sets booklets.student_id and marks the roster row scanned. Returns the
    matched session_students.id, or None if nothing matched."""
    key = (emplid or "").strip().upper()
    if not key:
        return None
    student = conn.execute(
        text("""
            SELECT id FROM session_students
            WHERE session_id = :sid AND UPPER(username) = :key
        """),
        {"sid": session_id, "key": key},
    ).mappings().first()
    if student is None:
        return None
    conn.execute(
        text("UPDATE booklets SET student_id = :stid WHERE id = :bid"),
        {"stid": student["id"], "bid": booklet_id},
    )
    conn.execute(
        text("""
            UPDATE session_students
            SET scanned = TRUE,
                booklet_id = :bid,
                scanned_at = COALESCE(scanned_at, NOW())
            WHERE id = :stid
        """),
        {"bid": booklet_id, "stid": student["id"]},
    )
    return student["id"]


# ── Pi-run collection: placeholder rows processed by a background task ────────

# A booklet stuck in 'processing' for longer than this is treated as abandoned
# (e.g. the API restarted mid-task) and its run may be collected again.
STALE_PROCESSING_SECONDS = 600


def create_pending_booklet(session_id: int, run_id: str) -> int:
    """
    Insert a placeholder booklet for a Pi run that is about to be processed by
    a background task. `emplid` is a per-run sentinel ("__run_<run_id>") so the
    row can exist before OCR without colliding on uq_session_emplid; `pdf_path`
    is blank until processing finishes. Returns the new booklet id.
    """
    with _engine.begin() as conn:
        result = conn.execute(
            text("""
                INSERT INTO booklets
                    (session_id, emplid, course_code_scanned, course_code_verified,
                     num_pages, confidence, pdf_path, run_id, status)
                VALUES
                    (:session_id, :emplid, NULL, FALSE,
                     NULL, NULL, '', :run_id, 'processing')
            """),
            {
                "session_id": session_id,
                "emplid": f"__run_{run_id}",
                "run_id": run_id,
            },
        )
        return result.lastrowid


def update_booklet_result(
    booklet_id: int,
    emplid: str,
    course_code_scanned: str,
    verified: bool,
    num_pages: int | None,
    pdf_path: str,
    confidence: float | None = None,
    checksum: str | None = None,
) -> dict:
    """
    Fill in a placeholder booklet (see create_pending_booklet) with real OCR
    results, mark it 'complete', and link it to a class-list student the same
    way insert_booklet does. Raises DuplicateEmplidError if `emplid` now
    collides with another booklet in the same session, or
    DuplicateChecksumError if `checksum` matches another booklet's (the caller
    marks the row errored and leaves the sentinel emplid in place).

    Returns {"booklet_id": int, "student_id": int | None}.
    """
    try:
        with _engine.begin() as conn:
            row = conn.execute(
                text("SELECT session_id FROM booklets WHERE id = :bid"),
                {"bid": booklet_id},
            ).mappings().first()
            if row is None:
                raise ValueError(f"No booklet with id {booklet_id}")
            session_id = row["session_id"]
            conn.execute(
                text("""
                    UPDATE booklets
                    SET emplid = :emplid,
                        course_code_scanned = :course_code_scanned,
                        course_code_verified = :verified,
                        num_pages = :num_pages,
                        confidence = :confidence,
                        pdf_path = :pdf_path,
                        checksum = :checksum,
                        status = 'complete',
                        error_message = NULL
                    WHERE id = :bid
                """),
                {
                    "emplid": emplid,
                    "course_code_scanned": course_code_scanned,
                    "verified": verified,
                    "num_pages": num_pages,
                    "confidence": confidence,
                    "pdf_path": pdf_path,
                    "checksum": checksum,
                    "bid": booklet_id,
                },
            )
            student_id = _link_booklet_to_student(conn, session_id, booklet_id, emplid)
            return {"booklet_id": booklet_id, "student_id": student_id}
    except IntegrityError as exc:
        _raise_for_booklet_integrity_error(exc, emplid, checksum)


def mark_booklet_error(booklet_id: int, message: str) -> None:
    """Flag a placeholder booklet as failed, keeping it in the list so the
    operator sees what went wrong."""
    with _engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE booklets
                SET status = 'error', error_message = :msg
                WHERE id = :bid
            """),
            {"msg": (message or "")[:512], "bid": booklet_id},
        )


def update_booklet_fields(
    booklet_id: int,
    *,
    emplid=_UNSET,
    course_code_scanned=_UNSET,
    num_pages=_UNSET,
) -> dict:
    """
    Operator edit of a booklet's OCR-derived metadata. Only the supplied
    fields change. Changing `emplid` unlinks any previously matched roster
    student and re-links against the new value (via _link_booklet_to_student);
    changing `course_code_scanned` recomputes `course_code_verified` against
    the session's declared course code.

    Raises BookletNotFoundError for an unknown id, DuplicateEmplidError if the
    new emplid collides with another booklet in the same session.

    Returns {"booklet_id", "student_id", "course_code_verified", "emplid",
             "course_code_scanned", "num_pages"} after the update.
    """
    with _engine.begin() as conn:
        cur = conn.execute(
            text("""
                SELECT b.session_id, b.emplid, b.course_code_scanned, b.num_pages,
                       b.student_id, s.course_code AS session_course
                FROM booklets b
                JOIN scan_sessions s ON s.id = b.session_id
                WHERE b.id = :bid
            """),
            {"bid": booklet_id},
        ).mappings().first()
        if cur is None:
            raise BookletNotFoundError(booklet_id)

        session_id = cur["session_id"]
        new_emplid = (cur["emplid"] if emplid is _UNSET else (emplid or "")).strip()
        new_ccs = (
            cur["course_code_scanned"]
            if course_code_scanned is _UNSET
            else (course_code_scanned or "")
        )
        new_ccs = (new_ccs or "").strip()
        new_pages = cur["num_pages"] if num_pages is _UNSET else num_pages

        emplid_changed = new_emplid.upper() != (cur["emplid"] or "").strip().upper()
        verified = bool(new_ccs) and (
            new_ccs.upper() == (cur["session_course"] or "").strip().upper()
        )

        if emplid_changed and cur["student_id"] is not None:
            conn.execute(
                text("""
                    UPDATE session_students
                    SET scanned = FALSE, booklet_id = NULL, scanned_at = NULL
                    WHERE id = :sid AND booklet_id = :bid
                """),
                {"sid": cur["student_id"], "bid": booklet_id},
            )

        set_student_null = ", student_id = NULL" if emplid_changed else ""
        try:
            conn.execute(
                text(f"""
                    UPDATE booklets
                    SET emplid = :emplid,
                        course_code_scanned = :ccs,
                        course_code_verified = :verified,
                        num_pages = :pages{set_student_null}
                    WHERE id = :bid
                """),
                {
                    "emplid": new_emplid,
                    "ccs": new_ccs,
                    "verified": verified,
                    "pages": new_pages,
                    "bid": booklet_id,
                },
            )
        except IntegrityError as exc:
            raise DuplicateEmplidError(new_emplid) from exc

        student_id = cur["student_id"]
        if emplid_changed:
            student_id = _link_booklet_to_student(conn, session_id, booklet_id, new_emplid)

        return {
            "booklet_id": booklet_id,
            "student_id": student_id,
            "course_code_verified": verified,
            "emplid": new_emplid,
            "course_code_scanned": new_ccs,
            "num_pages": new_pages,
        }


def get_imported_run_ids(session_id: int) -> set[str]:
    """run_ids already collected for this session that should NOT be collected
    again — every 'complete' one, plus 'processing' ones still within the
    stale window. Errored and abandoned runs are omitted so they can retry."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT run_id FROM booklets
                WHERE session_id = :sid
                  AND run_id IS NOT NULL
                  AND (
                      status = 'complete'
                      OR (status = 'processing'
                          AND created_at > (NOW() - INTERVAL :secs SECOND))
                  )
            """),
            {"sid": session_id, "secs": STALE_PROCESSING_SECONDS},
        ).scalars().all()
    return {r for r in rows if r}


def list_booklets_for_session(session_id: int) -> list[dict]:
    """Every booklet for a session (any status), oldest first, with the linked
    class-list student's name when there is one. Feeds the View Session table."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT b.id, b.run_id, b.emplid, b.student_id,
                       b.course_code_scanned, b.course_code_verified,
                       b.num_pages, b.confidence, b.status, b.error_message,
                       b.created_at, ss.name AS student_name
                FROM booklets b
                LEFT JOIN session_students ss ON ss.id = b.student_id
                WHERE b.session_id = :sid
                ORDER BY b.created_at, b.id
            """),
            {"sid": session_id},
        ).mappings().all()
    out = []
    for r in rows:
        emplid = r["emplid"] or ""
        if emplid.startswith("__run_"):
            emplid = ""
        out.append({
            "id": r["id"],
            "run_id": r["run_id"],
            "emplid": emplid,
            "student_id": r["student_id"],
            "on_class_list": r["student_id"] is not None,
            "name": r["student_name"] or emplid or None,
            "course_code_scanned": r["course_code_scanned"],
            "course_code_verified": (
                bool(r["course_code_verified"])
                if r["course_code_verified"] is not None else None
            ),
            "num_pages": r["num_pages"],
            "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
            "status": r["status"],
            "error_message": r["error_message"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return out


def import_session_students(session_id: int, students: list[dict]) -> dict:
    """
    Upsert the class-list roster for a session. Each dict has 'name',
    'username', 'role'. Existing rows (same session_id + username) have their
    name/role refreshed and `expected` re-set to TRUE; scan state is left
    untouched, so a corrected class list can be re-uploaded safely.

    After the upsert, any booklets already scanned in this session that aren't
    linked to a student yet are re-checked against the new roster.

    Returns {"imported": int, "matched": int} — matched is how many
    previously-unlinked booklets got linked as a result of this import.
    """
    with _engine.begin() as conn:
        if students:
            conn.execute(
                text("""
                    INSERT INTO session_students (session_id, name, username, role, expected)
                    VALUES (:session_id, :name, :username, :role, TRUE)
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        role = VALUES(role),
                        expected = TRUE
                """),
                [
                    {
                        "session_id": session_id,
                        "name": s["name"],
                        "username": s["username"],
                        "role": s["role"],
                    }
                    for s in students
                ],
            )
        unlinked = conn.execute(
            text("SELECT id, emplid FROM booklets WHERE session_id = :sid AND student_id IS NULL"),
            {"sid": session_id},
        ).mappings().all()
        matched = sum(
            1
            for b in unlinked
            if _link_booklet_to_student(conn, session_id, b["id"], b["emplid"]) is not None
        )
    return {"imported": len(students), "matched": matched}


def get_session_students(session_id: int) -> list[dict]:
    """The class-list roster for a session, ordered by name. `scanned_at` is
    an ISO string or None; `expected`/`scanned` are bools."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, name, username, role, expected, scanned, booklet_id, scanned_at
                FROM session_students
                WHERE session_id = :sid
                ORDER BY name
            """),
            {"sid": session_id},
        ).mappings().all()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "username": r["username"],
            "role": r["role"],
            "expected": bool(r["expected"]),
            "scanned": bool(r["scanned"]),
            "booklet_id": r["booklet_id"],
            "scanned_at": r["scanned_at"].isoformat() if r["scanned_at"] else None,
        }
        for r in rows
    ]


def get_unmatched_booklets(session_id: int) -> list[dict]:
    """Booklets scanned in this session whose emplid matched no class-list
    student (student_id IS NULL) — the review queue."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, emplid, course_code_scanned, num_pages, created_at
                FROM booklets
                WHERE session_id = :sid AND student_id IS NULL
                ORDER BY created_at
            """),
            {"sid": session_id},
        ).mappings().all()
    return [
        {
            "id": r["id"],
            "emplid": r["emplid"],
            "course_code_scanned": r["course_code_scanned"],
            "num_pages": r["num_pages"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


def set_students_expected(session_id: int, excluded_usernames: list[str]) -> dict:
    """
    Bulk-set the roster's `expected` flags for a session in one transaction:
    everyone is marked `expected = TRUE`, then the given usernames (matched
    case-insensitively) are set back to `expected = FALSE`. This is the
    "confirm who's sitting the exam" action — excluded students drop out of
    the missing / not-yet-scanned queue.

    Returns {"expected": int, "excluded": int} — counts after the update.
    """
    excluded_keys = sorted({u.strip().upper() for u in excluded_usernames if u.strip()})
    with _engine.begin() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM session_students WHERE session_id = :sid"),
            {"sid": session_id},
        ).scalar() or 0
        conn.execute(
            text("UPDATE session_students SET expected = TRUE WHERE session_id = :sid"),
            {"sid": session_id},
        )
        excluded = 0
        if excluded_keys:
            result = conn.execute(
                text("""
                    UPDATE session_students SET expected = FALSE
                    WHERE session_id = :sid AND UPPER(username) IN :keys
                """).bindparams(bindparam("keys", expanding=True)),
                {"sid": session_id, "keys": excluded_keys},
            )
            excluded = result.rowcount
    return {"expected": total - excluded, "excluded": excluded}


def _review_status(scanned: bool, expected: bool) -> str:
    """Derived status for a roster row (mirrors routes._student_status)."""
    if scanned:
        return "scanned" if expected else "unexpected"
    return "missing" if expected else "excluded"


_REVIEW_RANK = {"unexpected": 0, "missing": 1, "scanned": 2, "excluded": 3}


def get_session_review(session_id: int) -> list[dict]:
    """
    The post-processing feed for a session: every roster row plus every
    scanned booklet that matched nobody, each carrying a derived `status`
    and the booklet's OCR confidence. Ordered unexpected -> missing ->
    scanned -> excluded, then by name.
    """
    with _engine.connect() as conn:
        student_rows = conn.execute(
            text("""
                SELECT ss.id AS student_id, ss.name, ss.username,
                       ss.expected, ss.scanned, ss.booklet_id, ss.scanned_at,
                       b.emplid AS b_emplid, b.confidence,
                       b.course_code_scanned, b.course_code_verified, b.num_pages
                FROM session_students ss
                LEFT JOIN booklets b ON b.id = ss.booklet_id
                WHERE ss.session_id = :sid
            """),
            {"sid": session_id},
        ).mappings().all()
        booklet_rows = conn.execute(
            text("""
                SELECT id, emplid, confidence, course_code_scanned,
                       course_code_verified, num_pages, created_at
                FROM booklets
                WHERE session_id = :sid AND student_id IS NULL
            """),
            {"sid": session_id},
        ).mappings().all()

    items: list[dict] = []
    for r in student_rows:
        expected, scanned = bool(r["expected"]), bool(r["scanned"])
        items.append({
            "row_key": f"s{r['student_id']}",
            "kind": "student",
            "student_id": r["student_id"],
            "booklet_id": r["booklet_id"],
            "name": r["name"],
            "username": r["username"],
            "emplid": r["b_emplid"],
            "status": _review_status(scanned, expected),
            "expected": expected,
            "scanned": scanned,
            "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
            "course_code_scanned": r["course_code_scanned"],
            "course_code_verified": (
                bool(r["course_code_verified"]) if r["course_code_verified"] is not None else None
            ),
            "num_pages": r["num_pages"],
            "scanned_at": r["scanned_at"].isoformat() if r["scanned_at"] else None,
        })
    for r in booklet_rows:
        items.append({
            "row_key": f"b{r['id']}",
            "kind": "booklet",
            "student_id": None,
            "booklet_id": r["id"],
            "name": r["emplid"] or "Unknown",
            "username": None,
            "emplid": r["emplid"],
            "status": "unexpected",
            "expected": False,
            "scanned": True,
            "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
            "course_code_scanned": r["course_code_scanned"],
            "course_code_verified": (
                bool(r["course_code_verified"]) if r["course_code_verified"] is not None else None
            ),
            "num_pages": r["num_pages"],
            "scanned_at": r["created_at"].isoformat() if r["created_at"] else None,
        })

    items.sort(key=lambda it: (_REVIEW_RANK.get(it["status"], 99), (it["name"] or "").lower()))
    return items


def list_completed_booklet_pdfs(session_id: int) -> list[dict]:
    """`{id, emplid, pdf_path}` for every finished booklet in a session —
    feeds the bulk PDF download."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, emplid, pdf_path
                FROM booklets
                WHERE session_id = :sid AND status = 'complete'
                ORDER BY created_at, id
            """),
            {"sid": session_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def get_booklet(session_id: int, booklet_id: int) -> dict | None:
    """A single booklet scoped to its session, or None."""
    with _engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT id, emplid, pdf_path, num_pages
                FROM booklets
                WHERE id = :bid AND session_id = :sid
            """),
            {"bid": booklet_id, "sid": session_id},
        ).mappings().first()
    return dict(row) if row else None


def finalize_session(session_id: int, excluded_usernames: list[str]) -> dict:
    """
    Confirm a session's results: apply the final `expected` flags (everyone
    TRUE, then `excluded_usernames` FALSE) and stamp the session
    `status = 'finalized'`. One transaction, idempotent — `finalized_at` is
    only set the first time.

    Returns a counts summary: status, expected, excluded, scanned, missing,
    unexpected.
    """
    excluded_keys = sorted({u.strip().upper() for u in excluded_usernames if u.strip()})
    with _engine.begin() as conn:
        conn.execute(
            text("UPDATE session_students SET expected = TRUE WHERE session_id = :sid"),
            {"sid": session_id},
        )
        if excluded_keys:
            conn.execute(
                text("""
                    UPDATE session_students SET expected = FALSE
                    WHERE session_id = :sid AND UPPER(username) IN :keys
                """).bindparams(bindparam("keys", expanding=True)),
                {"sid": session_id, "keys": excluded_keys},
            )
        conn.execute(
            text("""
                UPDATE scan_sessions
                SET status = 'finalized', finalized_at = COALESCE(finalized_at, NOW())
                WHERE id = :sid
            """),
            {"sid": session_id},
        )
        rows = conn.execute(
            text("SELECT expected, scanned FROM session_students WHERE session_id = :sid"),
            {"sid": session_id},
        ).mappings().all()
        unexpected = conn.execute(
            text("SELECT COUNT(*) FROM booklets WHERE session_id = :sid AND student_id IS NULL"),
            {"sid": session_id},
        ).scalar() or 0

    return {
        "status": "finalized",
        "expected": sum(1 for r in rows if r["expected"]),
        "excluded": sum(1 for r in rows if not r["expected"]),
        "scanned": sum(1 for r in rows if r["expected"] and r["scanned"]),
        "missing": sum(1 for r in rows if r["expected"] and not r["scanned"]),
        "unexpected": int(unexpected),
    }
