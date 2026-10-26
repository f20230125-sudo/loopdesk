from loopdesk import create_app


def configured(url):
    return create_app(dict(TESTING=True, PRODUCTION=False, SECRET_KEY="local-fixture-secret-for-outage-tests", DATABASE_URL=url))


def test_health_distinguishes_pending_migrations(tmp_path):
    app = configured("sqlite:///" + str(tmp_path / "empty.sqlite3"))
    response = app.test_client().get("/health")
    assert response.status_code == 503
    assert response.json == {"status": "migration_required"}
    assert response.headers["Retry-After"] == "30"


def test_database_outage_does_not_expose_local_path_or_break_public_overview(tmp_path):
    sensitive_path = tmp_path / "private-connection-details" / "missing.sqlite3"
    client = configured("sqlite:///" + str(sensitive_path)).test_client()
    assert client.get("/").status_code == 200
    response = client.get("/health")
    assert response.status_code == 503 and response.json == {"status": "database_unavailable"}
    with client.session_transaction() as session:
        session["workspace_id"] = "previously-valid-workspace"
    response = client.get("/dashboard")
    assert response.status_code == 503
    assert b"temporarily unavailable" in response.data
    assert b"private-connection-details" not in response.data


def test_postgres_connection_failure_is_redacted(caplog):
    # Loopback port 1 rejects immediately; no external database or credentials are used.
    client = configured("postgresql://fixture:private-marker@127.0.0.1:1/no_database").test_client()
    response = client.get("/health")
    assert response.status_code == 503 and response.json == {"status": "database_unavailable"}
    assert "private-marker" not in response.get_data(as_text=True)
    assert "private-marker" not in caplog.text
