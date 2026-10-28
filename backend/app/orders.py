"""REST routes for proposals, orders, approvals, and order activity."""

import base64
import binascii
import hashlib
import json
import uuid

import mysql.connector
from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from app.database import DatabaseNotConfiguredError
from app.llm import (
    InvalidInterpretationError,
    LLMNotConfiguredError,
    LLMUnavailableError,
    interpret_order,
    transcribe_audio,
)
from app.order_service import (
    WorkflowError,
    approve_proposal,
    clarify_proposal,
    find_clarification,
    find_idempotent_proposal,
    get_clarification_context,
    get_order,
    get_order_events,
    get_customer_order_history_by_id,
    get_proposal,
    list_orders,
    list_proposals,
    reject_proposal,
    fulfill_pending_order,
    create_proposal,
)
from app.rule_parser import build_order_interpretation
from app.workflow import process_order_message
from app.agent import run_assistant_turn


orders_blueprint = Blueprint("orders", __name__)


@orders_blueprint.before_request
def require_local_development():
    if current_app.config.get("APP_ENV") != "development":
        return _error("AUTHORIZATION_NOT_CONFIGURED", "Order APIs are disabled outside local development until authentication is configured.", 503)


@orders_blueprint.errorhandler(HTTPException)
def handle_http_error(error):
    return _error("HTTP_ERROR", error.description, error.code or 500)


@orders_blueprint.errorhandler(Exception)
def handle_unexpected_error(_error):
    return _error("INTERNAL_ERROR", "The request could not be completed.", 500)


def _error(code, message, status, details=None):
    return jsonify(
        error={
            "code": code,
            "message": message,
            "requestId": str(uuid.uuid4()),
            "details": details or [],
        }
    ), status


def _offset_from_cursor(value):
    if not value:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii")).decode("ascii")
        offset = int(decoded)
        if offset < 0:
            raise ValueError
        return offset
    except (ValueError, UnicodeError, binascii.Error):
        raise WorkflowError("INVALID_CURSOR", "The page cursor is invalid.", 400)


@orders_blueprint.get("/customer-orders")
def customer_orders():
    customer_id = request.args.get("customerId", "").strip()
    if not customer_id or len(customer_id) > 64:
        return _error("CUSTOMER_REQUIRED", "Choose a registered customer account to view its saved orders.", 400)
    try:
        result = get_customer_order_history_by_id(customer_id, 20)
        if not result.get("customerMatched"):
            return _error("CUSTOMER_NOT_FOUND", "The selected customer account was not found.", 404)
        return jsonify(customer=result["customer"], orders=result["orders"]), 200
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Customer order status requires MySQL.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "Customer order status is temporarily unavailable.", 503)


@orders_blueprint.post("/assistant/messages")
def assistant_message():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("INVALID_REQUEST", "A JSON request body is required.", 400)
    actor = body.get("actor")
    message = body.get("message")
    proposal_id = body.get("proposalId")
    selected_customer_id = body.get("selectedCustomerId")
    confirmation = body.get("confirmation")
    page_context = body.get("pageContext")
    purpose = body.get("purpose", "business")
    key = request.headers.get("Idempotency-Key", "").strip()
    if not isinstance(actor, str) or actor not in {"customer", "shopkeeper"}:
        return _error("INVALID_ACTOR", "actor must be customer or shopkeeper.", 400)
    if not isinstance(purpose, str) or purpose not in {"business", "helper"}:
        return _error("INVALID_REQUEST", "purpose must be business or helper.", 400)
    if not isinstance(message, str) or not message.strip() or len(message) > 8000:
        return _error("INVALID_REQUEST", "message must contain at most 8000 characters.", 400)
    if proposal_id is not None and not isinstance(proposal_id, str):
        return _error("INVALID_REQUEST", "proposalId must be text.", 400)
    if selected_customer_id is not None and not isinstance(selected_customer_id, str):
        return _error("INVALID_REQUEST", "selectedCustomerId must be text.", 400)
    if confirmation is not None and not isinstance(confirmation, dict):
        return _error("INVALID_REQUEST", "confirmation must be an object.", 400)
    if page_context is not None:
        if not isinstance(page_context, dict) or set(page_context) - {"page", "entityType", "entityId", "entityLabel", "locale"}:
            return _error("INVALID_REQUEST", "pageContext must contain only page and optional entity fields.", 400)
        if not isinstance(page_context.get("page"), str) or not page_context["page"].strip() or len(page_context["page"]) > 80:
            return _error("INVALID_REQUEST", "pageContext.page must be short text.", 400)
        if page_context.get("entityType") is not None:
            if not isinstance(page_context["entityType"], str) or page_context["entityType"] not in {"order", "product", "customer", "proposal"}:
                return _error("INVALID_REQUEST", "pageContext.entityType is not supported.", 400)
        for field, maximum in (("entityId", 64), ("entityLabel", 120)):
            if page_context.get(field) is not None and (not isinstance(page_context[field], str) or len(page_context[field]) > maximum):
                return _error("INVALID_REQUEST", f"pageContext.{field} must be short text.", 400)
        if page_context.get("locale") is not None and (not isinstance(page_context["locale"], str) or page_context["locale"] not in {"en", "hi", "kn"}):
            return _error("INVALID_REQUEST", "pageContext.locale must be en, hi, or kn.", 400)
    if not key or len(key) > 128:
        return _error("IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key of at most 128 characters.", 400)
    mode = body.get("mode")
    try:
        result = run_assistant_turn(message.strip(), actor, key, proposal_id, confirmation, selected_customer_id, mode=mode, page_context=page_context, purpose=purpose)
        return jsonify(result), 200
    except ValueError as exc:
        return _error("INVALID_REQUEST", str(exc), 400)
    except LLMNotConfiguredError:
        return _error("LLM_NOT_CONFIGURED", "The Vyapro assistant is unavailable until an LLM endpoint is configured.", 503)
    except LLMUnavailableError:
        return _error("LLM_UNAVAILABLE", "The configured assistant model is unavailable.", 503)
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "The Vyapro assistant requires a configured MySQL database.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "The Vyapro assistant could not read or update MySQL data.", 503)
    except WorkflowError as exc:
        return _error(exc.code, str(exc), exc.status)


