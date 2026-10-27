"""Bounded CSV parsing and reviewed, single-use organisation/contact imports."""
import csv
import io
import json
import re

from flask import Blueprint, Response, g, redirect, render_template, request, url_for
from werkzeug.exceptions import NotFound, TooManyRequests

from . import services as s
from .db import get_db
from .security import _lock_workspace, positive_integer

bp = Blueprint("csv_import", __name__)
MAX_BYTES = 256 * 1024
MAX_ROWS = 500
MAX_COLUMNS = 20
MAX_CELL_BYTES = 2 * 1024
FIELDS = (("organisation", "Organisation name"), ("sector", "Sector"), ("city", "City"),
          ("contact", "Contact name"), ("email", "Email"), ("role", "Role"))
ALIASES = {"organisation": {"organisation", "organization", "organisation name", "organization name", "company", "company name"},
           "sector": {"sector", "industry"}, "city": {"city", "town"},
           "contact": {"contact", "contact name", "full name", "person"},
           "email": {"email", "email address", "e-mail"}, "role": {"role", "job title", "position"}}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_csv(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise s.ValidationError("Choose a UTF-8 CSV file of 256 KiB or less.")
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise s.ValidationError("CSV encoding is invalid. Save the spreadsheet as UTF-8 CSV and try again.") from None
    reader = csv.reader(io.StringIO(source, newline=""), strict=True)
    try:
        headers = next(reader, [])
        if not headers or len(headers) > MAX_COLUMNS:
            raise s.ValidationError("CSV needs a header row with 1 to 20 columns.")
        normalized = [h.strip().casefold() for h in headers]
        if any(not h for h in normalized) or len(set(normalized)) != len(headers):
            raise s.ValidationError("CSV headers must be non-empty and unique (ignoring case and surrounding spaces).")
        rows = []
        check_cells(headers, 1)
        while True:
            number = reader.line_num + 1
            cells = next(reader, None)
            if cells is None:
                break
            if len(rows) >= MAX_ROWS:
                raise s.ValidationError("CSV must have 500 data rows or fewer, including blank rows.")
            check_cells(cells, number)
            rows.append(dict(number=number, cells=cells))
        if not rows:
            raise s.ValidationError("CSV needs at least one data row after the headers.")
        return dict(headers=headers, rows=rows)
    except csv.Error:
        raise s.ValidationError(f"CSV syntax is invalid near row {reader.line_num}. Check quoting and delimiters.") from None


def check_cells(cells, number):
    if len(cells) > MAX_COLUMNS:
        raise s.ValidationError(f"CSV row {number} exceeds 20 columns.")
    if any(len(cell.encode("utf-8")) > MAX_CELL_BYTES for cell in cells):
        raise s.ValidationError(f"CSV row {number} contains a cell larger than 2 KiB.")
    if any(any(ord(c) < 32 and c not in "\r\n\t" for c in cell) for cell in cells):
        raise s.ValidationError(f"CSV row {number} contains unsupported control characters.")


def upload_preview(db, wid, raw):
    payload = encoded(parse_csv(raw))
    pid = s.uid()
    with db.transaction():
        _lock_workspace(db, wid)
        existing = db.all("SELECT payload FROM csv_previews WHERE workspace_id=?", (wid,))
        if len(existing) >= 10:
            raise TooManyRequests("This demo workspace reached its CSV preview record limit. Start a fresh workspace or wait for expiry.", retry_after=3600)
        if sum(len(row["payload"].encode("utf-8")) for row in existing) + len(payload.encode("utf-8")) > 2 * 1024 * 1024:
            raise TooManyRequests("This demo workspace reached its CSV preview storage limit. Start a fresh workspace or wait for expiry.", retry_after=3600)
        db.execute("INSERT INTO csv_previews(id,workspace_id,payload,created_at) VALUES (?,?,?,?)", (pid, wid, payload, s.stamp()))
    return pid


def get_preview(db, wid, pid):
    if not isinstance(pid, str) or not re.fullmatch(r"[a-f0-9]{32}", pid):
        raise NotFound("CSV preview is not available in this workspace.")
    row = db.one("SELECT * FROM csv_previews WHERE workspace_id=? AND id=?", (wid, pid))
    if not row:
        raise NotFound("CSV preview is not available in this workspace.")
    for field in ("payload", "mapping", "plan", "result"):
        row[field] = json.loads(row[field]) if row[field] else None
    return row


def guess_mapping(headers):
    return {key: next((str(i) for i, h in enumerate(headers) if h.strip().casefold().replace("_", " ") in ALIASES[key]), "") for key, _ in FIELDS}


def validate_mapping(headers, data):
    mapping, used = {}, set()
    for key, label in FIELDS:
        raw = data.get(key, "")
        if raw == "":
            mapping[key] = None
            continue
        # Index zero is valid; bound length before parsing untrusted form values.
        index = positive_integer(raw, MAX_COLUMNS) if raw != "0" else 0
        if index is None or index >= len(headers) or index in used:
            raise s.ValidationError(f"Choose a separate, listed CSV column for {label}.")
        used.add(index)
        mapping[key] = index
    if mapping["organisation"] is None:
        raise s.ValidationError("Map the organisation name column before previewing.")
    return mapping


def build_plan(db, wid, payload, mapping):
    organisations, emails = {}, set()
    for org in db.all("SELECT * FROM organisations WHERE workspace_id=? ORDER BY id", (wid,)):
        organisations.setdefault(org["name"].strip().casefold(), []).append(org)
    for contact in db.all("SELECT email FROM contacts WHERE workspace_id=?", (wid,)):
        emails.add(contact["email"].strip().casefold())
    plan = []
    for source in payload["rows"]:
        row = dict(number=source["number"], organisation="", contact="", actions=[], status="ready")
        cells = source["cells"]
        try:
            if not any(cell.strip() for cell in cells):
                row.update(status="skip", actions=["Skip blank row"])
            elif len(cells) != len(payload["headers"]):
                raise s.ValidationError("Column count does not match the headers.")
            else:
                values = {key: cells[index] if index is not None else "" for key, index in mapping.items()}
                row["organisation"] = name = s.text_field(values, "organisation", "Organisation name")
                row["contact"] = values["contact"].strip()
                has_contact = any(values[key].strip() for key in ("contact", "email", "role"))
                fields = None
                if has_contact:
                    fields = {key: s.text_field(values, key, label, limit) for key, label, limit in (("contact", "Contact name", 160), ("email", "Email", 254), ("role", "Role", 100))}
                    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", fields["email"]):
                        raise s.ValidationError("Enter a valid email address, such as alex@example.com.")
                if fields and fields["email"].casefold() in emails:
                    row.update(status="skip", actions=["Skip duplicate contact email (workspace or earlier CSV row)"])
                else:
                    matches = organisations.get(name.casefold(), [])
                    if len(matches) > 1:
                        raise s.ValidationError("More than one organisation matches this name. Resolve the names before importing.")
                    org = matches[0] if matches else None
                    if org and org["archived"] and fields:
                        raise s.ValidationError("Restore the existing organisation before adding a contact.")
                    if not org:
                        row["new_organisation"] = dict(name=name, sector=s.text_field(values, "sector", "Sector", 100), city=s.text_field(values, "city", "City", 100))
                        org = dict(id="csv-row-" + str(row["number"]), archived=0)
                        row["actions"].append("Create organisation")
                    elif fields:
                        row["actions"].append("Link to existing organisation")
                    else:
                        row.update(status="skip", actions=["Skip duplicate organisation name (workspace or earlier CSV row)"])
                    row["organisation_id"] = org["id"]
                    if fields:
                        row["new_contact"] = dict(name=fields["contact"], email=fields["email"], role=fields["role"])
                        row["actions"].append("Create contact")
                        emails.add(fields["email"].casefold())
                    organisations.setdefault(name.casefold(), [org])
        except s.ValidationError as error:
            row = dict(number=source["number"], organisation=row["organisation"], contact=row["contact"], status="reject", actions=[str(error)])
        plan.append(row)
    return plan


def map_preview(db, wid, pid, data):
    with db.transaction():
        _lock_workspace(db, wid)
        preview = get_preview(db, wid, pid)
        if preview["consumed"]:
            raise s.Conflict("This CSV preview has already been confirmed. Upload a new file to import more records.")
        mapping = validate_mapping(preview["payload"]["headers"], data)
        plan = build_plan(db, wid, preview["payload"], mapping)
        db.execute("UPDATE csv_previews SET mapping=?,plan=? WHERE workspace_id=? AND id=?", (encoded(mapping), encoded(plan), wid, pid))


def confirm(db, wid, pid):
    with db.transaction():
        _lock_workspace(db, wid)
        preview = get_preview(db, wid, pid)
        if preview["consumed"]:
            return preview["result"]
        if not preview["plan"]:
            raise s.Conflict("Map the columns and review the rows before confirming.")
        plan = build_plan(db, wid, preview["payload"], preview["mapping"])
        if plan != preview["plan"]:
            raise s.Conflict("Workspace records changed after this preview. Map the columns again and review the updated rows.")
        result = {"organisations": sum("new_organisation" in r for r in plan), "contacts": sum("new_contact" in r for r in plan),
                  "skipped": sum(r["status"] == "skip" for r in plan), "rejected": sum(r["status"] == "reject" for r in plan)}
        for table, added, maximum in (("organisations", result["organisations"], 100), ("contacts", result["contacts"], 200), ("activities", result["organisations"] + result["contacts"], 1500)):
            count = db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE workspace_id=?", (wid,))["n"]
            if count + added > maximum:
                raise s.ValidationError(f"Nothing imported: this would exceed the workspace limit of {maximum} {table}. Use a smaller file or a fresh workspace.")
        ids = {}
        for row in plan:
            if row["status"] != "ready":
                continue
            org_id = row["organisation_id"]
            if "new_organisation" in row:
                ids[org_id] = s.uid()
                s.insert(db, "organisations", dict(id=ids[org_id], workspace_id=wid, **row["new_organisation"]))
                s.audit(db, wid, "organisation", ids[org_id], "Organisation created.", kind="created")
            if "new_contact" in row:
                cid = s.uid()
                s.insert(db, "contacts", dict(id=cid, workspace_id=wid, organisation_id=ids.get(org_id, org_id), **row["new_contact"]))
                s.audit(db, wid, "contact", cid, "Contact created.", kind="created")
        db.execute("UPDATE csv_previews SET consumed=1,result=? WHERE workspace_id=? AND id=?", (encoded(result), wid, pid))
        return result


@bp.route("/import", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file:
            raise s.ValidationError("Choose a UTF-8 CSV file to import.")
        pid = upload_preview(get_db(), g.wid, file.read(MAX_BYTES + 1))
        return redirect(url_for("csv_import.mapping", pid=pid), 303)
    return render_template("csv_import.html", step="upload")


@bp.route("/import/<pid>/mapping", methods=["GET", "POST"])
def mapping(pid):
    db = get_db()
    preview = get_preview(db, g.wid, pid)
    if request.method == "POST":
        map_preview(db, g.wid, pid, request.form)
        return redirect(url_for("csv_import.review", pid=pid), 303)
    selected = {key: "" if index is None else str(index) for key, index in preview["mapping"].items()} if preview["mapping"] else guess_mapping(preview["payload"]["headers"])
    return render_template("csv_import.html", step="mapping", preview=preview, fields=FIELDS, selected=selected)


@bp.get("/import/<pid>")
def review(pid):
    preview = get_preview(get_db(), g.wid, pid)
    if not preview["plan"] and not preview["consumed"]:
        return redirect(url_for("csv_import.mapping", pid=pid), 303)
    return render_template("csv_import.html", step="review", preview=preview)


@bp.post("/import/<pid>/confirm")
def confirm_route(pid):
    confirm(get_db(), g.wid, pid)
    return redirect(url_for("csv_import.review", pid=pid), 303)


@bp.get("/import/example.csv")
def example():
    raw = "organisation name,sector,city,contact name,email,role\r\nCedar Example Systems,Electronics,Dubai,Alex Example,alex@example.com,Operations coordinator\r\nPalm Example Services,Logistics,Sharjah,Sam Example,sam@example.org,Collection coordinator\r\n"
    return Response(raw, content_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="loopdesk-example.csv"'})
