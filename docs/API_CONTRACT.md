# Vyapro API and Order Workflow Contract (Proposal)

This document proposes the first API contract for the web text-order MVP. It is a design proposal, not an implemented or running API. The Flask backend, MySQL persistence, LLM integration, and frontend integration do not exist yet.

## Contract goals

- Keep the current React/Vite frontend and connect it to a Flask REST API.
- Send all input channels through one shared order workflow. Channel adapters may normalize input, but must not implement their own stock, pricing, credit, approval, or order rules.
- Treat the LLM as an interpreter. It can propose structured intent, but trusted backend services resolve records and make business-rule decisions.
- Do not create or confirm an order until deterministic validation and any required human approval have succeeded.
- Retain the genuine source channel and an external message/conversation reference when one exists.
- Make retries safe so a repeated request does not create duplicate orders or repeat a committed action.

## Proposed API conventions

- Base path: `/api/v1`.
- JSON uses `camelCase` to align with the current TypeScript order model. Python code may use `snake_case` internally.
- Timestamps are ISO 8601 strings with an explicit UTC offset; the API should return UTC timestamps ending in `Z`.
- Money is represented as an integer number of the currency's minor units plus an ISO 4217 currency code. For INR, `amountMinor: 125050` represents ₹1,250.50. The backend, not the browser or LLM, calculates authoritative prices and totals.
- IDs are opaque strings. Clients must not infer business meaning from their format.
- API errors use the common envelope described below. Error responses must not include credentials, secrets, raw prompts, or private data the caller is not allowed to see.

These conventions need confirmation before the first endpoint is implemented, especially the money representation and whether the existing frontend should adopt `camelCase` throughout.

## Web text proposal flow

### Create or interpret a proposal

`POST /api/v1/order-proposals`

Headers:

```http
Content-Type: application/json
Idempotency-Key: <unique key for this user action>
```

Request:

```json
{
  "source": {
    "channel": "web",
    "externalReference": null
  },
  "message": {
    "text": "Send Sharma Stores 10 bags of rice and 5 cartons of cooking oil tomorrow."
  }
}
```

`source.channel` is a server-validated enum. The first MVP supports only `web`. Future accepted values may include `voice`, `phone`, and `whatsapp`, but they must not be advertised as connected until their adapters work. `externalReference` is optional for web and is reserved for a trusted channel adapter to provide an upstream message or conversation ID. Clients cannot use it to choose a different channel's permissions.

Successful interpretation and validation returns `200 OK` with a proposal. The proposal is not an order and does not reserve inventory or change customer credit.

```json
{
  "proposal": {
    "id": "opaque-proposal-id",
    "status": "needs_clarification",
    "source": {
      "channel": "web",
      "externalReference": null
    },
    "interpretation": {
      "customerText": "Sharma Stores",
      "items": [
        {
          "productText": "rice",
          "quantity": "10",
          "unitText": "bags"
        }
      ],
      "deliveryPreference": "tomorrow"
    },
    "matchedCustomer": null,
    "items": [],
    "warnings": [
      {
        "code": "CUSTOMER_AMBIGUOUS",
        "message": "More than one customer matches this name.",
        "requiresUserAction": true
      }
    ],
    "total": null,
    "createdAt": "2026-10-26T12:00:00Z",
    "expiresAt": "2026-10-26T12:15:00Z"
  }
}
```

This response is illustrative only. A real response must contain only LLM-extracted text and backend-verified matches/checks. Unmatched products, missing quantities, ambiguous customers, or unavailable authoritative prices must be represented as unresolved; they must never be filled with invented values. A total is present only when every included line has a backend-confirmed price.

### Resolve clarification

`POST /api/v1/order-proposals/{proposalId}/clarifications`

Request:

```json
{
  "answer": "The Sharma Stores customer in Andheri."
}
```

The backend reinterprets or applies the answer to the existing proposal, then reruns matching and relevant validations. A clarification does not approve or commit an order.

### Approve and commit

`POST /api/v1/order-proposals/{proposalId}/approval`

Headers include a new `Idempotency-Key` for this approval action.

Request:

```json
{
  "decision": "approve",
  "proposalVersion": 3
}
```

The server checks that the proposal is still current, reruns stock, price, credit, and applicable business checks, then applies the configured approval rules. If another approval is required, the response remains pending and explains the requirement. If any material value changed or validation now fails, the server does not commit; it returns the updated proposal and warnings for review. A successful commit returns `201 Created` with the persisted order. Only that response means an order was created.

