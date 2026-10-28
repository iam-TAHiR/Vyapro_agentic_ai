import type { OrderSummary } from '../services/orders'
import { formatMoney } from '../services/orders'
import { StatusBadge } from './StatusBadge'
import { localeTag, useI18n } from '../services/i18n'

type OrderRowProps = { order: OrderSummary }

export function OrderRow({ order }: OrderRowProps) {
  const { t } = useI18n()
  const received = new Intl.DateTimeFormat(localeTag(), { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(order.receivedAt))
  const total = formatMoney(order.total)
  return (
    <tr>
      <td data-label={t('Order ID')}><a href={`/orders/${encodeURIComponent(order.id)}`}>{order.id}</a></td>
      <td data-label={t('Customer')}>{order.customerName}</td>
      <td data-label={t('Received')}>{received}</td>
      <td data-label={t('Total')}>{total}</td>
      <td data-label={t('Status')}><StatusBadge status={order.status} /></td>
      <td data-label={t('Source')}>{order.source ?? t('Not available')}</td>
      <td data-label={t('Action')}><a className="text-action" href={`/orders/${encodeURIComponent(order.id)}`}>{t('View details')}<span className="sr-only"> {t('for')} {order.id}</span></a></td>
    </tr>
  )
}
