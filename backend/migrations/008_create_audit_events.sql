CREATE TABLE audit_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    proposal_id VARCHAR(64) NULL,
    order_id VARCHAR(64) NULL,
    event_type VARCHAR(64) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    source_channel VARCHAR(32) NOT NULL,
    details JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_proposal FOREIGN KEY (proposal_id) REFERENCES order_proposals(id),
    CONSTRAINT fk_audit_order FOREIGN KEY (order_id) REFERENCES orders(id)
) ENGINE=InnoDB
