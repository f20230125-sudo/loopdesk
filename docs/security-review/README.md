Public copy of the local three-app workspace audit. Suite-relative reproduction paths below refer to the offline suite layout.

# LoopDesk and ScopeDesk — adversarial security review

Reviewed locally on 26 October 2026 at the user's request. Scope: owned Flask applications, isolated synthetic SQLite databases and real Chromium/HTTP requests. No third-party website was attacked, no real customer data was used, and no deployment was performed.

## Findings and fixes

Severity is an assessment for these public-demo prototypes, not a CVSS certification. Configuration findings describe conditions that would matter at deployment; neither application is currently hosted.

| Finding | Evidence before the fix | Resolution and verification |
| --- | --- | --- |
| Oversized integers crash handlers — Medium availability | A 100-digit version caused HTTP 500 in both apps. ScopeDesk query/path revisions also caused 500. | Strict ASCII positive integer and length/range checks run before conversion/SQL binding. Invalid versions return 409 and invalid revisions 422, without writes. |
| Known placeholder session secret accepted — High if deployed with it | ScopeDesk accepted the exact long placeholder from its environment example as a production signing key. | Both apps reject known placeholder patterns, short secrets and repeated/low-diversity values. The placeholder is not treated as an actual random key. |
| Secure cookie omitted through factory configuration — Medium, conditional | Setting `PRODUCTION=True` through the factory while the environment was development left `SESSION_COOKIE_SECURE=False`. The normal `APP_ENV=production` path already set it correctly. | Cookie security is enforced after all configuration overrides. A real HTTPS-base test checks Secure, HttpOnly, SameSite and HSTS. |
| Old workspace cookie survived reset — Medium session lifecycle | A saved pre-reset signed cookie could still read the previous workspace after a successful reset. This requires possession of that cookie; no cookie theft was demonstrated. | Reset records server-side revocation. The old cookie can no longer read or write; retained records remain for expiry cleanup. Revocation rows cascade during cleanup. |
| Reset/upload/history resource accumulation — Medium availability | Eight rapid resets all succeeded in each app. Twelve inventory previews all persisted in ScopeDesk. Individual upload-size limits did not bound aggregate stored data. | Persistent IP/workspace request budgets, record quotas, aggregate byte budgets, combined inventory limits and revision limits. HTTP 429 includes Retry-After. Fresh cookies and spoofed forwarding headers do not bypass the IP budget. |
| Source-reference output amplification — Medium availability | A scope detail accepted 1,500 repeated source references. Cross-products between many allocations and count findings could duplicate citations into large responses. | Details require 1–32 distinct valid citations. Findings deduplicate and show at most 32 citations, with an explicit remaining count. Full allocation evidence is retained. Tests preserve the scope while bounding output. |
| Missing host/origin restrictions — defence in depth | Foreign Host requests returned 200. A foreign-origin POST with an already-valid CSRF token succeeded. No synchronizer-token bypass was found. | Explicit trusted hosts; exact scheme/host/port Origin matching; cross-site Fetch Metadata rejection; duplicate form-field rejection. Normal token checks remain required. Production fails closed without an explicit host list. |
| Special identifier handling — Low data integrity | Adding a `__proto__` duplicate-review key through JavaScript assigned the object's prototype instead of retaining an ordinary decision key. This was not a global prototype-pollution or code-execution demonstration. | Define an enumerable own property. A real browser confirms the identifier survives in the saved form state as text. |

Quotas serialize their check and write: PostgreSQL uses a workspace row lock; SQLite takes a write lock before the count. Simultaneous HTTP submissions at a quota boundary produce one success and five 429 responses, with the stored count staying at the limit. PostgreSQL execution remains pending, so that locking path is prepared rather than claimed tested.

## Retest results

| Check | Result | Evidence |
| --- | --- | --- |
| Focused exploit/hardening probes | 17/17 pass after fixes | [Retest](retest.json), [original baseline](baseline.json), [cookie-replay baseline](replay-baseline.json) |
| ScopeDesk automated suite | 92 pass, including all original 51 | `../scopedesk/artifacts/security-pytest.xml` |
| LoopDesk automated suite | 101 pass, including the previous 71 and original 51 | `../loopdesk/artifacts/security-pytest.xml` |
| Deterministic scope-state mutations | 629: 564 rejected with 422; 65 valid edits accepted; no unexpected failure or failed-write mutation | [Mutation report](fuzz-results.json) |
| Handoff mutations | 374: schema/digest validation handled every input; 28 structurally valid variations accepted | Same report |
| Malformed parser inputs | Six bounded nesting/encoding/duplicate-key/number probes, all handled | Same report |
| Real attack browser journey | 40 checks passed; no injected dialogs or script exceptions | [Browser evidence](browser-security.json) |
| Original normal browser journeys | ScopeDesk 43 and LoopDesk 20 checks pass after security changes | Application artifact reports |
| Accessibility regression | 11 new-flow scans and ten original LoopDesk scans, no automated violations | Application artifact reports |
| Dependency consistency | `pip check` passes in both environments | Runtime pins unchanged |

