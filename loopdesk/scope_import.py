"""Bounded, transactional and idempotent offline ScopeDesk import."""
import json
import sqlite3
import psycopg
from flask import Blueprint, g, redirect, render_template, request, url_for
from werkzeug.exceptions import NotFound
from . import services as s
from .db import get_db
from .scope_contract import read_handoff, canonical, HandoffError
from .security import quota, byte_quota

bp = Blueprint("scope",__name__)


def next_action(payload):
    items = [r["text"] for r in payload["followups"]]
    items += ["Confirm assumption: " + r["text"] for r in payload["assumptions"]]
    return ("; ".join(items) or "Confirm reviewed ITAD scope and arrange the next customer discussion.")[:500]


def preview(db,wid,raw):
    try:
        payload = read_handoff(raw)
    except HandoffError as exc:
        raise s.ValidationError(str(exc)) from None
    pid = s.uid()
    with db.transaction():
        quota(db,"scope_previews",wid,30)
        byte_quota(db,"scope_previews","payload",wid,len(canonical(payload).encode("utf-8")),1024*1024)
        db.execute("INSERT INTO scope_previews VALUES (?,?,?,?)",(pid,wid,canonical(payload),s.stamp()))
    return pid


def get_preview(db,wid,pid):
    row = db.one("SELECT * FROM scope_previews WHERE workspace_id=? AND id=?",(wid,pid))
    if not row:
        raise NotFound("Import preview is not available in this workspace.")
    row["payload"] = read_handoff(row["payload"].encode())
    return row


def confirm(db,wid,pid,organisation_id,contact_id,owner):
    try:
        with db.transaction():
            payload = get_preview(db,wid,pid)["payload"]
            cid,revision = payload["case_id"],payload["revision"]
            link = db.one("SELECT * FROM scope_links WHERE workspace_id=? AND case_id=?" + (" FOR UPDATE" if db.postgres else ""),(wid,cid))
            if link:
                if revision < link["latest_revision"]:
                    raise s.Conflict("An older revision cannot replace a newer scope already received.")
                previous = db.one("SELECT * FROM scope_imports WHERE workspace_id=? AND case_id=? AND revision=?",(wid,cid,revision))
                if previous:
                    if previous["digest"] != payload["digest"] or previous["payload"] != canonical(payload):
                        raise s.Conflict("This case and revision was already received with different content.")
                    return link["opportunity_id"],False
                oid = link["opportunity_id"]
                s.record(db,"opportunities",wid,oid)
                db.execute("UPDATE scope_links SET latest_revision=? WHERE workspace_id=? AND case_id=?",(revision,wid,cid))
            else:
                org = s.record(db,"organisations",wid,organisation_id)
                contact = s.record(db,"contacts",wid,contact_id)
                if contact["organisation_id"] != org["id"] or org["archived"] or contact["archived"]:
                    raise s.ValidationError("Choose an active contact belonging to the selected active organisation.")
                owners = set(s.OWNERS) | {r["owner"] for r in db.all("SELECT DISTINCT owner FROM opportunities WHERE workspace_id=?",(wid,))}
                if owner not in owners:
                    raise s.ValidationError("Select an owner from this workspace.")
                oid = s.uid()
                s.insert(db,"opportunities",dict(id=oid,workspace_id=wid,organisation_id=org["id"],contact_id=contact["id"],title=("ITAD scope · "+payload["client_display_name"])[:160],service="IT asset disposition",owner=owner,stage="New",value_minor=None,next_action=next_action(payload),version=1,created_at=s.stamp()))
                db.execute("INSERT INTO stage_events VALUES (?,?,?,?,?,?)",(s.uid(),wid,oid,None,"New",s.stamp()))
                db.execute("INSERT INTO scope_links VALUES (?,?,?,?)",(wid,cid,oid,revision))
            quota(db,"scope_imports",wid,20,case_id=cid)
            byte_quota(db,"scope_imports","payload",wid,len(canonical(payload).encode("utf-8")),2*1024*1024)
            db.execute("INSERT INTO scope_imports VALUES (?,?,?,?,?,?)",(wid,cid,revision,payload["digest"],canonical(payload),s.stamp()))
            s.audit(db,wid,"opportunity",oid,f"ScopeDesk revision {revision} received ({payload['review_status']}). Suggested next action: {next_action(payload)}",oid,"scope_import")
            return oid,True
    except (sqlite3.IntegrityError,psycopg.IntegrityError):
        raise s.Conflict("The scope mapping changed during confirmation. Reload the preview and try again.") from None


@bp.route("/scope-import",methods=["GET","POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("handoff")
        if not file:
            raise s.ValidationError("Choose a reviewed ScopeDesk JSON file.")
        pid = preview(get_db(),g.wid,file.read(48*1024+1))
        return redirect(url_for("scope.import_preview",pid=pid),303)
    return render_template("scope_import.html",payload=None)


@bp.route("/scope-import/<pid>",methods=["GET","POST"])
def import_preview(pid):
    db = get_db()
    p = get_preview(db,g.wid,pid)["payload"]
    link = db.one("SELECT * FROM scope_links WHERE workspace_id=? AND case_id=?",(g.wid,p["case_id"]))
    if request.method == "POST":
        oid,created = confirm(db,g.wid,pid,request.form.get("organisation_id"),request.form.get("contact_id"),request.form.get("owner"))
        return redirect(url_for("opportunity_detail",rid=oid),303)
    owners = sorted(set(s.OWNERS) | {r["owner"] for r in db.all("SELECT DISTINCT owner FROM opportunities WHERE workspace_id=?",(g.wid,))})
    return render_template("scope_import.html",payload=p,link=link,next_action=next_action(p),owners=owners,
                           organisations=db.all("SELECT * FROM organisations WHERE workspace_id=? AND archived=0 ORDER BY name",(g.wid,)),
                           contacts=db.all("SELECT * FROM contacts WHERE workspace_id=? AND archived=0 ORDER BY name",(g.wid,)))


@bp.get("/opportunities/<rid>/scopes")
def history(rid):
    db = get_db()
    opportunity = s.record(db,"opportunities",g.wid,rid)
    values = db.all("SELECT i.* FROM scope_imports i JOIN scope_links l ON l.workspace_id=i.workspace_id AND l.case_id=i.case_id WHERE l.workspace_id=? AND l.opportunity_id=? ORDER BY i.case_id,i.revision DESC",(g.wid,rid))
    for row in values:
        row["payload"] = json.loads(row["payload"])
    return render_template("scope_history.html",row=opportunity,imports=values)