@orders_blueprint.post("/order-proposals")
def post_order_proposal():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("INVALID_REQUEST", "A JSON request body is required.", 400)
    source = body.get("source") or {}
    message = body.get("message") or {}
    channel = source.get("channel") if isinstance(source, dict) else None
    external_reference = source.get("externalReference") if isinstance(source, dict) else None
    text = message.get("text") if isinstance(message, dict) else None
    customer_id = body.get("customerId")
    selected_items = body.get("items") if "items" in body else None
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if channel != "web":
        return _error("UNSUPPORTED_CHANNEL", "Only web text is connected in this MVP.", 422)
    if external_reference is not None:
        return _error("INVALID_SOURCE", "Web requests cannot set an external channel reference.", 400)
    if text is None:
        text = ""
    if not isinstance(text, str):
        return _error("INVALID_REQUEST", "message.text must be text.", 400)
    if not isinstance(customer_id, str) or not customer_id.strip():
        return _error("CUSTOMER_REQUIRED", "Choose a registered customer before creating an order proposal.", 400)
    if "items" in body and not isinstance(selected_items, list):
        return _error("INVALID_REQUEST", "items must be a list of selected catalog items.", 400)
    if not idempotency_key or len(idempotency_key) > 128:
        return _error("IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key of at most 128 characters.", 400)

    try:
        interpretation, original_text = build_order_interpretation(customer_id, text, selected_items)
        fingerprint = hashlib.sha256(json.dumps({
            "customerId": customer_id,
            "text": original_text,
            "interpretation": interpretation,
            "source": channel,
        }, sort_keys=True).encode("utf-8")).hexdigest()
        proposal, _created = create_proposal(
            original_text, channel, external_reference, idempotency_key,
            interpretation, fingerprint,
        )
        return jsonify(proposal=proposal), 200
    except WorkflowError as exc:
        return _error(exc.code, str(exc), exc.status)
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Order processing is unavailable until MySQL is configured.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "Order processing is temporarily unavailable.", 503)


