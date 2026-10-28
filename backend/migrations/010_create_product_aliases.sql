CREATE TABLE product_aliases (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    product_id VARCHAR(64) NOT NULL,
    alias VARCHAR(255) NOT NULL,
    UNIQUE KEY uq_product_alias (product_id, alias),
    KEY ix_product_alias_lookup (alias),
    CONSTRAINT fk_product_alias_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB
