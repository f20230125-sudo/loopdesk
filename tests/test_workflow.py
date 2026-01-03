import csv
import io
import re
import sqlite3
import psycopg
from datetime import datetime, timezone

import pytest

from loopdesk import create_app
from loopdesk import services as s
from loopdesk.db import Database, migrate
from conftest import session_for, start_demo


def related(db, wid, name="Fixture Organisation"):
    org = s.save_organisation(db, wid, dict(name=name, sector="Electronics", city="Dubai"))
    contact = s.save_contact(db, wid, dict(name="Alex Example", email="alex@example.com", role="Coordinator", organisation_id=org))
    return org, contact


def opportunity(db, wid, org, contact, **kwargs):
    data = dict(title="Battery collection enquiry", organisation_id=org, contact_id=contact,
                owner="Alex (demo)", stage="New", service="Battery recycling", value="", next_action="Confirm the collection location")
    data.update(kwargs)
    return s.save_opportunity(db, wid, data)


def form_version(response):
    return re.search(rb'name="version" value="(\d+)"', response.data)[1].decode()


def test_enquiry_to_outcome_and_csv_via_http(client, db, workspace):
    token = session_for(client, workspace)
    assert client.post("/organisations/new", data=dict(csrf_token=token,name="Demo Acacia",sector="Solar",city="Dubai")).status_code == 303
    org = db.one("SELECT * FROM organisations WHERE workspace_id=?", (workspace,))["id"]
    assert client.post("/contacts/new", data=dict(csrf_token=token,name="Sam Example",email="sam@example.com",role="Operations",organisation_id=org)).status_code == 303
    contact = db.one("SELECT * FROM contacts WHERE workspace_id=?", (workspace,))["id"]
    data = dict(csrf_token=token,title="Solar battery enquiry",organisation_id=org,contact_id=contact,
                owner="Sam (demo)",stage="New",service="Battery recycling",value="1250.55",next_action="Arrange a call")
    response = client.post("/opportunities/new", data=data)
    assert response.status_code == 303
    location = response.headers["Location"]
    rid = location.rsplit("/", 1)[1]
    assert client.post(location + "/tasks", data=dict(csrf_token=token,title="Call the coordinator",due_date="2020-01-01")).status_code == 303
    assert client.post(location + "/activity", data=dict(csrf_token=token,body="Confirmed the collection address.")).status_code == 303
    assert b"Confirmed the collection address." in client.get(location).data
    assert b"Call the coordinator" in client.get("/follow-ups?status=overdue").data
    data.update(stage="Proposal", version=form_version(client.get(location + "/edit")))
    assert client.post(location + "/edit", data=data).status_code == 303
    data.update(stage="Won", version=form_version(client.get(location + "/edit")))
    assert client.post(location + "/edit", data=data).status_code == 303
    assert s.report(db, workspace)["won_known"] == 125055
    assert s.report(db, workspace)["open"] == 0
    events = db.all("SELECT from_stage,to_stage FROM stage_events WHERE workspace_id=? AND opportunity_id=? ORDER BY created_at", (workspace, rid))
    assert [(e["from_stage"], e["to_stage"]) for e in events] == [(None,"New"),("New","Proposal"),("Proposal","Won")]
    response = client.get("/opportunities.csv?stage=Won&q=Solar")
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.data.decode("utf-8-sig"))))
    assert len(rows) == 2 and rows[1][5:7] == ["Won", "1250.55"]
    task = db.one("SELECT * FROM tasks WHERE workspace_id=?", (workspace,))
    assert client.post(f"/tasks/{task['id']}/complete", data=dict(csrf_token=token,version=task["version"])).status_code == 303
    assert s.report(db, workspace)["overdue"] == 0
    assert b"AED 1,250.55" in client.get("/reports").data


def test_seed_relationships_and_reports_reconcile(db):
    wid = s.create_workspace(db)
    assert db.one("SELECT COUNT(*) AS n FROM organisations WHERE workspace_id=?", (wid,))["n"] == 30
    assert db.one("SELECT COUNT(*) AS n FROM contacts WHERE workspace_id=?", (wid,))["n"] == 30
    r = s.report(db,wid)
    assert (r["total"],r["open"]) == (36,24)
    assert r["by_stage"] == {stage:6 for stage in s.STAGES}
    assert sum(r["by_service"].values()) == 24
    assert r["by_service"] == {service:8 for service in s.SERVICES}
    expected = db.one("SELECT SUM(value_minor) AS n FROM opportunities WHERE workspace_id=? AND stage='Won'", (wid,))["n"]
    assert r["won_known"] == expected
    assert all(".example.com" in c["email"] for c in db.all("SELECT email FROM contacts WHERE workspace_id=?", (wid,)))


