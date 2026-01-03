CREATE TABLE revoked_workspaces (
 workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
 revoked_at TEXT NOT NULL
);
