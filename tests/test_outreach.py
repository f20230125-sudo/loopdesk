import json
from datetime import timedelta

import pytest
from conftest import session_for
from test_workflow import related,opportunity
from loopdesk import services as s,outreach as o
from loopdesk.outreach_contract import canonical,digest


@pytest.fixture
def linked(db,workspace):
    org,contact=related(db,workspace)
    oid=opportunity(db,workspace,org,contact)
    code=o.make_code(db,workspace)
    grant=o.exchange(db,dict(pairing_code=code,client_workspace_id="a"*32))
    return workspace,oid,grant


def event(oid,**changes):
    value=dict(schema_version=1,source_system="followdesk",source_workspace_id="a"*32,event_id="b"*32,enrollment_id="c"*32,sequence=1,opportunity_id=oid,kind="demo_delivery",recorded_at_utc=s.stamp(),summary="Simulated delivery: Fictional message; no real email sent.")
    value.update(changes)
    value["digest"]=digest(value)
    return value


def auth(grant): return {"Authorization":"Bearer "+grant["access_token"]}


def test_pair_ui_and_code_is_single_use(client,db,workspace):
    token=session_for(client,workspace)
    assert client.get("/integrations/followdesk").status_code==200
    assert client.post("/integrations/followdesk",data=dict(action="pair")).status_code==400
    assert client.post("/integrations/followdesk",data=dict(csrf_token=token,action="pair")).status_code==200
    code=o.make_code(db,workspace)
    payload=dict(pairing_code=code,client_workspace_id="a"*32)
    first=client.post("/api/followdesk/v1/exchange",json=payload)
    assert first.status_code==200 and "access_token" in first.json
    assert client.post("/api/followdesk/v1/exchange",json=payload).status_code==401
    assert code not in str(db.all("SELECT * FROM outreach_pair_codes"))
    assert first.json["access_token"] not in str(db.all("SELECT * FROM outreach_grants"))


def test_expired_and_revoked_code(client,db,workspace):
    code=o.make_code(db,workspace)
    with db.transaction(): db.execute("UPDATE outreach_pair_codes SET expires_at=?",((s.utcnow()-timedelta(minutes=1)).isoformat(),))
    assert client.post("/api/followdesk/v1/exchange",json=dict(pairing_code=code,client_workspace_id="a"*32)).status_code==401


def test_api_requires_bearer_not_cookie(client,db,linked):
    wid,oid,grant=linked
    session_for(client,wid)
    assert client.get("/api/followdesk/v1/opportunities").status_code==401
    response=client.get("/api/followdesk/v1/opportunities",headers=auth(grant))
    assert response.status_code==200 and response.json["items"][0]["id"]==oid
    response=client.get("/api/followdesk/v1/opportunities/"+oid,headers=auth(grant))
    assert response.status_code==200 and response.json["context"]["contact"]["email"]=="alex@example.com"


def test_idempotent_event_and_no_crm_overwrite(client,db,linked):
    wid,oid,grant=linked
    before=s.record(db,"opportunities",wid,oid)
    value=event(oid)
    first=client.post("/api/followdesk/v1/events",json=value,headers=auth(grant))
    second=client.post("/api/followdesk/v1/events",json=value,headers=auth(grant))
    assert first.status_code==second.status_code==200
    assert first.json["receipt_id"]==second.json["receipt_id"] and second.json["duplicate"]
    assert db.one("SELECT COUNT(*) AS n FROM activities WHERE kind='followdesk'")["n"]==1
    assert s.record(db,"opportunities",wid,oid)==before
    changed=event(oid,summary="Different content")
    assert client.post("/api/followdesk/v1/events",json=changed,headers=auth(grant)).status_code==409


def test_reconnection_keeps_event_dedup(client,db,linked):
    wid,oid,grant=linked
    value=event(oid)
    one=client.post("/api/followdesk/v1/events",json=value,headers=auth(grant))
    new=o.exchange(db,dict(pairing_code=o.make_code(db,wid),client_workspace_id="a"*32))
    assert client.get("/api/followdesk/v1/opportunities",headers=auth(grant)).status_code==401
    two=client.post("/api/followdesk/v1/events",json=value,headers=auth(new))
    assert one.json["receipt_id"]==two.json["receipt_id"]


def test_no_cross_workspace_access_or_cookie_override(client,db,linked):
    wid,oid,grant=linked
    other=s.create_workspace(db,seed=False)
    org,contact=related(db,other,"Other")
    foreign=opportunity(db,other,org,contact)
    session_for(client,other)
    assert client.get("/api/followdesk/v1/opportunities/"+oid,headers=auth(grant)).status_code==200
    assert client.get("/api/followdesk/v1/opportunities/"+foreign,headers=auth(grant)).status_code==404
    assert client.post("/api/followdesk/v1/events",json=event(foreign),headers=auth(grant)).status_code==404
    assert client.post("/api/followdesk/v1/events",json=event(oid,source_workspace_id="d"*32),headers=auth(grant)).status_code==403


def test_revoke_and_workspace_reset_deny_api(client,db,linked):
    wid,oid,grant=linked
    assert client.post("/api/followdesk/v1/revoke",json={},headers=auth(grant)).status_code==200
    assert client.get("/api/followdesk/v1/opportunities",headers=auth(grant)).status_code==401
    grant=o.exchange(db,dict(pairing_code=o.make_code(db,wid),client_workspace_id="a"*32))
    from loopdesk.security import revoke_workspace
    revoke_workspace(db,wid,s.stamp())
    assert client.post("/api/followdesk/v1/events",json=event(oid),headers=auth(grant)).status_code==401


@pytest.mark.parametrize("variation",["digest","extra","duplicate","nan","huge","media","invalid_id","kind_array","kind_object"])
def test_malformed_requests_fail_without_writes(variation,client,db,linked):
    wid,oid,grant=linked
    payload=event(oid)
    headers=auth(grant)
    media="application/json"
    if variation=="digest": payload["digest"]="0"*64
    if variation=="extra": payload["owner"]="Attacker"
    if variation=="invalid_id": payload["opportunity_id"]="../other"
    if variation=="kind_array": payload["kind"]=[]
    if variation=="kind_object": payload["kind"]={}
    raw=canonical(payload)
    if variation=="duplicate": raw=raw[:-1]+',"sequence":2}'
    if variation=="nan": raw=raw.replace('"sequence":1','"sequence":NaN')
    if variation=="huge": raw="x"*8193
    if variation=="media": media="text/plain"
    response=client.post("/api/followdesk/v1/events",data=raw,content_type=media,headers=headers)
    assert response.status_code in {415,422}
    assert db.one("SELECT COUNT(*) AS n FROM outreach_receipts")["n"]==0


def test_historical_event_can_append_to_closed_enquiry(client,db,linked):
    wid,oid,grant=linked
    with db.transaction(): db.execute("UPDATE opportunities SET stage='Won' WHERE workspace_id=? AND id=?",(wid,oid))
    response=client.post("/api/followdesk/v1/events",json=event(oid),headers=auth(grant))
    assert response.status_code==200
    assert s.record(db,"opportunities",wid,oid)["stage"]=="Won"


def test_contract_copies_match():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    if (root/"followdesk/followdesk/contract.py").exists():
        assert (root/"followdesk/followdesk/contract.py").read_bytes()==(root/"loopdesk/loopdesk/outreach_contract.py").read_bytes()
