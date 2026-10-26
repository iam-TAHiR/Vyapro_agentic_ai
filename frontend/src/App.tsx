import { useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { AppLayout } from './components/AppLayout'
import { DevelopmentDataNotice } from './components/DevelopmentDataNotice'
import { EmptyState } from './components/EmptyState'
import { ErrorState } from './components/ErrorState'
import { ExampleDataTable } from './components/ExampleDataTable'
import { LoadingSkeleton } from './components/LoadingSkeleton'
import { OrderRow } from './components/OrderRow'
import { SearchFilter } from './components/SearchFilter'
import { developmentOrdersFixture } from './fixtures/orders'
import { customerExamples, dashboardExamples, inventoryExamples } from './fixtures/operations'
import './styles.css'

type FixtureView = 'loading' | 'populated' | 'empty' | 'error'

function OrdersDetailPlaceholder() {
  const orderId = decodeURIComponent(window.location.pathname.split('/').at(-1) ?? '')
  return (
    <AppLayout>
      <section className="page-heading">
        <p className="eyebrow">Development route placeholder</p>
        <h1>Order details</h1>
        <p><strong>{orderId}</strong> is an example route only. No real order has been retrieved or changed.</p>
        <a className="back-link" href="/orders">← Back to Orders</a>
      </section>
    </AppLayout>
  )
}

type PageHeadingProps = { eyebrow: string; title: string; children: ReactNode }
function PageHeading({ eyebrow, title, children }: PageHeadingProps) {
  return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{children}</p></div></div>
}

function DashboardScreen() {
  return <AppLayout><DevelopmentDataNotice /><PageHeading eyebrow="Dashboard" title="Shopkeeper overview">A frontend-only workspace for reviewing server-provided operations once the backend is connected.</PageHeading><section className="metric-grid" aria-label="Development dashboard fixtures">{dashboardExamples.map((item) => <article className="metric-card" key={item.label}><p>{item.label}</p><strong>{item.value}</strong><small>{item.context}</small></article>)}</section><section className="dashboard-section"><h2>Getting started</h2><p>Use the navigation to review development fixtures for grocery orders, inventory, and customers. No stock, credit, approval, or status decision is calculated in this browser.</p></section></AppLayout>
}

function InventoryScreen() {
  return <AppLayout><DevelopmentDataNotice /><PageHeading eyebrow="Inventory" title="Grocery inventory">Availability shown here is fixture display text. The backend remains the source of truth for stock and substitutions.</PageHeading><ExampleDataTable caption="Development grocery inventory fixtures" columns={['SKU', 'Product', 'Availability', 'Updated']} rows={inventoryExamples.map((item) => [item.sku, item.name, item.availability, item.updatedAt])} /></AppLayout>
}

function CustomersScreen() {
  return <AppLayout><DevelopmentDataNotice /><PageHeading eyebrow="Customers" title="Customer directory">Customer records are development fixtures only. Future permissions and customer data fields require an approved API contract.</PageHeading><ExampleDataTable caption="Development customer fixtures" columns={['Customer ID', 'Customer', 'Contact', 'Last fixture order']} rows={customerExamples.map((item) => [item.id, item.name, item.contact, item.lastOrder])} /></AppLayout>
}

function NewOrderScreen() {
  const [customer, setCustomer] = useState('')
  const [request, setRequest] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const canPrepareDraft = customer.trim().length > 0 && request.trim().length > 0

  function prepareDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setNotice(canPrepareDraft ? 'Development draft prepared locally. It has not been sent, approved, or created.' : 'Add an example customer and request before preparing a local development draft.')
  }

  return <AppLayout><DevelopmentDataNotice /><PageHeading eyebrow="New order" title="Prepare a grocery order draft">This form is a frontend-only draft experience. It does not calculate totals, validate stock or credit, submit an order, or show server success.</PageHeading><form className="order-form" onSubmit={prepareDraft} noValidate><div><label htmlFor="draft-customer">Development customer</label><input id="draft-customer" value={customer} onChange={(event) => setCustomer(event.target.value)} placeholder="Development customer name" aria-describedby="customer-help" /><small id="customer-help">Fixture input only; no customer data is sent.</small></div><div><label htmlFor="draft-request">Grocery items requested</label><textarea id="draft-request" value={request} onChange={(event) => setRequest(event.target.value)} placeholder="For example: 2 kg basmati rice, 1 L cooking oil" rows={5} /><small>Product availability and substitutions must be confirmed by the backend.</small></div><button type="submit">Prepare local development draft</button>{notice && <p className="draft-notice" role="status">{notice}</p>}<p className="form-footnote">Server-connected create/approve actions will prevent duplicate submission and only confirm success after a backend response.</p></form></AppLayout>
}

