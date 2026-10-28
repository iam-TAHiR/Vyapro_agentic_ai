import { formatStatusLabel } from '../services/status'
import { useI18n } from '../services/i18n'

type SearchFilterProps = {
  query: string
  status: string
  statuses: string[]
  onQueryChange: (value: string) => void
  onStatusChange: (value: string) => void
}

export function SearchFilter({ query, status, statuses, onQueryChange, onStatusChange }: SearchFilterProps) {
  const { t } = useI18n()
  return (
    <div className="filters" aria-label={t('Filter orders')}>
      <div>
        <label htmlFor="order-search">{t('Search orders')}</label>
        <input id="order-search" type="search" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={t('Order ID or customer')} />
      </div>
      <div>
        <label htmlFor="status-filter">{t('Status')}</label>
        <select id="status-filter" value={status} onChange={(event) => onStatusChange(event.target.value)}>
          <option value="">{t('All statuses')}</option>
          {statuses.map((option) => <option key={option} value={option}>{formatStatusLabel(option)}</option>)}
        </select>
      </div>
    </div>
  )
}
