CREATE TABLE data_import_batches (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    fingerprint CHAR(64) NOT NULL UNIQUE,
    content_sha256 CHAR(64) NOT NULL,
    source_filename VARCHAR(255) NOT NULL,
    source_format VARCHAR(16) NOT NULL,
    allow_updates BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(24) NOT NULL,
    confirmation_key VARCHAR(128) NULL UNIQUE,
    staged_data JSON NOT NULL,
    summary JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL
) ENGINE=InnoDB