function OrdersScreen() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [fixtureView, setFixtureView] = useState<FixtureView>('loading')

  useEffect(() => {
    if (fixtureView !== 'loading') return
    const timeout = window.setTimeout(() => setFixtureView('populated'), 450)
    return () => window.clearTimeout(timeout)
  }, [fixtureView])

  const statuses = useMemo(() => [...new Set(developmentOrdersFixture.map((order) => order.status))], [])
  const orders = useMemo(() => developmentOrdersFixture.filter((order) => {
    const searchable = `${order.id} ${order.customerName}`.toLowerCase()
    return searchable.includes(query.trim().toLowerCase()) && (!status || order.status === status)
  }), [query, status])

  function retryFixtures() {
    setFixtureView('loading')
  }

  return (
    <AppLayout>
      <DevelopmentDataNotice />
      <div className="page-heading">
        <div>
          <p className="eyebrow">Orders</p>
          <h1>Order workspace</h1>
          <p>Review a display of incoming orders. Authoritative stock, credit, approvals, and order decisions remain with the backend.</p>
        </div>
        <div className="fixture-control">
          <label htmlFor="fixture-view">Development preview state</label>
          <select id="fixture-view" value={fixtureView} onChange={(event) => setFixtureView(event.target.value as FixtureView)}>
            <option value="loading">Loading</option>
            <option value="populated">Populated</option>
            <option value="empty">Empty</option>
            <option value="error">Error</option>
          </select>
        </div>
      </div>

      <SearchFilter query={query} status={status} statuses={statuses} onQueryChange={setQuery} onStatusChange={setStatus} />

      {fixtureView === 'loading' && <LoadingSkeleton />}
      {fixtureView === 'error' && <ErrorState message="This is a simulated development error. Your filters are still preserved." onRetry={retryFixtures} />}
      {fixtureView === 'empty' && <EmptyState title="No development orders" message="This is an intentional empty-state preview. It does not mean there are no live orders." />}
      {fixtureView === 'populated' && orders.length === 0 && <EmptyState title="No matching development orders" message="Try a different search or status filter. These results are development fixtures only." />}
      {fixtureView === 'populated' && orders.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption>Development fixture orders</caption>
            <thead><tr><th scope="col">Order ID</th><th scope="col">Customer</th><th scope="col">Received</th><th scope="col">Total (INR)</th><th scope="col">Status</th><th scope="col">Source</th><th scope="col"><span className="sr-only">Action</span></th></tr></thead>
            <tbody>{orders.map((order) => <OrderRow key={order.id} order={order} />)}</tbody>
          </table>
        </div>
      )}
    </AppLayout>
  )
}

export default function App() {
  const pathname = window.location.pathname
  if (pathname.startsWith('/orders/')) return <OrdersDetailPlaceholder />
  if (pathname === '/orders') return <OrdersScreen />
  if (pathname === '/new-order') return <NewOrderScreen />
  if (pathname === '/inventory') return <InventoryScreen />
  if (pathname === '/customers') return <CustomersScreen />
  return <DashboardScreen />
}