@orders_blueprint.post("/audio/order-proposals")
def post_audio_order_proposal():
    audio = request.files.get("audio")
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if audio is None or not audio.filename:
        return _error("AUDIO_REQUIRED", "Upload an audio file in the audio field.", 400)
    supported_types = {"audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg", "audio/flac", "video/mp4"}
    mime_type = audio.mimetype.split(";", 1)[0].strip().lower()
    if mime_type not in supported_types:
        return _error("UNSUPPORTED_AUDIO_TYPE", "Use an MP3, M4A, WAV, WebM, OGG or FLAC recording.", 415)
    if not idempotency_key or len(idempotency_key) > 128:
        return _error("IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key of at most 128 characters.", 400)
    audio_bytes = audio.read()
    if not audio_bytes:
        return _error("AUDIO_REQUIRED", "The uploaded audio file is empty.", 400)
    requested_language = request.form.get("language", "en-IN").strip().lower()
    transcription_language = {"en-in": "en", "hi-in": "hi", "kn-in": "kn"}.get(requested_language)
    if transcription_language is None:
        return _error("UNSUPPORTED_LANGUAGE", "Choose English, Hindi, or Kannada for speech recognition.", 400)
    content_hash = hashlib.sha256(f"voice\0{transcription_language}\0".encode() + audio_bytes).hexdigest()
    try:
        existing = find_idempotent_proposal("", "voice", None, idempotency_key, content_hash)
        if existing:
            return jsonify(transcript=existing.get("transcript", ""), proposal=existing), 200
        try:
            transcript = transcribe_audio(audio_bytes, mime_type, transcription_language)
        except LLMNotConfiguredError:
            return _error("TRANSCRIPTION_NOT_CONFIGURED", "Audio transcription is unavailable until an audio model is configured.", 503)
        except LLMUnavailableError:
            return _error("TRANSCRIPTION_UNAVAILABLE", "The configured audio service could not process this recording.", 503)
        try:
            proposal, _created = process_order_message(
                transcript, "voice", None, idempotency_key, content_hash
            )
        except LLMNotConfiguredError:
            return _error("LLM_NOT_CONFIGURED", "Order interpretation is unavailable until a language model is configured.", 503)
        except LLMUnavailableError:
            return _error("LLM_UNAVAILABLE", "The configured interpretation service is unavailable.", 503)
        except InvalidInterpretationError:
            return _error("INVALID_LLM_RESPONSE", "The interpretation service returned an unusable result. No order was created.", 502)
        return jsonify(transcript=transcript, proposal=proposal), 200
    except WorkflowError as exc:
        return _error(exc.code, str(exc), exc.status)
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Order processing is unavailable until MySQL is configured.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "Order processing is temporarily unavailable.", 503)


@orders_blueprint.get("/order-proposals/<proposal_id>")
def order_proposal_details(proposal_id):
    try:
        proposal = get_proposal(proposal_id)
        if not proposal:
            return _error("NOT_FOUND", "Order proposal was not found.", 404)
        return jsonify(proposal=proposal), 200
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Order processing is unavailable until MySQL is configured.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "Order data is temporarily unavailable.", 503)


@orders_blueprint.post("/order-proposals/<proposal_id>/clarifications")
def order_proposal_clarification(proposal_id):
    body = request.get_json(silent=True)
    answer = body.get("answer") if isinstance(body, dict) else None
    key = request.headers.get("Idempotency-Key", "").strip()
    version = body.get("proposalVersion") if isinstance(body, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        return _error("INVALID_REQUEST", "answer must contain the clarification.", 400)
    if not key or len(key) > 128:
        return _error("IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key of at most 128 characters.", 400)
    if type(version) is not int or version < 1:
        return _error("INVALID_REQUEST", "proposalVersion is required for clarification.", 400)
    try:
        existing = find_clarification(proposal_id, answer, key)
        if existing:
            return jsonify(proposal=existing), 200
        context = get_clarification_context(proposal_id)
        interpretation = interpret_order(context["original_text"] + "\nClarification: " + answer.strip())
        proposal, _created = clarify_proposal(proposal_id, answer, key, version, interpretation)
        return jsonify(proposal=proposal), 200
    except WorkflowError as exc:
        return _error(exc.code, str(exc), exc.status)
    except LLMNotConfiguredError:
        return _error("LLM_NOT_CONFIGURED", "Clarification is unavailable until an LLM endpoint is configured.", 503)
    except (LLMUnavailableError, InvalidInterpretationError):
        return _error("LLM_UNAVAILABLE", "The configured interpretation service could not process the clarification.", 503)
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Order processing is unavailable until MySQL is configured.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "The clarification could not be saved.", 503)


