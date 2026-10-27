"""Hosted smoke check for LoopDesk: standard library only, no secrets, synthetic demo workspace only.

    python scripts/live-smoke.py [base-url]    (a local http://127.0.0.1 URL skips the HTTPS-only checks)

Exit code 0 when every check passes, 1 otherwise. Each run creates one private 24-hour demo
workspace on the hosted app (the same thing a visitor's "Try demo" button does)."""
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://loopdesk-sigma.vercel.app").rstrip("/")
PAGES = [('/dashboard', 'Open opportunities'), ('/opportunities', 'Export filtered CSV'), ('/organisations', 'Organisations'), ('/contacts', 'Contacts'), ('/follow-ups', 'Follow-ups'), ('/reports', 'Pipeline health'), ('/import', 'Upload CSV'), ('/scope-import', 'Scope import'), ('/integrations/followdesk', 'Create pairing code')]
LOCAL = BASE.startswith(("http://127.", "http://localhost"))
HEADERS = {"content-security-policy": "default-src 'self'", "strict-transport-security": "max-age=", "x-content-type-options": "nosniff", "x-frame-options": "DENY"}

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail and not ok else ""))


def fetch(path, data=None):
    request = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode() if data else None, headers={"User-Agent": "live-smoke/1"})
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace"), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace"), error.headers


status, body, headers = fetch("/health")
check("health endpoint reports ok", status == 200 and json.loads(body).get("status") == "ok", f"status {status}")
status, body, headers = fetch("/")
check("landing page loads", status == 200 and "Try demo" in body, f"status {status}")
for name, expected in HEADERS.items():
    if LOCAL and name == "strict-transport-security":
        continue
    check(f"landing sends {name}", expected.lower() in headers.get(name, "").lower(), headers.get(name, "missing"))
token = re.search(r'name="csrf_token" value="([^"]+)"', body)
check("landing form carries a CSRF token", bool(token))
status, body, headers = fetch("/demo", {"csrf_token": token.group(1) if token else ""})
check("demo workspace opens", status == 200, f"status {status}")
cookies = [c for c in jar]
check("session cookie is " + ("HttpOnly" if LOCAL else "Secure and HttpOnly"), bool(cookies) and all((LOCAL or c.secure) and c.has_nonstandard_attr("HttpOnly") for c in cookies), ", ".join(c.name for c in cookies))
for path, text in PAGES:
    status, body, _ = fetch(path)
    check(f"{path} loads with expected content", status == 200 and text in body, f"status {status}")
status, body, _ = fetch("/no-such-page-for-smoke-check")
check("unknown page is a 404, not a server error", status == 404, f"status {status}")
failed = results.count(False)
print(f"{len(results) - failed}/{len(results)} checks passed against {BASE}")
sys.exit(1 if failed else 0)
