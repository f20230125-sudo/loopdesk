# LoopDesk improvement report — 27 October 2026

All five numbered priorities and the three listed UI defects are implemented in this working copy. No push, deployment, provider setting change, Neon operation, dependency installation or paid service was used. No runtime dependencies were added. Work, temporary files, caches, SQLite databases and evidence stayed inside this project on D:. Private folders and release archives were not accessed. Existing contracts and migrations 001–005 were not changed. The README Hosting status section was left untouched.

## Changes and files

- `loopdesk/csv_import.py`, `loopdesk/templates/csv_import.html`, `migrations/006_csv_import.sql`: Import navigation and UTF-8 CSV upload, explicit auto-guessed mapping, per-row preview and explicit single-use confirmation. Implements inclusive 256 KiB / 500 data row / 20 column / 2 KiB UTF-8 cell limits; header, encoding, quoting and control-character rejections; physical CSV start-line numbers; blank-row skips; workspace-scoped trimmed/case-folded organisation and email matching; archived/ambiguous record handling; stale preview review; and a fictional example download. Confirmation locks the workspace, checks all record/audit quotas, and writes all ready records with manual-style audit entries in one transaction. Repeated and concurrent confirmation cannot duplicate records. CSV results have a labelled keyboard-scrollable region and visible scroll instructions.
- `loopdesk/services.py`, `loopdesk/seed.py`: Pipeline health uses existing opportunities, stage events, activities and tasks. It reports the ten oldest opportunities inactive for `STALE_DAYS = 14` elapsed days, average current-stage days, destination-stage changes and completed/due follow-up counts. New completion/reopening audit entries retain the existing task ID. Legacy completion entries have unknown attribution. Seed history spans the preceding 45 days deterministically; totals remain 30 organisations, 30 contacts, 36 opportunities and 24 follow-ups, including 24 open, six won and six lost.
- `loopdesk/__init__.py`: Registers the CSV blueprint, raises only the CSV upload route's request envelope to allow its file plus bounded multipart overhead, and makes health require migration 006. Other routes retain their existing 64 KiB request limit.
- Templates `base.html`, `dashboard.html`, `opportunities.html`, `reports.html`, `followups.html`, `landing.html`, `outreach_connection.html`, `error.html`, `detail.html`, `form.html`, `scope_import.html`, `scope_history.html`: distinct internal navigation icons, six-stage board visibility/scroll guidance, concrete headlines and counts, report definitions and text values, five-step demonstration card, three-step two-tab pairing explanation, new-tab/noopener FollowDesk link, progressive copy button, page-specific titles, Open Graph metadata, theme colour and specific error recovery wording. Scope template changes are titles only; no handoff contract changes.
- `public/assets/app.js`, `public/assets/app.css`: clipboard copy/selection fallback and responsive/accessibility styling, including six columns fitting at 1440 px and scrollable stages at narrower widths. All commands still work without JavaScript. CSP and CSRF protections remain enabled.
- `tests/test_csv_import.py`, `tests/test_pipeline_health.py`, `tests/test_improvement_pages.py`, `tests/test_workflow.py`: 73 additional checks and the expected migration list update. Includes concurrent quota and confirmation tests, audit rollback, all CSV boundaries, hostile text, invalid IDs, workspace isolation, CSRF, empty/unknown reports, hand-computed expectations, Dubai-midnight windows, seed determinism and page metadata.
- `scripts/browser-check.mjs`, `scripts/capture-improvements.mjs`: extended local journey and repeatable before/after capture. New browser evidence uses dated filenames, preserving the original browser screenshots/results.
- `pyproject.toml`: only adds the project-local pytest cache directory; runtime dependencies are unchanged. `README.md` and `docs/verification.md` describe the final features, limits, definitions and current local counts separately from historical CI evidence.

## Verification

Full command, with TEMP/TMP/TMPDIR and PYTHONPYCACHEPREFIX set under this project's `.local/`:

```text
.venv\Scripts\python scripts\manage.py test
194 passed in 17.20s
```

