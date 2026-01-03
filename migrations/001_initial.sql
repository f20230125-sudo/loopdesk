CREATE TABLE workspaces (
 id TEXT PRIMARY KEY,
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL
);
CREATE TABLE organisations (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 160),
 sector TEXT NOT NULL,
 city TEXT NOT NULL,
 archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
 version INTEGER NOT NULL DEFAULT 1,
 UNIQUE(workspace_id,id)
);
CREATE TABLE contacts (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 organisation_id TEXT NOT NULL,
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 160),
 email TEXT NOT NULL,
 role TEXT NOT NULL,
 archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
 version INTEGER NOT NULL DEFAULT 1,
 UNIQUE(workspace_id,id),
 UNIQUE(workspace_id,organisation_id,id),
 FOREIGN KEY(workspace_id,organisation_id) REFERENCES organisations(workspace_id,id)
);
CREATE TABLE opportunities (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 organisation_id TEXT NOT NULL,
 contact_id TEXT NOT NULL,
 title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
 service TEXT NOT NULL CHECK(service IN ('Battery recycling','E-waste','IT asset disposition')),
 owner TEXT NOT NULL,
 stage TEXT NOT NULL CHECK(stage IN ('New','Contacted','Qualified','Proposal','Won','Lost')),
 value_minor BIGINT CHECK(value_minor IS NULL OR value_minor BETWEEN 0 AND 999999999999),
 next_action TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 UNIQUE(workspace_id,id),
 FOREIGN KEY(workspace_id,organisation_id) REFERENCES organisations(workspace_id,id),
 FOREIGN KEY(workspace_id,organisation_id,contact_id) REFERENCES contacts(workspace_id,organisation_id,id)
);
CREATE TABLE activities (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 opportunity_id TEXT,
 entity_type TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 kind TEXT NOT NULL,
 body TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(workspace_id,opportunity_id) REFERENCES opportunities(workspace_id,id)
);
CREATE TABLE tasks (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 opportunity_id TEXT NOT NULL,
 title TEXT NOT NULL,
 due_date TEXT NOT NULL,
 completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
 version INTEGER NOT NULL DEFAULT 1,
 UNIQUE(workspace_id,id),
 FOREIGN KEY(workspace_id,opportunity_id) REFERENCES opportunities(workspace_id,id)
);
CREATE TABLE stage_events (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 opportunity_id TEXT NOT NULL,
 from_stage TEXT,
 to_stage TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(workspace_id,opportunity_id) REFERENCES opportunities(workspace_id,id)
);
CREATE INDEX ix_opportunities_workspace_stage ON opportunities(workspace_id,stage);
CREATE INDEX ix_tasks_workspace_due ON tasks(workspace_id,completed,due_date);
CREATE INDEX ix_activity_workspace_entity ON activities(workspace_id,entity_type,entity_id);
CREATE INDEX ix_workspace_expiry ON workspaces(expires_at);