The mutation corpus deliberately disables the request limiter only in its isolated scratch app so it can exercise validation paths. Rate limits, cookie changes, forwarding-header spoofing, quota failures, rollback and concurrent submissions are tested separately with the controls enabled. Mutations include valid values, so accepting a documented valid variation is expected; the criterion is correct validation and state safety, not rejecting every changed byte.

The browser used hostile enquiry/client text, a hostile CSV item and path-like filename, template expressions, malicious assumptions, stored activity text, reviewed JSON and downloaded standalone HTML. It checked the preview, editor, scope brief, HTML download without server CSP, CRM opportunity and immutable history. Cross-workspace reads, signed-cookie forgery, replay after reset, SQL-like filters, file/secret traversal attempts, Windows device paths, oversized revisions, foreign-origin submission and framing were exercised. No business responses were mocked.

## New runtime limits

| Limit | Value |
| --- | --- |
| Demo creation/reset per source IP | 5 per fixed minute; 20 per fixed hour |
| Other POSTs per source IP / workspace | 120 / 90 per minute |
| Protected reads per source IP / workspace | 600 / 240 per minute |
| Multipart fields | 32, within the existing total body limits |
| ScopeDesk cases / workspace | 20 |
| Inventory / case | 1,000 records across all committed imports |
| Immutable sources / case | 40; original source text totals at most 1 MiB per workspace |
| Pending CSV previews | 10 per case, 30 per workspace; raw CSV total at most 1 MiB |
| Scope details / findings | 32 distinct source references per detail; 32 displayed citations per finding, with remainder disclosed |
| Scope revisions | 20 per case; snapshots total at most 8 MiB per workspace |
| Scope audit events | 1,000 per workspace |
| CRM organisations / contacts / opportunities / tasks | 100 / 200 / 150 / 300 per workspace |
| CRM activities | 1,500 per workspace |
| CRM pending scope previews | 30; payload total at most 1 MiB per workspace |
| CRM imported revisions | 20 per case; payload total at most 2 MiB per workspace |

These are demo budgets and return explicit errors rather than deleting accepted source rows or silently dropping history. Global active-workspace capacity and 24-hour expiry remain. Request counters are persisted in the application database, not an in-process dictionary, and stored IP subjects are keyed hashes rather than raw addresses. Client-supplied `X-Forwarded-For` and `X-Forwarded-Host` are ignored.

## Deployment checks still required

This is a local security pass, not a production penetration-test certification or a guarantee that no flaws remain. PostgreSQL transactions/locking, real HTTPS, provider ingress, trusted proxy identity, global abuse protection, dependency scanning against a complete advisory database and operational controls still need verification before deployment. Behind a proxy the default limiter sees the connecting proxy address; configure provider edge protection and verified forwarding behaviour during the later deployment phase, not by trusting arbitrary forwarding headers now. These controls do not claim to stop a distributed denial-of-service attack.

The applications remain synthetic 24-hour demos without staff authentication. Offline handoff hashes provide integrity and can be recomputed; they are not customer signatures or proof of approval. No authentication bypass, stored script execution, cross-workspace disclosure or SQL execution was found in the exercised paths. Absence of a successful attack in this corpus is not proof of universal safety.

The dependency check was a manual review of the publishers' Flask/Werkzeug/Jinja advisory pages plus installed-version consistency, not a full automated SCA run. Werkzeug is already pinned to 3.1.9, which includes the publisher's [NTFS device-name fix](https://github.com/pallets/werkzeug/security/advisories/GHSA-g6x2-hccm-hh4m). The browser path probes also returned safe responses. No dependency upgrade is claimed.

Controls were checked against [Flask's security guidance](https://flask.palletsprojects.com/en/stable/web-security/), [OWASP CSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html) and [OWASP application resource-limit guidance](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html). All artifacts, scratch databases, caches and temporary files for this review are on D:.

## Reproduce locally

Use either prepared Python environment with the D: cache/temp settings from the application launcher. From the shared parent directory:

```powershell
scopedesk\.venv\Scripts\python security-review\probe.py retest
scopedesk\.venv\Scripts\python security-review\fuzz.py
scopedesk\.venv\Scripts\python security-review\serve.py scopedesk 5068
# Separate terminal:
scopedesk\.venv\Scripts\python security-review\serve.py loopdesk 5065
# With the existing Playwright installation available:
node security-review\browser-security.mjs
```

The test servers have their own synthetic databases under `security-review/.local`; no user workspace is overwritten. Both original application test suites and browser scripts remain runnable. Deployment is intentionally deferred until after the planned third project.
