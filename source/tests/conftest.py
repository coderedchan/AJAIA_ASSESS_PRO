import pytest

from relay import create_app
from relay.db import connect


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "relay-test.sqlite3")


@pytest.fixture
def app(db_path):
    return create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})


@pytest.fixture
def as_user(app):
    """Return a signed-in test client for a seeded user id."""
    clients = {}

    def make(user_id):
        if user_id not in clients:
            client = app.test_client()
            res = client.post("/api/session", json={"user_id": user_id})
            assert res.status_code == 200, res.get_json()
            clients[user_id] = client
        return clients[user_id]

    return make


@pytest.fixture
def raw_db(db_path):
    """Direct database access, used to check stored records without the API."""
    conn = connect(db_path)
    yield conn
    conn.close()
