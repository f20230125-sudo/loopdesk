"""Workspace-scoped commands, validation, optimistic locking and report formulas."""
import csv
import io
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from werkzeug.exceptions import NotFound
from .security import positive_integer, quota

STAGES = ("New", "Contacted", "Qualified", "Proposal", "Won", "Lost")
SERVICES = ("Battery recycling", "E-waste", "IT asset disposition")
OWNERS = ("Maya (demo)", "Omar (demo)", "Leena (demo)")
TABLES = {"organisations", "contacts", "opportunities", "tasks"}


class ValidationError(ValueError):
    pass


class Conflict(ValidationError):
    pass


def uid():
    return uuid.uuid4().hex


def utcnow():
    return datetime.now(timezone.utc)


def stamp():
    return utcnow().isoformat()


def dubai_today(now=None):
    return (now or utcnow()).astimezone(ZoneInfo("Asia/Dubai")).date()


def text_field(data, key, label, limit=160, required=True):
    value = str(data.get(key, "")).strip()
    if required and not value:
        raise ValidationError(f"{label} is required.")
    if len(value) > limit:
        raise ValidationError(f"{label} must be {limit} characters or fewer.")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValidationError(f"{label} contains unsupported control characters.")
    return value


def money_minor(raw):
    if not str(raw).strip():
        return None
    try:
        amount = Decimal(str(raw).strip())
        if not amount.is_finite() or amount < 0 or amount > Decimal("9999999999.99"):
            raise InvalidOperation
        if amount != amount.quantize(Decimal("0.01")):
            raise InvalidOperation
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValidationError("Estimated value must be a non-negative AED amount with at most two decimals (maximum 9,999,999,999.99).") from None


def record(db, table, wid, rid):
    if table not in TABLES:
        raise ValueError("Unsupported table")
    row = db.one(f"SELECT * FROM {table} WHERE workspace_id=? AND id=?", (wid, rid))
    if not row:
        raise NotFound("This record is not available in your workspace.")
    return row


def audit(db, wid, entity_type, entity_id, body, opportunity_id=None, kind="edit"):
    quota(db,"activities",wid,1500)
    db.execute("INSERT INTO activities(id,workspace_id,opportunity_id,entity_type,entity_id,kind,body,created_at) VALUES (?,?,?,?,?,?,?,?)",
               (uid(), wid, opportunity_id, entity_type, entity_id, kind, body, stamp()))


def insert(db, table, fields):
    if table not in TABLES:
        raise ValueError("Unsupported table")
    quota(db,table,fields["workspace_id"],{"organisations":100,"contacts":200,"opportunities":150,"tasks":300}[table])
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(fields.values()))


def checked_update(db, table, wid, rid, version, fields):
    if table not in TABLES:
        raise ValueError("Unsupported table")
    version = positive_integer(version)
    if version is None:
        raise Conflict("This form has no valid version. Reload the page and try again.")
    result = db.execute(f"UPDATE {table} SET {','.join(k+'=?' for k in fields)},version=version+1 WHERE workspace_id=? AND id=? AND version=?",
                        (*fields.values(), wid, rid, version))
    if result.rowcount != 1:
        raise Conflict("Someone changed this record after you opened it. Reload the page before saving again.")


def save_organisation(db, wid, data, rid=None):
    fields = {k: text_field(data, k, label, limit, required) for k, label, limit, required in (
        ("name", "Organisation name", 160, True), ("sector", "Sector", 100, True), ("city", "City", 100, True))}
    with db.transaction():
        if rid:
            before = record(db, "organisations", wid, rid)
            checked_update(db, "organisations", wid, rid, data.get("version"), fields)
            audit(db, wid, "organisation", rid, f"Organisation updated: {before['name']} → {fields['name']}.")
        else:
            rid = uid()
            insert(db, "organisations", dict(id=rid, workspace_id=wid, **fields))
            audit(db, wid, "organisation", rid, "Organisation created.", kind="created")
    return rid


