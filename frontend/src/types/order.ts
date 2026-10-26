/**
 * Boundary model for a future Orders API.
 *
 * No Vyapro API contract was available when this was created. Fields are
 * deliberately conservative: status and source remain server-defined strings
 * rather than frontend-owned enums. Confirm field names, nullable fields, and
 * timestamp/currency formats with the backend owner before wiring this model
 * to a response.
 */
export type Order = {
  id: string
  customerName: string
  receivedAt: string
  total: {
    amount: number
    currency: string
  }
  status: string
  source?: string
}

export type OrdersListResult = {
  orders: Order[]
}
