from datetime import timedelta
import re

from sqlalchemy import text

import auth
import db
from conftest import login_as


def test_password_request_is_generic_and_pending_password_can_log_in(client):
    test_client, delivered = client
    unknown = test_client.post("/auth/password/request", json={"uct_id": "UNKNOWN001"})
    known = test_client.post("/auth/password/request", json={"uct_id": "tstadm001"})

    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert len(delivered) == 1
    with db.get_engine().connect() as conn:
        pending_hash = conn.execute(text("""
            SELECT pending_password_hash FROM users WHERE uct_id = 'TSTADM001'
        """)).scalar_one()
    assert pending_hash.startswith("$argon2id$")

    # Requesting a replacement does not invalidate the current password.
    current = test_client.post("/auth/login", json={
        "uct_id": "TSTADM001", "password": "admin-password"
    })
    assert current.status_code == 200
    previous_token = test_client.cookies.get(auth.COOKIE_NAME)

    response = test_client.post("/auth/login", json={
        "uct_id": "TSTADM001",
        "password": delivered[0]["password"],
    })
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"

    with db.get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT password_hash, pending_password_hash FROM users
            WHERE uct_id = 'TSTADM001'
        """)).mappings().one()
        previous_session_revoked = conn.execute(text("""
            SELECT revoked_at FROM auth_sessions WHERE token_hash = :token_hash
        """), {"token_hash": auth._hash_token(previous_token)}).scalar_one()
    assert row["password_hash"]
    assert row["password_hash"].startswith("$argon2id$")
    assert row["pending_password_hash"] is None
    assert previous_session_revoked is not None
    assert test_client.post("/auth/login", json={
        "uct_id": "TSTADM001", "password": "admin-password"
    }).status_code == 401


def test_bootstrap_is_idempotent(client, monkeypatch):
    _test_client, _delivered = client
    with db.get_engine().begin() as conn:
        conn.execute(text("DELETE FROM auth_sessions"))
        conn.execute(text("DELETE FROM users"))
    monkeypatch.setenv("EXAMSCAN_BOOTSTRAP_UCT_ID", "tstboot001")
    monkeypatch.setenv("EXAMSCAN_BOOTSTRAP_NAME", "Bootstrap Administrator")
    monkeypatch.setenv("EXAMSCAN_BOOTSTRAP_EMAIL", "bootstrap@example.test")
    auth.init_auth()
    auth.init_auth()
    with db.get_engine().connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
        bootstrapped = conn.execute(text("SELECT * FROM users")).mappings().one()
    assert bootstrapped["uct_id"] == "TSTBOOT001"
    assert bootstrapped["role"] == "admin"
    assert bootstrapped["password_hash"] is None


def test_password_request_cooldown_and_disabled_response_are_generic(client):
    test_client, delivered = client
    first = test_client.post("/auth/password/request", json={"uct_id": "TSTADM001"})
    second = test_client.post("/auth/password/request", json={"uct_id": "TSTADM001"})
    unknown = test_client.post("/auth/password/request", json={"uct_id": "UNKNOWN001"})
    assert first.status_code == second.status_code == unknown.status_code == 202
    assert first.json() == second.json() == unknown.json()
    assert len(delivered) == 1

    with db.get_engine().begin() as conn:
        conn.execute(text("UPDATE users SET active = FALSE WHERE uct_id = 'TSTADM001'"))
    disabled = test_client.post("/auth/password/request", json={"uct_id": "TSTADM001"})
    assert disabled.status_code == 202
    assert disabled.json() == unknown.json()
    assert len(delivered) == 1


def test_existing_password_survives_failed_delivery(client, monkeypatch):
    test_client, _delivered = client

    def fail_delivery(_user, _password):
        raise OSError("mail unavailable")

    monkeypatch.setattr(auth, "send_password_email", fail_delivery)
    response = test_client.post("/auth/password/request", json={"uct_id": "TSTADM001"})
    assert response.status_code == 202
    assert test_client.post("/auth/login", json={
        "uct_id": "TSTADM001", "password": "admin-password"
    }).status_code == 200


def test_email_change_discards_pending_password_and_allows_resend(client):
    test_client, delivered = client
    csrf = login_as(test_client)
    assert test_client.post(
        "/auth/password/request", json={"uct_id": "TSTADM001"}
    ).status_code == 202
    with db.get_engine().connect() as conn:
        admin_id = conn.execute(text(
            "SELECT id FROM users WHERE uct_id = 'TSTADM001'"
        )).scalar_one()

    updated = test_client.patch(
        f"/admin/users/{admin_id}",
        headers={"X-CSRF-Token": csrf},
        json={"email": "new-admin@example.test"},
    )
    assert updated.status_code == 200
    with db.get_engine().connect() as conn:
        state = conn.execute(text("""
            SELECT pending_password_hash, pending_password_expires_at,
                   last_password_email_at
            FROM users WHERE id = :id
        """), {"id": admin_id}).mappings().one()
    assert state["pending_password_hash"] is None
    assert state["pending_password_expires_at"] is None
    assert state["last_password_email_at"] is None

    resent = test_client.post(
        f"/admin/users/{admin_id}/password",
        headers={"X-CSRF-Token": csrf},
    )
    assert resent.status_code == 202
    assert len(delivered) == 2
    assert delivered[-1]["user"]["email"] == "new-admin@example.test"


def test_protected_routes_and_csrf(client):
    test_client, _delivered = client
    assert test_client.get("/sessions").status_code == 401

    csrf = login_as(test_client)
    assert test_client.get("/sessions").status_code == 200
    missing_csrf = test_client.post("/admin/users", json={
        "uct_id": "TSTOPR001",
        "name": "Test Operator",
        "email": "operator@example.test",
        "role": "operator",
    })
    assert missing_csrf.status_code == 403

    created = test_client.post("/admin/users", headers={"X-CSRF-Token": csrf}, json={
        "uct_id": "TSTOPR001",
        "name": "Test Operator",
        "email": "operator@example.test",
        "role": "operator",
    })
    assert created.status_code == 201


def test_operator_cannot_manage_staff(client):
    test_client, _delivered = client
    with db.get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO users (uct_id, name, email, role, password_hash)
            VALUES ('TSTOPR001', 'Test Operator', 'operator@example.test',
                    'operator', :password_hash)
        """), {"password_hash": auth._password_hasher.hash("operator-password")})

    login_as(test_client, "TSTOPR001", "operator-password")
    assert test_client.get("/sessions").status_code == 200
    assert test_client.get("/admin/users").status_code == 403