def save_contact(db, wid, data, rid=None):
    fields = {k: text_field(data, k, label, limit, required) for k, label, limit, required in (
        ("name", "Contact name", 160, True), ("email", "Email", 254, True), ("role", "Role", 100, True))}
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", fields["email"]):
        raise ValidationError("Enter a valid email address, such as alex@example.com.")
    org = record(db, "organisations", wid, data.get("organisation_id", ""))
    fields["organisation_id"] = org["id"]
    with db.transaction():
        before = record(db, "contacts", wid, rid) if rid else None
        if org["archived"] and (not before or before["organisation_id"] != org["id"]):
            raise ValidationError("Restore the organisation before adding or moving a contact.")
        if before and before["organisation_id"] != org["id"] and db.one("SELECT id FROM opportunities WHERE workspace_id=? AND contact_id=?", (wid, rid)):
            raise ValidationError("This contact has linked opportunities. Keep its organisation or create a new contact.")
        if rid:
            checked_update(db, "contacts", wid, rid, data.get("version"), fields)
            audit(db, wid, "contact", rid, "Contact details updated.")
        else:
            rid = uid()
            insert(db, "contacts", dict(id=rid, workspace_id=wid, **fields))
            audit(db, wid, "contact", rid, "Contact created.", kind="created")
    return rid


def archive(db, table, wid, rid, version):
    if table not in {"organisations", "contacts"}:
        raise ValueError("Only organisations and contacts can be archived")
    with db.transaction():
        row = record(db, table, wid, rid)
        archived = 1 - row["archived"]
        checked_update(db, table, wid, rid, version, {"archived": archived})
        audit(db, wid, table[:-1] if table == "contacts" else "organisation", rid, "Archived." if archived else "Restored.", kind="archive")


def save_opportunity(db, wid, data, rid=None):
    fields = {k: text_field(data, k, label, limit, True) for k, label, limit in (
        ("title", "Opportunity title", 160), ("next_action", "Next action", 500), ("owner", "Owner", 100))}
    fields["stage"] = data.get("stage", "New")
    fields["service"] = data.get("service", "")
    if fields["stage"] not in STAGES or fields["service"] not in SERVICES:
        raise ValidationError("Choose a listed stage and service category.")
    fields["value_minor"] = money_minor(data.get("value", ""))
    org = record(db, "organisations", wid, data.get("organisation_id", ""))
    contact = record(db, "contacts", wid, data.get("contact_id", ""))
    if contact["organisation_id"] != org["id"]:
        raise ValidationError("Choose a contact belonging to the selected organisation.")
    fields.update(organisation_id=org["id"], contact_id=contact["id"])
    with db.transaction():
        before = record(db, "opportunities", wid, rid) if rid else None
        if (org["archived"] or contact["archived"]) and (not before or before["organisation_id"] != org["id"] or before["contact_id"] != contact["id"]):
            raise ValidationError("Choose an active organisation and contact, or restore them first.")
        previous = before["stage"] if before else None
        if rid:
            checked_update(db, "opportunities", wid, rid, data.get("version"), fields)
            changed = [key.replace('_', ' ') for key in fields if fields[key] != before[key]]
            audit(db, wid, "opportunity", rid, "Updated: " + (", ".join(changed) or "reviewed without field changes") + ".", rid)
        else:
            rid = uid()
            insert(db, "opportunities", dict(id=rid, workspace_id=wid, created_at=stamp(), **fields))
            audit(db, wid, "opportunity", rid, "Enquiry added to the pipeline.", rid, kind="created")
        if previous != fields["stage"]:
            db.execute("INSERT INTO stage_events(id,workspace_id,opportunity_id,from_stage,to_stage,created_at) VALUES (?,?,?,?,?,?)",
                       (uid(), wid, rid, previous, fields["stage"], stamp()))
            audit(db, wid, "opportunity", rid, f"Stage: {previous or 'Enquiry'} → {fields['stage']}.", rid, "stage")
    return rid


def add_activity(db, wid, rid, data):
    record(db, "opportunities", wid, rid)
    body = text_field(data, "body", "Activity note", 2000)
    with db.transaction():
        audit(db, wid, "opportunity", rid, body, rid, "note")


