"""Revocable demo integration. Dedicated bearer routes never use browser cookies."""
import hashlib
import json
import secrets
from datetime import timedelta

from flask import Blueprint, abort, current_app, g, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException, TooManyRequests

from . import services as s, security
from .db import get_db
from .outreach_contract import ContractError, canonical, strict_json, identifier, event_payload

api = Blueprint("outreach_api", __name__, url_prefix="/api/followdesk/v1")
ui = Blueprint("outreach", __name__)


def hashed(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bounded(db, table, wid, maximum):
    if db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE workspace_id=?", (wid,))["n"] >= maximum:
        raise TooManyRequests("The connection demo limit was reached.", retry_after=300)


def make_code(db, wid):
    token = secrets.token_urlsafe(32)
    with db.transaction():
        security._lock_workspace(db, wid)
        db.execute("DELETE FROM outreach_pair_codes WHERE workspace_id=? AND expires_at<=?", (wid,s.stamp()))
        bounded(db, "outreach_pair_codes", wid, 20)
        db.execute("UPDATE outreach_pair_codes SET used=1 WHERE workspace_id=?", (wid,))
        db.execute("INSERT INTO outreach_pair_codes VALUES (?,?,?,0)", (hashed(token),wid,(s.utcnow()+timedelta(minutes=5)).isoformat()))
    return token


def exchange(db, raw):
    if not isinstance(raw,dict) or set(raw) != {"pairing_code","client_workspace_id"}:
        raise ContractError("Supply a pairing code and client workspace.")
    client_id = identifier(raw["client_workspace_id"])
    code = raw["pairing_code"]
    if not isinstance(code,str) or not 32 <= len(code) <= 100:
        abort(401, "Invalid or expired pairing code.")
    token = secrets.token_urlsafe(32)
    with db.transaction():
        row = db.one("SELECT * FROM outreach_pair_codes WHERE token_hash=?", (hashed(code),))
        if not row:
            abort(401, "Invalid or expired pairing code.")
        security._lock_workspace(db,row["workspace_id"])
        workspace = security.active_workspace(db,row["workspace_id"],s.stamp())
        consumed = db.execute("UPDATE outreach_pair_codes SET used=1 WHERE token_hash=? AND used=0 AND expires_at>?", (hashed(code),s.stamp()))
        if not workspace or consumed.rowcount != 1:
            abort(401, "Invalid or expired pairing code.")
        db.execute("DELETE FROM outreach_grants WHERE workspace_id=? AND expires_at<=?", (workspace["id"],s.stamp()))
        bounded(db,"outreach_grants",workspace["id"],20)
        db.execute("UPDATE outreach_grants SET revoked=1 WHERE workspace_id=?", (workspace["id"],))
        expiry = min(workspace["expires_at"],(s.utcnow()+timedelta(hours=1)).isoformat())
        db.execute("INSERT INTO outreach_grants VALUES (?,?,?,?,?,0)",(s.uid(),workspace["id"],client_id,hashed(token),expiry))
    return dict(schema_version=1,access_token=token,source_workspace_id=workspace["id"],expires_at=expiry)


def authorize_api():
    db = get_db()
    if request.endpoint == "outreach_api.exchange_route":
        security.enforce_rate_limits(db)
        return None
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer ") or not 32 <= len(value[7:]) <= 100:
        abort(401,"An active scoped connection is required.")
    grant = db.one("SELECT * FROM outreach_grants WHERE token_hash=? AND revoked=0 AND expires_at>?",(hashed(value[7:]),s.stamp()))
    if not grant or not security.active_workspace(db,grant["workspace_id"],s.stamp()):
        abort(401,"Connection expired or revoked. Reconnect from LoopDesk.")
    g.outreach_grant, g.api_wid = grant, grant["workspace_id"]
    security.enforce_rate_limits(db,g.api_wid)


def context(db, wid, oid):
    identifier(oid)
    row = s.record(db,"opportunities",wid,oid)
    org = s.record(db,"organisations",wid,row["organisation_id"])
    contact = s.record(db,"contacts",wid,row["contact_id"])
    scopes = db.all("SELECT l.case_id,l.latest_revision,i.digest,i.payload FROM scope_links l JOIN scope_imports i ON i.workspace_id=l.workspace_id AND i.case_id=l.case_id AND i.revision=l.latest_revision WHERE l.workspace_id=? AND l.opportunity_id=? ORDER BY l.case_id",(wid,oid))
    summaries=[]
    for item in scopes:
        payload=json.loads(item["payload"])
        summaries.append(dict(case_id=item["case_id"],revision=item["latest_revision"],digest=item["digest"],review_status=payload["review_status"],assumption_count=len(payload["assumptions"])))
    return dict(id=row["id"],title=row["title"],stage=row["stage"],service=row["service"],owner=row["owner"],next_action=row["next_action"],version=row["version"],
                organisation=dict(id=org["id"],name=org["name"],archived=bool(org["archived"]),version=org["version"]),
                contact=dict(id=contact["id"],name=contact["name"],email=contact["email"],archived=bool(contact["archived"]),version=contact["version"]),received_scopes=summaries)


def receive_event(db, grant, value):
    payload=event_payload(value)
    if payload["source_workspace_id"] != grant["client_workspace_id"]:
        abort(403,"This event belongs to another client workspace.")
    wid=grant["workspace_id"]
    with db.transaction():
        security._lock_workspace(db,wid)
        # Re-check revocation under the write lock; cookie identity is never used.
        if not db.one("SELECT id FROM outreach_grants WHERE id=? AND revoked=0 AND expires_at>?",(grant["id"],s.stamp())) or not security.active_workspace(db,wid,s.stamp()):
            abort(401,"Connection expired or revoked.")
        existing=db.one("SELECT * FROM outreach_receipts WHERE workspace_id=? AND source_workspace_id=? AND event_id=?",(wid,payload["source_workspace_id"],payload["event_id"]))
        encoded=canonical(payload)
        if existing:
            if existing["payload"] != encoded:
                abort(409,"This event ID already has different content.")
            return dict(receipt_id=existing["activity_id"],duplicate=True)
        s.record(db,"opportunities",wid,payload["opportunity_id"])
        bounded(db,"outreach_receipts",wid,500)
        activity_id=s.uid()
        security.quota(db,"activities",wid,1500)
        db.execute("INSERT INTO activities VALUES (?,?,?,?,?,?,?,?)",(activity_id,wid,payload["opportunity_id"],"opportunity",payload["opportunity_id"],"followdesk",f"FollowDesk · {payload['kind']} · {payload['summary']}",s.stamp()))
        db.execute("INSERT INTO outreach_receipts VALUES (?,?,?,?,?,?,?,?)",(wid,payload["source_workspace_id"],payload["event_id"],payload["opportunity_id"],activity_id,encoded,payload["digest"],s.stamp()))
    return dict(receipt_id=activity_id,duplicate=False)


def json_body():
    if request.mimetype != "application/json":
        abort(415,"Use application/json.")
    return strict_json(request.get_data(cache=False),8192)


@api.post("/exchange")
def exchange_route():
    return exchange(get_db(),json_body())


@api.get("/opportunities")
def opportunities():
    # CRM quota bounds the total at 150. Each item contains only selection context.
    rows=get_db().all("SELECT id,title,stage FROM opportunities WHERE workspace_id=? ORDER BY title,id LIMIT 150",(g.api_wid,))
    return dict(schema_version=1,items=rows)


@api.get("/opportunities/<oid>")
def opportunity(oid):
    return dict(schema_version=1,context=context(get_db(),g.api_wid,oid),checked_at=s.stamp())


@api.post("/events")
def events():
    return receive_event(get_db(),g.outreach_grant,json_body())


@api.post("/revoke")
def revoke():
    with get_db().transaction():
        security._lock_workspace(get_db(),g.api_wid)
        get_db().execute("UPDATE outreach_grants SET revoked=1 WHERE id=?",(g.outreach_grant["id"],))
    return {"revoked":True}


@api.errorhandler(ContractError)
def contract_error(error):
    return {"error":str(error)},422


@api.errorhandler(HTTPException)
def api_error(error):
    response=error.get_response()
    response.data=canonical({"error":error.description})
    response.content_type="application/json"
    return response


@ui.route("/integrations/followdesk",methods=["GET","POST"])
def connections():
    code=None
    if request.method == "POST":
        if request.form.get("action") == "revoke":
            with get_db().transaction():
                security._lock_workspace(get_db(),g.wid)
                get_db().execute("UPDATE outreach_grants SET revoked=1 WHERE workspace_id=?",(g.wid,))
                get_db().execute("UPDATE outreach_pair_codes SET used=1 WHERE workspace_id=?",(g.wid,))
        else:
            code=make_code(get_db(),g.wid)
    grants=get_db().all("SELECT id,client_workspace_id,expires_at,revoked FROM outreach_grants WHERE workspace_id=? ORDER BY expires_at DESC",(g.wid,))
    return render_template("outreach_connection.html",code=code,grants=grants,followdesk_url=current_app.config.get("FOLLOWDESK_URL"))