Evidence: `artifacts/improvement-pytest-sqlite-2026-10-27.xml` (dated copy of the runner's `pytest-sqlite.xml`). The original baseline passed 121 tests before implementation. The final run has no warnings.

Browser command used the existing installed tools, with no download:

```text
LOOPDESK_BROWSER_PACKAGE=D:/codex/rx-market-pulse/dashboard/package.json
node scripts/browser-check.mjs
36 checks passed; 19 axe scans; 0 detected accessibility violations;
0 page exceptions; 0 HTTP 5xx responses.
```

Evidence: `artifacts/improvement-browser-verification-2026-10-27.json`, verified at `2026-10-27T01:53:15.689Z`, Chromium `156.0.8078.4`, local LoopDesk at port 5055. The run covers the original CRM journey, Lost at 1440/1024/390 px, clipboard success and denial fallback, JavaScript-disabled upload/mapping/preview/confirmation and keyboard scrolling, the single-use result and manual pairing without JavaScript. Axe needs scripting, so the same import HTML was scanned separately in a scripting-enabled tab. Automated scans do not constitute a complete accessibility review. Local `/health` returned `200 {"status":"ok"}` after applying migration 006.

Screenshots: 39 `improvement-2026-10-27-before-*.png` captures and 43 `after-*.png` captures cover existing pages with 1440×900 and 390×844 viewports, plus the pipeline at 1024×900. They are full-page screenshots, so image heights can exceed the viewport. Additional `journey-import-{upload,mapping,preview,result}-{desktop,mobile}.png` captures cover all new import screens; no earlier versions of those pages existed. Scope upload and empty history have before/after evidence; populated scope preview/history have additional after evidence. Pairing codes were excluded from screenshots. The local server started for this work was stopped after verification.

## Interpretation choices and limits for review

- The actual schema has no phone or notes fields. Those columns cannot be imported into contact records; the mapping page says this explicitly. No fields were invented. CSV parsing preserves text and leading zeros, including in uploaded preview cells; unmapped cells remain only in the temporary upload preview until workspace cleanup. Formula-like values remain literal text and existing opportunity exports still neutralise them. New organisations require real mapped sector/city values; contacts require name/email/role, matching manual creation.
- Thirty-day reports include today's Dubai date and the preceding 29 dates, from Dubai midnight through now. Initial creation events are excluded from stage-change counts. Completed follow-ups count distinct task IDs with completion audits in that window, including later reopenings; due follow-ups use their current due dates regardless of status. Legacy entries without task identity are explicitly unknown, with no guessed backfill. No completion timestamp column or additional report migration was introduced.
- CSV previews additionally have a ten-upload and 2 MiB uploaded-payload budget per workspace. Plans are bounded by file/row/cell limits. Invalid rows are excluded from confirmation; quota overflow rejects the entire import. If matching records change after review, confirmation requires a fresh mapping review.
- PostgreSQL cannot be run here. The 194-test source state has not been run against PostgreSQL or hosted infrastructure; the earlier 121-test CI checkpoint is historical. The lead should run the new suite on PostgreSQL and apply migration 006 only after review. New SQL uses bound parameters and portable statements; report date arithmetic stays in Python.
- A complete live ScopeDesk → LoopDesk → FollowDesk journey was not rerun. Existing contract, outreach and isolation tests passed; the new tab attributes, copy fallback and no-JavaScript pairing screen were checked locally. No other project was changed or server started.
- Intermediate checks exposed Windows-length automatic test IDs, shared-security byte-comparison failure, ambiguous mapping labels and browser-harness assumptions about scripting-disabled axe/polling. These were resolved; the shared security module remains unchanged. One initial browser attempt after a server restart returned a CSRF 400; its cause was not established, and subsequent fresh-context full journeys passed repeatedly without weakening CSRF. Watch for recurrence when reviewing with clean local ports.
- No implementation priority remains unfinished. Remaining checks are PostgreSQL CI, hosted verification, the full three-app journey and manual assistive-technology review, all outside the verification completed here.
