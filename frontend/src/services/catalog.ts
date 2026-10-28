import { createApiClient } from './api'
import type { Money } from './orders'

const api = createApiClient({ baseUrl: import.meta.env.VITE_API_BASE_URL || '/api/v1' })

export type Customer = {
  id: string
  name: string
  creditLimit: Money
  creditUsed: Money
}
export type Product = {
  id: string
  sku: string
  name: string
  quantityAvailable: string
  unit: string
  unitPrice: Money
}

export async function listCustomers() {
  return api.requestJson<{ customers: Customer[] }>('/customers')
}

export async function listInventory() {
  return api.requestJson<{ products: Product[] }>('/inventory')
}