For a proposal that is awaiting approval from an authorized reviewer, the same resource can receive `decision: "approve"` or `"reject"` from an authenticated, authorized user. Authentication and role policy are deployment requirements to define before enabling approvals; this proposal does not prescribe a provider.

## Read operations for the unified inbox

These endpoints support the existing Orders page after the web flow is in place:

- `GET /api/v1/orders?status=pending_review&query=sharma&source=web` returns `{ "orders": [...], "nextCursor": null }`.
- `GET /api/v1/orders/{orderId}` returns `{ "order": {...} }`.
- `GET /api/v1/orders/{orderId}/events` returns `{ "events": [...] }` for the order's permitted activity history.

An order list row includes at least `id`, `customer`, `receivedAt`, `total`, `status`, and `source`. An order's source is one of the channels actually accepted by the backend for that order. Current UI fixture labels such as `Fixture: phone` are not evidence that a channel is integrated.

The exact paging strategy, filters, customer-data visibility, and activity-event fields should be settled with the first read API implementation. The dashboard should consume server summaries rather than derive operational counts from fixtures.

## Proposed status values

Proposal lifecycle:

- `interpreting` — request accepted and interpretation is in progress.
- `needs_clarification` — missing or ambiguous information needs the user's response.
- `needs_review` — a valid proposal needs a human approval under configured rules.
- `ready_to_commit` — required user confirmation is present; final backend checks remain necessary.
- `rejected` — a user or authorized reviewer rejected the proposal.
- `expired` — the proposal is too old to approve safely and must be refreshed.
- `committed` — an order was persisted successfully.

Persisted order lifecycle (initial proposal):

- `pending_approval`
- `confirmed`
- `rejected`
- `cancelled`

The backend owns allowed transitions. A proposal state and an order state are separate: there is no persisted order until commit. Status names are provisional and must be agreed before frontend code relies on them.

## Error envelope

All non-success responses use a stable shape:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "The request could not be processed.",
    "requestId": "opaque-request-id",
    "details": []
  }
}
```

Proposed HTTP use:

- `400` malformed JSON or invalid request shape.
- `401` unauthenticated, once authentication is configured.
- `403` authenticated caller lacks permission.
- `404` resource not found or not visible to caller.
- `409` stale proposal version, conflicting idempotency key, or state conflict.
- `422` well-formed request that cannot proceed under business rules; include safe, actionable details.
- `429` rate limited.
- `500` unexpected server failure with a generic message and request ID.
- `503` required dependency temporarily unavailable.

Clarification and ordinary business warnings belong in a successful proposal response, not a server error. The UI must not interpret an HTTP success by itself as proof that an order was committed; it must check the returned resource state.

## Retry and duplicate handling

- Require an idempotency key for proposal creation and approval/commit actions. Scope keys to the authenticated actor and operation.
- Repeating a key with the same request returns the original result; reusing it with a different request returns `409`.
- Channel adapters use the provider's stable message/event ID as a deduplication key in addition to the API idempotency mechanism.
- Enforce uniqueness in persistent storage so simultaneous retries cannot create duplicate orders.
- Record accepted source channel, external reference, and processing outcome in the audit history, subject to data-retention and privacy rules.

## Decisions required before implementation

1. Confirm `camelCase` JSON and integer minor-unit money representation, or choose a consistent alternative before frontend/backend models are built.
2. Define authentication and authorization for users, shopkeepers, and approvers. Do not expose approval endpoints without this policy.
3. Confirm the initial status names and whether order creation should be allowed before or only after required human approval.
4. Define proposal expiry and what changes require renewed confirmation (for example, price or available quantity changes).
5. Select a MySQL migration approach and define the first customer, product, inventory, price, order, and audit data model before schema work.
6. Keep LLM, transcription, telephony, and messaging providers undecided until their options, cost, credentials, API requirements, and limitations are reviewed.

## Implementation sequence after contract review

1. Confirm or revise this contract.
2. Add the minimal Flask foundation and health endpoint.
3. Agree on the MySQL schema/migration approach and persist core records.
4. Implement and test deterministic order services and idempotency.
5. Add the proposal, clarification, approval, order-read, and event APIs.
6. Add server-side LLM interpretation with schema validation.
7. Connect the existing web Assistant and order screens; verify the end-to-end web workflow.
8. Evaluate and, only after approval, add audio transcription, telephony, and messaging adapters to the same workflow.
