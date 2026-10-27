# Deployment runbook

Hosted since 27 October 2026 at <https://loopdesk-sigma.vercel.app>.

## Where it runs

- **Application:** a Vercel project on the free Hobby plan (Python/Flask runtime; `app.py` exports `app`, `pyproject.toml` declares the entrypoint and the dependencies Vercel installs, `vercel.json` sets a 30-second maximum duration).
- **Database:** a Neon PostgreSQL database on Neon's free plan, added through the Vercel Marketplace. Each of the three apps has its own database; nothing is shared and no database from another project is reused. The app connects through Neon's pooled endpoint (prepared statements are disabled for it); migrations use the direct, unpooled endpoint.
- **Static assets:** `public/assets/` is served by Vercel's CDN at the same `/assets/` URLs as locally.

Nothing here needs a paid plan. If a free limit blocks a step, stop and change the design instead of upgrading.

## Environment

| Name | Purpose |
| --- | --- |
| `APP_ENV=production` | Turns on the production guards below. |
| `DATABASE_URL` | PostgreSQL connection string with TLS. SQLite is refused in production. |
| `SECRET_KEY` | Random session secret, at least 32 characters. Stored as a write-only (sensitive) variable. |
| `LOOPDESK_TRUSTED_HOSTS` | Exact host names the app answers to. Requests for any other host are rejected. |
| `LOOPDESK_FOLLOWDESK_URL` | HTTPS origin of FollowDesk, used for the "Open FollowDesk" link. Without it the link is omitted; production has no localhost default. |

Credentials live in the provider's settings, never in source, chat or logs. Production and preview must use separate databases and secrets.

## Release procedure, in order

1. Run the test suites (`python scripts/manage.py test`; the PostgreSQL job runs in GitHub Actions) and the local browser journey.
2. Apply migrations to the production database **before** deploying code that needs them: `python -m flask --app app migrate` with `DATABASE_URL` set to the unpooled Neon URL. Migrations never run at import or during a build. They are forward-only and additive, so the previous deployment keeps working while the new schema is in place. `/health` returns `migration_required` (HTTP 503) until the latest migration is present.
3. Build the allowlisted runtime payload with `scripts/prepare-deployment.py` (or, for all three apps at once, `../followdesk/scripts/prepare-suite.py`). It contains only runtime code, assets, migrations and dependency configuration, with a checksum manifest, and excludes tests, screenshots, databases, credentials and private material. Deploy it to the production project through Vercel's deployments API.
4. Verify the hosted app: `python scripts/live-smoke.py` (health, security headers, cookie flags, every main page, 404 page), then the browser journey with `LOOPDESK_URL=https://loopdesk-sigma.vercel.app node scripts/browser-check.mjs`. Record the results in [verification](verification.md).

A weekly GitHub Actions workflow (`live-smoke.yml`) runs the smoke check against the hosted app.

## Defects that only showed up when hosted

Found and fixed on the first deployment, because CI cannot exercise the production-only code path:

- Vercel installs from `pyproject.toml`, not `requirements.txt`, so the dependency list is duplicated in `pyproject.toml` (keep both in step).
- A function-local import that only ran in the non-production branch broke one production route in a sibling app. Production-only branches are not covered by the local suite, so every deployment is followed by the hosted journey.

## Production configuration guards

Production refuses SQLite, an absent or short secret and missing trusted hosts; it enables Secure, HttpOnly, SameSite=Lax session cookies and HSTS. Request limits are keyed on the visitor's address. Behind Vercel that is the `X-Vercel-Forwarded-For` header, which the platform sets to the client's public address and overwrites if a client supplies one ([Vercel request headers](https://vercel.com/docs/headers/request-headers)); everywhere else forwarding headers are ignored, because anyone could spoof them. Before this was added every visitor could have shared the proxy's address and therefore one demo budget (20 demos an hour). Check provider edge protection before tuning the limits.

## Free-tier behaviour

Neon suspends an idle database, so the first request after a quiet period can take a second or two longer. Neon's free allowance is 1 GB and 100 compute-hours per project, which is ample for demonstration traffic. The demo has a 250 active-workspace capacity guard, and expired workspaces are removed opportunistically when a new one is created.

## Local storage

`scripts/manage.py` keeps TEMP, TMP, TMPDIR, pip/npm cache, XDG cache and Python bytecode cache under the project's `.local/` folder; no system environment variable or storage location is changed.
