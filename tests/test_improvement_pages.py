import re

from conftest import session_for
from test_workflow import related, opportunity


def test_distinct_titles_metadata_icons_and_demo_path(client, db, workspace):
    landing = client.get("/")
    assert b"Track recycling enquiries" in landing.data
    session_for(client, workspace)
    org, contact = related(db, workspace)
    oid = opportunity(db, workspace, org, contact, title="<script>Title</script>")
    titles = set()
    for path in ("/", "/dashboard", "/opportunities", "/organisations", "/contacts", "/follow-ups", "/reports", "/import", "/integrations/followdesk", "/scope-import", "/organisations/new", "/contacts/new", "/opportunities/new", "/opportunities/" + oid, "/opportunities/" + oid + "/scopes", "/opportunities/" + oid + "/edit", "/organisations/" + org + "/edit", "/contacts/" + contact + "/edit"):
        page = client.get(path)
        assert page.status_code == 200
        title = re.search(rb"<title>(.*?)</title>", page.data)[1]
        assert title not in titles
        titles.add(title)
        assert b'property="og:title"' in page.data and b'property="og:description"' in page.data
        assert b'name="theme-color"' in page.data
        assert b"<script>Title</script>" not in page.data
        assert "script-src 'self'" in page.headers["Content-Security-Policy"]
    overview = client.get("/dashboard").data
    assert b"Try the 3-minute path" in overview and b'href="/opportunities.csv"' in overview
    assert overview.count(b'class="nav-icon"') == 4
    board = client.get("/opportunities").data
    assert b"All six stages" in board and b'aria-describedby="board-help"' in board
    assert b'tabindex="0"' in board and b"Lost" in board


def test_pairing_flow_and_error_recovery(client, workspace):
    token = session_for(client, workspace)
    page = client.post("/integrations/followdesk", data=dict(csrf_token=token, action="pair"))
    assert page.status_code == 200
    assert b'id="copy-pair-code" hidden' in page.data
    assert b' target="_blank" rel="noopener"' in page.data
    assert b"Never put this code in a URL" in page.data
    code = re.search(rb'id="pair-code" value="([^"]+)"', page.data)[1]
    assert all(code not in link for link in re.findall(rb'href="([^"]+)"', page.data))
    missing = client.get("/missing-page")
    assert missing.status_code == 404 and b"Page or record not found" in missing.data
    assert b"Back to overview" in missing.data
