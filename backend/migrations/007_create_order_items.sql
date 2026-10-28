CREATE TABLE order_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    quantity DECIMAL(14, 3) UNSIGNED NOT NULL,
    unit VARCHAR(32) NOT NULL,
    unit_price_minor BIGINT UNSIGNED NOT NULL,
    line_total_minor BIGINT UNSIGNED NOT NULL,
    currency CHAR(3) NOT NULL,
    CONSTRAINT fk_order_item_order FOREIGN KEY (order_id) REFERENCES orders(id),
    CONSTRAINT fk_order_item_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB
