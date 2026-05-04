import sqlite3
import psycopg
from datetime import datetime, timedelta, timezone

import pytest

from conftest import session_for, start_demo
from loopdesk import create_app
from loopdesk import services as s
from test_workflow import related, opportunity


@pytest.mark.parametrize("token",[None,"wrong-token","☃"])
def test_missing_invalid_csrf_is_rejected(client,token):
    client.get("/")
    response = client.post("/demo",data={} if token is None else {"csrf_token":token})
    assert response.status_code == 400
    assert b"security token" in response.data


def test_csrf_protects_record_writes(client,db,workspace):
    session_for(client,workspace)
    org,c = related(db,workspace)
    rid = opportunity(db,workspace,org,c)
    assert client.post(f"/opportunities/{rid}/activity",data={"body":"forged"}).status_code == 400
    assert not db.one("SELECT id FROM activities WHERE workspace_id=? AND body=?",(workspace,"forged"))


def test_workspace_ids_never_grant_access(db,app):
    a,b = s.create_workspace(db,False),s.create_workspace(db,False)
    oa,ca = related(db,a,"ONLY WORKSPACE A")
    ob,cb = related(db,b,"ONLY WORKSPACE B")
    ra,rb = opportunity(db,a,oa,ca),opportunity(db,b,ob,cb)
    task_b = s.add_task(db,b,rb,dict(title="Private B task",due_date="2026-10-25"))
    client = app.test_client()
    token = session_for(client,a)
    for path in [f"/opportunities/{rb}",f"/opportunities/{rb}/edit",f"/contacts/{cb}/edit",f"/organisations/{ob}/edit"]:
        assert client.get(path).status_code == 404
    for path,data in [(f"/opportunities/{rb}/activity",dict(body="wrong workspace")),(f"/opportunities/{rb}/tasks",dict(title="wrong",due_date="2026-10-25")),(f"/tasks/{task_b}/complete",dict(version=1)),(f"/contacts/{cb}/archive",dict(version=1)),(f"/organisations/{ob}/archive",dict(version=1))]:
        assert client.post(path,data=dict(csrf_token=token,**data)).status_code == 404
    for path in ["/organisations","/contacts","/opportunities?view=list","/opportunities.csv","/dashboard","/follow-ups","/reports"]:
        response = client.get(path)
        assert response.status_code == 200
        assert b"ONLY WORKSPACE B" not in response.data and b"Private B task" not in response.data
    payload = dict(csrf_token=token,title="Forbidden relationship",organisation_id=ob,contact_id=cb,owner="Demo",stage="New",service="E-waste",next_action="Call")
    assert client.post("/opportunities/new",data=payload).status_code == 404
    assert s.record(db,"tasks",b,task_b)["completed"] == 0
    with pytest.raises((sqlite3.IntegrityError, psycopg.IntegrityError)):
        with db.transaction():
            db.execute("UPDATE opportunities SET contact_id=?,organisation_id=? WHERE workspace_id=? AND id=?",(cb,ob,a,ra))


def test_expired_workspaces_inaccessible_and_cleanup_cascades(db,app,monkeypatch):
    old_time = datetime(2026,10,1,12,tzinfo=timezone.utc)
    monkeypatch.setattr(s,"utcnow",lambda:old_time)
    wid = s.create_workspace(db)
    monkeypatch.setattr(s,"utcnow",lambda:old_time+timedelta(hours=24))
    client = app.test_client()
    session_for(client,wid)
    assert client.get("/dashboard").status_code == 303
    s.create_workspace(db,False)
    for table in ["workspaces","organisations","contacts","opportunities","tasks","activities","stage_events"]:
        column = "id" if table == "workspaces" else "workspace_id"
        assert db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE {column}=?",(wid,))["n"] == 0


def test_resume_and_reset_demo_are_isolated(client,db):
    wid,token = start_demo(client)
    assert client.post("/demo",data=dict(csrf_token=token)).status_code == 303
    with client.session_transaction() as sess:
        assert sess["workspace_id"] == wid
    assert client.post("/demo",data=dict(csrf_token=token,reset="1")).status_code == 303
    with client.session_transaction() as sess:
        assert sess["workspace_id"] != wid
    assert db.one("SELECT id FROM workspaces WHERE id=?",(wid,))  # retained until expiry cleanup


def test_stored_html_is_escaped_in_all_surfaces(db,workspace,client):
    token = session_for(client,workspace)
    org,c = related(db,workspace,"<script>alert('org')</script>")
    rid = opportunity(db,workspace,org,c,title="<img src=x onerror=alert(1)>")
    client.post(f"/opportunities/{rid}/activity",data=dict(csrf_token=token,body="<script>alert('note')</script>"))
    for path in ["/organisations","/opportunities",f"/opportunities/{rid}",f"/opportunities/{rid}/edit"]:
        response = client.get(path)
        assert response.status_code == 200
        assert b"<script>alert" not in response.data and b"<img src=x" not in response.data
        assert b"&lt;" in response.data


def test_public_overview_and_session_security(client,app):
    response = client.get("/")
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert client.get("/dashboard").status_code == 303
    wid,token = start_demo(client)
    # A signed cookie cannot be forged by changing its payload.
    client.set_cookie("session","forged-workspace-id")
    assert client.get("/dashboard").status_code == 303


@pytest.mark.parametrize("config",[
    {"DATABASE_URL":"sqlite:///:memory:","SECRET_KEY":"x"*64},
    {"DATABASE_URL":"postgresql://example.invalid/db","SECRET_KEY":"short"},
    {"DATABASE_URL":"postgresql://example.invalid/db","SECRET_KEY":None},
])
def test_production_rejects_ephemeral_db_and_missing_secrets(config):
    with pytest.raises(RuntimeError):
        create_app(dict(PRODUCTION=True,**config))


def test_failed_multi_statement_command_rolls_back(db,workspace,monkeypatch):
    org,c = related(db,workspace)
    original = s.audit
    def fail_audit(*args,**kwargs):
        raise RuntimeError("simulated storage failure")
    monkeypatch.setattr(s,"audit",fail_audit)
    with pytest.raises(RuntimeError,match="simulated"):
        opportunity(db,workspace,org,c)
    monkeypatch.setattr(s,"audit",original)
    assert db.one("SELECT COUNT(*) AS n FROM opportunities WHERE workspace_id=?",(workspace,))["n"] == 0


def test_search_payload_stays_data(db,workspace,client):
    session_for(client,workspace)
    org,c = related(db,workspace)
    opportunity(db,workspace,org,c)
    assert s.opportunity_list(db,workspace,{"q":"' OR 1=1 --"}) == []
    assert client.get("/opportunities?stage=';DROP%20TABLE%20opportunities;--").status_code == 200
    assert s.report(db,workspace)["total"] == 1
