import csv
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from werkzeug.exceptions import NotFound, TooManyRequests

from conftest import session_for
from loopdesk import csv_import as importer, services as s
from loopdesk.db import get_db

HEADERS = ["organisation name", "sector", "city", "contact name", "email", "role"]
MAPPING = {key: str(index) for index, (key, _) in enumerate(importer.FIELDS)}
ROW = ["Cedar Example", "Electronics", "Dubai", "Alex Example", "alex@example.com", "Coordinator"]


def raw_csv(rows, headers=HEADERS):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def staged(db, wid, rows, headers=HEADERS, mapping=MAPPING):
    pid = importer.upload_preview(db, wid, raw_csv(rows, headers))
    importer.map_preview(db, wid, pid, mapping)
    return pid


def counts(db, wid):
    return {table: db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE workspace_id=?", (wid,))["n"] for table in ("organisations", "contacts", "activities")}


def test_http_upload_mapping_review_confirm_and_example(client, db, workspace):
    token = session_for(client, workspace)
    assert b"Download example CSV" in client.get("/import").data
    response = client.get("/import/example.csv")
    assert response.status_code == 200 and "attachment" in response.headers["Content-Disposition"]
    assert importer.parse_csv(response.data)["rows"][0]["cells"][4] == "alex@example.com"
    response = client.post("/import", data=dict(csrf_token=token, csv_file=(io.BytesIO(raw_csv([ROW])), "example.csv")))
    assert response.status_code == 303
    mapping_url = response.headers["Location"]
    assert b"Map CSV columns" in client.get(mapping_url).data
    assert counts(db, workspace) == dict(organisations=0, contacts=0, activities=0)
    response = client.post(mapping_url, data=dict(csrf_token=token, **MAPPING))
    review_url = response.headers["Location"]
    preview = client.get(review_url)
    assert b"Create organisation; Create contact" in preview.data and b"<td>2</td>" in preview.data
    assert b'aria-describedby="csv-preview-help"' in preview.data
    assert counts(db, workspace)["organisations"] == 0
    assert client.post(review_url + "/confirm", data=dict(csrf_token=token)).status_code == 303
    assert b"Created 1 organisations and 1 contacts" in client.get(review_url).data
    assert counts(db, workspace) == dict(organisations=1, contacts=1, activities=2)
    assert client.post(review_url + "/confirm", data=dict(csrf_token=token)).status_code == 303
    assert counts(db, workspace)["activities"] == 2
    assert client.post(mapping_url, data=dict(csrf_token=token, **MAPPING)).status_code == 409


def test_duplicates_existing_in_file_blank_reject_and_link(db, workspace):
    oid = s.save_organisation(db, workspace, dict(name="  Existing  ", sector="IT", city="Dubai"))
    s.save_contact(db, workspace, dict(name="Known", email="KNOWN@example.com", role="IT", organisation_id=oid))
    pid = staged(db, workspace, [
        ["existing", "", "", "New", "new@example.com", "IT"],
        [" Existing ", "", "", "", "", ""],
        ["Not created", "IT", "Dubai", "Known", " known@EXAMPLE.com ", "IT"],
        ROW, [" cedar EXAMPLE ", "", "", "Second", "second@example.org", "IT"],
        ["Other", "IT", "Dubai", "Duplicate", "ALEX@EXAMPLE.COM", "IT"],
        [], ["", "IT", "Dubai", "", "", ""], ["Wrong", "width"],
        ["Rejected org", "IT", "Dubai", "Name", "bad-email", "IT"],
        ["Rejected org", "IT", "Dubai", "Valid", "valid@example.com", "IT"],
    ])
    plan = importer.get_preview(db, workspace, pid)["plan"]
    assert [row["status"] for row in plan] == ["ready", "skip", "skip", "ready", "ready", "skip", "skip", "reject", "reject", "reject", "ready"]
    assert plan[0]["actions"] == ["Link to existing organisation", "Create contact"]
    assert plan[8]["number"] == 10
    assert importer.confirm(db, workspace, pid) == dict(organisations=2, contacts=4, skipped=4, rejected=3)
    assert counts(db, workspace) == dict(organisations=3, contacts=5, activities=8)
    assert len(db.all("SELECT * FROM contacts WHERE workspace_id=? AND organisation_id=?", (workspace, oid))) == 2


@pytest.mark.parametrize("raw,message", [
    (b"", "256 KiB"), (b"x" * (importer.MAX_BYTES + 1), "256 KiB"),
    (b"name\n\xff", "UTF-8"), (b"a,,b\n1,2,3", "non-empty"),
    (b"a,A \n1,2", "unique"), (b"a,a\n1,2", "unique"),
    (b"a\n\"unclosed", "syntax"), (b"a\n\x00", "control"),
    (b"a\n\x01", "control"), (b"a\n", "at least one"),
    (raw_csv([ROW] * 501), "500 data rows"),
    (raw_csv([["x"] * 21], [f"h{i}" for i in range(21)]), "20 columns"),
    (raw_csv([["x"] * 21], ["header"]), "20 columns"),
    (raw_csv([["x" * 2049]], ["header"]), "2 KiB"),
    (raw_csv([["é" * 1025]], ["header"]), "2 KiB"),
    (raw_csv([["x"]], ["h" * 2049]), "2 KiB"),
], ids=["empty", "bytes-over", "encoding", "empty-header", "case-header", "duplicate-header", "quoting", "nul", "control", "no-data", "rows-over", "headers-over", "columns-over", "cell-over", "unicode-cell-over", "header-cell-over"])
def test_parser_limits_and_hostile_csv(raw, message):
    with pytest.raises(s.ValidationError, match=message):
        importer.parse_csv(raw)


def test_exact_limits_bom_unicode_multiline_and_text():
    rows = [["x"] * 20 for _ in range(500)]
    rows[0][0] = "é" * 1024
    payload = importer.parse_csv(b"\xef\xbb\xbf" + raw_csv(rows, [f"h{i}" for i in range(20)]))
    assert len(payload["rows"]) == 500 and len(payload["headers"]) == 20
    # Precisely 256 KiB including headers, separators and newlines.
    body = b"h\n" + b"x\n" * 500
    padding = importer.MAX_BYTES - len(body)
    cells = ["x" for _ in range(500)]
    for index in range(500):
        added = min(padding, 2047)
        cells[index] += " " * added
        padding -= added
    exact = b"h\n" + b"".join((cell + "\n").encode() for cell in cells)
    assert len(exact) == importer.MAX_BYTES
    assert len(importer.parse_csv(exact)["rows"]) == 500
    payload = importer.parse_csv(raw_csv([["line\ntext", "0012345"], ["plain", "@literal"]], ["a", "b"]))
    assert payload["rows"][0]["cells"][1] == "0012345"
    assert payload["rows"][1]["number"] == 4


@pytest.mark.parametrize("mapping", [dict(organisation=""), dict(MAPPING, organisation="9" * 1000), dict(MAPPING, sector="0"), dict(MAPPING, city="20"), dict(MAPPING, role="-1"), dict(MAPPING, role="<script>"), dict(MAPPING, role="1.5")])
def test_invalid_mapping(db, workspace, mapping):
    pid = importer.upload_preview(db, workspace, raw_csv([ROW]))
    with pytest.raises(s.ValidationError):
        importer.map_preview(db, workspace, pid, mapping)
    assert importer.get_preview(db, workspace, pid)["plan"] is None


@pytest.mark.parametrize("field,value,message", [(0,"a"*161,"160"), (1,"a"*101,"100"), (2,"a"*101,"100"), (3,"a"*161,"160"), (4,"a"*243+"@example.com","254"), (5,"a"*101,"100"), (1,"","Sector"), (2,"","City"), (3,"","Contact name"), (4,"","Email"), (5,"","Role"), (4,"x@example.com<script>",None)])
def test_row_validation_and_boundaries(db, workspace, field, value, message):
    row = ROW.copy()
    row[field] = value
    pid = staged(db, workspace, [row])
    plan = importer.get_preview(db, workspace, pid)["plan"]
    if message:
        assert plan[0]["status"] == "reject" and message in plan[0]["actions"][0]
        assert importer.confirm(db, workspace, pid)["organisations"] == 0
    else:
        # The manual form uses the same basic syntax check; HTML remains escaped text.
        assert plan[0]["status"] == "ready"


@pytest.mark.parametrize("prefix", ["=1+1", "+SUM(A1)", "-2+3", "@SUM(A1)", '<script>alert("x")</script>'])
def test_hostile_text_is_literal_and_html_escaped(db, workspace, client, prefix):
    session_for(client, workspace)
    pid = staged(db, workspace, [[prefix, "IT", "Dubai", prefix, "literal@example.com", prefix]])
    page = client.get("/import/" + pid)
    assert b'<script>alert("x")</script>' not in page.data
    importer.confirm(db, workspace, pid)
    assert db.one("SELECT name FROM organisations WHERE workspace_id=?", (workspace,))["name"] == prefix
    assert db.one("SELECT role FROM contacts WHERE workspace_id=?", (workspace,))["role"] == prefix
    assert counts(db, workspace)["activities"] == 2
    exported = s.csv_export([dict(title=prefix, organisation_name=prefix, contact_name=prefix, service="E-waste", owner="Alex", stage="New", value_minor=None, next_action="Call")])
    first = list(csv.reader(io.StringIO(exported.lstrip("\ufeff"))))[1][0]
    assert first == ("'" + prefix if prefix[0] in "=+-@" else prefix)


def test_only_schema_fields_and_text_with_leading_zeros(db, workspace):
    pid = staged(db, workspace, [["00123", "IT", "Dubai", "", "", "", "0012345678"]], HEADERS + ["phone"])
    importer.confirm(db, workspace, pid)
    assert db.one("SELECT name FROM organisations WHERE workspace_id=?", (workspace,))["name"] == "00123"
    assert counts(db, workspace)["contacts"] == 0
    assert "phone" not in importer.guess_mapping(HEADERS + ["phone"])
    assert importer.guess_mapping(["Company", "Industry", "City", "Full_Name", "Email Address", "Job Title"]) == MAPPING


def test_schema_field_limits_are_inclusive_and_blank_rows_count(db, workspace):
    row = ["o" * 160, "s" * 100, "c" * 100, "n" * 160, "a" * 242 + "@example.com", "r" * 100]
    assert len(row[4]) == 254
    pid = staged(db, workspace, [row])
    assert importer.confirm(db, workspace, pid) == dict(organisations=1, contacts=1, skipped=0, rejected=0)
    assert len(importer.parse_csv(b"h\n" + b"\n" * 500)["rows"]) == 500
    with pytest.raises(s.ValidationError, match="500"):
        importer.parse_csv(b"h\n" + b"\n" * 501)


def test_workspace_isolation_all_preview_routes_and_matching(db, workspace, client):
    other = s.create_workspace(db, False)
    s.save_organisation(db, other, dict(name=ROW[0], sector="IT", city="Dubai"))
    pid = staged(db, workspace, [ROW])
    session_for(client, other)
    for path, method, data in [(f"/import/{pid}", "get", {}), (f"/import/{pid}/mapping", "get", {}), (f"/import/{pid}/mapping", "post", dict(csrf_token="fixture-csrf", **MAPPING)), (f"/import/{pid}/confirm", "post", dict(csrf_token="fixture-csrf"))]:
        response = getattr(client, method)(path, data=data)
        assert response.status_code == 404 and b"Cedar Example" not in response.data
    with pytest.raises(NotFound):
        importer.confirm(db, other, pid)
    assert importer.confirm(db, workspace, pid)["organisations"] == 1


@pytest.mark.parametrize("pid", ["a" * 31, "' OR 1=1--", "a" * 10000], ids=["short", "hostile", "oversized"])
def test_preview_ids_are_bounded_and_rejected_without_echo(db, workspace, client, pid):
    session_for(client, workspace)
    with pytest.raises(NotFound):
        importer.get_preview(db, workspace, pid)
    assert client.get("/import/" + pid).status_code == 404
    assert client.post("/import/" + pid + "/confirm", data=dict(csrf_token="fixture-csrf")).status_code == 404


@pytest.mark.parametrize("path", ["/import", "/import/missing/mapping", "/import/missing/confirm"])
def test_csv_posts_require_csrf(client, workspace, path):
    session_for(client, workspace)
    assert client.post(path, data={}).status_code == 400


def test_request_bounds_and_missing_upload(client, workspace):
    token = session_for(client, workspace)
    assert client.post("/import", data=dict(csrf_token=token)).status_code == 422
    large = b"x" * (importer.MAX_BYTES + 1)
    response = client.post("/import", data=dict(csrf_token=token, csv_file=(io.BytesIO(large), "big.csv")))
    assert response.status_code == 422 and b"256 KiB" in response.data
    response = client.post("/import", data=dict(csrf_token=token, csv_file=(io.BytesIO(large * 2), "big.csv")))
    assert response.status_code == 413
    assert client.post("/organisations/new", data=dict(csrf_token=token, name="x" * 70000)).status_code == 413


def test_malicious_headers_are_escaped_in_mapping(client, db, workspace):
    session_for(client, workspace)
    pid = importer.upload_preview(db, workspace, raw_csv([["literal"]], ['<script>alert("x")</script>']))
    response = client.get(f"/import/{pid}/mapping")
    assert b'<script>alert("x")</script>' not in response.data
    assert b"&lt;script&gt;" in response.data


@pytest.mark.parametrize("table,maximum", [("organisations", 100), ("contacts", 200), ("activities", 1500)])
def test_quota_rolls_back_whole_import(db, workspace, table, maximum):
    org = s.save_organisation(db, workspace, dict(name="Existing", sector="IT", city="Dubai"))
    with db.transaction():
        present = counts(db, workspace)[table]
        for index in range(maximum - 1 - present):
            if table == "organisations":
                db.execute("INSERT INTO organisations(id,workspace_id,name,sector,city) VALUES (?,?,?,?,?)", (s.uid(), workspace, f"Existing {index}", "IT", "Dubai"))
            elif table == "contacts":
                db.execute("INSERT INTO contacts(id,workspace_id,organisation_id,name,email,role) VALUES (?,?,?,?,?,?)", (s.uid(), workspace, org, "Known", f"known{index}@example.com", "IT"))
            else:
                db.execute("INSERT INTO activities(id,workspace_id,entity_type,entity_id,kind,body,created_at) VALUES (?,?,?,?,?,?,?)", (s.uid(), workspace, "organisation", org, "edit", "Fixture", s.stamp()))
    pid = staged(db, workspace, [ROW, ["Palm Example", "IT", "Dubai", "Sam", "sam@example.org", "IT"]])
    before = counts(db, workspace)
    with pytest.raises(s.ValidationError, match="Nothing imported"):
        importer.confirm(db, workspace, pid)
    assert counts(db, workspace) == before
    assert not importer.get_preview(db, workspace, pid)["consumed"]


def test_audit_failure_rolls_back_records_and_consumption(db, workspace, monkeypatch):
    pid = staged(db, workspace, [ROW])
    original = s.audit
    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Injected audit failure")
    monkeypatch.setattr(s, "audit", failing)
    with pytest.raises(RuntimeError):
        importer.confirm(db, workspace, pid)
    assert counts(db, workspace) == dict(organisations=0, contacts=0, activities=0)
    assert not importer.get_preview(db, workspace, pid)["consumed"]


def test_stale_preview_requires_review_and_confirm_needs_mapping(db, workspace):
    pid = importer.upload_preview(db, workspace, raw_csv([ROW]))
    with pytest.raises(s.Conflict, match="Map the columns"):
        importer.confirm(db, workspace, pid)
    importer.map_preview(db, workspace, pid, MAPPING)
    s.save_organisation(db, workspace, dict(name=ROW[0], sector="IT", city="Dubai"))
    with pytest.raises(s.Conflict, match="changed"):
        importer.confirm(db, workspace, pid)
    importer.map_preview(db, workspace, pid, MAPPING)
    assert importer.confirm(db, workspace, pid)["organisations"] == 0


def test_archived_and_ambiguous_organisations(db, workspace):
    org = s.save_organisation(db, workspace, dict(name=ROW[0], sector="IT", city="Dubai"))
    s.archive(db, "organisations", workspace, org, 1)
    pid = staged(db, workspace, [ROW])
    assert "Restore" in importer.get_preview(db, workspace, pid)["plan"][0]["actions"][0]
    s.save_organisation(db, workspace, dict(name=ROW[0].upper(), sector="IT", city="Dubai"))
    importer.map_preview(db, workspace, pid, MAPPING)
    assert "More than one" in importer.get_preview(db, workspace, pid)["plan"][0]["actions"][0]


def test_preview_count_and_storage_budgets(db, workspace):
    # A large ignored column still consumes the persistent upload budget.
    large = raw_csv([["x" * 1900] for _ in range(130)], ["organisation"])
    for _ in range(8):
        importer.upload_preview(db, workspace, large)
    with pytest.raises(TooManyRequests, match="storage limit"):
        importer.upload_preview(db, workspace, large)
    for _ in range(2):
        importer.upload_preview(db, workspace, raw_csv([ROW]))
    with pytest.raises(TooManyRequests, match="record limit"):
        importer.upload_preview(db, workspace, raw_csv([ROW]))


def test_concurrent_confirmation_is_single_use(app, db, workspace):
    pid = staged(db, workspace, [ROW])
    db.conn.commit()
    barrier = Barrier(4)
    def worker(_):
        with app.app_context():
            barrier.wait(timeout=10)
            return importer.confirm(get_db(), workspace, pid)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(worker, range(4)))
    assert all(result == dict(organisations=1, contacts=1, skipped=0, rejected=0) for result in results)
    assert counts(db, workspace) == dict(organisations=1, contacts=1, activities=2)


def test_concurrent_imports_cannot_exceed_quota(app, db, workspace):
    with db.transaction():
        for index in range(99):
            db.execute("INSERT INTO organisations(id,workspace_id,name,sector,city) VALUES (?,?,?,?,?)", (s.uid(), workspace, f"Existing {index}", "IT", "Dubai"))
    previews = [staged(db, workspace, [[name, "IT", "Dubai", "", "", ""]]) for name in ("New A", "New B")]
    db.conn.commit()
    barrier = Barrier(2)
    def worker(pid):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                importer.confirm(get_db(), workspace, pid)
                return "created"
            except s.ValidationError as error:
                assert "Nothing imported" in str(error)
                return "quota"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, previews))
    assert sorted(results) == ["created", "quota"]
    assert counts(db, workspace) == dict(organisations=100, contacts=0, activities=1)
