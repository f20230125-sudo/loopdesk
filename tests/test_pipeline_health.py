from datetime import datetime, timedelta, timezone

from conftest import session_for
from loopdesk import services as s
from test_workflow import related, opportunity

NOW = datetime(2026, 10, 27, 8, tzinfo=timezone.utc)


def time_at(days):
    return (NOW - timedelta(days=days)).isoformat()


def history(db, wid, rid, created, entered=None, activity=None):
    with db.transaction():
        db.execute("UPDATE opportunities SET created_at=? WHERE workspace_id=? AND id=?", (created, wid, rid))
        db.execute("DELETE FROM stage_events WHERE workspace_id=? AND opportunity_id=?", (wid, rid))
        db.execute("DELETE FROM activities WHERE workspace_id=? AND opportunity_id=?", (wid, rid))
        if entered is not None:
            row = s.record(db, "opportunities", wid, rid)
            db.execute("INSERT INTO stage_events VALUES (?,?,?,?,?,?)", (s.uid(), wid, rid, "New", row["stage"], entered))
        if activity is not None:
            db.execute("INSERT INTO activities(id,workspace_id,opportunity_id,entity_type,entity_id,kind,body,created_at) VALUES (?,?,?,?,?,?,?,?)", (s.uid(), wid, rid, "opportunity", rid, "edit", "Updated", activity))


def test_health_hand_computed_stale_stage_average_and_changes(db, workspace):
    org, contact = related(db, workspace)
    a = opportunity(db, workspace, org, contact, title="Old new")
    b = opportunity(db, workspace, org, contact, title="Recent note", stage="Contacted")
    c = opportunity(db, workspace, org, contact, title="Exactly fourteen", stage="Contacted")
    closed = opportunity(db, workspace, org, contact, title="Closed", stage="Lost")
    history(db, workspace, a, time_at(40))
    history(db, workspace, b, time_at(40), time_at(20), time_at(2))
    history(db, workspace, c, time_at(30), time_at(14), time_at(14))
    history(db, workspace, closed, time_at(45), time_at(10))
    health = s.report(db, workspace, NOW)["health"]
    assert [(row["id"], row["days"]) for row in health["stale"]] == [(a, 40), (c, 14)]
    assert health["average_stage_days"] == dict(New=40.0, Contacted=17.0, Qualified=None, Proposal=None)
    assert health["changes"] == dict(New=0, Contacted=2, Qualified=0, Proposal=0, Won=0, Lost=1)
    assert health["stale_days"] == s.STALE_DAYS == 14
    assert health["stale_count"] == 2 and health["stale_unknown"] == 0


def test_stale_threshold_boundary_order_limit_and_recent_edit(db, workspace):
    org, contact = related(db, workspace)
    ids = []
    for index in range(12):
        rid = opportunity(db, workspace, org, contact, title=f"Old {index:02}")
        history(db, workspace, rid, time_at(45 - index))
        ids.append(rid)
    recent = opportunity(db, workspace, org, contact)
    history(db, workspace, recent, time_at(40), activity=(NOW - timedelta(days=14) + timedelta(seconds=1)).isoformat())
    health = s.report(db, workspace, NOW)["health"]
    assert health["stale_count"] == 12
    assert [row["id"] for row in health["stale"]] == ids[:10]


def test_latest_stage_event_and_creation_fallback(db, workspace):
    org, contact = related(db, workspace)
    rid = opportunity(db, workspace, org, contact, stage="Qualified")
    history(db, workspace, rid, time_at(45), time_at(3.5))
    with db.transaction():
        db.execute("INSERT INTO stage_events VALUES (?,?,?,?,?,?)", (s.uid(), workspace, rid, "New", "Contacted", time_at(20)))
    assert s.report(db, workspace, NOW)["health"]["average_stage_days"]["Qualified"] == 3.5
    with db.transaction():
        db.execute("DELETE FROM stage_events WHERE workspace_id=?", (workspace,))
    assert s.report(db, workspace, NOW)["health"]["average_stage_days"]["Qualified"] == 45.0


def test_unknown_dates_and_legacy_completion_attribution(db, workspace, client):
    org, contact = related(db, workspace)
    rid = opportunity(db, workspace, org, contact)
    history(db, workspace, rid, "unknown", "unknown")
    with db.transaction():
        db.execute("INSERT INTO activities(id,workspace_id,entity_type,entity_id,kind,body,created_at) VALUES (?,?,?,?,?,?,?)", (s.uid(), workspace, "opportunity", rid, "task", "Follow-up completed: Legacy", NOW.isoformat()))
    health = s.report(db, workspace, NOW)["health"]
    assert health["average_stage_days"]["New"] is None
    assert health["stale_count"] == 0 and health["stale_unknown"] == 1
    assert health["changes_unknown"] == 1 and health["completions_unknown"] == 1
    session_for(client, workspace)
    assert b"unknown task attribution" in client.get("/reports").data


