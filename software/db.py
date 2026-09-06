"""
MySQL access layer for scan sessions and booklets.

Config is read from env vars (DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME),
loaded from a `.env` file if present. Schema is created with a plain
CREATE TABLE IF NOT EXISTS on startup (see init_db()) — no migration
tooling, since there are only two tables.
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


class DuplicateSessionError(Exception):
    """Raised when session_code already exists."""


class DuplicateEmplidError(Exception):
    """Raised when (session_id, emplid) already exists."""


def init_db() -> None:
    with _engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS scan_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_code VARCHAR(64) NOT NULL UNIQUE,
                operator_name VARCHAR(128) NOT NULL,
                test_date DATE NOT NULL,
                course_code VARCHAR(64) NOT NULL,
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
                pdf_path VARCHAR(512) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES scan_sessions(id),
                UNIQUE KEY uq_session_emplid (session_id, emplid),
                KEY idx_booklets_student (student_id)
            )
        """))
        # `booklets` predates the student_id column on databases created by an
        # earlier version; add it in place since there's no migration tooling.
        has_col = conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'booklets'
              AND column_name = 'student_id'
        """)).scalar()
        if not has_col:
            conn.execute(text("ALTER TABLE booklets ADD COLUMN student_id INT NULL"))
            conn.execute(text("ALTER TABLE booklets ADD KEY idx_booklets_student (student_id)"))


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


def insert_booklet(
    session_id: int,
    emplid: str,
    course_code_scanned: str,
    verified: bool,
    num_pages: int | None,
    pdf_path: str,
) -> dict:
    """
    Insert a booklet and try to link it to an expected class-list student
    (session_students.username == emplid, case-insensitive). When a match is
    found, booklets.student_id is set and the roster row is marked scanned.

    Returns {"booklet_id": int, "student_id": int | None} — student_id is None
    for a booklet whose emplid isn't on the class list (flagged for review).
    """
    try:
        with _engine.begin() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO booklets
                        (session_id, emplid, course_code_scanned, course_code_verified, num_pages, pdf_path)
                    VALUES
                        (:session_id, :emplid, :course_code_scanned, :verified, :num_pages, :pdf_path)
                """),
                {
                    "session_id": session_id,
                    "emplid": emplid,
                    "course_code_scanned": course_code_scanned,
                    "verified": verified,
                    "num_pages": num_pages,
                    "pdf_path": pdf_path,
                },
            )
            booklet_id = result.lastrowid
            student_id = _link_booklet_to_student(conn, session_id, booklet_id, emplid)
            return {"booklet_id": booklet_id, "student_id": student_id}
    except IntegrityError as exc:
        raise DuplicateEmplidError(emplid) from exc


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
