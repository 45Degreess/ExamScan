import auth
from scanner_api import app


def test_uct_ids_are_trimmed_and_uppercased():
    assert auth._normalize_uct_id("  abcdef001  ") == "ABCDEF001"


def test_argon2_hash_verifies_without_containing_password():
    password = "unit-test-only-value"
    encoded = auth._password_hasher.hash(password)
    assert password not in encoded
    assert auth._verify_password(encoded, password)
    assert not auth._verify_password(encoded, "wrong-password")


def test_only_intended_routes_are_public():
    assert auth.PUBLIC_ROUTES == {
        ("GET", "/health"),
        ("POST", "/auth/login"),
        ("POST", "/auth/password/request"),
    }


def test_csrf_value_is_stable_but_does_not_expose_the_session_token():
    session_token = "unit-test-session-value"
    first = auth._csrf_for_session(session_token)
    assert first == auth._csrf_for_session(session_token)
    assert first != session_token
    assert auth._hash_token(first) != auth._hash_token(session_token)


def test_openapi_documents_authentication_error_contracts():
    paths = app.openapi()["paths"]
    expected = {
        ("/auth/login", "post"): {"200", "401", "422"},
        ("/auth/password/request", "post"): {"202", "422"},
        ("/auth/me", "get"): {"200", "401"},
        ("/auth/logout", "post"): {"200", "401", "403"},
        ("/admin/users", "get"): {"200", "401", "403"},
        ("/admin/users", "post"): {"201", "401", "403", "409", "422"},
        ("/admin/users/{user_id}", "patch"): {"200", "401", "403", "404", "409", "422"},
        ("/admin/users/{user_id}/password", "post"): {
            "202", "401", "403", "404", "409", "422", "429", "502",
        },
    }
    for (path, method), statuses in expected.items():
        assert set(paths[path][method]["responses"]) == statuses
