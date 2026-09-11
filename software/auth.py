"""Staff authentication, password delivery, and route protection for ExamScan."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware

import db

logger = logging.getLogger(__name__)

COOKIE_NAME = "examscan_session"
SESSION_IDLE = timedelta(hours=8)
SESSION_TOUCH_INTERVAL = timedelta(minutes=5)
PENDING_PASSWORD_LIFETIME = timedelta(minutes=30)
PASSWORD_EMAIL_COOLDOWN = timedelta(minutes=5)
LOCKOUT_DURATION = timedelta(minutes=15)
MAX_FAILED_LOGINS = 5

PUBLIC_ROUTES = {
    ("GET", "/health"),
    ("POST", "/auth/login"),
    ("POST", "/auth/password/request"),
}

PASSWORD_REQUEST_MESSAGE = (
    "If that UCT ID is registered and eligible, a password email will be sent shortly."
)

_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)
_dummy_hash = _password_hasher.hash("ExamScan timing-equalization value")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_uct_id(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized or len(normalized) > 128:
        raise ValueError("UCT ID must be between 1 and 128 characters.")
    return normalized


def _validate_email(value: str) -> str:
    normalized = value.strip()
    local, separator, domain = normalized.rpartition("@")
    if not separator or not local or "." not in domain or len(normalized) > 255:
        raise ValueError("Enter a valid email address.")
    return normalized


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _csrf_for_session(session_token: str) -> str:
    """Derive a stable, non-reversible CSRF value from an opaque session."""
    digest = hashlib.sha256(f"examscan-csrf:{session_token}".encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_password(encoded_hash: str | None, password: str) -> bool:
    if not encoded_hash:
        return False
    try:
        return _password_hasher.verify(encoded_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _public_user(row: dict) -> dict:
    return {
        "id": row["id"],
        "uct_id": row["uct_id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "active": bool(row["active"]),
        "last_login_at": row.get("last_login_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def init_auth() -> None:
    """Create auth tables and seed the first administrator when required."""
    engine = db.get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                uct_id VARCHAR(128) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL UNIQUE,
                role VARCHAR(32) NOT NULL DEFAULT 'operator',
                active BOOLEAN NOT NULL DEFAULT TRUE,
                password_hash VARCHAR(512) NULL,
                pending_password_hash VARCHAR(512) NULL,
                pending_password_expires_at DATETIME NULL,
                failed_login_attempts INT NOT NULL DEFAULT 0,
                locked_until DATETIME NULL,
                last_password_email_at DATETIME NULL,
                last_login_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_users_role_active (role, active)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                token_hash CHAR(64) NOT NULL UNIQUE,
                user_id INT NOT NULL,
                csrf_hash CHAR(64) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_accessed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                revoked_at DATETIME NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_auth_sessions_user (user_id),
                INDEX idx_auth_sessions_expiry (expires_at, revoked_at)
            )
        """))

        user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
        if user_count:
            return

        bootstrap = {
            "uct_id": os.environ.get("EXAMSCAN_BOOTSTRAP_UCT_ID", ""),
            "name": os.environ.get("EXAMSCAN_BOOTSTRAP_NAME", ""),
            "email": os.environ.get("EXAMSCAN_BOOTSTRAP_EMAIL", ""),
        }
        if not all(bootstrap.values()):
            raise RuntimeError(
                "No ExamScan users exist. Configure EXAMSCAN_BOOTSTRAP_UCT_ID, "
                "EXAMSCAN_BOOTSTRAP_NAME, and EXAMSCAN_BOOTSTRAP_EMAIL."
            )
        try:
            bootstrap["uct_id"] = _normalize_uct_id(bootstrap["uct_id"])
            bootstrap["email"] = _validate_email(bootstrap["email"])
        except ValueError as exc:
            raise RuntimeError(f"Invalid bootstrap administrator: {exc}") from exc
        conn.execute(text("""
            INSERT INTO users (uct_id, name, email, role)
            VALUES (:uct_id, :name, :email, 'admin')
        """), bootstrap)
        logger.info("Created bootstrap administrator account for %s", bootstrap["uct_id"])


def _smtp_settings() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST", "localhost"),
        "port": int(os.environ.get("SMTP_PORT", "1025")),
        "username": os.environ.get("SMTP_USERNAME", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "security": os.environ.get("SMTP_SECURITY", "none").strip().lower(),
        "sender": os.environ.get("SMTP_FROM", "ExamScan <examscan@localhost>"),
        "frontend_url": os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
    }


