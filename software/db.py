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
from sqlalchemy import create_engine, text
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
            CREATE TABLE IF NOT EXISTS booklets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id INT NOT NULL,
                emplid VARCHAR(64) NOT NULL,
                course_code_scanned VARCHAR(64) NULL,
                course_code_verified BOOLEAN NOT NULL DEFAULT FALSE,
                num_pages INT NULL,
                pdf_path VARCHAR(512) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES scan_sessions(id),
                UNIQUE KEY uq_session_emplid (session_id, emplid)
            )
        """))


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
) -> int:
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
            return result.lastrowid
    except IntegrityError as exc:
        raise DuplicateEmplidError(emplid) from exc
