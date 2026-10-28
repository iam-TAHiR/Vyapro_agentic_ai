import type { ReactNode } from 'react'
import { AssistantWidget } from './AssistantWidget'
import type { PageContext } from './AssistantWidget'
import { VyaproBrand } from './VyaproBrand'
import { LocaleSelector, useI18n } from '../services/i18n'

const navigation = [
  { label: 'Shopkeeper Dashboard', href: '/shopkeeper' },
  { label: 'Orders', href: '/orders' },
  { label: 'Shopkeeper Assistant', href: '/new-order' },
  { label: 'Inventory', href: '/inventory' },
  { label: 'Customer Accounts', href: '/customers' },
  { label: 'Review Queue', href: '/review-queue' },
  { label: 'Activity', href: '/activity' },
  { label: 'Import Data', href: '/imports' },
]

type AppLayoutProps = { children: ReactNode; pageContext?: PageContext }

const customerNavigation = [{ label: 'Customer Dashboard', href: '/customer' }]
const workspaceLinks = [
  { label: 'Workspaces', href: '/', workspace: 'chooser' },
  { label: 'Shopkeeper', href: '/shopkeeper', workspace: 'shopkeeper' },
  { label: 'Customer', href: '/customer', workspace: 'customer' },
] as const

export function AppLayout({ children, workspace = 'shopkeeper', pageContext }: AppLayoutProps & { workspace?: 'customer' | 'shopkeeper' }) {
  const { t } = useI18n()
  const pathname = window.location.pathname
  const isCustomer = workspace === 'customer'
  const visibleNavigation = isCustomer ? customerNavigation : navigation
  return (
    <div className={`app-shell app-shell-${workspace}`}>
      <a className="skip-link" href="#main-content">{t('Skip to main content')}</a>
      <header className="app-header">
        <VyaproBrand href={isCustomer ? '/customer' : '/shopkeeper'} workspace={t(isCustomer ? 'Customer' : 'Shopkeeper')} />
        <p>{t(isCustomer ? 'Customer workspace · Order and track requests' : 'Shopkeeper workspace · Business operations')}</p>
        <nav className="portal-switcher" aria-label={t('Workspace navigation')}>
          {workspaceLinks.map((item) => <a className={item.workspace === 'chooser' ? 'portal-switcher-home' : undefined} key={item.workspace} href={item.href} aria-current={workspace === item.workspace ? 'page' : undefined} aria-label={item.workspace === 'chooser' ? t('Return to workspace selection') : `${t('Open')} ${t(item.label)} ${t('portal')}`} title={item.workspace === 'chooser' ? t('Workspace home') : t(item.label)}>{item.workspace === 'chooser' ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3.5 10.2 8.5-6.8 8.5 6.8" /><path d="M5.5 9.4v10.1h13V9.4M9.5 19.5v-6h5v6" /></svg> : t(item.label)}</a>)}
        </nav>
        <LocaleSelector compact />
      </header>
      <div className="app-body">
        <nav className="sidebar" aria-label={t('Primary navigation')}>
          <ul>
            {visibleNavigation.map((item) => {
              const isCurrent = pathname === item.href || (item.href === '/orders' && pathname.startsWith('/orders/')) || (item.href === '/new-order' && pathname.startsWith('/order-review/'))
              return <li key={item.href}><a aria-current={isCurrent ? 'page' : undefined} href={item.href}>{t(item.label)}</a></li>
            })}
          </ul>
        </nav>
        <main id="main-content" className="main-content">{children}</main>
      </div>
      <AssistantWidget actor={workspace} pageContext={pageContext} />
    </div>
  )
}
