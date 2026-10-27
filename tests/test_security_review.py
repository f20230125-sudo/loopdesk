"""Adversarial regression tests. This common suite is vendored in both apps."""
import importlib
from pathlib import Path
import pytest
from werkzeug.datastructures import MultiDict


def setup_case(app,db):
    s=importlib.import_module(app.import_name+".services")
    if app.import_name=="scopedesk":
        wid=s.workspace(db)
        cid=s.create_case(db,wid,"Security fixture","Security case","Two fictional laptops.")
        return s,wid,f"/cases/{cid}/statement",dict(kind="reviewer statement",text="Hostile version probe"),"cases",cid
    wid=s.create_workspace(db,False)
    rid=s.save_organisation(db,wid,dict(name="Security fixture",sector="IT",city="Dubai"))
    return s,wid,f"/organisations/{rid}/edit",dict(name="Security fixture",sector="IT",city="Dubai"),"organisations",rid


def authenticated(app,wid):
    client=app.test_client()
    with client.session_transaction() as sess:sess.update(workspace_id=wid,csrf="review-token")
    return client


@pytest.mark.parametrize("raw",["9"*100,"9"*1000,"2147483648","0","-1","1.0","+1","١"])
def test_version_numbers_never_overflow_sql(app,db,raw):
    s,wid,path,data,table,rid=setup_case(app,db)
    client=authenticated(app,wid)
    before=db.one(f"SELECT version FROM {table} WHERE workspace_id=? AND id=?",(wid,rid))
    assert client.post(path,data=dict(csrf_token="review-token",version=raw,**data)).status_code==409
    assert db.one(f"SELECT version FROM {table} WHERE workspace_id=? AND id=?",(wid,rid))==before


@pytest.mark.parametrize("host",["attacker.example","localhost.attacker.example","127.0.0.1.attacker.example","localhost:999999"])
def test_foreign_host_headers_are_rejected(app,host):
    response=app.test_client().get("/",headers={"Host":host,"X-Forwarded-Host":"localhost"})
    assert response.status_code==400
    assert b"Traceback" not in response.data
    assert response.headers["Cache-Control"]=="no-store"


@pytest.mark.parametrize("origin",["https://attacker.example","http://localhost.attacker.example","null","http://localhost:5059","http://user@localhost","http://localhost/path"])
def test_cross_origin_request_cannot_use_valid_csrf_token(app,db,origin):
    _,wid,path,data,table,rid=setup_case(app,db)
    client=authenticated(app,wid)
    response=client.post(path,data=dict(csrf_token="review-token",version=1,**data),headers={"Origin":origin})
    assert response.status_code==403
    assert db.one(f"SELECT version FROM {table} WHERE workspace_id=? AND id=?",(wid,rid))["version"]==1


def test_fetch_metadata_and_duplicate_form_fields_are_rejected(app,db):
    _,wid,path,data,table,rid=setup_case(app,db)
    client=authenticated(app,wid)
    response=client.post(path,data=dict(csrf_token="review-token",version=1,**data),headers={"Origin":"http://localhost","Sec-Fetch-Site":"cross-site"})
    assert response.status_code==403
    fields=MultiDict([("csrf_token","review-token"),("csrf_token","different-token"),("version","1"),*data.items()])
    assert client.post(path,data=fields).status_code==400
    assert db.one(f"SELECT version FROM {table} WHERE workspace_id=? AND id=?",(wid,rid))["version"]==1


