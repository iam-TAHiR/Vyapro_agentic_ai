import type { OrderSummary } from '../types/order'

/**
 * DEVELOPMENT FIXTURES ONLY. These names, IDs, amounts, statuses, sources,
 * and timestamps are illustrative UI data, not business records or confirmed
 * backend values. Keep this module separate from future live API calls.
 */
export const developmentOrdersFixture: OrderSummary[] = [
  {
    id: 'DEV-ORDER-1042',
    customerId: 'DEV-CUSTOMER-A',
    customerName: 'Development Customer A',
    receivedAt: '2026-10-26T09:20:00+05:30',
    total: { amountMinor: 1240, currency: 'INR' },
    status: 'Fixture: received',
    source: 'Fixture: web',
    hasPending: false,
    externalReference: null,
    deliveryPreference: null,
  },
  {
    id: 'DEV-ORDER-1041',
    customerId: 'DEV-CUSTOMER-B',
    customerName: 'Development Customer B',
    receivedAt: '2026-10-26T08:55:00+05:30',
    total: { amountMinor: 860, currency: 'INR' },
    status: 'Fixture: pending review',
    source: 'Fixture: phone',
    hasPending: false,
    externalReference: null,
    deliveryPreference: null,
  },
  {
    id: 'DEV-ORDER-1040',
    customerId: 'DEV-CUSTOMER-C',
    customerName: 'Development Customer C',
    receivedAt: '2026-10-25T17:40:00+05:30',
    total: { amountMinor: 3199, currency: 'INR' },
    status: 'Fixture: confirmed',
    source: 'Fixture: web',
    hasPending: false,
    externalReference: null,
    deliveryPreference: null,
  },
]
