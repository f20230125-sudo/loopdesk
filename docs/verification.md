Hosted verification, 27 October 2026, against <https://loopdesk-sigma.vercel.app> (Vercel Hobby plus Neon PostgreSQL, both free plans): migration `006_csv_import` was applied to the production database first, then the deployment went out. `scripts/live-smoke.py` passed **19/19** checks (health, security headers, Secure/HttpOnly session cookie, every main page including `/import`, 404 page). The browser journey `scripts/browser-check.mjs` passed **36 checks** against the hosted origin, including the whole CSV import (upload, mapping, preview, confirm) on PostgreSQL, with **19 axe scans reporting no automated WCAG A/AA violations** and no page errors or HTTP 5xx responses. Record: `artifacts/hosted-verification-2026-10-27.json`. The scripts print a fixed "hosted: not run" string left over from the local runs; the JSON file is the hosted record. Not verified: that the Vercel client-address header changes the rate-limit key in production (the demo ran from one address), behaviour under real traffic, and any assistive-technology review.

Local verification, 27 October 2026: **195 tests pass on SQLite** (121 existing + 74 new; the last is the Vercel client-address test), **36 Chromium journey checks pass**, and **19 axe scans find no automated WCAG A/AA violations**. The new code's PostgreSQL behaviour is covered by the hosted run above and by the pull request's PostgreSQL CI job; the CI evidence below covers its earlier 121-test source state only.

New evidence:

- `artifacts/pytest-sqlite.xml`: full local suite, run with `.venv\Scripts\python scripts\manage.py test`.
- `artifacts/improvement-browser-verification-2026-10-27.json`: 36 named checks, Chromium version, timestamp and local scope.
- `artifacts/improvement-2026-10-27-*-axe.json`: 19 automated scans. JavaScript-disabled import is exercised directly; the same server-rendered HTML is scanned separately in a scripting-enabled tab because axe requires scripting.
- `artifacts/improvement-2026-10-27-before-*.png` and `after-*.png`: existing pages captured with 1440×900 and 390×844 viewports (full page), plus pipeline at 1024×900. New import screens have `journey-import-*.png` evidence; they have no prior page to capture.
- `artifacts/improvement-filtered-opportunities-2026-10-27.csv`: real browser download with one matching opportunity.
- [Improvement report](../artifacts/improvement-report-2026-10-27.md): files, exact test output, interpretation choices and remaining lead checks.

The additional automated coverage includes the exact CSV file/row/column/UTF-8-cell limits and rejections; blank/duplicate headers, bad encoding and quoting; mapping and field boundaries; existing and within-file duplicates; literal formulas and escaped HTML; leading-zero text; archived/ambiguous organisations; per-workspace preview limits; cross-workspace preview denial; CSRF; stale preview review; repeated/concurrent confirmation; audit rollback and quota rollback, including concurrent imports at the organisation cap. Health fixtures hand-compute stage age and inactivity, exercise the 14-day threshold and ten-row cap, isolate workspaces, handle legacy unknowns, deduplicate completions after reopening, and check Dubai-midnight date windows and seed determinism.

Earlier verification, 26 October 2026: **121 checks pass on SQLite and PostgreSQL in Linux CI**. See `artifacts/ci-verification.json` and [the successful run](https://github.com/f20230125-sudo/loopdesk/actions/runs/40375197884).

Historical security follow-up: **101 passing checks** (`artifacts/security-pytest.xml`). Earlier figures below document the initial release. The focused 17-probe retest, 1,009 mutation/parser cases and 40-check attack browser journey are recorded in `../../security-review/README.md`. Both original browser journeys pass after the fixes.

# Local verification — 25 October 2026

Story: a visitor starts a fictional workspace, creates an organisation and contact, logs a recycling enquiry, schedules and completes a follow-up, changes its stage, reviews reports and exports the filtered pipeline.

| Boundary | Result | Evidence |
| --- | --- | --- |
| Public overview → demo | Passed locally | Browser creates a new signed-cookie workspace without login. |
| Forms → Flask → database | Passed locally | Organisation/contact/opportunity journey; exact AED 1,250.55 persisted. |
| Database → activity and history | Passed locally | Note and stage transition remain after reload; version conflicts and failures roll back. |
| Tasks → dates → reports | Passed locally | Overdue/completed views; independent fixtures before and at Dubai midnight. |
| Filters → rows → CSV | Passed locally | Browser downloads one matching opportunity; automated fixtures reconcile filters and escape formula prefixes. |
| Separate visitor → tenant boundary | Passed locally | Other browser receives 404; automated tests deny cross-workspace reads and writes and enforce storage constraints. |
| Browser response → usability | Passed locally | Desktop 1440px and mobile 390px checks; keyboard skip link; validation; no page exceptions or HTTP 5xx responses. |

## Evidence files

- `artifacts/pytest-sqlite.xml` (and canonical `pytest.xml` copy): 51 passing automated checks. Tests use a fresh directory below the ignored `.local/` path. The three additional operations checks cover missing migrations, an unavailable database and redacted PostgreSQL connection failure; they do not constitute a successful PostgreSQL server test.
- `artifacts/browser-verification.json`: 20 named journey checks, Chromium version, timestamp and scope.
- `artifacts/*-axe.json`: ten automated WCAG A/AA scans across landing, overview, form, detail, reports and pipeline at desktop/mobile sizes. No detected violations. Automated scans are not a full accessibility certification.
- `artifacts/*-desktop.png`, `artifacts/*-mobile.png`: selected synthetic-data captures.
- `artifacts/filtered-opportunities.csv`: actual browser download from the filtered example.
- `artifacts/LoopDesk-Demo.webm`: real local browser recording with presentation captions. The chapter JSON describes those captions and timings.
- `artifacts/offline-verification.json`, when generated: clean-virtual-environment installation using only bundled wheels, readiness, demo creation, report rendering and a 36-opportunity CSV from the extracted Windows package.

## Limits

SQLite, PostgreSQL service-container CI, Flask test clients, local Chromium and (since 27 October 2026) the hosted Vercel/Neon deployment were exercised. No real email delivery, staff sign-in, real-user load, manual assistive-technology review, backup/restore or production incident handling was tested. Layout captures establish the tested viewports, not every possible device.

The full business suite passes against isolated PostgreSQL schemas in GitHub Actions. The runtime driver uses bounded connection/statement timeouts and disables prepared statements for transaction-pooling compatibility. Neon networking, TLS, pooling and the production migrations were exercised by the hosted run on 27 October 2026.

Timeout and test-schema settings are applied at the start of each transaction, so they do not depend on retaining a server session through a pooler. This follows [PostgreSQL SET LOCAL semantics](https://www.postgresql.org/docs/current/sql-set.html), [psycopg transaction behaviour](https://www.psycopg.org/psycopg3/docs/basic/transactions.html) and [Neon pooling guidance](https://neon.com/docs/connect/connection-pooling). The passing PostgreSQL CI service is distinct from the production Neon deployment, which has its own record above.

The browser run found and fixed ambiguous dropdown label names and mobile overflow caused by hidden text outside its scroll container. The complete journey subsequently passed. These findings do not imply real-world company use or a measured business improvement.
