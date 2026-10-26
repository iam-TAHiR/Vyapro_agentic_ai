type SearchFilterProps = {
  query: string
  status: string
  statuses: string[]
  onQueryChange: (value: string) => void
  onStatusChange: (value: string) => void
}

export function SearchFilter({ query, status, statuses, onQueryChange, onStatusChange }: SearchFilterProps) {
  return (
    <div className="filters" aria-label="Filter orders">
      <div>
        <label htmlFor="order-search">Search orders</label>
        <input id="order-search" type="search" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Order ID or customer" />
      </div>
      <div>
        <label htmlFor="status-filter">Status</label>
        <select id="status-filter" value={status} onChange={(event) => onStatusChange(event.target.value)}>
          <option value="">All fixture statuses</option>
          {statuses.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      </div>
    </div>
  )
}
