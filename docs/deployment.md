# Deployment runbook — projects linked, database provisioning pending

Updated 26 October 2026. No application deployment exists. A new **loopdesk** project (`prj_PBu1fIAONvCoQBLbLptQDntykAUp`) is created and linked in the user's existing Vercel scope `uzair-ba1c` (`team_9J7RIvaVArU0PAVj1U73qHwE`). ScopeDesk and FollowDesk have separate new projects. No existing project was repurposed.

The user subsequently granted full permission to finish and publish the app/source, and requested that new files, downloads, caches and artifacts be saved on D:. That authorisation is recorded and must not be requested again. Vercel's one-time team-access consent and a database connection remain external prerequisites; chat permission does not grant provider OAuth access. Application submission remains manual.

## Observed preflight

- Connected Vercel project listing succeeds.
- Team access was granted and the three new Flask project identities were read back and linked locally. The verified LoopDesk production hostname is `loopdesk-sigma.vercel.app`. No application is serving there yet.
- Production `APP_ENV`, exact trusted hostnames and links between the apps are configured. Database/session/vault credentials have not been installed in Vercel; no database was provisioned, and no credentials were pulled.
- The local shell cannot access PyPI. Cached wheels supplied the tested local environment.
- No local Vercel CLI, PostgreSQL server or container runtime was available. PostgreSQL and hosted behaviour remain untested. Neon was found in the plugin directory but is not connected; its connection would supply a direct provisioning route.
- The GitHub connector can update repository files/branches but has no repository-creation action. `f20230125-sudo/loopdesk` returned 404. The GitHub CLI is not installed and shell outbound networking is restricted. A new repository has not been created or substituted with another project.

## Deployment contents to review

The public source package contains Flask/Jinja source, static assets, migrations, pinned Python dependencies, tests, scripts, synthetic screenshots/CSV, public company research links and documentation. It excludes `private/`, `instance/`, secrets, `.env` files, `.vercel/`, the virtual environment, local cache and private application documents. The application bundle also excludes browser QA scripts and artifacts through `.vercelignore`.

`app.py` exports `app`. `pyproject.toml` declares the Vercel entrypoint and Python minimum. Assets live at `public/assets/`, with identical `/assets/` URLs locally and on the CDN. `vercel.json` sets a 30-second maximum duration. No build-time or import-time migration runs against a database.

The official [Vercel Flask guide](https://vercel.com/docs/frameworks/backend/flask), checked 24 October 2026, documents the Flask entrypoint and public asset directory. Recheck the platform settings when publishing.

## Required steps, in order

1. Project creation/linking is complete. Verify the recorded IDs before changing any resource. Publication is already authorised.
2. Provision a new persistent PostgreSQL database, preferably through the Vercel Marketplace Neon integration. Confirm the plan and any price before incurring a charge. Do not reuse a database from another portfolio project.
3. Add a random `SECRET_KEY` (at least 32 characters), a TLS-enabled `DATABASE_URL`, and `APP_ENV=production` to the intended environments. Store credentials in provider settings, not source or chat. Pull environment variables locally through an authenticated CLI if available, without printing values.
4. Apply migrations once through the CLI against that database, before serving traffic: `python -m flask --app app migrate`. Do not add migrations to the build command. Preview and production must have separate databases and secrets.
5. Run `scripts/manage.py test-postgres` with a dedicated `LOOPDESK_TEST_DATABASE_URL`. Business fixtures now use isolated unique schemas per test. Verify composite constraints, transactional rollback, expiry cascades and stale-write row counts on PostgreSQL. Existing SQLite success does not establish PostgreSQL success.
6. Regenerate the three reviewed runtime payloads with `../followdesk/scripts/prepare-suite.py` after any source change. Each app receives `.local/deployment/runtime-payload.json` and a checksum manifest bound to its verified project ID. They exclude credentials, databases and private application documents. Set the intended environment explicitly before using a deployment tool. The user's publication approval is already recorded.
7. Deploy to the approved environment. Smoke-test `/health`, the public overview, fresh demo creation, the complete enquiry journey, cross-browser isolation and CSV download without an existing login. Confirm HTTPS, Secure cookies, caching headers and restart persistence. Save separate hosted evidence and record the exact deployment URL.
8. Update the CV/project summary with an actual tested link only after the deployment passes. Never replace a local result with a claimed hosted result.

## Release decision

Current release status: **publication authorised; local application verified; Vercel projects linked; cloud release pending PostgreSQL provisioning, protected runtime secrets and deployment verification**. GitHub repositories now exist; source publication and CI are tracked separately. The source, recording and offline Windows package remain available on D:. The user alone submits the university application and retains its acknowledgement.

## D: storage policy

`scripts/manage.py` sets TEMP, TMP, TMPDIR, pip/npm cache, XDG cache and Python bytecode-cache locations under the project's `.local/` folder. Browser checks and recordings inherit these settings. `Start-LoopDesk.cmd` installs from the included wheel cache when present and delegates to the same launcher. No system environment variables or Windows storage locations are changed globally.

## Security review deployment gate

Apply all pending migrations, including database-backed request buckets and workspace revocation. Set explicit trusted hostnames using the application-specific `*_TRUSTED_HOSTS` variable, a real random secret and PostgreSQL. Cookie security is enforced after configuration overrides. Verify provider edge protection and connecting-client identity before tuning limits; arbitrary forwarding headers are deliberately ignored. Run the PostgreSQL suite, deployed HTTPS/session/host/origin tests and normal handoff journey before publishing. See `../../security-review/README.md` for the local audit and remaining checks. All three projects are to be deployed together later, following completion of the third project.