def test_completion_distinct_tasks_with_same_titles_reopen_and_due_window(db, workspace, monkeypatch):
    monkeypatch.setattr(s, "utcnow", lambda: NOW)
    org, contact = related(db, workspace)
    rid = opportunity(db, workspace, org, contact)
    a = s.add_task(db, workspace, rid, dict(title="Same title", due_date="2026-09-28"))
    b = s.add_task(db, workspace, rid, dict(title="Same title", due_date="2026-10-27"))
    s.add_task(db, workspace, rid, dict(title="Outside", due_date="2026-09-27"))
    s.add_task(db, workspace, rid, dict(title="Future", due_date="2026-10-28"))
    s.complete_task(db, workspace, a, 1)
    s.complete_task(db, workspace, a, 2)
    s.complete_task(db, workspace, a, 3)
    s.complete_task(db, workspace, b, 1)
    health = s.report(db, workspace, NOW)["health"]
    assert health["completed"] == health["due"] == 2
    assert health["completions_unknown"] == 0
    assert db.one("SELECT COUNT(*) AS n FROM activities WHERE workspace_id=? AND kind='task_completed'", (workspace,))["n"] == 3


def test_dubai_midnight_windows_completion_and_stage_changes(db, workspace):
    org, contact = related(db, workspace)
    rid = opportunity(db, workspace, org, contact)
    history(db, workspace, rid, "2026-08-01T00:00:00+00:00")
    with db.transaction():
        for at in ("2026-09-27T19:59:59+00:00", "2026-09-27T20:00:00+00:00", "2026-10-27T20:00:00+00:00"):
            db.execute("INSERT INTO stage_events VALUES (?,?,?,?,?,?)", (s.uid(), workspace, rid, "Contacted", "New", at))
            db.execute("INSERT INTO activities(id,workspace_id,opportunity_id,entity_type,entity_id,kind,body,created_at) VALUES (?,?,?,?,?,?,?,?)", (s.uid(), workspace, rid, "task", s.uid(), "task_completed", "Completed", at))
        for due in ("2026-09-27", "2026-09-28", "2026-10-27", "2026-10-28"):
            s.insert(db, "tasks", dict(id=s.uid(), workspace_id=workspace, opportunity_id=rid, title="Boundary", due_date=due))
    before = s.report(db, workspace, datetime(2026, 10, 27, 19, 59, 59, tzinfo=timezone.utc))["health"]
    after = s.report(db, workspace, datetime(2026, 10, 27, 20, tzinfo=timezone.utc))["health"]
    assert before["window_start"] == "2026-09-28" and before["due"] == 2
    assert after["window_start"] == "2026-09-29" and after["due"] == 2
    assert before["changes"]["New"] == before["completed"] == 1
    assert after["changes"]["New"] == after["completed"] == 1


def test_empty_health_and_cross_workspace_exclusion(db, workspace, client):
    other = s.create_workspace(db)
    health = s.report(db, workspace, NOW)["health"]
    assert health["stale"] == [] and health["stale_count"] == 0
    assert all(value is None for value in health["average_stage_days"].values())
    assert sum(health["changes"].values()) == health["completed"] == health["due"] == 0
    session_for(client, workspace)
    page = client.get("/reports")
    assert page.status_code == 200 and b"Unknown" in page.data and b"Cedar Circuit" not in page.data
    assert s.report(db, other)["total"] == 36


def test_seed_history_is_deterministic_relative_and_totals_unchanged(db, monkeypatch):
    monkeypatch.setattr(s, "utcnow", lambda: NOW)
    wid = s.create_workspace(db)
    second = s.create_workspace(db)
    for table, total in (("organisations", 30), ("contacts", 30), ("opportunities", 36), ("tasks", 24)):
        assert db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE workspace_id=?", (wid,))["n"] == total
    health = s.report(db, wid, NOW)["health"]
    assert health == {**s.report(db, second, NOW)["health"], "stale": health["stale"]}
    assert health["stale_count"] > 0 and sum(health["changes"].values()) > 0
    times = [s.parsed_time(row["created_at"]) for row in db.all("SELECT created_at FROM stage_events WHERE workspace_id=?", (wid,))]
    assert min(times) == NOW - timedelta(days=45) and max(times) <= NOW
    assert s.report(db, wid, NOW)["by_stage"] == {stage: 6 for stage in s.STAGES}
