import copy
import json
from pathlib import Path
import pytest
from loopdesk import services as s
from loopdesk import scope_import as importer
from loopdesk.scope_contract import read_handoff,digest,canonical,HandoffError
from conftest import session_for


def payload(revision=1):
    p=dict(schema_version=1,source_system="ScopeDesk",case_id="synthetic-case-1",revision=revision,review_status="Reviewed",reviewed_at="2026-10-26T08:00:00+00:00",client_display_name="Acacia Demo Systems",scope=[dict(kind="equipment",item="Laptop",site="Dubai",quantity=120,outcome="reuse",location="",collection="",source_refs=["S1:L1"])],assumptions=[],followups=[dict(text="Confirm access windows before scheduling.",refs=["S1:L1"])],source_references=[dict(ref="S1:L1",origin="enquiry")])
    p["digest"]=digest(p)
    return p


def mapped(db,wid):
    org=s.save_organisation(db,wid,dict(name="Acacia",sector="Technology",city="Dubai"))
    contact=s.save_contact(db,wid,dict(name="Alex",email="alex@example.com",role="IT",organisation_id=org))
    return org,contact


def stage(db,wid,p):return importer.preview(db,wid,canonical(p).encode())


def test_idempotent_newer_history_and_preserved_crm_fields(db,workspace):
    org,contact=mapped(db,workspace)
    p=payload()
    pid=stage(db,workspace,p)
    oid,created=importer.confirm(db,workspace,pid,org,contact,s.OWNERS[0])
    assert created
    row=s.record(db,"opportunities",workspace,oid)
    assert row["stage"]=="New" and row["service"]=="IT asset disposition" and row["value_minor"] is None
    assert "access windows" in row["next_action"]
    assert importer.confirm(db,workspace,pid,org,contact,s.OWNERS[0])==(oid,False)
    s.save_opportunity(db,workspace,dict(row,version=row["version"],stage="Proposal",owner="Existing salesperson",value="100.00"),oid)
    before=s.record(db,"opportunities",workspace,oid)
    newer=stage(db,workspace,payload(2))
    assert importer.confirm(db,workspace,newer,None,None,None)==(oid,True)
    assert s.record(db,"opportunities",workspace,oid)==before
    assert len(db.all("SELECT * FROM scope_imports WHERE workspace_id=?",(workspace,)))==2
    assert len(db.all("SELECT * FROM opportunities WHERE workspace_id=?",(workspace,)))==1
    with pytest.raises(s.Conflict,match="older"):importer.confirm(db,workspace,pid,org,contact,s.OWNERS[0])


def test_same_revision_different_content_rejected(db,workspace):
    org,contact=mapped(db,workspace)
    p=payload()
    pid=stage(db,workspace,p)
    importer.confirm(db,workspace,pid,org,contact,s.OWNERS[0])
    p["client_display_name"]="Changed name"
    p["digest"]=digest(p)
    forged=stage(db,workspace,p)
    with pytest.raises(s.Conflict,match="different content"):importer.confirm(db,workspace,forged,org,contact,s.OWNERS[0])


@pytest.mark.parametrize("mutation",["digest","schema","status","quantity","source","serial","timestamp","boolean_revision","duplicate_keys","oversize","invalid_encoding","status_array","kind_array","action_array","origin_array"])
def test_malformed_handoffs(mutation):
    p=payload()
    if mutation=="digest":p["digest"]="0"*64
    elif mutation=="schema":p["schema_version"]=2
    elif mutation=="status":p["review_status"]="Draft"
    elif mutation=="quantity":p["scope"][0]["quantity"]="120"
    elif mutation=="source":p["scope"][0]["source_refs"]=["Unknown:L1"]
    elif mutation=="serial":p["serial_register"]=["0001"]
    elif mutation=="timestamp":p["reviewed_at"]="2026-10-26T08:00:00+04:00"
    elif mutation=="boolean_revision":p["revision"]=True
    elif mutation=="status_array":p["review_status"]=[]
    elif mutation=="kind_array":p["scope"][0]["kind"]=[]
    elif mutation=="action_array":p["scope"][0]["outcome"]=[]
    elif mutation=="origin_array":p["source_references"][0]["origin"]=[]
    if mutation!="digest":p["digest"]=digest(p)
    raw=canonical(p).encode()
    if mutation=="duplicate_keys":raw=b'{"revision":1,"revision":1}'
    elif mutation=="oversize":raw=b" "*(48*1024+1)
    elif mutation=="invalid_encoding":raw=b"\xff"
    with pytest.raises(HandoffError):read_handoff(raw)


def test_mapping_cross_workspace_denial_and_transaction_rollback(db,workspace,monkeypatch):
    other=s.create_workspace(db,False)
    org,contact=mapped(db,other)
    pid=stage(db,workspace,payload())
    with pytest.raises(Exception):importer.confirm(db,workspace,pid,org,contact,s.OWNERS[0])
    assert not db.all("SELECT * FROM scope_links")
    org,contact=mapped(db,workspace)
    def fail(*args,**kwargs):raise RuntimeError("Injected history failure")
    monkeypatch.setattr(s,"audit",fail)
    with pytest.raises(RuntimeError):importer.confirm(db,workspace,pid,org,contact,s.OWNERS[0])
    assert not db.all("SELECT * FROM scope_links")
    assert not db.all("SELECT * FROM opportunities")


def test_http_preview_confirmation_and_workspace_scoped_history(client,db,workspace):
    import io
    token=session_for(client,workspace)
    org,contact=mapped(db,workspace)
    response=client.post("/scope-import",data=dict(csrf_token=token,handoff=(io.BytesIO(canonical(payload()).encode()),"scope.json")))
    assert response.status_code==303
    preview_url=response.headers["Location"]
    assert b"cannot detect a newer revision" in client.get(preview_url).data
    response=client.post(preview_url,data=dict(csrf_token=token,organisation_id=org,contact_id=contact,owner=s.OWNERS[0]))
    assert response.status_code==303
    detail=response.headers["Location"]
    assert b"ScopeDesk revision 1 received" in client.get(detail).data
    assert b"Revision 1" in client.get(detail+"/scopes").data
    other=s.create_workspace(db,False)
    session_for(client,other)
    assert client.get(preview_url).status_code==404
    assert client.get(detail+"/scopes").status_code==404
    assert client.post("/scope-import",data={}).status_code==400


def test_contract_copies_match():
    scope=Path(__file__).resolve().parents[2]/"scopedesk/scopedesk/contract.py"
    if scope.exists():assert scope.read_bytes()==(Path(__file__).resolve().parents[1]/"loopdesk/scope_contract.py").read_bytes()
    p=payload()
    p["client_display_name"]="\ud800"
    with pytest.raises(HandoffError):read_handoff(json.dumps(p,ensure_ascii=True).encode())
