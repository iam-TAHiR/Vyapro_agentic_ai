CREATE TABLE order_proposals (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    request_hash CHAR(64) NOT NULL,
    source_channel VARCHAR(32) NOT NULL,
    external_reference VARCHAR(255) NULL,
    original_text TEXT NOT NULL,
    interpretation JSON NOT NULL,
    status VARCHAR(32) NOT NULL,
    version INT UNSIGNED NOT NULL DEFAULT 1,
    customer_id VARCHAR(64) NULL,
    total_minor BIGINT UNSIGNED NULL,
    currency CHAR(3) NULL,
    validation JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_proposal_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
) ENGINE=InnoDB
