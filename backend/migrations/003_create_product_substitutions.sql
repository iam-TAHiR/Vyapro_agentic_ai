CREATE TABLE product_substitutions (
    product_id VARCHAR(64) NOT NULL,
    substitute_product_id VARCHAR(64) NOT NULL,
    reason VARCHAR(255) NOT NULL,
    PRIMARY KEY (product_id, substitute_product_id),
    CONSTRAINT fk_substitution_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_substitution_alternative FOREIGN KEY (substitute_product_id) REFERENCES products(id)
) ENGINE=InnoDB
