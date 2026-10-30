-- SQLite: Chatbot document upload metadata. Raw files live in document storage.

CREATE TABLE IF NOT EXISTS chat_document (
    document_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    upload_user_id TEXT NOT NULL,
    case_id TEXT,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    storage_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'UPLOADED',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (chat_id) REFERENCES chat_conversation(id) ON DELETE CASCADE,
    FOREIGN KEY (upload_user_id) REFERENCES membership_user(id)
);

CREATE INDEX IF NOT EXISTS idx_chat_document_chat_created
ON chat_document(chat_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_document_user_chat
ON chat_document(upload_user_id, chat_id);

CREATE TABLE IF NOT EXISTS chat_message_document (
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    document_id TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (conversation_id, message_id, document_id),
    FOREIGN KEY (conversation_id, message_id)
        REFERENCES chat_conversation_message(conversation_id, id)
        ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES chat_document(document_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_message_document_message
ON chat_message_document(conversation_id, message_id, sort_order);

INSERT OR REPLACE INTO membership_schema_migrations (version, description)
VALUES ('V1.12', 'Add Chatbot document storage and message associations');
