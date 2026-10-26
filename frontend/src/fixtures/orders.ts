import type { Order } from '../types/order'

/**
 * DEVELOPMENT FIXTURES ONLY. These names, IDs, amounts, statuses, sources,
 * and timestamps are illustrative UI data, not business records or confirmed
 * backend values. Keep this module separate from future live API calls.
 */
export const developmentOrdersFixture: Order[] = [
  {
    id: 'DEV-ORDER-1042',
    customerName: 'Development Customer A',
    receivedAt: '2026-10-26T09:20:00+05:30',
    total: { amount: 1240, currency: 'INR' },
    status: 'Fixture: received',
    source: 'Fixture: chat',
  },
  {
    id: 'DEV-ORDER-1041',
    customerName: 'Development Customer B',
    receivedAt: '2026-10-26T08:55:00+05:30',
    total: { amount: 860, currency: 'INR' },
    status: 'Fixture: pending review',
    source: 'Fixture: phone',
  },
  {
    id: 'DEV-ORDER-1040',
    customerName: 'Development Customer C',
    receivedAt: '2026-10-25T17:40:00+05:30',
    total: { amount: 3199, currency: 'INR' },
    status: 'Fixture: confirmed',
  },
]
