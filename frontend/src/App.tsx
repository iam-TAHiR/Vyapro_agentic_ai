import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { AppLayout } from './components/AppLayout'
import { EmptyState } from './components/EmptyState'
import { ErrorState } from './components/ErrorState'
import { ExampleDataTable } from './components/ExampleDataTable'
import { LoadingSkeleton } from './components/LoadingSkeleton'
import { OrderRow } from './components/OrderRow'
import { SearchFilter } from './components/SearchFilter'
import { StatusBadge } from './components/StatusBadge'
import { ImportsScreen } from './components/ImportsScreen'
import { CustomerOrderPage } from './components/CustomerOrderPage'
import { VyaproBrand } from './components/VyaproBrand'
import { ApiError } from './services/api'
import { formatStatusLabel } from './services/status'
import { listCustomers, listInventory } from './services/catalog'
import type { Customer, Product } from './services/catalog'
import {
  createAudioProposal,
  fulfillPendingOrder,
  formatMoney,
  getOrder,
  getOrderEvents,
  getProposal,
  listOrders,
  listProposals,
  rejectProposal,
  reviewProposal,
  sendAssistantMessage,
} from './services/orders'
import type { Order, OrderEvent, OrderProposal, OrderSummary } from './services/orders'
import './styles.css'
import { getSpeechLocale, I18nProvider, localeTag, LocaleSelector, SpeechLocaleSelector, useI18n } from './services/i18n'

type VoiceResultEvent = { results: ArrayLike<ArrayLike<{ transcript: string }>> }
type VoiceErrorEvent = { error: string }
type BrowserSpeechRecognition = {
  lang: string; interimResults: boolean; maxAlternatives: number
  onresult: ((event: VoiceResultEvent) => void) | null
  onerror: ((event: VoiceErrorEvent) => void) | null
  onend: (() => void) | null
  start(): void; stop(): void; abort(): void
}
type BrowserSpeechConstructor = new () => BrowserSpeechRecognition
type SpeechWindow = Window & { SpeechRecognition?: BrowserSpeechConstructor; webkitSpeechRecognition?: BrowserSpeechConstructor }
const BrowserSpeechAPI = typeof window === 'undefined' ? null : (window as SpeechWindow).SpeechRecognition ?? (window as SpeechWindow).webkitSpeechRecognition ?? null

type PageHeadingProps = { eyebrow: string; title: string; children?: ReactNode; actions?: ReactNode }
function PageHeading({ eyebrow, title, children, actions }: PageHeadingProps) {
  const { t } = useI18n()
  return <div className="page-heading"><div><p className="eyebrow">{t(eyebrow)}</p><h1>{t(title)}</h1>{children && <p>{typeof children === 'string' ? t(children) : children}</p>}</div>{actions}</div>
}

function messageFor(error: unknown) {
  if (error instanceof ApiError) return error.message
  return 'The server could not be reached. Check that the Flask backend is running, then try again.'
}

function describeToolCall(call: { name: string; status: string }, t: (value: string) => string) {
  const names: Record<string, string> = {
    explain_page: 'Explained this screen', get_my_order_history: 'Checked your recent orders',
    get_order_history: 'Checked customer orders', inspect_order: 'Checked the selected order',
    inspect_proposal: 'Checked the selected request', lookup_customer: 'Looked up a customer',
    match_product: 'Looked up a product', check_inventory: 'Checked stock',
    get_customer_pricing: 'Checked the customer price', check_credit: 'Checked available credit',
    get_substitution_options: 'Checked alternatives', prepare_order_proposal: 'Prepared a request for review',
    clarify_order: 'Rechecked the updated request', submit_order: 'Submitted the confirmed order',
  }
  const outcome = call.status === 'ok' || call.status === 'completed' ? 'done'
    : call.status === 'confirmation_required' ? 'waiting for confirmation'
      : 'needs attention'
  return `${t(names[call.name] ?? 'Vyapro check')}: ${t(outcome)}`
}

function LoadingMessage({ children = 'Loading live data…' }: { children?: string }) {
  const { t } = useI18n()
  return <div className="skeleton" role="status" aria-live="polite"><span>{t(children)}</span><i /><i /><i /></div>
}