def send_password_email(user: dict, password: str) -> None:
    settings = _smtp_settings()
    if settings["security"] not in {"none", "starttls", "ssl"}:
        raise RuntimeError("SMTP_SECURITY must be one of: none, starttls, ssl")

    message = EmailMessage()
    message["Subject"] = "Your ExamScan password"
    message["From"] = settings["sender"]
    message["To"] = user["email"]
    message.set_content(
        f"""Hello {user['name']},

An ExamScan password was requested for UCT ID {user['uct_id']}.

Password: {password}

Use it within 30 minutes at {settings['frontend_url']}/login. After your first
successful sign-in, it remains valid until another password is activated.

If you did not request this email, your current password is still valid. Contact
an ExamScan administrator if these messages continue.
"""
    )

    context = ssl.create_default_context()
    if settings["security"] == "ssl":
        client = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=15, context=context)
    else:
        client = smtplib.SMTP(settings["host"], settings["port"], timeout=15)
    with client:
        if settings["security"] == "starttls":
            client.starttls(context=context)
        if settings["username"]:
            client.login(settings["username"], settings["password"])
        client.send_message(message)


PasswordIssueStatus = Literal["sent", "unknown", "disabled", "cooldown", "mail_failed"]


def issue_password(uct_id: str, *, bypass_cooldown: bool = False) -> PasswordIssueStatus:
    """Stage and email a replacement without invalidating the current password."""
    try:
        normalized = _normalize_uct_id(uct_id)
    except ValueError:
        return "unknown"

    now = _utcnow()
    engine = db.get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM users WHERE uct_id = :uct_id FOR UPDATE"),
            {"uct_id": normalized},
        ).mappings().first()
        if row is None:
            return "unknown"
        user = dict(row)
        if not user["active"]:
            return "disabled"
        last_email = user["last_password_email_at"]
        if not bypass_cooldown and last_email and now - last_email < PASSWORD_EMAIL_COOLDOWN:
            return "cooldown"

        password = secrets.token_urlsafe(16)
        pending_hash = _password_hasher.hash(password)
        previous = {
            "pending_hash": user["pending_password_hash"],
            "pending_expires": user["pending_password_expires_at"],
            "last_email": user["last_password_email_at"],
        }
        conn.execute(text("""
            UPDATE users
            SET pending_password_hash = :pending_hash,
                pending_password_expires_at = :pending_expires,
                last_password_email_at = :now
            WHERE id = :id
        """), {
            "pending_hash": pending_hash,
            "pending_expires": now + PENDING_PASSWORD_LIFETIME,
            "now": now,
            "id": user["id"],
        })

    try:
        send_password_email(user, password)
    except Exception:
        logger.exception("Could not deliver an ExamScan password email for %s", normalized)
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE users
                SET pending_password_hash = :previous_hash,
                    pending_password_expires_at = :previous_expires,
                    last_password_email_at = :previous_email
                WHERE id = :id AND pending_password_hash = :attempted_hash
            """), {
                "previous_hash": previous["pending_hash"],
                "previous_expires": previous["pending_expires"],
                "previous_email": previous["last_email"],
                "id": user["id"],
                "attempted_hash": pending_hash,
            })
        return "mail_failed"
    return "sent"


def _record_failed_login(user: dict) -> None:
    now = _utcnow()
    attempts = user["failed_login_attempts"] or 0
    if user["locked_until"] and user["locked_until"] <= now:
        attempts = 0
    attempts += 1
    locked_until = now + LOCKOUT_DURATION if attempts >= MAX_FAILED_LOGINS else None
    with db.get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE users
            SET failed_login_attempts = :attempts, locked_until = :locked_until
            WHERE id = :id
        """), {"attempts": attempts, "locked_until": locked_until, "id": user["id"]})


