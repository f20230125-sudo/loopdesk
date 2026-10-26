import pytest
from werkzeug.exceptions import TooManyRequests
from loopdesk import scope_import as importer
from loopdesk.scope_contract import canonical,digest
from test_scope_import import payload


def test_import_preview_storage_budget_is_atomic(db,workspace):
    p=payload()
    p["review_status"]="Reviewed with assumptions"
    p["assumptions"]=[dict(text="a"*500,refs=["S1:L1"]) for _ in range(90)]
    p["digest"]=digest(p)
    raw=canonical(p).encode()
    assert len(raw)<=48*1024
    rejected=False
    for i in range(30):
        before=db.one("SELECT count(*) AS n FROM scope_previews WHERE workspace_id=?",(workspace,))["n"]
        try:importer.preview(db,workspace,raw)
        except TooManyRequests as exc:
            assert "storage limit" in str(exc)
            assert db.one("SELECT count(*) AS n FROM scope_previews WHERE workspace_id=?",(workspace,))["n"]==before
            rejected=True
            break
    assert rejected
