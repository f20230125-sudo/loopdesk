# FollowDesk scoped connection

FollowDesk is a separately runnable local application at port 5059. LoopDesk remains the authority for contacts and opportunities. Migration `005_followdesk` adds hashed one-use pairing codes, hashed revocable grants and immutable outreach receipts without changing existing CRM records.

## Connect locally

Start both applications. In the same browser, open a private demo in each app. In LoopDesk choose **Outreach connection**, create a five-minute code and paste it into FollowDesk's CRM connection form. Redeeming a code creates a grant lasting at most one hour or the source workspace's remaining lifetime. It replaces any existing active grant for that LoopDesk workspace. Merely generating a code does not revoke the current connection.

The grant permits workspace-scoped opportunity/contact context reads and append-only outreach history. It cannot create contacts/opportunities or change stage, owner, value, next action or tasks. LoopDesk's connection page can revoke grants and unused codes. A FollowDesk reset/disconnect attempts issuer revocation and disables local access; if the issuer is unavailable it reports unconfirmed revocation and the source grant still expires.

Use only synthetic demo data. The simulated FollowDesk inbox sends no real email. An internal reviewed scope does not establish customer acceptance. FollowDesk can see only the latest scope revision received by LoopDesk, not changes that have not been exported.

## API boundary

All routes are under `/api/followdesk/v1`. The exchange accepts strict bounded JSON containing `pairing_code` and `client_workspace_id`. Other routes require the bearer grant; browser cookies cannot authorise API requests.

| Route | Purpose |
| --- | --- |
| `POST /exchange` | Consume a valid one-use code and issue a scoped grant |
| `GET /opportunities` | Bounded selection list from the source workspace |
| `GET /opportunities/<id>` | Current contact, organisation, opportunity and latest received scope summaries |
| `POST /events` | Validate a version-one event and append one immutable history entry |
| `POST /revoke` | Revoke the presenting grant |

`loopdesk/outreach_contract.py` fixes event fields and canonical SHA-256 integrity checking. A digest is not customer authentication. Grant identity supplies the issuer workspace; the event's client workspace must match that grant. The event key persists across reconnects. Repeating identical content returns the original receipt; reusing the key with different content returns 409. Delivery is local to FollowDesk; receipt retries cannot send another message or silently alter CRM fields.

For hosting, set `LOOPDESK_FOLLOWDESK_URL` to the fixed HTTPS FollowDesk origin. Production has no default localhost link. Hosted HTTPS, PostgreSQL and production dependency/secret configuration still require verification. The local test suite covers authenticated API isolation, expiry, revocation, malformed events, duplicate/conflicting events and concurrent exchanges/receipts. The three-app browser and clean offline package exercise real local HTTP.