function DashboardScreen() {
  const { t } = useI18n()
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [pending, setPending] = useState<OrderProposal[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    Promise.all([listOrders({ limit: 8 }), listProposals(), listInventory()])
      .then(([orderResult, proposalResult, inventoryResult]) => {
        if (!active) return
        setOrders(orderResult.orders)
        const incoming = proposalResult.proposals.filter((proposal) => ['needs_review', 'needs_clarification'].includes(proposal.status))
        setPending(incoming)
        setProducts(inventoryResult.products)
        setError('')
      })
      .catch((reason: unknown) => { if (active) setError(messageFor(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [refresh])

  return <AppLayout pageContext={{ page: 'shopkeeper-dashboard' }}>
    <PageHeading eyebrow="Overview" title="Shopkeeper workspace">Handle incoming orders and see what needs your attention.</PageHeading>
    <section className="shopkeeper-agent-banner"><div><p className="eyebrow">{t('Order help')}</p><h2>{t('Vyapro checks each request before it is placed')}</h2><p>{t('It checks the customer, products, stock, prices, and credit, then asks for review when a request needs attention.')}</p></div><a className="button-link" href="/new-order">{t('Open order assistant')}</a></section>
    {error && <ErrorState message={error} onRetry={() => setRefresh((value) => value + 1)} />}
    {loading ? <LoadingMessage /> : !error && <>
      <section className="metric-grid" aria-label={t('Live business summary')}>
        <article className="metric-card"><p>{t('Latest orders')}</p><strong>{orders.length}</strong><small>{t('Saved orders loaded')}</small></article>
        <article className="metric-card"><p>{t('Need attention')}</p><strong>{pending.length}</strong><small>{t('Requests to review or clarify')}</small></article>
        <article className="metric-card"><p>{t('Products')}</p><strong>{products.length}</strong><small>{t('Products in your catalog')}</small></article>
      </section>
      <section className="dashboard-section">
        <div className="section-title-row"><h2>{t('Recent orders')}</h2><a href="/orders">{t('View all orders')}</a></div>
        {orders.length ? <div className="table-wrap"><table><caption>{t('Recent orders from MySQL')}</caption><thead><tr>{['Order ID', 'Customer', 'Received', 'Total', 'Status', 'Source'].map((label) => <th key={label}>{t(label)}</th>)}<th><span className="sr-only">{t('Action')}</span></th></tr></thead><tbody>{orders.slice(0, 5).map((order) => <OrderRow key={order.id} order={order} />)}</tbody></table></div> : <EmptyState title="No orders yet" message="Approved orders will appear here." />}
      </section>
      <section className="dashboard-section"><div className="section-title-row"><h2>{t('Requests needing attention')}</h2><a href="/review-queue">{t('Open review list')}</a></div>
        {pending.length ? <div className="review-list">{pending.slice(0, 5).map((proposal) => <article className="review-row" key={proposal.id}><div><strong>{proposal.matchedCustomer?.name ?? t('Customer identification needed')}</strong><p>{proposal.items.map((item) => `${item.requested.quantity} ${item.requested.unit} ${item.requested.productText}`).join(', ') || t('Order details need clarification')}</p><small>{proposal.status === 'needs_clarification' ? t('Needs a detail') : t('Ready for your review')} · {proposal.source.channel}</small>{proposal.validation.warnings.length > 0 && <ul className="queue-reasons">{proposal.validation.warnings.map((warning) => <li key={warning.code}>{t(warning.message)}</li>)}</ul>}</div><a className="button-link" href={proposal.status === 'needs_review' ? `/order-review/${encodeURIComponent(proposal.id)}` : `/new-order?proposalId=${encodeURIComponent(proposal.id)}`}>{proposal.status === 'needs_review' ? t('Review request') : t('Add details')}</a></article>)}</div> : <EmptyState title="Nothing needs your attention" message="Requests that need clarification or review will appear here." />}
      </section>
    </>}
  </AppLayout>
}

function OrdersScreen() {
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    listOrders({ limit: 100 })
      .then((result) => { if (active) { setOrders(result.orders); setError('') } })
      .catch((reason: unknown) => { if (active) setError(messageFor(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [refresh])

  const statuses = useMemo(() => [...new Set(orders.map((order) => order.status))], [orders])
  const filteredOrders = useMemo(() => orders.filter((order) => {
    const searchable = `${order.id} ${order.customerName}`.toLowerCase()
    return searchable.includes(query.trim().toLowerCase()) && (!status || order.status === status)
  }), [orders, query, status])

  return <AppLayout pageContext={{ page: 'orders' }}>
    <PageHeading eyebrow="Orders" title="Order inbox" actions={<a className="button-link" href="/new-order">Create order request</a>}>Search real orders and review their current backend status.</PageHeading>
    <SearchFilter query={query} status={status} statuses={statuses} onQueryChange={setQuery} onStatusChange={setStatus} />
    {error && <ErrorState message={error} onRetry={() => setRefresh((value) => value + 1)} />}
    {loading ? <LoadingSkeleton /> : !error && (filteredOrders.length === 0
      ? <EmptyState title={orders.length ? 'No matching orders' : 'No orders yet'} message={orders.length ? 'Try another search or status.' : 'An order appears here after the backend confirms it.'} />
      : <div className="table-wrap"><table><caption>Orders returned by the backend</caption><thead><tr><th>Order ID</th><th>Customer</th><th>Received</th><th>Total</th><th>Status</th><th>Source</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{filteredOrders.map((order) => <OrderRow key={order.id} order={order} />)}</tbody></table></div>)}
  </AppLayout>
}

function InventoryScreen() {
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    listInventory().then((result) => { if (active) { setProducts(result.products); setError('') } })
      .catch((reason: unknown) => { if (active) setError(messageFor(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [refresh])

  return <AppLayout pageContext={{ page: 'inventory' }}><PageHeading eyebrow="Inventory" title="Product availability">Stock and unit prices are read from MySQL. Order decisions are checked again by the backend.</PageHeading>
    {error && <ErrorState message={error} onRetry={() => setRefresh((value) => value + 1)} />}
    {loading ? <LoadingMessage /> : !error && (products.length ? <ExampleDataTable caption="Products from the backend" columns={['SKU', 'Product', 'Available', 'Unit price']} rows={products.map((product) => [product.sku, product.name, `${product.quantityAvailable} ${product.unit}`, formatMoney(product.unitPrice)])} /> : <EmptyState title="No products yet" message="Add product records to MySQL before creating order proposals." />)}
  </AppLayout>
}

function CustomersScreen() {
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    listCustomers().then((result) => { if (active) { setCustomers(result.customers); setError('') } })
      .catch((reason: unknown) => { if (active) setError(messageFor(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [refresh])

  return <AppLayout pageContext={{ page: 'customers' }}><PageHeading eyebrow="Customers" title="Customer accounts">Credit balances are read from the backend. Vyapro never calculates credit decisions in the browser.</PageHeading>
    {error && <ErrorState message={error} onRetry={() => setRefresh((value) => value + 1)} />}
    {loading ? <LoadingMessage /> : !error && (customers.length ? <ExampleDataTable caption="Customers from the backend" columns={['Customer ID', 'Customer', 'Credit limit', 'Credit used', 'Available']} rows={customers.map((customer) => [customer.id, customer.name, formatMoney(customer.creditLimit), formatMoney(customer.creditUsed), formatMoney({ amountMinor: Math.max(0, customer.creditLimit.amountMinor - customer.creditUsed.amountMinor), currency: customer.creditLimit.currency })])} /> : <EmptyState title="No customers yet" message="Add customer records to MySQL before submitting order requests." />)}
  </AppLayout>
}

function ProposalCard({ proposal }: { proposal: OrderProposal }) {
  const { t } = useI18n()
  const hasSubstitutions = proposal.items.some((item) => item.substitution)
  const hasPartial = proposal.items.some((item) => Number(item.remainingQuantity) > 0)
  return <section className="proposal-card" aria-labelledby="proposal-title">
    <div className="section-title-row"><div><p className="eyebrow">{t('Order request')}</p><h2 id="proposal-title">{t('Review order details')}</h2></div><StatusBadge status={proposal.status} /></div>
    <dl className="proposal-summary"><div><dt>{t('Customer request')}</dt><dd>{proposal.interpretation.customerText || t('Needs identification')}</dd></div><div><dt>{t('Matched customer')}</dt><dd>{proposal.matchedCustomer?.name ?? t('Not matched')}</dd></div><div><dt>{t('Delivery')}</dt><dd>{proposal.interpretation.deliveryPreference ?? t('Not specified')}</dd></div><div><dt>{t('Estimated total')}</dt><dd>{formatMoney(proposal.total)}</dd></div></dl>
    <div className="table-wrap"><table><caption>{t('Requested items and checks')}</caption><thead><tr>{['Requested', 'Matched item', 'Available now', 'Offered now', 'Pending', 'Unit price', 'Line total'].map((label) => <th key={label}>{t(label)}</th>)}</tr></thead><tbody>{proposal.items.map((item, index) => <tr key={`${item.requested.productText}-${index}`}><td>{item.requested.quantity} {item.requested.unit} {item.requested.productText}</td><td>{item.substitution ? <><strong>{item.substitution.product.name}</strong><small className="cell-note">{t('Suggested:')} {item.substitution.reason}</small></> : item.matchedProduct?.name ?? t('Needs clarification')}</td><td>{item.availability ? `${item.availability.quantityAvailable} ${item.availability.unit}` : formatStatusLabel(item.status)}</td><td>{item.offeredQuantity} {item.requested.unit}</td><td>{item.remainingQuantity} {item.requested.unit}</td><td>{formatMoney(item.availability?.unitPrice)}</td><td>{formatMoney(item.lineTotal)}</td></tr>)}</tbody></table></div>
    {proposal.validation.warnings.length > 0 && <div className="warning-list" role="status"><h3>{t('Needs attention')}</h3><ul>{proposal.validation.warnings.map((warning, index) => <li key={`${warning.code}-${index}`}>{t(warning.message)}</li>)}</ul></div>}
    <p className="muted-note">Vyapro checked these details against the backend. Stock, price and credit are checked again before an order is saved.</p>
    {hasSubstitutions && <p className="substitution-note">A substitute will be used only if you explicitly accept it below.</p>}
    {hasPartial && <p className="substitution-note">The pending quantity has no confirmed restock date. It will not be fulfilled until stock and credit are checked again.</p>}
  </section>
}

function NewOrderScreen({ actor = 'shopkeeper' }: { actor?: 'customer' | 'shopkeeper' }) {
  const { t, locale } = useI18n()
  const [text, setText] = useState('')
  const [proposal, setProposal] = useState<OrderProposal | null>(null)
  const [answer, setAnswer] = useState('')
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; text: string }>>([])
  const [toolActivity, setToolActivity] = useState<string[]>([])
  const [acceptSubstitutions, setAcceptSubstitutions] = useState(false)
  const [acceptPartial, setAcceptPartial] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState<Order | null>(null)
  const [submissionMode, setSubmissionMode] = useState<'explicit_confirmation' | 'autonomous_policy' | null>(null)
  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [transcript, setTranscript] = useState('')
  const [recording, setRecording] = useState(false)
  const [speechListening, setSpeechListening] = useState(false)
  const [speechError, setSpeechError] = useState('')
  const createKey = useRef<string | null>(null)
  const audioKey = useRef<string | null>(null)
  const clarificationKey = useRef<string | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const recordingStream = useRef<MediaStream | null>(null)
  const recordingChunks = useRef<Blob[]>([])
  const speechRecognition = useRef<BrowserSpeechRecognition | null>(null)

  useEffect(() => () => {
    recorderRef.current?.stop()
    speechRecognition.current?.abort()
    recordingStream.current?.getTracks().forEach((track) => track.stop())
  }, [])
  useEffect(() => {
    const resetAudioIdempotency = () => { audioKey.current = null }
    window.addEventListener('vyapro:speech-locale-change', resetAudioIdempotency)
    return () => window.removeEventListener('vyapro:speech-locale-change', resetAudioIdempotency)
  }, [])

  function toggleTextSpeech() {
    if (speechListening) {
      speechRecognition.current?.stop()
      setSpeechListening(false)
      return
    }
    if (!BrowserSpeechAPI) {
      setSpeechError(t('Microphone input is not supported in this browser. You can type instead.'))
      return
    }
    try {
      const recognition = new BrowserSpeechAPI()
      recognition.lang = getSpeechLocale()
      recognition.interimResults = false
      recognition.maxAlternatives = 1
      recognition.onresult = (event) => {
        const recognized = event.results[0]?.[0]?.transcript?.trim()
        if (recognized) setText((current) => `${current.trim()}${current.trim() ? ' ' : ''}${recognized}`)
      }
      recognition.onerror = (event) => {
        if (event.error !== 'no-speech' && event.error !== 'aborted') setSpeechError(`${t('Microphone error')}: ${event.error}. ${t('Please try again or type instead.')}`)
        setSpeechListening(false)
      }
      recognition.onend = () => { setSpeechListening(false); speechRecognition.current = null }
      speechRecognition.current = recognition
      recognition.start()
      setSpeechError('')
      setSpeechListening(true)
    } catch {
      speechRecognition.current = null
      setSpeechListening(false)
      setSpeechError(t('Microphone input could not start. Check browser permission or type the order instead.'))
    }
  }

  function speakAssistant(text: string) {
    if (!('speechSynthesis' in window)) {
      setSpeechError(t('Spoken playback is not supported in this browser.'))
      return
    }
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = getSpeechLocale()
    utterance.onerror = () => setSpeechError(t('Spoken playback is not supported in this browser.'))
    window.speechSynthesis.speak(utterance)
  }
  const approvalKey = useRef<string | null>(null)
  const rejectKey = useRef<string | null>(null)

  useEffect(() => {
    const proposalId = new URLSearchParams(window.location.search).get('proposalId')
    if (!proposalId) return
    let active = true
    getProposal(proposalId).then((value) => { if (active) setProposal(value) })
      .catch((reason: unknown) => { if (active) setError(messageFor(reason)) })
    return () => { active = false }
  }, [])

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true); setError(''); setSuccess(null)
    setTranscript('')
    const requestText = text.trim()
    createKey.current ??= crypto.randomUUID()
    setMessages((current) => [...current, { role: 'user', text: requestText }])
    try {
      const result = await sendAssistantMessage(actor, requestText, createKey.current, proposal?.id, undefined, undefined, 'deterministic', { page: 'shopkeeper-assistant', locale })
      setProposal(result.proposal ?? proposal); setAcceptSubstitutions(false); setAcceptPartial(false)
      setSubmissionMode(result.submissionMode)
      setMessages((current) => [...current, { role: 'assistant', text: result.message }])
      setToolActivity(result.toolCalls.map((call) => describeToolCall(call, t)))
      if (result.order) setSuccess(result.order)
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }

  async function submitClarification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!proposal) return
    setBusy(true); setError(''); clarificationKey.current ??= crypto.randomUUID()
    const clarification = answer.trim()
    setMessages((current) => [...current, { role: 'user', text: clarification }])
    try {
      const result = await sendAssistantMessage(actor, clarification, clarificationKey.current, proposal.id, undefined, undefined, 'deterministic', { page: 'shopkeeper-assistant', locale })
      setProposal(result.proposal ?? proposal); setAnswer(''); clarificationKey.current = null
      setMessages((current) => [...current, { role: 'assistant', text: result.message }])
      setToolActivity(result.toolCalls.map((call) => describeToolCall(call, t)))
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }

  async function submitAudio() {
    if (!audioFile) return
    setBusy(true); setError(''); setSuccess(null)
    audioKey.current ??= crypto.randomUUID()
    try {
      const result = await createAudioProposal(audioFile, audioKey.current, getSpeechLocale())
      setTranscript(result.transcript); setProposal(result.proposal); setAcceptSubstitutions(false); setAcceptPartial(false)
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop()
      setRecording(false)
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      recordingStream.current = stream
      recordingChunks.current = []
      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder
      recorder.ondataavailable = (event) => { if (event.data.size) recordingChunks.current.push(event.data) }
      recorder.onstop = () => {
        const type = recorder.mimeType || 'audio/webm'
        const extension = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm'
        const recordingFile = new File(recordingChunks.current, `order-recording.${extension}`, { type })
        setAudioFile(recordingFile)
        audioKey.current = null
        recordingStream.current?.getTracks().forEach((track) => track.stop())
        recordingStream.current = null
      }
      recorder.start()
      setRecording(true)
      setError('')
    } catch {
      setError(t('Microphone access is unavailable. Check browser permission or upload an audio file instead.'))
    }
  }

  async function approve() {
    if (!proposal) return
    setBusy(true); setError(''); approvalKey.current ??= crypto.randomUUID()
    try {
      const result = await sendAssistantMessage(
        actor,
        'Submit the order I have explicitly confirmed.',
        approvalKey.current,
        proposal.id,
        { proposalId: proposal.id, proposalVersion: proposal.version, confirmed: true, acceptSubstitutions, acceptPartial },
        undefined,
        'deterministic',
        { page: 'shopkeeper-assistant', entityType: 'proposal', entityId: proposal.id, locale },
      )
      if (!result.order) { setError(result.message); return }
      setSuccess(result.order); approvalKey.current = null
      setSubmissionMode(result.submissionMode ?? 'explicit_confirmation')
      setProposal(result.proposal ?? proposal)
      setMessages((current) => [...current, { role: 'assistant', text: result.message }])
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }

  async function reject() {
    if (!proposal) return
    setBusy(true); setError(''); rejectKey.current ??= crypto.randomUUID()
    try {
      await rejectProposal(proposal.id, rejectKey.current)
      setProposal({ ...proposal, status: 'rejected' })
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }

  return <AppLayout pageContext={{ page: 'shopkeeper-assistant' }}>
    <PageHeading eyebrow={t(actor === 'customer' ? 'Customer assistant · Web' : 'Shopkeeper assistant · Web')} title={t(actor === 'customer' ? 'Talk to Vyapro about an order' : 'Vyapro order assistant')}>{t(actor === 'customer' ? 'Describe what you need. Vyapro checks the customer, stock, price, and credit before asking you to confirm.' : 'Ask about orders, customers, products, stock, prices, or credit. Vyapro shows its checks and warnings, and waits for confirmation before placing an order.')}</PageHeading>
    {messages.length > 0 && <section className="assistant-transcript" aria-label={t('Assistant conversation')} aria-live="polite">{messages.map((message, index) => <article className={`chat-message chat-message-${message.role}`} key={`${message.role}-${index}`}><strong>{message.role === 'user' ? t('You') : 'Vyapro'}</strong><p>{message.text}</p>{message.role === 'assistant' && <button type="button" className="button-secondary" onClick={() => speakAssistant(message.text)}>{t('Speak this answer')}</button>}</article>)}{toolActivity.length > 0 && <details><summary>{t('What Vyapro checked')}</summary><ul>{toolActivity.map((item, index) => <li key={`${item}-${index}`}>{t(item)}</li>)}</ul></details>}</section>}
    <form className="assistant-form" onSubmit={submitRequest}>
      <label htmlFor="order-message">{t(actor === 'customer' ? 'How can Vyapro help?' : 'Ask Vyapro')}</label>
      <textarea id="order-message" value={text} onChange={(event) => { setText(event.target.value); createKey.current = null }} placeholder={t('For example: Send Sharma Stores 10 kg of basmati rice tomorrow.')} rows={4} required disabled={busy} />
      {speechError && <p className="assistant-widget-voice-error" role="alert">{speechError}</p>}
      {speechListening && <p role="status">{t('Listening… speak now. Your words will appear above so you can edit them.')}</p>}
      <div className="assistant-form-footer"><small>{t('Registered tools read live MySQL data. A proposal is never an order until confirmed and saved by the backend.')}</small><div className="assistant-form-actions"><SpeechLocaleSelector /><button type="button" className="button-secondary" onClick={toggleTextSpeech} disabled={busy} aria-label={speechListening ? t('Stop listening') : t('Speak to Vyapro')}>{speechListening ? t('Stop') : t('Speak')}</button><button type="submit" disabled={busy || speechListening || !text.trim()}>{busy ? t('Working…') : t('Send to Vyapro')}</button></div></div>
    </form>
    <section className="assistant-form audio-form"><label htmlFor="order-audio">{t('Or record or upload an audio order')}</label><div className="audio-controls"><button className={recording ? 'button-recording' : 'button-secondary'} type="button" onClick={toggleRecording} disabled={busy}>{recording ? t('Stop recording') : t('Record with microphone')}</button><input id="order-audio" type="file" accept="audio/*,.m4a,.mp3,.wav,.webm,.ogg,.flac" onChange={(event) => { setAudioFile(event.target.files?.[0] ?? null); audioKey.current = null; setTranscript('') }} disabled={busy || recording} /></div>{audioFile && <small>{t('Selected:')} {audioFile.name}</small>}<div className="assistant-form-footer"><small>{t('Audio uses the configured transcription model, then follows the same backend validation and approval flow.')}</small><button type="button" disabled={busy || !audioFile || recording} onClick={submitAudio}>{busy ? t('Transcribing…') : t('Transcribe and review')}</button></div></section>
    {error && <div className="inline-error" role="alert"><strong>{t('Request not completed.')}</strong><p>{t(error)}</p></div>}
    {transcript && <section className="transcript-card"><p className="eyebrow">{t('Voice transcript')}</p><p>{transcript}</p></section>}
    {proposal && <>
      <ProposalCard proposal={proposal} />
      {proposal.status === 'needs_clarification' && <form className="clarification-form" onSubmit={submitClarification}><label htmlFor="clarification">{t('Clarify the request')}</label><input id="clarification" value={answer} onChange={(event) => { setAnswer(event.target.value); clarificationKey.current = null }} placeholder={t('Add the exact customer or product detail')} required disabled={busy} /><button type="submit" disabled={busy || !answer.trim()}>{busy ? t('Checking…') : t('Update proposal')}</button></form>}
      {proposal.status === 'needs_review' && <div className="approval-panel">{proposal.items.some((item) => item.substitution) && <label className="check-label"><input type="checkbox" checked={acceptSubstitutions} onChange={(event) => setAcceptSubstitutions(event.target.checked)} disabled={busy} /> {t('I accept the substitutions shown above.')}</label>}{proposal.items.some((item) => Number(item.remainingQuantity) > 0) && <label className="check-label"><input type="checkbox" checked={acceptPartial} onChange={(event) => setAcceptPartial(event.target.checked)} disabled={busy} /> {t('I accept the available quantity now and the remaining quantity pending, with no confirmed restock date.')}</label>}<p>{t('Approving rechecks current stock, prices and credit before saving.')}</p><button type="button" onClick={approve} disabled={busy || (proposal.items.some((item) => item.substitution) && !acceptSubstitutions) || (proposal.items.some((item) => Number(item.remainingQuantity) > 0) && !acceptPartial)}>{busy ? t('Rechecking…') : t('Approve and create order')}</button></div>}
      {['needs_review', 'needs_clarification'].includes(proposal.status) && <button className="button-secondary" type="button" onClick={reject} disabled={busy}>{t('Reject proposal')}</button>}
    </>}
    {proposal && proposal.status === 'needs_review' && !success && <p className="approval-state-note">{t('Awaiting confirmation. No order is saved until the backend returns a confirmed order.')}</p>}
    {proposal && proposal.status === 'needs_clarification' && <p className="approval-state-note">{t('Held for clarification. No order has been submitted.')}</p>}
    {success && <section className="success-panel" role="status"><p className="eyebrow">{t('Order confirmed')}</p><h2>{success.id}</h2><p>{success.customerName} · {formatMoney(success.total)}</p><p>{t(submissionMode === 'autonomous_policy' ? 'Vyapro submitted this order automatically under the configured routine-order policy.' : 'The backend saved this order after explicit confirmation and recorded its activity.')}</p><a className="button-link" href={`/orders/${encodeURIComponent(success.id)}`}>{t('View order')}</a></section>}
  </AppLayout>
}

function ReviewQueueScreen() {
  const { t } = useI18n()
  const [proposals, setProposals] = useState<OrderProposal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    listProposals().then((result) => { if (active) { setProposals(result.proposals.filter((proposal) => ['needs_review', 'needs_clarification'].includes(proposal.status))); setError('') } })
      .catch((reason: unknown) => { if (active) setError(messageFor(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [refresh])

  return <AppLayout pageContext={{ page: 'review-queue' }}><PageHeading eyebrow="Review queue" title="Incoming orders and held requests">Review proposals awaiting approval and resolve requests held for clarification. The backend remains authoritative.</PageHeading>
    {error && <ErrorState message={error} onRetry={() => setRefresh((value) => value + 1)} />}
    {loading ? <LoadingMessage /> : !error && (proposals.length ? <div className="review-list">{proposals.map((proposal) => <article className="review-row" key={proposal.id}><div><strong>{proposal.matchedCustomer?.name ?? t('Customer needs review')}</strong><p>{proposal.items.map((item) => `${item.requested.quantity} ${item.requested.unit} ${item.requested.productText}`).join(' · ') || t('Order details need clarification')}</p><small>{proposal.status === 'needs_clarification' ? t('Held for clarification') : t('Awaiting approval')} · {formatMoney(proposal.total)} · {t(proposal.source.channel)}</small>{proposal.validation.warnings.length > 0 && <ul className="queue-reasons">{proposal.validation.warnings.map((warning) => <li key={warning.code}>{t(warning.message)}</li>)}</ul>}</div><a className="button-link" href={proposal.status === 'needs_review' ? `/order-review/${encodeURIComponent(proposal.id)}` : `/new-order?proposalId=${encodeURIComponent(proposal.id)}`}>{proposal.status === 'needs_review' ? t('Review') : t('Clarify')}</a></article>)}</div> : <EmptyState title="No orders need review" message="Incoming proposals and requests needing clarification will appear here." />)}
  </AppLayout>
}

function ProposalReviewScreen({ proposalId }: { proposalId: string }) {
  const { t } = useI18n()
  const [proposal, setProposal] = useState<OrderProposal | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [accepted, setAccepted] = useState(false)
  const [acceptedPartial, setAcceptedPartial] = useState(false)
  const [busy, setBusy] = useState(false)
  const [order, setOrder] = useState<Order | null>(null)
  const [refresh, setRefresh] = useState(0)
  const approvalKey = useRef<string | null>(null)
  const rejectKey = useRef<string | null>(null)
  useEffect(() => {
    let active = true
    setLoading(true)
    getProposal(proposalId)
      .then((value) => { if (active) { setProposal(value); setError('') } })
      .catch((reason: unknown) => { if (active) setError(messageFor(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [proposalId, refresh])

  async function approve() {
    if (!proposal) return
    setBusy(true); setError('')
    try {
      approvalKey.current ??= crypto.randomUUID()
      const result = await reviewProposal(proposal.id, proposal.version, accepted, approvalKey.current, acceptedPartial)
      setOrder(result.order)
    } catch (reason) { setError(messageFor(reason)); setRefresh((value) => value + 1) } finally { setBusy(false) }
  }

  async function reject() {
    if (!proposal) return
    setBusy(true); setError('')
    try {
      rejectKey.current ??= crypto.randomUUID()
      await rejectProposal(proposal.id, rejectKey.current)
      setProposal({ ...proposal, status: 'rejected' })
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }

  return <AppLayout pageContext={{ page: 'order-review', entityType: 'proposal', entityId: proposalId }}><PageHeading eyebrow={t('Order review')} title={t('Review proposal')}>{t('Check the backend interpretation and validation before creating an order.')}</PageHeading>
    {error && <div className="inline-error" role="alert">{error}</div>}
    {loading ? <LoadingMessage /> : proposal && <><ProposalCard proposal={proposal} />{proposal.status === 'needs_review' && <div className="approval-panel">{proposal.items.some((item) => item.substitution) && <label className="check-label"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /> {t('I accept the substitutions shown above.')}</label>}{proposal.items.some((item) => Number(item.remainingQuantity) > 0) && <label className="check-label"><input type="checkbox" checked={acceptedPartial} onChange={(event) => setAcceptedPartial(event.target.checked)} /> {t('I accept the available quantity now and the remaining quantity pending, with no confirmed restock date.')}</label>}<button type="button" disabled={busy || (proposal.items.some((item) => item.substitution) && !accepted) || (proposal.items.some((item) => Number(item.remainingQuantity) > 0) && !acceptedPartial)} onClick={approve}>{busy ? t('Rechecking…') : t('Approve and create order')}</button><button className="button-secondary" type="button" disabled={busy} onClick={reject}>{t('Reject proposal')}</button></div>}</>}
    {order && <div className="success-panel" role="status"><h2>{t('Order confirmed')}</h2><a href={`/orders/${encodeURIComponent(order.id)}`}>{order.id}</a></div>}
  </AppLayout>
}

function OrderDetailsScreen({ orderId }: { orderId: string }) {
  const { t } = useI18n()
  const [order, setOrder] = useState<Order | null>(null)
  const [events, setEvents] = useState<OrderEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [fulfilling, setFulfilling] = useState(false)
  const [refreshOrder, setRefreshOrder] = useState(0)
  useEffect(() => {
    let active = true
    Promise.all([getOrder(orderId), getOrderEvents(orderId)])
      .then(([currentOrder, history]) => { if (active) { setOrder(currentOrder); setEvents(history) } })
      .catch((reason: unknown) => { if (active) setError(messageFor(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [orderId, refreshOrder])

  async function fulfillPending() {
    if (!order || !window.confirm(t('Vyapro will recheck current stock and credit, then fulfill only the quantity currently available. No restock date is promised. Continue?'))) return
    setFulfilling(true)
    setError('')
    try {
      const result = await fulfillPendingOrder(order.id, crypto.randomUUID())
      setOrder(result.order)
      setRefreshOrder((value) => value + 1)
    } catch (reason) {
      setError(messageFor(reason))
    } finally {
      setFulfilling(false)
    }
  }

  return <AppLayout pageContext={{ page: 'orders', entityType: 'order', entityId: orderId }}><PageHeading eyebrow="Order details" title={order?.id ?? 'Order'}><a className="back-link" href="/orders">← {t('Back to orders')}</a></PageHeading>
    {error && <ErrorState message={error} onRetry={() => window.location.reload()} />}
    {loading ? <LoadingMessage /> : order && <>
      <section className="detail-card"><div className="section-title-row"><div><h2>{order.customerName}</h2><p className="muted-note">{t('Received')} {new Date(order.receivedAt).toLocaleString(localeTag())} · {t('Source')}: {t(order.source)}</p></div><StatusBadge status={order.status} /></div>
        <div className="table-wrap"><table><caption>{t('Accepted order quantities and fulfillment')}</caption><thead><tr>{['Product', 'Requested', 'Fulfilled', 'Pending', 'Unit price', 'Line total'].map((label) => <th key={label}>{t(label)}</th>)}</tr></thead><tbody>{order.items.map((item) => <tr key={item.product.id}><td>{item.product.name} <small className="cell-note">{item.product.sku}</small></td><td>{item.requestedQuantity} {item.unit}</td><td>{item.quantity} {item.unit}</td><td>{item.remainingQuantity} {item.unit}</td><td>{formatMoney(item.unitPrice)}</td><td>{formatMoney(item.lineTotal)}</td></tr>)}</tbody><tfoot><tr><th colSpan={5}>{t('Order total for fulfilled quantity')}</th><td><strong>{formatMoney(order.total)}</strong></td></tr></tfoot></table></div>
        {order.items.some((item) => Number(item.remainingQuantity) > 0) && <div className="approval-panel"><p>These quantities remain pending: {order.items.filter((item) => Number(item.remainingQuantity) > 0).map((item) => `${item.remainingQuantity} ${item.unit} ${item.product.name}`).join(', ')}. Vyapro has no verified restock date.</p><button type="button" onClick={() => void fulfillPending()} disabled={fulfilling}>{fulfilling ? 'Rechecking stock and credit…' : 'Recheck and fulfill available quantity'}</button></div>}
      </section>
      <section className="dashboard-section"><h2>{t('Processing history')}</h2>{events.length ? <ol className="activity-list">{events.map((event, index) => <li key={`${event.type}-${event.createdAt}-${index}`}><strong>{t(event.type.replaceAll('_', ' '))}</strong><span>{new Date(event.createdAt).toLocaleString(localeTag())} · {t(event.actor)} · {t(event.source)}</span></li>)}</ol> : <p>{t('No activity events are available.')}</p>}</section>
    </>}
  </AppLayout>
}

function ActivityScreen() {
  const { t } = useI18n()
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [histories, setHistories] = useState<Array<{ order: OrderSummary; events: OrderEvent[] }>>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    listOrders({ limit: 10 }).then(async ({ orders: recent }) => {
      const history = await Promise.all(recent.map(async (order) => ({ order, events: await getOrderEvents(order.id) })))
      if (active) { setOrders(recent); setHistories(history) }
    }).catch((reason: unknown) => { if (active) setError(messageFor(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  return <AppLayout pageContext={{ page: 'activity' }}><PageHeading eyebrow="Activity" title="Recent processing activity">Interpretation, validation and approval events recorded by the backend.</PageHeading>
    {error && <ErrorState message={error} onRetry={() => window.location.reload()} />}
    {loading ? <LoadingMessage /> : !error && (orders.length ? <div className="activity-feed">{histories.flatMap(({ order, events }) => events.map((event, index) => <article className="activity-item" key={`${order.id}-${event.type}-${index}`}><div className="activity-mark" aria-hidden="true">✓</div><div><strong>{t(event.type.replaceAll('_', ' '))}</strong><p><a href={`/orders/${encodeURIComponent(order.id)}`}>{order.id}</a> · {order.customerName}</p><small>{new Date(event.createdAt).toLocaleString(localeTag())} · {t(event.source)}</small></div></article>))}</div> : <EmptyState title="No activity yet" message="Order processing events will appear here." />)}
  </AppLayout>
}

export default function App() {
  return <I18nProvider><AppRoutes /></I18nProvider>
}

function AppRoutes() {
  const { locale } = useI18n()
  void locale
  const pathname = window.location.pathname
  if (pathname === '/') return <WorkspaceChooser />
  if (pathname === '/shopkeeper') return <DashboardScreen />
  if (pathname.startsWith('/order-review/')) return <ProposalReviewScreen proposalId={decodeURIComponent(pathname.split('/').at(-1) ?? '')} />
  if (pathname.startsWith('/orders/')) return <OrderDetailsScreen orderId={decodeURIComponent(pathname.split('/').at(-1) ?? '')} />
  if (pathname === '/orders') return <OrdersScreen />
  if (pathname === '/new-order') return <NewOrderScreen />
  if (pathname === '/customer' || pathname === '/customer-assistant' || pathname === '/customer-order') return <CustomerOrderPage />
  if (pathname === '/inventory') return <InventoryScreen />
  if (pathname === '/customers') return <CustomersScreen />
  if (pathname === '/review-queue') return <ReviewQueueScreen />
  if (pathname === '/activity') return <ActivityScreen />
  if (pathname === '/imports') return <ImportsScreen />
  return <WorkspaceChooser />
}

function WorkspaceChooser() {
  const { t } = useI18n()
  return <main className="workspace-chooser"><div className="workspace-chooser-inner"><header className="workspace-chooser-header"><VyaproBrand href="/" workspace={t('Workspaces')} /><LocaleSelector /><p>{t('Choose how you want to use Vyapro in this local demo.')}</p></header><div className="workspace-cards"><a className="workspace-card workspace-card-shopkeeper" href="/shopkeeper"><span className="workspace-icon" aria-hidden="true">S</span><p className="eyebrow">{t('Business operations')}</p><h1>{t('Shopkeeper workspace')}</h1><p>{t('Monitor incoming orders, inventory, customer accounts, approvals, and Vyapro agent activity.')}</p><strong>{t('Open shopkeeper dashboard')} <span aria-hidden="true">→</span></strong></a><a className="workspace-card workspace-card-customer" href="/customer"><span className="workspace-icon" aria-hidden="true">C</span><p className="eyebrow">{t('Customer ordering')}</p><h1>{t('Customer workspace')}</h1><p>{t('Search the live catalog, ask Vyapro to prepare an order, review substitutions, and track its status.')}</p><strong>{t('Open customer dashboard')} <span aria-hidden="true">→</span></strong></a></div><p className="workspace-demo-note">{t('Both workspaces use the same backend order engine. Account selection in this demo is not authentication.')}</p></div></main>
}
