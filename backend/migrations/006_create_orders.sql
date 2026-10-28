CREATE TABLE orders (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    proposal_id VARCHAR(64) NOT NULL UNIQUE,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    customer_id VARCHAR(64) NOT NULL,
    source_channel VARCHAR(32) NOT NULL,
    external_reference VARCHAR(255) NULL,
    status VARCHAR(32) NOT NULL,
    total_minor BIGINT UNSIGNED NOT NULL,
    currency CHAR(3) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_order_proposal FOREIGN KEY (proposal_id) REFERENCES order_proposals(id),
    CONSTRAINT fk_order_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
) ENGINE=InnoDB
