CREATE TABLE scope_links (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 case_id TEXT NOT NULL, opportunity_id TEXT NOT NULL, latest_revision INTEGER NOT NULL,
 PRIMARY KEY(workspace_id,case_id),
 FOREIGN KEY(workspace_id,opportunity_id) REFERENCES opportunities(workspace_id,id)
);
CREATE TABLE scope_imports (
 workspace_id TEXT NOT NULL, case_id TEXT NOT NULL, revision INTEGER NOT NULL,
 digest TEXT NOT NULL, payload TEXT NOT NULL, received_at TEXT NOT NULL,
 PRIMARY KEY(workspace_id,case_id,revision),
 FOREIGN KEY(workspace_id,case_id) REFERENCES scope_links(workspace_id,case_id) ON DELETE CASCADE
);
CREATE TABLE scope_previews (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 payload TEXT NOT NULL, created_at TEXT NOT NULL
);
