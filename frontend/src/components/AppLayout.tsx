import type { ReactNode } from 'react'

const navigation = [
  { label: 'Dashboard', href: '/' },
  { label: 'Orders', href: '/orders' },
  { label: 'New Order', href: '/new-order' },
  { label: 'Inventory', href: '/inventory' },
  { label: 'Customers', href: '/customers' },
  { label: 'Review Queue', href: '/review-queue' },
  { label: 'Activity', href: '/activity' },
]

type AppLayoutProps = { children: ReactNode }

export function AppLayout({ children }: AppLayoutProps) {
  const pathname = window.location.pathname
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <header className="app-header">
        <a className="brand" href="/orders" aria-label="Vyapro home">Vyapro <span>development</span></a>
        <p>Shopkeeper workspace</p>
      </header>
      <div className="app-body">
        <nav className="sidebar" aria-label="Primary navigation">
          <ul>
            {navigation.map((item) => {
              const isCurrent = pathname === item.href || (item.href === '/orders' && pathname.startsWith('/orders/'))
              return <li key={item.href}><a aria-current={isCurrent ? 'page' : undefined} href={item.href}>{item.label}</a></li>
            })}
          </ul>
        </nav>
        <main id="main-content" className="main-content">{children}</main>
      </div>
    </div>
  )
}
