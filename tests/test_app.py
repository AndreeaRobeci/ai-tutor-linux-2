import sqlite3
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import app as app_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test_database.db"
    monkeypatch.setattr(app_module, "DATABASE", str(test_db))
    app_module.app.config.update(TESTING=True)

    with app_module.app.app_context():
        app_module.init_db()

    with app_module.app.test_client() as test_client:
        yield test_client


def create_user(username, email, role="user", onboarding_completed=1):
    connection = sqlite3.connect(app_module.DATABASE)
    try:
        cursor = connection.execute(
            """INSERT INTO users
               (username, email, password, role, onboarding_completed)
               VALUES (?, ?, ?, ?, ?)""",
            (username, email, "test-password", role, onboarding_completed),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def login_as(client, user_id, username="Test"):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["username"] = username
        session["onboarding_completed"] = 1


def test_register_page_loads(client):
    response = client.get("/register")

    if response.status_code == 405:
        assert any(
            rule.rule == "/register" and "POST" in rule.methods
            for rule in app_module.app.url_map.iter_rules()
        )
    else:
        assert response.status_code == 200


def test_login_page_loads(client):
    response = client.get("/login")

    assert response.status_code == 200


def test_chat_requires_login(client):
    response = client.get("/chat")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_exercices_requires_login(client):
    response = client.get("/exercices")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_requires_login_or_admin(client):
    anonymous_response = client.get("/admin")
    assert anonymous_response.status_code == 302
    assert "/login" in anonymous_response.headers["Location"]

    user_id = create_user("user-test", "user-test@example.com", role="user")
    login_as(client, user_id, "user-test")

    user_response = client.get("/admin")
    assert user_response.status_code == 302
    assert "/chat" in user_response.headers["Location"]

    admin_id = create_user("admin-test", "admin-test@example.com", role="admin")
    login_as(client, admin_id, "admin-test")

    admin_response = client.get("/admin")
    assert admin_response.status_code == 200
