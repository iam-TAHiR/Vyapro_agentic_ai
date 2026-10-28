CREATE TABLE imported_order_history (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    external_order_id VARCHAR(128) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    order_date DATETIME NOT NULL,
    status VARCHAR(32) NOT NULL,
    total_minor BIGINT UNSIGNED NOT NULL,
    currency CHAR(3) NOT NULL,
    source_import_id VARCHAR(64) NOT NULL,
    UNIQUE KEY uq_imported_order_customer (customer_id, external_order_id),
    CONSTRAINT fk_imported_order_customer FOREIGN KEY (customer_id) REFERENCES customers(id),
    CONSTRAINT fk_imported_order_batch FOREIGN KEY (source_import_id) REFERENCES data_import_batches(id)
) ENGINE=InnoDB
