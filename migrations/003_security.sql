CREATE TABLE security_buckets (
 bucket TEXT PRIMARY KEY, hits INTEGER NOT NULL CHECK(hits>0), expires_at BIGINT NOT NULL
);
CREATE INDEX ix_security_expiry ON security_buckets(expires_at);
