from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from loopdesk import services as s,outreach as o
from loopdesk.db import get_db
from test_outreach import event,auth
from test_workflow import related,opportunity


def test_code_exchange_is_atomic(app,db,workspace):
    code=o.make_code(db,workspace)
    barrier=Barrier(5)
    def worker(_):
        with app.test_client() as client:
            barrier.wait(timeout=10)
            response=client.post("/api/followdesk/v1/exchange",json=dict(pairing_code=code,client_workspace_id="a"*32))
            return response.status_code
    with ThreadPoolExecutor(max_workers=5) as pool: statuses=list(pool.map(worker,range(5)))
    assert statuses.count(200)==1 and statuses.count(401)==4
    assert db.one("SELECT COUNT(*) AS n FROM outreach_grants WHERE revoked=0")["n"]==1


def test_concurrent_event_receipt_deduplicates(app,db,workspace):
    org,contact=related(db,workspace)
    oid=opportunity(db,workspace,org,contact)
    grant=o.exchange(db,dict(pairing_code=o.make_code(db,workspace),client_workspace_id="a"*32))
    value=event(oid)
    barrier=Barrier(5)
    def worker(_):
        with app.test_client() as client:
            barrier.wait(timeout=10)
            response=client.post("/api/followdesk/v1/events",json=value,headers=auth(grant))
            assert response.status_code==200
            return response.json["receipt_id"]
    with ThreadPoolExecutor(max_workers=5) as pool: receipts=list(pool.map(worker,range(5)))
    assert len(set(receipts))==1
    assert db.one("SELECT COUNT(*) AS n FROM activities WHERE kind='followdesk'")["n"]==1