def login(uct_id: str, password: str) -> tuple[dict, str, str] | None:
    """Validate a current or pending password and create a revocable session."""
    try:
        normalized = _normalize_uct_id(uct_id)
    except ValueError:
        _verify_password(_dummy_hash, password)
        return None

    now = _utcnow()
    with db.get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM users WHERE uct_id = :uct_id"),
            {"uct_id": normalized},
        ).mappings().first()
    if row is None:
        _verify_password(_dummy_hash, password)
        return None

    user = dict(row)
    if not user["active"] or (user["locked_until"] and user["locked_until"] > now):
        _verify_password(_dummy_hash, password)
        return None

    pending_valid = bool(
        user["pending_password_hash"]
        and user["pending_password_expires_at"]
        and user["pending_password_expires_at"] > now
    )
    used_pending = pending_valid and _verify_password(user["pending_password_hash"], password)
    used_current = False if used_pending else _verify_password(user["password_hash"], password)
    if not used_pending and not used_current:
        _record_failed_login(user)
        return None

    engine = db.get_engine()
    with engine.begin() as conn:
        if used_pending:
            conn.execute(text("""
                UPDATE users
                SET password_hash = pending_password_hash,
                    pending_password_hash = NULL,
                    pending_password_expires_at = NULL,
                    failed_login_attempts = 0,
                    locked_until = NULL,
                    last_login_at = :now
                WHERE id = :id
            """), {"now": now, "id": user["id"]})
            conn.execute(text("""
                UPDATE auth_sessions SET revoked_at = :now
                WHERE user_id = :id AND revoked_at IS NULL
            """), {"now": now, "id": user["id"]})
        else:
            updated_hash = user["password_hash"]
            if _password_hasher.check_needs_rehash(updated_hash):
                updated_hash = _password_hasher.hash(password)
            conn.execute(text("""
                UPDATE users
                SET password_hash = :password_hash,
                    failed_login_attempts = 0,
                    locked_until = NULL,
                    last_login_at = :now
                WHERE id = :id
            """), {"password_hash": updated_hash, "now": now, "id": user["id"]})

        token = secrets.token_urlsafe(32)
        csrf_token = _csrf_for_session(token)
        conn.execute(text("""
            INSERT INTO auth_sessions
                (token_hash, user_id, csrf_hash, last_accessed_at, expires_at)
            VALUES (:token_hash, :user_id, :csrf_hash, :now, :expires_at)
        """), {
            "token_hash": _hash_token(token),
            "user_id": user["id"],
            "csrf_hash": _hash_token(csrf_token),
            "now": now,
            "expires_at": now + SESSION_IDLE,
        })
        refreshed = conn.execute(
            text("SELECT * FROM users WHERE id = :id"), {"id": user["id"]}
        ).mappings().one()
    return _public_user(dict(refreshed)), token, csrf_token


def authenticate_session(token: str | None) -> dict | None:
    if not token:
        return None
    token_hash = _hash_token(token)
    now = _utcnow()
    engine = db.get_engine()
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT u.*, s.token_hash AS session_hash, s.csrf_hash,
                   s.last_accessed_at, s.expires_at, s.revoked_at
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = :token_hash
        """), {"token_hash": token_hash}).mappings().first()
        if row is None:
            return None
        session = dict(row)
        if not session["active"] or session["revoked_at"] or session["expires_at"] <= now:
            if not session["revoked_at"]:
                conn.execute(text("""
                    UPDATE auth_sessions SET revoked_at = :now WHERE token_hash = :token_hash
                """), {"now": now, "token_hash": token_hash})
            return None
        if now - session["last_accessed_at"] >= SESSION_TOUCH_INTERVAL:
            conn.execute(text("""
                UPDATE auth_sessions
                SET last_accessed_at = :now, expires_at = :expires_at
                WHERE token_hash = :token_hash
            """), {
                "now": now,
                "expires_at": now + SESSION_IDLE,
                "token_hash": token_hash,
            })
        public = _public_user(session)
        public["_session_hash"] = token_hash
        public["_csrf_hash"] = session["csrf_hash"]
        return public


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with db.get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE auth_sessions SET revoked_at = :now
            WHERE token_hash = :token_hash AND revoked_at IS NULL
        """), {"now": _utcnow(), "token_hash": _hash_token(token)})


class AuthMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated API calls and enforce per-session CSRF tokens."""

    async def dispatch(self, request: Request, call_next):
        route_key = (request.method.upper(), request.url.path)
        if request.method.upper() == "OPTIONS" or route_key in PUBLIC_ROUTES:
            return await call_next(request)

        user = authenticate_session(request.cookies.get(COOKIE_NAME))
        if user is None:
            response = JSONResponse({"detail": "Authentication required."}, status_code=401)
            response.delete_cookie(COOKIE_NAME, path="/")
            return response

        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or not hmac.compare_digest(_hash_token(supplied), user["_csrf_hash"]):
                return JSONResponse({"detail": "Invalid CSRF token."}, status_code=403)

        request.state.auth_user = user
        return await call_next(request)


def require_admin(request: Request) -> dict:
    user = request.state.auth_user
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user


class LoginRequest(BaseModel):
    uct_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class PasswordRequest(BaseModel):
    uct_id: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    uct_id: str
    name: str
    email: str
    role: Literal["admin", "operator"]
    active: bool
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AuthResponse(BaseModel):
    user: UserOut
    csrf_token: str


class MessageResponse(BaseModel):
    message: str


class UserCreate(BaseModel):
    uct_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    role: Literal["admin", "operator"] = "operator"


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    role: Literal["admin", "operator"] | None = None
    active: bool | None = None


class UserCreateResponse(BaseModel):
    user: UserOut
    password_email_sent: bool


class ErrorResponse(BaseModel):
    detail: str


AUTH_REQUIRED_RESPONSES = {
    401: {"model": ErrorResponse, "description": "The session is missing, expired, or revoked."},
}
ADMIN_REQUIRED_RESPONSES = {
    **AUTH_REQUIRED_RESPONSES,
    403: {
        "model": ErrorResponse,
        "description": "The CSRF token is invalid or the user is not an administrator.",
    },
}


def _get_user(user_id: int) -> dict | None:
    with db.get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM users WHERE id = :id"), {"id": user_id}
        ).mappings().first()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with db.get_engine().connect() as conn:
        rows = conn.execute(text("SELECT * FROM users ORDER BY name, uct_id")).mappings().all()
    return [_public_user(dict(row)) for row in rows]


def create_user(payload: UserCreate) -> dict:
    try:
        values = {
            "uct_id": _normalize_uct_id(payload.uct_id),
            "name": payload.name.strip(),
            "email": _validate_email(payload.email),
            "role": payload.role,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not values["name"]:
        raise HTTPException(status_code=422, detail="Name is required.")
    try:
        with db.get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO users (uct_id, name, email, role)
                VALUES (:uct_id, :name, :email, :role)
            """), values)
            user_id = result.lastrowid
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="UCT ID or email is already registered.") from exc
    return _get_user(user_id)


def update_user(user_id: int, payload: UserUpdate) -> dict:
    existing = _get_user(user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Staff account not found.")

    name = payload.name.strip() if payload.name is not None else existing["name"]
    if not name:
        raise HTTPException(status_code=422, detail="Name is required.")
    try:
        email = _validate_email(payload.email) if payload.email is not None else existing["email"]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    role = payload.role if payload.role is not None else existing["role"]
    active = payload.active if payload.active is not None else bool(existing["active"])
    email_changed = email.casefold() != existing["email"].casefold()

    removing_admin = existing["role"] == "admin" and existing["active"] and (
        role != "admin" or not active
    )
    with db.get_engine().begin() as conn:
        if removing_admin:
            # Lock every active administrator row so concurrent updates cannot
            # both remove an administrator and leave the system without one.
            active_admin_ids = conn.execute(text("""
                SELECT id FROM users
                WHERE role = 'admin' AND active = TRUE
                FOR UPDATE
            """)).scalars().all()
            if len(active_admin_ids) <= 1:
                raise HTTPException(status_code=409, detail="The final active administrator cannot be changed.")
        try:
            conn.execute(text("""
                UPDATE users
                SET name = :name, email = :email, role = :role, active = :active,
                    pending_password_hash = CASE WHEN :email_changed THEN NULL ELSE pending_password_hash END,
                    pending_password_expires_at = CASE WHEN :email_changed THEN NULL ELSE pending_password_expires_at END,
                    last_password_email_at = CASE WHEN :email_changed THEN NULL ELSE last_password_email_at END
                WHERE id = :id
            """), {
                "name": name,
                "email": email,
                "email_changed": email_changed,
                "role": role,
                "active": active,
                "id": user_id,
            })
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="That email address is already registered.") from exc
        if not active:
            now = _utcnow()
            conn.execute(text("""
                UPDATE auth_sessions SET revoked_at = :now
                WHERE user_id = :id AND revoked_at IS NULL
            """), {"now": now, "id": user_id})
            conn.execute(text("""
                UPDATE users
                SET pending_password_hash = NULL, pending_password_expires_at = NULL
                WHERE id = :id
            """), {"id": user_id})
    return _get_user(user_id)


