from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

SOFTWARE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOFTWARE_DIR))

os.environ.setdefault("EXAMSCAN_BOOTSTRAP_UCT_ID", "TSTADM001")
os.environ.setdefault("EXAMSCAN_BOOTSTRAP_NAME", "Test Administrator")
os.environ.setdefault("EXAMSCAN_BOOTSTRAP_EMAIL", "admin@example.test")
os.environ.setdefault("AUTH_COOKIE_SECURE", "false")

import auth  # noqa: E402
import db  # noqa: E402
from scanner_api import app  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    if not os.environ.get("DB_NAME", "").endswith("_test"):
        pytest.skip("Auth integration tests require a DB_NAME ending in '_test'.")

    delivered = []

    def capture_email(user, password):
        delivered.append({"user": user, "password": password})

    monkeypatch.setattr(auth, "send_password_email", capture_email)

    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        with db.get_engine().begin() as conn:
            conn.execute(text("DELETE FROM auth_sessions"))
            conn.execute(text("DELETE FROM users"))
            conn.execute(text("""
                INSERT INTO users (uct_id, name, email, role, password_hash)
                VALUES ('TSTADM001', 'Test Administrator', 'admin@example.test',
                        'admin', :password_hash)
            """), {"password_hash": auth._password_hasher.hash("admin-password")})
        yield test_client, delivered


def login_as(client, uct_id="TSTADM001", password="admin-password"):
    response = client.post("/auth/login", json={"uct_id": uct_id, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]