def test_final_active_admin_cannot_be_disabled(client):
    test_client, _delivered = client
    csrf = login_as(test_client)
    with db.get_engine().connect() as conn:
        admin_id = conn.execute(text("SELECT id FROM users WHERE uct_id = 'TSTADM001'")).scalar_one()
    demotion = test_client.patch(
        f"/admin/users/{admin_id}",
        headers={"X-CSRF-Token": csrf},
        json={"role": "operator"},
    )
    assert demotion.status_code == 409
    response = test_client.patch(
        f"/admin/users/{admin_id}",
        headers={"X-CSRF-Token": csrf},
        json={"active": False},
    )
    assert response.status_code == 409


def test_five_failures_lock_account(client):
    test_client, _delivered = client
    for _ in range(auth.MAX_FAILED_LOGINS):
        response = test_client.post("/auth/login", json={
            "uct_id": "TSTADM001", "password": "wrong-password"
        })
        assert response.status_code == 401
    assert test_client.post("/auth/login", json={
        "uct_id": "TSTADM001", "password": "admin-password"
    }).status_code == 401
    test_client.post("/auth/password/request", json={"uct_id": "TSTADM001"})
    with db.get_engine().connect() as conn:
        state = conn.execute(text("""
            SELECT failed_login_attempts, locked_until
            FROM users WHERE uct_id = 'TSTADM001'
        """)).mappings().one()
    assert state["failed_login_attempts"] == auth.MAX_FAILED_LOGINS
    assert state["locked_until"] is not None


def test_expired_session_is_rejected(client):
    test_client, _delivered = client
    login_as(test_client)
    with db.get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE auth_sessions SET expires_at = :expired WHERE revoked_at IS NULL
        """), {"expired": auth._utcnow() - timedelta(seconds=1)})
    assert test_client.get("/auth/me").status_code == 401


def test_session_restoration_returns_stable_csrf_token(client):
    test_client, _delivered = client
    login_csrf = login_as(test_client)
    first = test_client.get("/auth/me")
    second = test_client.get("/auth/me")
    assert first.status_code == second.status_code == 200
    assert first.json()["csrf_token"] == second.json()["csrf_token"] == login_csrf


def test_logout_revokes_session(client):
    test_client, _delivered = client
    csrf = login_as(test_client)
    token = test_client.cookies.get(auth.COOKIE_NAME)
    response = test_client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200

    test_client.cookies.set(auth.COOKIE_NAME, token)
    assert test_client.get("/auth/me").status_code == 401


def test_only_explicit_allowlist_is_public(client):
    test_client, _delivered = client
    assert auth.PUBLIC_ROUTES == {
        ("GET", "/health"),
        ("POST", "/auth/login"),
        ("POST", "/auth/password/request"),
    }
    observed_public = set()
    for route in auth_router_routes():
        concrete_path = re.sub(r"\{[^}]+\}", "1", route.path)
        for method in route.methods or set():
            if method in {"HEAD", "OPTIONS"}:
                continue
            response = test_client.request(method, concrete_path, json={})
            if response.status_code != 401:
                observed_public.add((method, route.path))
    assert observed_public == auth.PUBLIC_ROUTES


def auth_router_routes():
    """Return every HTTP route, including FastAPI's documentation routes."""
    from scanner_api import app

    def walk(routes):
        for route in routes:
            if getattr(route, "methods", None) and getattr(route, "path", None):
                yield route
            included = getattr(route, "original_router", None)
            if included is not None:
                yield from walk(included.routes)

    return list(walk(app.routes))
