import pytest
import os
import uuid

from loopdesk import create_app
from loopdesk.db import Database, get_db, migrate
from loopdesk.services import create_workspace


@pytest.fixture
def app(tmp_path):
    url = os.environ.get("LOOPDESK_TEST_DATABASE_URL")
    schema, admin = None, None
    if url:
        if not url.startswith(("postgres://", "postgresql://")):
            raise ValueError("LOOPDESK_TEST_DATABASE_URL must identify a dedicated PostgreSQL test database.")
        from psycopg import sql
        schema = "loopdesk_test_" + uuid.uuid4().hex
        admin = Database(url)
        with admin.transaction():
            admin.conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        app = create_app({"TESTING": True, "PRODUCTION": False, "SECRET_KEY": "test-secret-for-isolated-fixtures-only",
                          "DATABASE_URL": url or "sqlite:///" + str(tmp_path / "test.sqlite3"),
                          "DATABASE_SCHEMA": schema})
        with app.app_context():
            migrate(get_db())
        yield app
    finally:
        if admin:
            # Drop only the unique schema created by this fixture, never public or another project.
            with admin.transaction():
                admin.conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            admin.close()


@pytest.fixture
def db(app):
    with app.app_context():
        yield get_db()


@pytest.fixture
def workspace(db):
    return create_workspace(db, seed=False)


@pytest.fixture
def client(app):
    return app.test_client()


def start_demo(client):
    assert client.get("/").status_code == 200
    with client.session_transaction() as sess:
        token = sess["csrf"]
    assert client.post("/demo", data={"csrf_token": token}).status_code == 303
    client.get("/dashboard")
    with client.session_transaction() as sess:
        return sess["workspace_id"], sess["csrf"]


def session_for(client, wid):
    with client.session_transaction() as sess:
        sess["workspace_id"] = wid
        sess["csrf"] = "fixture-csrf"
    return "fixture-csrf"
