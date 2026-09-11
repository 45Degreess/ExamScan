"""Opt-in end-to-end authentication check using real MySQL and Mailpit."""

from __future__ import annotations

import os
import re
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import auth
import db
from scanner_api import app


pytestmark = pytest.mark.skipif(
    os.environ.get("EXAMSCAN_MAILPIT_E2E") != "1",
    reason="Set EXAMSCAN_MAILPIT_E2E=1 with isolated MySQL and Mailpit services.",
)


def _message_ids(api_url: str) -> set[str]:
    response = httpx.get(f"{api_url}/api/v1/messages", timeout=5)
    response.raise_for_status()
    return {message["ID"] for message in response.json()["messages"]}


def _new_password(api_url: str, previous_ids: set[str]) -> str:
    for _ in range(20):
        response = httpx.get(f"{api_url}/api/v1/messages", timeout=5)
        response.raise_for_status()
        new_messages = [
            message for message in response.json()["messages"]
            if message["ID"] not in previous_ids
        ]
        if new_messages:
            detail = httpx.get(
                f"{api_url}/api/v1/message/{new_messages[0]['ID']}", timeout=5
            )
            detail.raise_for_status()
            match = re.search(
                r"^Password:\s+(\S+)\r?$", detail.json()["Text"], re.MULTILINE
            )
            assert match, "Mailpit message did not contain the generated password."
            return match.group(1)
        time.sleep(0.1)
    raise AssertionError("Mailpit did not receive a password message.")


def test_bootstrap_to_operator_mailpit_flow(monkeypatch):
    assert os.environ.get("DB_NAME", "").endswith("_test")
    mailpit_api = os.environ.get("MAILPIT_API_URL", "http://mailpit:8025").rstrip("/")
    monkeypatch.setenv("EXAMSCAN_BOOTSTRAP_UCT_ID", "e2eadm001")
    monkeypatch.setenv("EXAMSCAN_BOOTSTRAP_NAME", "E2E Administrator")
    monkeypatch.setenv("EXAMSCAN_BOOTSTRAP_EMAIL", "administrator@example.test")
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_SECURITY", "none")

    # This opt-in test is only permitted against a *_test database.
    db.init_db()
    auth.init_auth()
    with db.get_engine().begin() as conn:
        conn.execute(text("DELETE FROM auth_sessions"))
        conn.execute(text("DELETE FROM users"))

    with TestClient(app) as admin_client:
        before_admin = _message_ids(mailpit_api)
        requested = admin_client.post(
            "/auth/password/request", json={"uct_id": "e2eadm001"}
        )
        assert requested.status_code == 202
        admin_password = _new_password(mailpit_api, before_admin)
        admin_login = admin_client.post("/auth/login", json={
            "uct_id": "E2EADM001", "password": admin_password,
        })
        assert admin_login.status_code == 200
        admin_csrf = admin_login.json()["csrf_token"]

        before_operator = _message_ids(mailpit_api)
        created = admin_client.post(
            "/admin/users",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "uct_id": "e2eopr001",
                "name": "E2E Operator",
                "email": "operator@example.test",
                "role": "operator",
            },
        )
        assert created.status_code == 201
        assert created.json()["password_email_sent"] is True
        operator_password = _new_password(mailpit_api, before_operator)

    with TestClient(app) as operator_client:
        operator_login = operator_client.post("/auth/login", json={
            "uct_id": "E2EOPR001", "password": operator_password,
        })
        assert operator_login.status_code == 200
        assert operator_client.get("/sessions").status_code == 200
        assert operator_client.get("/admin/users").status_code == 403
