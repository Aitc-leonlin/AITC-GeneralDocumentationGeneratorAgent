CREATE TABLE IF NOT EXISTS report_conversation_thread (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES membership_user(id),
    title TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_report_conversation_thread_user_updated
ON report_conversation_thread(user_id, updated_at DESC);

INSERT INTO membership_schema_migrations (version, description)
VALUES ('V1.13', 'Add account-scoped report conversation threads')
ON CONFLICT (version) DO UPDATE SET description = EXCLUDED.description;
