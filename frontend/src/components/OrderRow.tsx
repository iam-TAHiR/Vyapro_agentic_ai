import type { Order } from '../types/order'
import { StatusBadge } from './StatusBadge'

type OrderRowProps = { order: Order }

export function OrderRow({ order }: OrderRowProps) {
  const received = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(order.receivedAt))
  const total = new Intl.NumberFormat('en-IN', { style: 'currency', currency: order.total.currency }).format(order.total.amount)
  return (
    <tr>
      <td data-label="Order ID"><a href={`/orders/${encodeURIComponent(order.id)}`}>{order.id}</a></td>
      <td data-label="Customer">{order.customerName}</td>
      <td data-label="Received">{received}</td>
      <td data-label="Total">{total}</td>
      <td data-label="Status"><StatusBadge status={order.status} /></td>
      <td data-label="Source">{order.source ?? 'Not available'}</td>
      <td data-label="Action"><a className="text-action" href={`/orders/${encodeURIComponent(order.id)}`}>View details<span className="sr-only"> for {order.id}</span></a></td>
    </tr>
  )
}
