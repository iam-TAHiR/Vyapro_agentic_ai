CREATE TABLE customer_product_prices (
    customer_id VARCHAR(64) NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    unit_price_minor BIGINT UNSIGNED NOT NULL,
    currency CHAR(3) NOT NULL,
    PRIMARY KEY (customer_id, product_id),
    CONSTRAINT fk_customer_product_price_customer FOREIGN KEY (customer_id) REFERENCES customers(id),
    CONSTRAINT fk_customer_product_price_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB
