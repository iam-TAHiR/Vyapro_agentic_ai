ALTER TABLE order_proposal_items
    ADD COLUMN offered_quantity DECIMAL(14, 3) UNSIGNED NULL AFTER requested_quantity,
    ADD COLUMN remaining_quantity DECIMAL(14, 3) UNSIGNED
        GENERATED ALWAYS AS (GREATEST(requested_quantity - COALESCE(offered_quantity, requested_quantity), 0)) STORED AFTER offered_quantity