def test_legitimate_same_origin_form_and_security_headers(app,db):
    _,wid,path,data,table,rid=setup_case(app,db)
    client=authenticated(app,wid)
    response=client.post(path,data=dict(csrf_token="review-token",version=1,**data),headers={"Origin":"http://localhost","Sec-Fetch-Site":"same-origin","X-Forwarded-Host":"attacker.example"})
    assert response.status_code==303
    assert db.one(f"SELECT version FROM {table} WHERE workspace_id=? AND id=?",(wid,rid))["version"]==2
    assert "camera=()" in response.headers["Permissions-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_production_config_enforces_cookies_after_overrides(app,monkeypatch):
    factory=importlib.import_module(app.import_name).create_app
    prod=factory(dict(PRODUCTION=True,DATABASE_URL="postgresql://example.invalid/security-test",SECRET_KEY="A4c9f20b8e6d3517F02a94Bc56d180ee",TRUSTED_HOSTS=["demo.example"],SESSION_COOKIE_SECURE=False))
    assert prod.config["SESSION_COOKIE_SECURE"] is True
    response=prod.test_client().get("/",base_url="https://demo.example")
    assert response.status_code==200
    assert "Secure;" in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    assert response.headers["Strict-Transport-Security"]=="max-age=31536000"


@pytest.mark.parametrize("key",["replace-with-a-random-secret-of-at-least-32-characters","x"*64,"example-value-0123456789-abcdef-0123456789"])
def test_production_rejects_known_or_low_diversity_secrets(app,key):
    factory=importlib.import_module(app.import_name).create_app
    with pytest.raises(RuntimeError):factory(dict(PRODUCTION=True,DATABASE_URL="postgresql://example.invalid/security-test",SECRET_KEY=key,TRUSTED_HOSTS=["demo.example"]))


def test_production_requires_explicit_trusted_hosts(app,monkeypatch):
    factory=importlib.import_module(app.import_name).create_app
    monkeypatch.delenv(app.import_name.upper()+"_TRUSTED_HOSTS",raising=False)
    with pytest.raises(RuntimeError,match="trusted hostnames"):
        factory(dict(PRODUCTION=True,DATABASE_URL="postgresql://example.invalid/security-test",SECRET_KEY="A4c9f20b8e6d3517F02a94Bc56d180ee"))


def test_demo_reset_throttle_survives_cookie_and_forwarding_spoof(app,db):
    client=app.test_client()
    for i in range(6):
        # A new browser cookie does not provide a new IP budget.
        client=app.test_client()
        client.get("/")
        with client.session_transaction() as sess:token=sess["csrf"]
        response=client.post("/demo",data=dict(csrf_token=token,reset="1"),headers={"X-Forwarded-For":f"198.51.100.{i+1}"})
        assert response.status_code==(303 if i<5 else 429)
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert db.one("SELECT count(*) AS n FROM workspaces")["n"]==5
    assert not any("127.0.0.1" in row["bucket"] for row in db.all("SELECT bucket FROM security_buckets"))


def test_vercel_client_address_header_is_trusted_only_on_vercel(app,db,monkeypatch):
    def burst(forwarded,count=6):
        statuses=[]
        for i in range(count):
            client=app.test_client()
            client.get("/")
            with client.session_transaction() as sess:token=sess["csrf"]
            statuses.append(client.post("/demo",data=dict(csrf_token=token,reset="1"),headers={"X-Vercel-Forwarded-For":forwarded(i)}).status_code)
        return statuses
    monkeypatch.delenv("VERCEL",raising=False)
    # Off Vercel the header is one more spoofable header: a single budget of five demos.
    assert burst(lambda i:f"203.0.113.{i+1}")==[303]*5+[429]
    monkeypatch.setenv("VERCEL","1")
    # On Vercel the platform sets it to the visitor's address, so each visitor has a separate budget...
    assert burst(lambda i:f"203.0.113.{i+101}")==[303]*6
    # ...but a repeated address, or a first hop followed by spoofed extras, is still throttled.
    assert burst(lambda i:"203.0.113.250, 198.51.100.%d"%i)==[303]*5+[429]
    # A malformed value falls back to the connection address, whose budget is already spent.
    assert burst(lambda i:"<script>",1)==[429]


def test_security_module_copies_match(app):
    root=Path(__file__).resolve().parents[2]
    left,right=root/"scopedesk/scopedesk/security.py",root/"loopdesk/loopdesk/security.py"
    if left.exists() and right.exists():assert left.read_bytes()==right.read_bytes()


def test_reset_revokes_prior_cookie_without_deleting_retained_records(app,db):
    _,wid,path,data,table,rid=setup_case(app,db)
    client=authenticated(app,wid)
    cookie_name=app.config["SESSION_COOKIE_NAME"]
    before=client.get_cookie(cookie_name).value
    assert client.post("/demo",data=dict(csrf_token="review-token",reset="1")).status_code==303
    replay=app.test_client()
    replay.set_cookie(cookie_name,before)
    read_path=f"/cases/{rid}" if app.import_name=="scopedesk" else f"/organisations/{rid}/edit"
    assert replay.get(read_path).status_code==303
    assert replay.post(path,data=dict(csrf_token="review-token",version=1,**data)).status_code==303
    assert db.one(f"SELECT version FROM {table} WHERE workspace_id=? AND id=?",(wid,rid))["version"]==1
    assert db.one("SELECT id FROM workspaces WHERE id=?",(wid,))
    assert db.one("SELECT workspace_id FROM revoked_workspaces WHERE workspace_id=?",(wid,))


def test_concurrent_requests_cannot_race_past_record_quotas(app,db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import io
    s,wid,_,_,_,rid=setup_case(app,db)
    if app.import_name=="scopedesk":
        for i in range(9):s.preview(db,wid,rid,b"item,quantity\nLaptop,1",",","quantity","input.csv")
    else:
        for i in range(98):s.save_organisation(db,wid,dict(name=f"Synthetic org {i}",sector="IT",city="Dubai"))
    barrier=Barrier(6)
    def submit(i):
        client=authenticated(app,wid)
        barrier.wait(timeout=10)
        if app.import_name=="scopedesk":
            return client.post(f"/cases/{rid}/preview",data=dict(csrf_token="review-token",inventory=(io.BytesIO(b"item,quantity\nLaptop,1"),"input.csv"),delimiter=",",mode="quantity")).status_code
        return client.post("/organisations/new",data=dict(csrf_token="review-token",name=f"Concurrent org {i}",sector="IT",city="Dubai")).status_code
    with ThreadPoolExecutor(max_workers=6) as pool:statuses=list(pool.map(submit,range(6)))
    assert sorted(statuses)==[303,429,429,429,429,429]
    table,expected=("import_previews",10) if app.import_name=="scopedesk" else ("organisations",100)
    assert db.one(f"SELECT count(*) AS n FROM {table} WHERE workspace_id=?",(wid,))["n"]==expected