def test_dashboard_empty_and_unknown_values(db, workspace, client):
    session_for(client, workspace)
    r = s.report(db,workspace)
    assert r["total"] == r["open"] == r["won_known"] == r["overdue"] == 0
    assert client.get("/dashboard").status_code == 200
    assert b"No opportunities in this view" in client.get("/opportunities").data
    org,c = related(db,workspace)
    opportunity(db,workspace,org,c,stage="Won")
    opportunity(db,workspace,org,c,stage="Won",value="0")
    opportunity(db,workspace,org,c,stage="Won",value="15.20")
    opportunity(db,workspace,org,c,stage="Lost",value="999")
    r = s.report(db,workspace)
    assert (r["won_known"],r["won_unknown"],r["by_stage"]["Won"],r["by_stage"]["Lost"]) == (1520,1,3,1)


def test_dubai_midnight_boundary(db,workspace):
    org,c = related(db,workspace)
    rid = opportunity(db,workspace,org,c)
    s.add_task(db,workspace,rid,dict(title="Previous day",due_date="2026-10-23"))
    s.add_task(db,workspace,rid,dict(title="Midnight boundary",due_date="2026-10-24"))
    r = s.report(db,workspace,datetime(2026,10,24,19,59,59,tzinfo=timezone.utc))
    assert (r["date"],r["overdue"],r["today"]) == ("2026-10-24",1,1)
    r = s.report(db,workspace,datetime(2026,10,24,20,0,0,tzinfo=timezone.utc))
    assert (r["date"],r["overdue"],r["today"]) == ("2026-10-25",2,0)


@pytest.mark.parametrize("value", ["-1","1.001","NaN","Infinity","1e100000","not-a-number","10000000000"])
def test_invalid_amount_rejected_without_partial_writes(db,workspace,value):
    org,c = related(db,workspace)
    with pytest.raises(s.ValidationError, match="non-negative"):
        opportunity(db,workspace,org,c,value=value)
    assert db.one("SELECT COUNT(*) AS n FROM opportunities WHERE workspace_id=?",(workspace,))["n"] == 0
    assert db.one("SELECT COUNT(*) AS n FROM stage_events WHERE workspace_id=?",(workspace,))["n"] == 0


@pytest.mark.parametrize("field,value",[("title",""),("next_action",""),("owner",""),("stage","Pending"),("service","Scrap"),("title","a"*161)])
def test_invalid_opportunity_fields(db,workspace,field,value):
    org,c = related(db,workspace)
    with pytest.raises(s.ValidationError):
        opportunity(db,workspace,org,c,**{field:value})


def test_invalid_relationship_rejected_in_service_and_database(db,workspace):
    org,c = related(db,workspace)
    second,c2 = related(db,workspace,"Second organisation")
    with pytest.raises(s.ValidationError, match="belonging"):
        opportunity(db,workspace,org,c2)
    rid = opportunity(db,workspace,org,c)
    with pytest.raises((sqlite3.IntegrityError, psycopg.IntegrityError)):
        with db.transaction():
            db.execute("UPDATE opportunities SET contact_id=? WHERE workspace_id=? AND id=?",(c2,workspace,rid))
    with pytest.raises(s.ValidationError, match="linked opportunities"):
        s.save_contact(db,workspace,dict(name="Alex",email="alex@example.com",role="Coordinator",organisation_id=second,version=1),c)


def test_stale_update_rolls_back_stage_and_audit(db,workspace,client):
    token = session_for(client,workspace)
    org,c = related(db,workspace)
    rid = opportunity(db,workspace,org,c)
    data = dict(csrf_token=token,title="Updated title",organisation_id=org,contact_id=c,owner="Alex",stage="Qualified",service="Battery recycling",value="12.50",next_action="Call",version=1)
    assert client.post(f"/opportunities/{rid}/edit",data=data).status_code == 303
    before = db.one("SELECT COUNT(*) AS n FROM activities WHERE workspace_id=?",(workspace,))["n"]
    data.update(stage="Won",title="Stale title")
    response = client.post(f"/opportunities/{rid}/edit",data=data)
    assert response.status_code == 409 and b"Reload" in response.data
    row = s.record(db,"opportunities",workspace,rid)
    assert (row["title"],row["stage"],row["version"]) == ("Updated title","Qualified",2)
    assert db.one("SELECT COUNT(*) AS n FROM activities WHERE workspace_id=?",(workspace,))["n"] == before
    assert db.one("SELECT COUNT(*) AS n FROM stage_events WHERE workspace_id=?",(workspace,))["n"] == 2


