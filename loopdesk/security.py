"""Shared demo security controls, independently vendored in both applications."""
import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlsplit
from flask import current_app, request
from werkzeug.exceptions import BadRequest, Forbidden, TooManyRequests


def configure(app, prefix):
    """Apply security defaults after caller config, and fail closed for deployment."""
    hosts = app.config.get("TRUSTED_HOSTS")
    if hosts is None:
        raw = os.environ.get(prefix + "_TRUSTED_HOSTS", "")
        hosts = [host.strip() for host in raw.split(",") if host.strip()]
        if not hosts and not app.config["PRODUCTION"]:
            hosts = ["localhost", "127.0.0.1", "[::1]"]
    if not isinstance(hosts, (list, tuple)) or not hosts or any(not isinstance(h,str) or not re.fullmatch(r"\.?[a-zA-Z0-9][a-zA-Z0-9.-]*|\[::1\]",h) for h in hosts):
        raise RuntimeError("Set explicit trusted hostnames before serving this application.")
    app.config["TRUSTED_HOSTS"] = list(hosts)
    if app.config["PRODUCTION"]:
        key = app.config.get("SECRET_KEY")
        if not isinstance(key,str) or len(key) < 32 or len(set(key)) < 8 or any(word in key.lower() for word in ("replace", "change-me", "changeme", "example", "test-secret", "development", "secret-key")):
            raise RuntimeError("Production requires a random session secret, never a placeholder or repeated value.")
        app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    app.config.setdefault("SECURITY_RATE_LIMITS", True)
    app.config["MAX_FORM_PARTS"] = 32


def positive_integer(raw, maximum=2147483647):
    """Bound decimal length before conversion and before passing to SQL drivers."""
    if type(raw) is int:
        return raw if 1 <= raw <= maximum else None
    if not isinstance(raw,str) or not re.fullmatch(r"[0-9]{1,10}",raw):
        return None
    value = int(raw)
    return value if 1 <= value <= maximum else None


def active_workspace(db,wid,now):
    return db.one("SELECT w.* FROM workspaces w WHERE w.id=? AND w.expires_at>? AND NOT EXISTS (SELECT 1 FROM revoked_workspaces r WHERE r.workspace_id=w.id)",(wid,now)) if wid else None


def revoke_workspace(db,wid,now):
    with db.transaction():
        db.execute("INSERT INTO revoked_workspaces(workspace_id,revoked_at) VALUES (?,?) ON CONFLICT(workspace_id) DO NOTHING",(wid,now))


def check_origin():
    # A missing Origin is allowed with the synchronizer token for non-browser clients.
    # Never trust caller-supplied forwarded hosts/addresses as an alternative origin.
    origin = request.headers.get("Origin")
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise Forbidden("Cross-site form submissions are not accepted.")
    if origin is not None:
        try:
            actual, expected = urlsplit(origin), urlsplit(request.host_url)
            same = (actual.scheme, actual.hostname, actual.port or (443 if actual.scheme=="https" else 80)) == (expected.scheme, expected.hostname, expected.port or (443 if expected.scheme=="https" else 80))
            same = same and not (actual.username or actual.password or actual.path or actual.query or actual.fragment)
        except ValueError:
            same = False
        if not same:
            raise Forbidden("The form origin does not match this application.")
    for key in request.form:
        if len(request.form.getlist(key)) != 1:
            raise BadRequest("Duplicate form fields are not accepted.")


def client_address():
    """Address the request limits are keyed on.

    Forwarding headers are ignored everywhere except Vercel, where the platform sets X-Vercel-Forwarded-For to the
    client's public address and overwrites any client-supplied value. Without this every visitor would share the
    proxy's address and therefore one demo budget."""
    if os.environ.get("VERCEL"):
        forwarded = request.headers.get("X-Vercel-Forwarded-For", "").split(",")[0].strip()
        if re.fullmatch(r"[0-9a-fA-F:.]{3,45}", forwarded):
            return forwarded
    return request.remote_addr or "unknown"


def enforce_rate_limits(db, workspace=None, demo=False):
    if not current_app.config["SECURITY_RATE_LIMITS"]:
        return
    now = int(time.time())
    key = str(current_app.secret_key).encode()
    address = client_address()
    subject = hmac.new(key,address.encode(),hashlib.sha256).hexdigest()
    rules = [("ip-write" if request.method=="POST" else "ip-read",subject,60,120 if request.method=="POST" else 600)]
    if workspace:
        rules.append(("workspace-write" if request.method=="POST" else "workspace-read",workspace,60,90 if request.method=="POST" else 240))
    if demo:
        rules.extend([("demo-minute",subject,60,5),("demo-hour",subject,3600,20)])
    with db.transaction():
        db.execute("DELETE FROM security_buckets WHERE expires_at<=?",(now,))
        for kind,identity,window,limit in rules:
            start = now//window*window
            bucket = f"{kind}:{identity}:{start}"
            changed = db.execute("INSERT INTO security_buckets(bucket,hits,expires_at) VALUES (?,1,?) ON CONFLICT(bucket) DO UPDATE SET hits=security_buckets.hits+1 WHERE security_buckets.hits<?",(bucket,start+window,limit))
            if changed.rowcount != 1:
                raise TooManyRequests("Demo request limit reached. Wait before trying again.",retry_after=max(1,start+window-now))


TABLES = {"cases","sources","source_rows","import_previews","revisions","audit_events","organisations","contacts","opportunities","tasks","activities","scope_previews","scope_imports"}
TEXT_COLUMNS = {"raw_text","state","snapshot","payload","parsed"}


def _lock_workspace(db,wid):
    if db.postgres:
        db.one("SELECT id FROM workspaces WHERE id=? FOR UPDATE",(wid,))
    else:
        # SQLite's default deferred mode does not begin a transaction for SELECT.
        # Take the write lock before checking, so simultaneous requests cannot both pass the count.
        db.execute("UPDATE workspaces SET created_at=created_at WHERE id=?",(wid,))


def quota(db, table, wid, maximum, case_id=None):
    if table not in TABLES:
        raise ValueError("Unsupported quota table")
    _lock_workspace(db,wid)
    clause = "workspace_id=?" + (" AND case_id=?" if case_id is not None else "")
    args = (wid,case_id) if case_id is not None else (wid,)
    count = db.one(f"SELECT count(*) AS n FROM {table} WHERE {clause}",args)["n"]
    if count >= maximum:
        raise TooManyRequests("This demo workspace reached its record limit. Start a fresh workspace or wait for expiry.",retry_after=3600)


def byte_quota(db,table,column,wid,added,maximum):
    if table not in TABLES or column not in TEXT_COLUMNS:
        raise ValueError("Unsupported byte quota")
    _lock_workspace(db,wid)
    size = f"octet_length({column})" if db.postgres else f"length(CAST({column} AS BLOB))"
    total = db.one(f"SELECT COALESCE(sum({size}),0) AS n FROM {table} WHERE workspace_id=?",(wid,))["n"]
    if total+added > maximum:
        raise TooManyRequests("This demo workspace reached its storage limit. Start a fresh workspace or wait for expiry.",retry_after=3600)
