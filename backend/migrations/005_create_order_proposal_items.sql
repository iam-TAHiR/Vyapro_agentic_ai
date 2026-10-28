CREATE TABLE order_proposal_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    proposal_id VARCHAR(64) NOT NULL,
    requested_product_text VARCHAR(255) NOT NULL,
    requested_quantity DECIMAL(14, 3) UNSIGNED NOT NULL,
    requested_unit VARCHAR(32) NOT NULL,
    product_id VARCHAR(64) NULL,
    substitute_product_id VARCHAR(64) NULL,
    substitution_reason VARCHAR(255) NULL,
    unit_price_minor BIGINT UNSIGNED NULL,
    line_total_minor BIGINT UNSIGNED NULL,
    currency CHAR(3) NULL,
    line_status VARCHAR(32) NOT NULL,
    CONSTRAINT fk_proposal_item_proposal FOREIGN KEY (proposal_id) REFERENCES order_proposals(id),
    CONSTRAINT fk_proposal_item_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_proposal_item_substitute FOREIGN KEY (substitute_product_id) REFERENCES products(id)
) ENGINE=InnoDB
