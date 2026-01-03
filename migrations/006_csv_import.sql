CREATE TABLE csv_previews (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 payload TEXT NOT NULL,
 created_at TEXT NOT NULL,
 mapping TEXT,
 plan TEXT,
 consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0,1)),
 result TEXT
);
CREATE INDEX ix_csv_previews_workspace ON csv_previews(workspace_id);
