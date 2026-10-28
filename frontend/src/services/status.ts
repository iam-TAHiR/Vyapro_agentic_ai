import { translate } from './i18n'

const statusLabels: Record<string, string> = {
  confirmed: 'Placed',
  committed: 'Order placed',
  needs_review: 'Needs shopkeeper review',
  needs_clarification: 'Needs more detail',
  pending_approval: 'Waiting for approval',
  partially_fulfilled: 'Partly fulfilled',
  fulfilled: 'Fulfilled',
  delivered: 'Delivered',
  cancelled: 'Cancelled',
  rejected: 'Declined',
}

export function formatStatusLabel(status: string) {
  return translate(statusLabels[status] ?? status.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()))
}
