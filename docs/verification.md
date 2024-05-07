Latest verification, 26 October 2026: **121 checks pass on SQLite and PostgreSQL in Linux CI**. See `artifacts/ci-verification.json` and [the successful run](https://github.com/f20230125-sudo/loopdesk/actions/runs/40375197884). Hosted verification remains pending.

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

SQLite, PostgreSQL service-container CI, Flask test clients and local Chromium were exercised. No Vercel deployment or production Neon database has been verified. No real email delivery, staff sign-in, real-user load, manual assistive-technology review, backup/restore or production incident handling was tested. Layout captures establish the tested viewports, not every possible device.

The full business suite passes against isolated PostgreSQL schemas in GitHub Actions. The runtime driver uses bounded connection/statement timeouts and disables prepared statements for transaction-pooling compatibility. Neon-specific networking, TLS, pooling and production migrations remain separate checks.

Timeout and test-schema settings are applied at the start of each transaction, so they do not depend on retaining a server session through a pooler. This follows [PostgreSQL SET LOCAL semantics](https://www.postgresql.org/docs/current/sql-set.html), [psycopg transaction behaviour](https://www.psycopg.org/psycopg3/docs/basic/transactions.html) and [Neon pooling guidance](https://neon.com/docs/connect/connection-pooling). The passing PostgreSQL CI service is distinct from the pending production Neon check.

The browser run found and fixed ambiguous dropdown label names and mobile overflow caused by hidden text outside its scroll container. The complete journey subsequently passed. These findings do not imply real-world company use or a measured business improvement.
