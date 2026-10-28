ALTER TABLE order_items
    ADD COLUMN remaining_quantity DECIMAL(14, 3) UNSIGNED NOT NULL DEFAULT 0 AFTER quantity,
    ADD COLUMN requested_quantity DECIMAL(14, 3) UNSIGNED
        GENERATED ALWAYS AS (quantity + remaining_quantity) STORED AFTER remaining_quantity
