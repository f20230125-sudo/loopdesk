Security follow-up, 26 October 2026: current suite **101 passing checks** (`artifacts/security-pytest.xml`). The earlier figures below document the initial release. The focused 17-probe retest, 1,009 mutation/parser cases and 40-check attack browser journey are recorded in `../../security-review/README.md`. Both original browser journeys pass after the fixes. PostgreSQL and hosted verification remain pending.

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

SQLite, Flask test clients and local Chromium were exercised. No hosted deployment or PostgreSQL runtime has been verified. No external system, email delivery, staff sign-in, real-user load, manual assistive-technology review, data backup/restore or production incident handling was tested. Layout captures establish the tested viewports, not every possible device.

The full business suite now supports isolated PostgreSQL schemas, and a GitHub Actions workflow defines a PostgreSQL service-container job. Both remain unexecuted until an actual database or repository is available. The runtime PostgreSQL driver uses a bounded connection timeout, statement timeout and disables prepared statements for compatibility with transaction-pooling endpoints.

Timeout and test-schema settings are applied locally at the start of each transaction, so they do not depend on retaining a server session through a pooler. This follows [PostgreSQL SET LOCAL semantics](https://www.postgresql.org/docs/current/sql-set.html), [psycopg transaction behaviour](https://www.psycopg.org/psycopg3/docs/basic/transactions.html) and [Neon pooling guidance](https://neon.com/docs/connect/connection-pooling). Documentation review is not a substitute for the pending PostgreSQL execution check.

The browser run found and fixed ambiguous dropdown label names and mobile overflow caused by hidden text outside its scroll container. The complete journey subsequently passed. These findings do not imply real-world company use or a measured business improvement.