@pytest.mark.parametrize("kind",["organisations","contacts","tasks"])
def test_other_stale_commands_are_rejected(db,workspace,client,kind):
    token = session_for(client,workspace)
    org,c = related(db,workspace)
    if kind == "tasks":
        rid = opportunity(db,workspace,org,c)
        target = s.add_task(db,workspace,rid,dict(title="Call",due_date="2026-10-25"))
        url = f"/tasks/{target}/complete"
    else:
        target = org if kind == "organisations" else c
        url = f"/{kind}/{target}/archive"
    assert client.post(url,data=dict(csrf_token=token,version=1)).status_code == 303
    assert client.post(url,data=dict(csrf_token=token,version=1)).status_code == 409


def test_archives_preserve_history_and_exclude_new_links(db,workspace):
    org,c = related(db,workspace)
    rid = opportunity(db,workspace,org,c)
    s.archive(db,"contacts",workspace,c,1)
    s.archive(db,"organisations",workspace,org,1)
    assert s.record(db,"opportunities",workspace,rid)["contact_id"] == c
    assert s.report(db,workspace)["open"] == 1
    with pytest.raises(s.ValidationError,match="active"):
        opportunity(db,workspace,org,c)
    s.archive(db,"contacts",workspace,c,2)
    s.archive(db,"organisations",workspace,org,2)
    assert opportunity(db,workspace,org,c)


def test_data_persists_after_app_and_connection_restart(app):
    db = Database(app.config["DATABASE_URL"], app.config.get("DATABASE_SCHEMA"))
    wid = s.create_workspace(db,seed=False)
    org,c = related(db,wid)
    rid = opportunity(db,wid,org,c,value="42.01")
    db.close()
    restarted = create_app(dict(TESTING=True,PRODUCTION=False,SECRET_KEY=app.config["SECRET_KEY"],DATABASE_URL=app.config["DATABASE_URL"],DATABASE_SCHEMA=app.config.get("DATABASE_SCHEMA")))
    from loopdesk.db import get_db
    with restarted.app_context():
        assert s.record(get_db(),"opportunities",wid,rid)["value_minor"] == 4201


def test_migrations_are_idempotent(db):
    migrate(db)
    migrate(db)
    assert db.all("SELECT version FROM schema_migrations ORDER BY version") == [
        {"version": "001_initial"}, {"version": "002_scopedesk"}, {"version": "003_security"},
        {"version": "004_session_revocation"}, {"version": "005_followdesk"}, {"version": "006_csv_import"}]


def test_filter_export_matches_visible_rows_including_literal_wildcards(db,workspace,client):
    session_for(client,workspace)
    org,c = related(db,workspace)
    for title,stage,service,owner in [("100% collection","New","Battery recycling","Alex"),("100_ collection","Won","E-waste","Sam"),("Other enquiry","Proposal","Battery recycling","Alex")]:
        opportunity(db,workspace,org,c,title=title,stage=stage,service=service,owner=owner)
    for filters,expected in [({"q":"%"},1),({"q":"_"},1),({"stage":"Won"},1),({"service":"Battery recycling","owner":"Alex"},2),({"q":"no match"},0)]:
        from urllib.parse import urlencode
        rows = list(csv.reader(io.StringIO(client.get("/opportunities.csv?"+urlencode(filters)).data.decode("utf-8-sig"))))
        assert len(rows)-1 == expected
        assert len(s.opportunity_list(db,workspace,filters)) == expected


@pytest.mark.parametrize("prefix",["=1+1","+SUM(A1)","-2+3","@SUM(A1)","  =1+1","\t=1+1","\r=1+1","\n=1+1"])
def test_export_neutralises_spreadsheet_formulas(prefix):
    row = dict(title=prefix,organisation_name="Normal",contact_name="Alex",service="E-waste",owner="Sam",stage="New",value_minor=None,next_action="Call")
    exported = list(csv.reader(io.StringIO(s.csv_export([row]).removeprefix("\ufeff"))))
    assert exported[1][0] == "'"+prefix
    assert exported[1][6] == ""
