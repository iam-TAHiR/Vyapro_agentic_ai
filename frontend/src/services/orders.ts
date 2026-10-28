import { createApiClient } from './api'
import { localeTag } from './i18n'

export type Money = { amountMinor: number; currency: string }
export type OrderItem = {
  product: { id: string; sku: string; name: string }
  quantity: string
  unit: string
  requestedQuantity: string
  remainingQuantity: string
  unitPrice: Money
  lineTotal: Money
}
export type OrderSummary = {
  id: string
  customerId: string
  customerName: string
  receivedAt: string
  total: Money
  status: string
  source: string
  externalReference: string | null
  deliveryPreference: string | null
  hasPending: boolean
}
export type Order = OrderSummary & {
  items: OrderItem[]
  pendingItems: Array<{ productId: string; productName: string; quantity: string; unit: string }>
}
export type OrderListResult = { orders: OrderSummary[]; nextCursor: string | null }
export type OrderEvent = { type: string; actor: string; source: string; details: Record<string, unknown>; createdAt: string }
export type ProposalItem = {
  requested: { productText: string; quantity: string; unit: string }
  matchedProduct: { id: string; sku: string; name: string } | null
  substitution: { product: { id: string; sku: string; name: string }; reason: string; requiresApproval: boolean } | null
  availability: { quantityAvailable: string; unit: string; unitPrice: Money } | null
  status: string
  offeredQuantity: string
  remainingQuantity: string
  lineTotal: Money | null
}
export type OrderProposal = {
  id: string
  status: string
  version: number
  source: { channel: string; externalReference: string | null }
  interpretation: { customerText: string | null; items: Array<{ productText: string; quantity: string; unitText: string }>; deliveryPreference: string | null }
  matchedCustomer: { id: string; name: string } | null
  items: ProposalItem[]
  validation: { warnings: Array<{ code: string; message: string; requiresUserAction: boolean }> }
  total: Money | null
  createdAt: string
  transcript?: string
}
export type ProposalListResult = { proposals: OrderProposal[]; nextCursor: string | null }
export type AgentTurn = {
  conversationId: string
  status: 'completed' | 'confirmation_required' | 'escalated'
  message: string
  proposal: OrderProposal | null
  order: Order | null
  submissionMode: 'explicit_confirmation' | 'autonomous_policy' | null
  toolCalls: Array<{ name: string; status: string }>
  escalationReason?: string | null
}

const api = createApiClient({ baseUrl: import.meta.env.VITE_API_BASE_URL || '/api/v1' })

export async function listOrders(params: { status?: string; query?: string; limit?: number } = {}) {
  const search = new URLSearchParams()
  if (params.status) search.set('status', params.status)
  if (params.query) search.set('query', params.query)
  if (params.limit) search.set('limit', String(params.limit))
  const query = search.toString()
  const suffix = query ? `?${query}` : ''
  return api.requestJson<OrderListResult>(`/orders${suffix}`)
}

export async function getCustomerOrders(customerId: string) {
  const result = await api.requestJson<{ customer: { id: string; name: string }; orders: OrderSummary[] }>(
    `/customer-orders?customerId=${encodeURIComponent(customerId)}`,
  )
  return result.orders
}

export async function getOrder(orderId: string) {
  const result = await api.requestJson<{ order: Order }>(`/orders/${encodeURIComponent(orderId)}`)
  return result.order
}

export async function getOrderEvents(orderId: string) {
  const result = await api.requestJson<{ events: OrderEvent[] }>(`/orders/${encodeURIComponent(orderId)}/events`)
  return result.events
}

export async function listProposals(status?: string) {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return api.requestJson<ProposalListResult>(`/order-proposals${suffix}`)
}

export async function getProposal(proposalId: string) {
  const result = await api.requestJson<{ proposal: OrderProposal }>(`/order-proposals/${encodeURIComponent(proposalId)}`)
  return result.proposal
}

export async function createProposal(text: string, idempotencyKey: string) {
  const result = await api.requestJson<{ proposal: OrderProposal }>('/order-proposals', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ source: { channel: 'web', externalReference: null }, message: { text } }),
  })
  return result.proposal
}

export async function createCustomerProposal(
  customerId: string,
  text: string,
  idempotencyKey: string,
  items?: Array<{ productId: string; quantity: string; unit: string }>,
) {
  const result = await api.requestJson<{ proposal: OrderProposal }>('/order-proposals', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({
      source: { channel: 'web', externalReference: null },
      customerId,
      message: { text },
      ...(items?.length ? { items } : {}),
    }),
  })
  return result.proposal
}

export async function sendAssistantMessage(
  actor: 'customer' | 'shopkeeper',
  message: string,
  idempotencyKey: string,
  proposalId?: string,
  confirmation?: { proposalId: string; proposalVersion: number; confirmed: boolean; acceptSubstitutions?: boolean; acceptPartial?: boolean },
  selectedCustomerId?: string,
  mode?: 'deterministic',
  pageContext?: { page: string; entityType?: string; entityId?: string; entityLabel?: string; locale?: string },
  purpose: 'business' | 'helper' = 'business',
) {
  return api.requestJson<AgentTurn>('/assistant/messages', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ actor, message, proposalId, confirmation, selectedCustomerId, mode, pageContext, purpose }),
  })
}

export async function createAudioProposal(file: File, idempotencyKey: string, language = 'en-IN') {
  const form = new FormData()
  form.append('audio', file)
  form.append('language', language)
  return api.requestJson<{ transcript: string; proposal: OrderProposal }>('/audio/order-proposals', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: form,
  })
}

export async function clarifyProposal(proposalId: string, answer: string, proposalVersion: number, idempotencyKey: string) {
  const result = await api.requestJson<{ proposal: OrderProposal }>(`/order-proposals/${encodeURIComponent(proposalId)}/clarifications`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ answer, proposalVersion }),
  })
  return result.proposal
}

export async function reviewProposal(proposalId: string, proposalVersion: number, acceptSubstitutions: boolean, idempotencyKey: string, acceptPartial = false) {
  return api.requestJson<{ order: Order }>(`/order-proposals/${encodeURIComponent(proposalId)}/approval`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ decision: 'approve', proposalVersion, acceptSubstitutions, acceptPartial }),
  })
}

export async function fulfillPendingOrder(orderId: string, idempotencyKey: string) {
  return api.requestJson<{ order: Order }>(`/orders/${encodeURIComponent(orderId)}/fulfill-pending`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ confirm: true }),
  })
}

export async function rejectProposal(proposalId: string, idempotencyKey: string) {
  return api.requestJson<{ proposal: { id: string; status: string } }>(`/order-proposals/${encodeURIComponent(proposalId)}/approval`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ decision: 'reject' }),
  })
}

export function formatMoney(money: Money | null | undefined) {
  if (!money) return '—'
  const formatter = new Intl.NumberFormat(localeTag(), { style: 'currency', currency: money.currency })
  const fractionDigits = formatter.resolvedOptions().maximumFractionDigits ?? 2
  return formatter.format(money.amountMinor / (10 ** fractionDigits))
}
