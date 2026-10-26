import hmac
import os
import secrets
import sqlite3
from datetime import timedelta
from pathlib import Path

import click
import psycopg
from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.exceptions import SecurityError

from . import services as s
from .db import get_db, migrate
from . import security


def create_app(config=None):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, static_folder=str(root / "public" / "assets"), static_url_path="/assets")
    production = os.environ.get("APP_ENV") == "production" or bool(os.environ.get("VERCEL"))
    app.config.update(
        DATABASE_URL=os.environ.get("DATABASE_URL", f"sqlite:///{root / 'instance' / 'loopdesk.sqlite3'}"),
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        PRODUCTION=production,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
        MAX_CONTENT_LENGTH=65536,
        FOLLOWDESK_URL=os.environ.get("LOOPDESK_FOLLOWDESK_URL", "" if production else "http://127.0.0.1:5059"),
        TEMPLATES_AUTO_RELOAD=not production,
    )
    if config:
        app.config.update(config)
    if app.config["PRODUCTION"] and not os.environ.get("LOOPDESK_FOLLOWDESK_URL") and not (config and "FOLLOWDESK_URL" in config):
        app.config["FOLLOWDESK_URL"] = ""
    if app.config["FOLLOWDESK_URL"]:
        from urllib.parse import urlsplit
        try:
            linked = urlsplit(app.config["FOLLOWDESK_URL"])
            local = linked.hostname in {"127.0.0.1", "localhost", "::1"}
            if not linked.hostname or linked.username or linked.password or linked.path or linked.query or linked.fragment or linked.scheme not in {"http", "https"} or (linked.scheme == "http" and (app.config["PRODUCTION"] or not local)):
                raise ValueError()
        except (ValueError, TypeError):
            raise RuntimeError("Configure an HTTPS FollowDesk origin, or loopback HTTP for local development.") from None
    if app.config["PRODUCTION"]:
        if not app.config["DATABASE_URL"].startswith(("postgres://", "postgresql://")):
            raise RuntimeError("Production requires a persistent PostgreSQL DATABASE_URL.")
        if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32 or "replace-with" in app.config["SECRET_KEY"]:
            raise RuntimeError("Production requires a random SECRET_KEY of at least 32 characters.")
    elif not app.config["SECRET_KEY"]:
        # Stable through local restarts. This ignored file is never packaged.
        folder = root / "instance"
        folder.mkdir(exist_ok=True)
        secret_file = folder / "session-secret"
        try:
            with secret_file.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config["SECRET_KEY"] = secret_file.read_text().strip()
    security.configure(app,"LOOPDESK")

    @app.teardown_appcontext
    def close_db(error):
        if "db" in g:
            g.pop("db").close()

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    @app.before_request
    def protect_request():
        if isinstance(request.routing_exception,SecurityError):
            return Response("Untrusted request host.\n",status=400,content_type="text/plain")
        if request.blueprint == "outreach_api":
            from .outreach import authorize_api
            return authorize_api()
        if request.method == "POST":
            security.check_origin()
            token = request.form.get("csrf_token", "")
            if not session.get("csrf") or not hmac.compare_digest(token.encode("utf-8"), session["csrf"].encode("utf-8")):
                abort(400, "This form expired or has an invalid security token. Reload the page and try again.")
        if request.endpoint not in {"landing", "try_demo", "static", "health"}:
            wid = session.get("workspace_id")
            workspace = security.active_workspace(get_db(),wid,s.stamp())
            if not workspace:
                session.pop("workspace_id", None)
                flash("Start a fresh demo to continue. Workspaces expire after 24 hours.", "info")
                return redirect(url_for("landing"), code=303)
            g.wid = wid
            g.workspace = workspace
        if request.method == "POST" or getattr(g,"wid",None):
            security.enforce_rate_limits(get_db(),getattr(g,"wid",None),demo=request.endpoint=="try_demo")

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if app.config["PRODUCTION"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.context_processor
    def context():
        return dict(csrf_token=csrf_token, STAGES=s.STAGES, SERVICES=s.SERVICES, OWNERS=s.OWNERS,
                    today=s.dubai_today().isoformat(), workspace=getattr(g, "workspace", None))

    @app.template_filter("aed")
    def aed(value):
        return "Not estimated" if value is None else f"AED {value / 100:,.2f}"

    @app.cli.command("migrate")
    def migrate_command():
        """Apply pending database migrations (no sample data or public deployment)."""
        if app.config["DATABASE_URL"].startswith("sqlite:///"):
            Path(app.config["DATABASE_URL"].removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        migrate(get_db())
        click.echo("Database migrations applied.")

    @app.get("/health")
    def health():
        db = get_db()
        row = db.one("SELECT version FROM schema_migrations WHERE version=?", ("005_followdesk",))
        return ({"status": "ok" if row else "migration_required"}, 200 if row else 503)

    @app.get("/")
    def landing():
        return render_template("landing.html")

    @app.post("/demo")
    def try_demo():
        # A return visit reuses its live workspace; reset is explicit on the dashboard.
        wid = session.get("workspace_id")
        existing = security.active_workspace(get_db(),wid,s.stamp())
        if not existing or request.form.get("reset") == "1":
            previous = wid if existing else None
            try:
                wid = s.create_workspace(get_db(), seed=True)
            except s.ValidationError as error:
                return render_template("error.html", message=str(error), code=429), 429
            if previous:
                security.revoke_workspace(get_db(),previous,s.stamp())
            session.clear()
            session["workspace_id"] = wid
            session.permanent = True
        return redirect(url_for("dashboard"), code=303)

    @app.get("/dashboard")
    def dashboard():
        return render_template("dashboard.html", metrics=s.report(get_db(), g.wid),
                               tasks=s.task_list(get_db(), g.wid)[:6],
                               recent=get_db().all("SELECT * FROM activities WHERE workspace_id=? ORDER BY created_at DESC,id DESC LIMIT 5", (g.wid,)))

    @app.get("/organisations")
    def organisations():
        rows = get_db().all("SELECT * FROM organisations WHERE workspace_id=? ORDER BY name,id", (g.wid,))
        q, sector, status = request.args.get("q", "").strip().lower(), request.args.get("sector", ""), request.args.get("status", "active")
        sectors = sorted({r["sector"] for r in rows})
        rows = [r for r in rows if (not q or q in r["name"].lower() or q in r["city"].lower()) and (not sector or r["sector"] == sector) and (status == "all" or bool(r["archived"]) == (status == "archived"))]
        return render_template("organisations.html", rows=rows, sectors=sectors)

    @app.get("/contacts")
    def contacts():
        rows = get_db().all("SELECT c.*,o.name AS organisation_name FROM contacts c JOIN organisations o ON o.workspace_id=c.workspace_id AND o.id=c.organisation_id WHERE c.workspace_id=? ORDER BY c.name,c.id", (g.wid,))
        q, oid, status = request.args.get("q", "").strip().lower(), request.args.get("organisation_id", ""), request.args.get("status", "active")
        rows = [r for r in rows if (not q or q in (r["name"] + r["email"] + r["organisation_name"]).lower()) and (not oid or r["organisation_id"] == oid) and (status == "all" or bool(r["archived"]) == (status == "archived"))]
        return render_template("contacts.html", rows=rows, organisations=get_db().all("SELECT * FROM organisations WHERE workspace_id=? ORDER BY name", (g.wid,)))

    def entity_form(kind, rid=None):
        db = get_db()
        table = {"organisation": "organisations", "contact": "contacts", "opportunity": "opportunities"}[kind]
        row = s.record(db, table, g.wid, rid) if rid else {}
        error, status = None, 200
        data = row.copy()
        if kind == "opportunity":
            data["value"] = "" if row.get("value_minor") is None else f"{row['value_minor'] / 100:.2f}"
        if request.method == "POST":
            data = request.form
            try:
                saved = {"organisation": s.save_organisation, "contact": s.save_contact, "opportunity": s.save_opportunity}[kind](db, g.wid, data, rid)
                flash(f"{kind.capitalize()} saved.", "success")
                return redirect(url_for("opportunity_detail", rid=saved) if kind == "opportunity" else url_for(table), code=303)
            except s.ValidationError as exc:
                error, status = str(exc), 409 if isinstance(exc, s.Conflict) else 422
        history = db.all("SELECT * FROM activities WHERE workspace_id=? AND entity_type=? AND entity_id=? ORDER BY created_at DESC,id DESC", (g.wid, kind, rid)) if rid else []
        return render_template("form.html", kind=kind, data=data, rid=rid, error=error, history=history,
                               organisations=db.all("SELECT * FROM organisations WHERE workspace_id=? ORDER BY archived,name,id", (g.wid,)),
                               contacts=db.all("SELECT * FROM contacts WHERE workspace_id=? ORDER BY archived,name,id", (g.wid,))), status

    for kind in ("organisation", "contact", "opportunity"):
        plural = {"organisation": "organisations", "contact": "contacts", "opportunity": "opportunities"}[kind]
        app.add_url_rule(f"/{plural}/new", endpoint=f"new_{kind}", view_func=lambda kind=kind: entity_form(kind), methods=["GET", "POST"])
        app.add_url_rule(f"/{plural}/<rid>/edit", endpoint=f"edit_{kind}", view_func=lambda rid, kind=kind: entity_form(kind, rid), methods=["GET", "POST"])

    @app.post("/<kind>/<rid>/archive")
    def archive(kind, rid):
        if kind not in {"organisations", "contacts"}:
            abort(404)
        s.archive(get_db(), kind, g.wid, rid, request.form.get("version"))
        flash("Archive status updated. Linked opportunity history is retained.", "success")
        return redirect(url_for(kind, status="all"), code=303)

    @app.get("/opportunities")
    def opportunities():
        rows = s.opportunity_list(get_db(), g.wid, request.args)
        owners = get_db().all("SELECT DISTINCT owner FROM opportunities WHERE workspace_id=? ORDER BY owner", (g.wid,))
        return render_template("opportunities.html", rows=rows, owners=owners,
                               query={k: request.args[k] for k in ("q", "stage", "service", "owner") if request.args.get(k)})

    @app.get("/opportunities.csv")
    def export():
        return Response(s.csv_export(s.opportunity_list(get_db(), g.wid, request.args)), content_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="loopdesk-opportunities.csv"'})

    @app.get("/opportunities/<rid>")
    def opportunity_detail(rid):
        db = get_db()
        row = s.record(db, "opportunities", g.wid, rid)
        return render_template("detail.html", row=row,
                               organisation=s.record(db, "organisations", g.wid, row["organisation_id"]),
                               contact=s.record(db, "contacts", g.wid, row["contact_id"]),
                               activities=db.all("SELECT * FROM activities WHERE workspace_id=? AND opportunity_id=? ORDER BY created_at DESC,id DESC", (g.wid, rid)),
                               events=db.all("SELECT * FROM stage_events WHERE workspace_id=? AND opportunity_id=? ORDER BY created_at,id", (g.wid, rid)),
                               tasks=db.all("SELECT * FROM tasks WHERE workspace_id=? AND opportunity_id=? ORDER BY completed,due_date,id", (g.wid, rid)))

    @app.post("/opportunities/<rid>/activity")
    def activity(rid):
        s.add_activity(get_db(), g.wid, rid, request.form)
        flash("Activity recorded.", "success")
        return redirect(url_for("opportunity_detail", rid=rid), code=303)

    @app.post("/opportunities/<rid>/tasks")
    def add_task(rid):
        s.add_task(get_db(), g.wid, rid, request.form)
        flash("Follow-up scheduled.", "success")
        return redirect(url_for("opportunity_detail", rid=rid), code=303)

    @app.post("/tasks/<rid>/complete")
    def complete_task(rid):
        s.complete_task(get_db(), g.wid, rid, request.form.get("version"))
        flash("Follow-up updated.", "success")
        return redirect(url_for("followups"), code=303)

    @app.get("/follow-ups")
    def followups():
        return render_template("followups.html", tasks=s.task_list(get_db(), g.wid, request.args.get("status", "open")))

    @app.get("/reports")
    def reports():
        return render_template("reports.html", metrics=s.report(get_db(), g.wid))

    @app.errorhandler(s.ValidationError)
    def validation(error):
        code = 409 if isinstance(error, s.Conflict) else 422
        return render_template("error.html", message=str(error), code=code), code

    def database_unavailable(error):
        # Driver exception messages can contain server/connection details; do not expose them.
        app.logger.warning("Workspace database request failed (%s)", type(error).__name__)
        if request.endpoint == "health":
            missing = isinstance(error, psycopg.errors.UndefinedTable) or "no such table: schema_migrations" in str(error)
            response = app.json.response({"status": "migration_required" if missing else "database_unavailable"})
        else:
            response = app.make_response((render_template("error.html", code=503, message="The workspace database is temporarily unavailable. Please try again shortly."), 503))
        response.status_code = 503
        response.headers["Retry-After"] = "30"
        return response

    for database_error in (sqlite3.OperationalError, psycopg.OperationalError, psycopg.errors.UndefinedTable):
        app.register_error_handler(database_error, database_unavailable)

    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def http_error(error):
        response = error.get_response()
        response.set_data(render_template("error.html", message=error.description, code=error.code))
        response.content_type = "text/html; charset=utf-8"
        return response

    from .scope_import import bp as scope_bp
    app.register_blueprint(scope_bp)
    from .outreach import api as outreach_api, ui as outreach_ui
    app.register_blueprint(outreach_api)
    app.register_blueprint(outreach_ui)
    return app
