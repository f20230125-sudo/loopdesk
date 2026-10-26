CREATE TABLE outreach_pair_codes (
 token_hash TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 expires_at TEXT NOT NULL,
 used INTEGER NOT NULL DEFAULT 0 CHECK(used IN (0,1))
);
CREATE TABLE outreach_grants (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 client_workspace_id TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE,
 expires_at TEXT NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1))
);
CREATE UNIQUE INDEX ix_outreach_one_grant ON outreach_grants(workspace_id) WHERE revoked=0;
CREATE TABLE outreach_receipts (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 source_workspace_id TEXT NOT NULL,
 event_id TEXT NOT NULL,
 opportunity_id TEXT NOT NULL,
 activity_id TEXT NOT NULL,
 payload TEXT NOT NULL,
 digest TEXT NOT NULL,
 received_at TEXT NOT NULL,
 PRIMARY KEY(workspace_id,source_workspace_id,event_id),
 FOREIGN KEY(workspace_id,opportunity_id) REFERENCES opportunities(workspace_id,id)
);
