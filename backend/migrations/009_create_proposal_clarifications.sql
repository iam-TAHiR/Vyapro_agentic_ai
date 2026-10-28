CREATE TABLE proposal_clarifications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    proposal_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    request_hash CHAR(64) NOT NULL,
    answer TEXT NOT NULL,
    proposal_version INT UNSIGNED NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_clarification_proposal FOREIGN KEY (proposal_id) REFERENCES order_proposals(id)
) ENGINE=InnoDB