def add_task(db, wid, rid, data):
    record(db, "opportunities", wid, rid)
    title = text_field(data, "title", "Follow-up title", 160)
    try:
        due = datetime.strptime(data.get("due_date", ""), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValidationError("Choose a valid follow-up date.") from None
    task_id = uid()
    with db.transaction():
        insert(db, "tasks", dict(id=task_id, workspace_id=wid, opportunity_id=rid, title=title, due_date=due))
        audit(db, wid, "opportunity", rid, f"Follow-up scheduled for {due}: {title}", rid, "task")
    return task_id


def complete_task(db, wid, rid, version):
    with db.transaction():
        row = record(db, "tasks", wid, rid)
        checked_update(db, "tasks", wid, rid, version, {"completed": 1 - row["completed"]})
        audit(db, wid, "opportunity", row["opportunity_id"], f"Follow-up {'reopened' if row['completed'] else 'completed'}: {row['title']}", row["opportunity_id"], "task")


def opportunity_list(db, wid, filters):
    sql = """SELECT o.*, g.name AS organisation_name, c.name AS contact_name
             FROM opportunities o JOIN organisations g ON g.workspace_id=o.workspace_id AND g.id=o.organisation_id
             JOIN contacts c ON c.workspace_id=o.workspace_id AND c.id=o.contact_id WHERE o.workspace_id=?"""
    args = [wid]
    q = filters.get("q", "").strip()[:160]
    if q:
        sql += " AND (LOWER(o.title) LIKE ? ESCAPE '!' OR LOWER(g.name) LIKE ? ESCAPE '!' OR LOWER(c.name) LIKE ? ESCAPE '!')"
        term = "%" + q.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        args.extend([term] * 3)
    for key in ("stage", "service", "owner"):
        if filters.get(key):
            sql += f" AND o.{key}=?"
            args.append(filters[key])
    sql += " ORDER BY o.created_at DESC,o.title,o.id"
    return db.all(sql, args)


def task_list(db, wid, status="open"):
    rows = db.all("""SELECT t.*,o.title AS opportunity_title,o.owner,g.name AS organisation_name
        FROM tasks t JOIN opportunities o ON o.workspace_id=t.workspace_id AND o.id=t.opportunity_id
        JOIN organisations g ON g.workspace_id=o.workspace_id AND g.id=o.organisation_id
        WHERE t.workspace_id=? ORDER BY t.due_date,t.title,t.id""", (wid,))
    today = dubai_today().isoformat()
    if status == "overdue":
        return [r for r in rows if not r["completed"] and r["due_date"] < today]
    if status == "today":
        return [r for r in rows if not r["completed"] and r["due_date"] == today]
    if status == "completed":
        return [r for r in rows if r["completed"]]
    return [r for r in rows if not r["completed"]]


def report(db, wid, now=None):
    rows = opportunity_list(db, wid, {})
    open_rows = [r for r in rows if r["stage"] not in ("Won", "Lost")]
    tasks = db.all("SELECT * FROM tasks WHERE workspace_id=?", (wid,))
    today = dubai_today(now).isoformat()
    won = [r for r in rows if r["stage"] == "Won"]
    return dict(total=len(rows), open=len(open_rows),
                by_stage={s: sum(r["stage"] == s for r in rows) for s in STAGES},
                by_service={s: sum(r["service"] == s for r in open_rows) for s in SERVICES},
                overdue=sum(not t["completed"] and t["due_date"] < today for t in tasks),
                today=sum(not t["completed"] and t["due_date"] == today for t in tasks),
                won_known=sum(r["value_minor"] for r in won if r["value_minor"] is not None),
                won_unknown=sum(r["value_minor"] is None for r in won),
                open_known=sum(r["value_minor"] for r in open_rows if r["value_minor"] is not None),
                open_unknown=sum(r["value_minor"] is None for r in open_rows),
                date=today)


def csv_export(rows):
    def safe(value):
        value = str(value)
        if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
            return "'" + value
        return value
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["Opportunity", "Organisation", "Contact", "Service", "Owner", "Stage", "Estimated value (AED)", "Next action"])
    for r in rows:
        amount = "" if r["value_minor"] is None else f"{Decimal(r['value_minor']) / 100:.2f}"
        writer.writerow([safe(r[k]) for k in ("title", "organisation_name", "contact_name", "service", "owner", "stage")] + [amount, safe(r["next_action"])])
    return "\ufeff" + buffer.getvalue()


def create_workspace(db, seed=True):
    now = utcnow()
    wid = uid()
    with db.transaction():
        db.execute("DELETE FROM workspaces WHERE expires_at<=?", (now.isoformat(),))
        count = db.one("SELECT COUNT(*) AS n FROM workspaces")["n"]
        if count >= 250:
            raise ValidationError("The demo is at capacity. Please try again after older workspaces expire.")
        db.execute("INSERT INTO workspaces(id,created_at,expires_at) VALUES (?,?,?)", (wid, now.isoformat(), (now + timedelta(hours=24)).isoformat()))
        if seed:
            from .seed import seed_workspace
            seed_workspace(db, wid)
    return wid
