"""Shared order interpretation and proposal workflow for channel adapters."""

from app.llm import interpret_order
from app.order_service import create_proposal, find_idempotent_proposal


def process_order_message(text, channel, external_reference, idempotency_key, request_hash_override=None):
    """Interpret a normalized message and pass it to deterministic services."""
    existing = find_idempotent_proposal(
        text, channel, external_reference, idempotency_key, request_hash_override
    )
    if existing:
        return existing, False
    interpretation = interpret_order(text)
    return create_proposal(
        text, channel, external_reference, idempotency_key, interpretation, request_hash_override
    )
