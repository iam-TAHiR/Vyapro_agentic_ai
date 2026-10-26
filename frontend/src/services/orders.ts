import type { Order, OrdersListResult } from '../types/order'
import type { createApiClient } from './api'

export type OrdersService = {
  listOrders(): Promise<OrdersListResult>
  getOrder(orderId: string): Promise<Order>
}

/**
 * Integration seam only. No endpoints are encoded because no API contract was
 * supplied. Implement this after the backend owner confirms routes, response
 * shapes, auth, and supported status/source values.
 */
export function createOrdersService(api: ReturnType<typeof createApiClient>): OrdersService {
  // Retain the injected client as the future integration boundary without
  // guessing an endpoint before the contract is confirmed.
  void api
  return {
    async listOrders() {
      throw new Error('Orders API integration is not configured. Development fixtures are in use.')
    },
    async getOrder(orderId: string) {
      void orderId
      throw new Error('Orders API integration is not configured. Development fixtures are in use.')
    },
  }
}