auth_router = APIRouter(tags=["authentication"])


@auth_router.post(
    "/auth/login",
    response_model=AuthResponse,
    responses={
        401: {"model": ErrorResponse, "description": "The supplied credentials are not accepted."},
    },
)
def login_endpoint(payload: LoginRequest, response: Response):
    result = login(payload.uct_id, payload.password)
    if result is None:
        raise HTTPException(status_code=401, detail="Incorrect UCT ID or password.")
    user, token, csrf_token = result
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=_env_bool(
            "AUTH_COOKIE_SECURE",
            os.environ.get("EXAMSCAN_ENV", "development").strip().lower() == "production",
        ),
        samesite="lax",
        path="/",
    )
    return {"user": user, "csrf_token": csrf_token}


@auth_router.post(
    "/auth/password/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_password_endpoint(payload: PasswordRequest):
    issue_password(payload.uct_id)
    return {"message": PASSWORD_REQUEST_MESSAGE}


@auth_router.get(
    "/auth/me",
    response_model=AuthResponse,
    responses=AUTH_REQUIRED_RESPONSES,
)
def me_endpoint(request: Request):
    user = request.state.auth_user
    csrf_token = _csrf_for_session(request.cookies[COOKIE_NAME])
    return {"user": _public_user(user), "csrf_token": csrf_token}


@auth_router.post(
    "/auth/logout",
    response_model=MessageResponse,
    responses={
        **AUTH_REQUIRED_RESPONSES,
        403: {"model": ErrorResponse, "description": "The CSRF token is invalid."},
    },
)
def logout_endpoint(request: Request, response: Response):
    revoke_session(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"message": "Signed out."}


@auth_router.get(
    "/admin/users",
    response_model=list[UserOut],
    tags=["staff administration"],
    responses=ADMIN_REQUIRED_RESPONSES,
)
def list_users_endpoint(_admin: dict = Depends(require_admin)):
    return list_users()


@auth_router.post(
    "/admin/users",
    response_model=UserCreateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["staff administration"],
    responses={
        **ADMIN_REQUIRED_RESPONSES,
        409: {"model": ErrorResponse, "description": "The UCT ID or email already exists."},
    },
)
def create_user_endpoint(payload: UserCreate, _admin: dict = Depends(require_admin)):
    user = create_user(payload)
    delivery = issue_password(user["uct_id"], bypass_cooldown=True)
    return {"user": _public_user(user), "password_email_sent": delivery == "sent"}


@auth_router.patch(
    "/admin/users/{user_id}",
    response_model=UserOut,
    tags=["staff administration"],
    responses={
        **ADMIN_REQUIRED_RESPONSES,
        404: {"model": ErrorResponse, "description": "The staff account does not exist."},
        409: {"model": ErrorResponse, "description": "The update conflicts with another account or final-administrator protection."},
    },
)
def update_user_endpoint(user_id: int, payload: UserUpdate, _admin: dict = Depends(require_admin)):
    return _public_user(update_user(user_id, payload))


@auth_router.post(
    "/admin/users/{user_id}/password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["staff administration"],
    responses={
        **ADMIN_REQUIRED_RESPONSES,
        404: {"model": ErrorResponse, "description": "The staff account does not exist."},
        409: {"model": ErrorResponse, "description": "The staff account is inactive."},
        429: {"model": ErrorResponse, "description": "The account password-email cooldown is active."},
        502: {"model": ErrorResponse, "description": "SMTP delivery failed."},
    },
)
def admin_password_endpoint(user_id: int, _admin: dict = Depends(require_admin)):
    user = _get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Staff account not found.")
    delivery = issue_password(user["uct_id"])
    if delivery == "cooldown":
        raise HTTPException(status_code=429, detail="A password email was sent recently. Try again later.")
    if delivery == "disabled":
        raise HTTPException(status_code=409, detail="Activate the account before sending a password.")
    if delivery == "mail_failed":
        raise HTTPException(status_code=502, detail="The password email could not be delivered.")
    return {"message": "A new password has been emailed."}