@orders_blueprint.post("/order-proposals/<proposal_id>/approval")
def order_proposal_approval(proposal_id):
    if current_app.config.get("APP_ENV") != "development":
        return _error("AUTHORIZATION_NOT_CONFIGURED", "Approval actions are limited to local development until user authentication is configured.", 503)
    body = request.get_json(silent=True)
    decision = body.get("decision") if isinstance(body, dict) else None
    if not isinstance(decision, str) or decision not in {"approve", "reject"}:
        return _error("INVALID_REQUEST", "decision must be approve or reject.", 400)
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not idempotency_key or len(idempotency_key) > 128:
        return _error("IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key of at most 128 characters.", 400)
    if decision == "reject":
        try:
            return jsonify(proposal=reject_proposal(proposal_id)), 200
        except WorkflowError as exc:
            return _error(exc.code, str(exc), exc.status)
        except DatabaseNotConfiguredError:
            return _error("DATABASE_NOT_CONFIGURED", "The approval action is unavailable until MySQL is configured.", 503)
        except mysql.connector.Error:
            return _error("DATABASE_UNAVAILABLE", "The approval action could not be saved.", 503)

    if type(body.get("proposalVersion")) is not int or body["proposalVersion"] < 1:
        return _error("INVALID_REQUEST", "proposalVersion is required for approval.", 400)
    if "acceptSubstitutions" in body and not isinstance(body["acceptSubstitutions"], bool):
        return _error("INVALID_REQUEST", "acceptSubstitutions must be a boolean.", 400)
    if "acceptPartial" in body and not isinstance(body["acceptPartial"], bool):
        return _error("INVALID_REQUEST", "acceptPartial must be a boolean.", 400)
    try:
        order, created = approve_proposal(
            proposal_id,
            bool(body.get("acceptSubstitutions", False)),
            body["proposalVersion"],
            idempotency_key,
            actor="local-development-user",
            accept_partial=body.get("acceptPartial", False),
        )
        return jsonify(order=order), 201 if created else 200
    except WorkflowError as exc:
        return _error(exc.code, str(exc), exc.status)
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Order processing is unavailable until MySQL is configured.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "The approval action could not be saved.", 503)


@orders_blueprint.get("/order-proposals")
def proposals_list():
    try:
        limit = int(request.args.get("limit", "50"))
        if limit < 1 or limit > 100:
            raise ValueError
        offset = _offset_from_cursor(request.args.get("cursor"))
    except (ValueError, WorkflowError) as exc:
        if isinstance(exc, WorkflowError):
            return _error(exc.code, str(exc), exc.status)
        return _error("INVALID_REQUEST", "limit must be between 1 and 100.", 400)
    try:
        proposals, next_offset = list_proposals(request.args.get("status") or None, limit, offset)
        next_cursor = base64.urlsafe_b64encode(str(next_offset).encode("ascii")).decode("ascii") if next_offset is not None else None
        return jsonify(proposals=proposals, nextCursor=next_cursor), 200
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Proposal data is not configured.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "Proposal data is temporarily unavailable.", 503)


@orders_blueprint.get("/orders")
def orders_list():
    try:
        limit = int(request.args.get("limit", "50"))
        if limit < 1 or limit > 100:
            raise ValueError
        offset = _offset_from_cursor(request.args.get("cursor"))
    except (ValueError, WorkflowError) as exc:
        if isinstance(exc, WorkflowError):
            return _error(exc.code, str(exc), exc.status)
        return _error("INVALID_REQUEST", "limit must be between 1 and 100.", 400)
    try:
        orders, next_offset = list_orders(
            status=request.args.get("status") or None,
            query=request.args.get("query") or None,
            source=request.args.get("source") or None,
            limit=limit,
            offset=offset,
        )
        next_cursor = base64.urlsafe_b64encode(str(next_offset).encode("ascii")).decode("ascii") if next_offset is not None else None
        return jsonify(orders=orders, nextCursor=next_cursor), 200
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Order data is not configured.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "Order data is temporarily unavailable.", 503)


@orders_blueprint.get("/orders/<order_id>")
def order_details(order_id):
    try:
        order = get_order(order_id)
        if not order:
            return _error("NOT_FOUND", "Order was not found.", 404)
        return jsonify(order=order), 200
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Order data is not configured.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "Order data is temporarily unavailable.", 503)


@orders_blueprint.get("/orders/<order_id>/events")
def order_events(order_id):
    try:
        events = get_order_events(order_id)
        if events is None:
            return _error("NOT_FOUND", "Order was not found.", 404)
        return jsonify(events=events), 200
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Order activity is not configured.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "Order activity is temporarily unavailable.", 503)


@orders_blueprint.post("/orders/<order_id>/fulfill-pending")
def fulfill_order_pending_quantity(order_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("confirm") is not True:
        return _error("EXPLICIT_CONFIRMATION_REQUIRED", "Confirm the pending fulfillment before Vyapro rechecks stock and credit.", 422)
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 128:
        return _error("IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key of at most 128 characters.", 400)
    try:
        order, created = fulfill_pending_order(order_id, key, actor="local-development-user")
        return jsonify(order=order), 201 if created else 200
    except WorkflowError as exc:
        return _error(exc.code, str(exc), exc.status)
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Order fulfillment requires MySQL.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "The pending fulfillment could not be saved.", 503)
