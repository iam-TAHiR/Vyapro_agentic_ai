import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import type { FormEvent } from 'react'
import { AppLayout } from './AppLayout'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { formatStatusLabel } from '../services/status'
import { ApiError } from '../services/api'
import { listCustomers, listInventory } from '../services/catalog'
import type { Customer, Product } from '../services/catalog'
import { createCustomerProposal, formatMoney, getCustomerOrders, getProposal, reviewProposal } from '../services/orders'
import type { Order, OrderProposal, OrderSummary } from '../services/orders'
import { getSpeechLocale, localeTag, SpeechLocaleSelector, useI18n } from '../services/i18n'

type CartLine = { productId: string; quantity: string }
type SpeechResultEvent = { results: ArrayLike<ArrayLike<{ transcript: string }>> }
type SpeechErrorEvent = { error: string }
type SpeechRecognitionLike = {
  lang: string
  interimResults: boolean
  maxAlternatives: number
  onresult: ((event: SpeechResultEvent) => void) | null
  onerror: ((event: SpeechErrorEvent) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}
type SpeechRecognitionConstructor = new () => SpeechRecognitionLike
type SpeechRecognitionWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

// Browser SpeechRecognition API — Chrome/Edge only; no LLM, no API key.
const SpeechRecognitionAPI =
  (typeof window !== 'undefined' &&
    ((window as SpeechRecognitionWindow).SpeechRecognition || (window as SpeechRecognitionWindow).webkitSpeechRecognition)) || null

function requestError(reason: unknown) {
  if (reason instanceof ApiError) return reason.message
  return 'Vyapro could not reach the backend. Check that Flask is running and try again.'
}

export function CustomerOrderPage() {
  const { t } = useI18n()
  const [customers, setCustomers] = useState<Customer[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [customerId, setCustomerId] = useState('')
  const [search, setSearch] = useState('')
  const [cart, setCart] = useState<CartLine[]>([])
  const [message, setMessage] = useState('')
  const [proposal, setProposal] = useState<OrderProposal | null>(null)
  const [savedOrder, setSavedOrder] = useState<Order | null>(null)
  const [customerOrders, setCustomerOrders] = useState<OrderSummary[]>([])
  const [ordersError, setOrdersError] = useState('')
  const [conversation, setConversation] = useState<Array<{ role: 'customer' | 'assistant'; text: string }>>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [acceptSubstitutions, setAcceptSubstitutions] = useState(false)
  const [acceptPartial, setAcceptPartial] = useState(false)
  const [listening, setListening] = useState(false)
  const [voiceError, setVoiceError] = useState('')
  const turnKey = useRef<string | null>(null)
  const confirmKey = useRef<string | null>(null)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)

  useEffect(() => {
    let active = true
    Promise.all([listCustomers(), listInventory()])
      .then(([customerResult, inventoryResult]) => {
        if (!active) return
        setCustomers(customerResult.customers)
        setProducts(inventoryResult.products)
      })
      .catch((reason: unknown) => { if (active) setLoadError(requestError(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    const proposalId = new URLSearchParams(window.location.search).get('proposalId')
    if (!proposalId) return
    let active = true
    setLoading(true)
    getProposal(proposalId).then((value) => {
      if (!active) return
      setProposal(value)
      if (value.matchedCustomer) setCustomerId(value.matchedCustomer.id)
    }).catch((reason: unknown) => { if (active) setLoadError(requestError(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!customerId) {
      setCustomerOrders([])
      return
    }
    let active = true
    const loadOrders = () => getCustomerOrders(customerId)
      .then((orders) => { if (active) { setCustomerOrders(orders); setOrdersError('') } })
      .catch((reason: unknown) => { if (active) setOrdersError(requestError(reason)) })
    void loadOrders()
    const timer = window.setInterval(() => { void loadOrders() }, 30000)
    return () => { active = false; window.clearInterval(timer) }
  }, [customerId])

  // Cleanup recognition on unmount
  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.abort()
      }
    }
  }, [])

  const customer = customers.find((item) => item.id === customerId) ?? null
  const visibleProducts = useMemo(() => {
    const term = search.trim().toLowerCase()
    return products.filter((product) => !term || `${product.name} ${product.sku}`.toLowerCase().includes(term))
  }, [products, search])
  const cartLines = cart.map((line) => ({ ...line, product: products.find((item) => item.id === line.productId) })).filter((line) => line.product)
  const requiresSubstitutionAcceptance = Boolean(proposal?.items.some((item) => item.substitution))
  const requiresPartialAcceptance = Boolean(proposal?.items.some((item) => Number(item.remainingQuantity) > 0))

  function addProduct(productId: string) {
    turnKey.current = null
    setCart((current) => {
      const existing = current.find((item) => item.productId === productId)
      return existing
        ? current.map((item) => item.productId === productId ? { ...item, quantity: String(Number(item.quantity) + 1) } : item)
        : [...current, { productId, quantity: '1' }]
    })
  }

  function fillExample(name: string, request: string) {
    const match = customers.find((item) => item.name === name)
    if (match) setCustomerId(match.id)
    setCart([])
    setMessage(request)
    setProposal(null)
    setSavedOrder(null)
    setConversation([])
    setError('')
    turnKey.current = null
    confirmKey.current = null
  }

  function startNewRequest() {
    setProposal(null)
    setSavedOrder(null)
    setConversation([])
    setMessage('')
    setCart([])
    setAcceptSubstitutions(false)
    setAcceptPartial(false)
    setError('')
    turnKey.current = null
    confirmKey.current = null
  }

  function reviseRequest() {
    setProposal(null)
    setSavedOrder(null)
    setAcceptSubstitutions(false)
    setAcceptPartial(false)
    setConversation([])
    setError('')
    turnKey.current = null
    confirmKey.current = null
  }

  const startListening = useCallback(() => {
    if (!SpeechRecognitionAPI) return
    setVoiceError('')
    let recognition: SpeechRecognitionLike
    try {
      recognition = new SpeechRecognitionAPI()
    } catch {
      setVoiceError(t('Microphone input could not start. Check browser permission or type the order instead.'))
      return
    }
    recognition.lang = getSpeechLocale()
    recognition.interimResults = false
    recognition.maxAlternatives = 1
    recognition.onresult = (event: SpeechResultEvent) => {
      const transcript = event.results[0]?.[0]?.transcript ?? ''
      if (transcript) {
        setMessage((prev) => (prev.trim() ? prev.trim() + ' ' + transcript : transcript))
        turnKey.current = null
      }
    }
    recognition.onerror = (event: SpeechErrorEvent) => {
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        setVoiceError(`${t('Microphone error')}: ${event.error}. ${t('Please try again or type instead.')}`)
      }
      setListening(false)
    }
    recognition.onend = () => {
      setListening(false)
    }
    recognitionRef.current = recognition
    try {
      recognition.start()
      setListening(true)
    } catch {
      recognitionRef.current = null
      setVoiceError(t('Microphone input could not start. Check browser permission or type the order instead.'))
    }
  }, [t])

  function stopListening() {
    recognitionRef.current?.stop()
    setListening(false)
  }

  function speak(text: string) {
    if (!('speechSynthesis' in window)) {
      setVoiceError(t('Spoken playback is not supported in this browser.'))
      return
    }
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = getSpeechLocale()
    utterance.onerror = () => setVoiceError(t('Spoken playback is not supported in this browser.'))
    window.speechSynthesis.speak(utterance)
  }

  async function send(event?: FormEvent<HTMLFormElement>) {
    if (event) event.preventDefault()
    if (!customer) { setError(t('Choose a registered customer before sending an order request.')); return }
    if (!message.trim() && cartLines.length === 0) return
    setBusy(true)
    setError('')
    try {
      turnKey.current ??= crypto.randomUUID()
      const result = await createCustomerProposal(
        customer.id,
        message.trim(),
        turnKey.current,
        cartLines.map((line) => ({ productId: line.productId, quantity: line.quantity, unit: line.product!.unit })),
      )
      setProposal(result)
      setSavedOrder(null)
      const customerText = message.trim() || cartLines.map((line) => `${line.quantity} ${line.product?.unit} ${line.product?.name}`).join(', ')
      const warnings = result.validation.warnings.map((warning) => warning.message).join(' ')
      const partialItems = result.items.filter((item) => Number(item.remainingQuantity) > 0)
      const partialMessage = partialItems.map((item) => `${item.offeredQuantity} ${item.requested.unit} ${t('available now and')} ${item.remainingQuantity} ${item.requested.unit} ${t('pending for')} ${item.requested.productText}`).join('; ')
      const summary = result.status === 'needs_review'
        ? `${partialMessage ? t('Stock is short: {details}. No restock date is recorded. ').replace('{details}', partialMessage) : t('Rule-based checks passed. ')}${t('Estimated total for the available quantity:')} ${formatMoney(result.total)}. ${t('No order has been submitted; review and confirm below.')}`
        : `${t('This request is held for review.')} ${warnings || t('Please revise the order details.')} ${t('No order has been submitted.')}`
      setConversation((current) => [...current, { role: 'customer', text: customerText }, { role: 'assistant', text: summary }])
      setAcceptSubstitutions(false)
      setAcceptPartial(false)
    } catch (reason) {
      turnKey.current = null
      setError(requestError(reason))
    } finally {
      setBusy(false)
    }
  }

  async function confirmOrder() {
    if (!proposal || !customer) return
    setBusy(true)
    setError('')
    try {
      confirmKey.current ??= crypto.randomUUID()
      const result = await reviewProposal(proposal.id, proposal.version, acceptSubstitutions, confirmKey.current, acceptPartial)
      setSavedOrder(result.order)
      setCustomerOrders((current) => [result.order, ...current.filter((item) => item.id !== result.order.id)])
      setConversation((current) => [...current, { role: 'customer', text: t('I confirm this reviewed order.') }, { role: 'assistant', text: t('The backend saved order {orderId} after confirmation.').replace('{orderId}', result.order.id) }])
      confirmKey.current = null
      turnKey.current = null
    } catch (reason) {
      confirmKey.current = null
      setError(requestError(reason))
    } finally {
      setBusy(false)
    }
  }

  return <AppLayout workspace="customer" pageContext={{ page: 'customer-order' }}>
    <div className="page-heading"><div>
      <p className="eyebrow">{t('Customer workspace')}</p>
      <h1>{t('Customer ordering')}</h1>
      <p>{t('Choose your account, add products or describe what you need, and review the result before placing. Vyapro checks stock, price, and credit first.')}</p>
    </div></div>
    {loadError && <ErrorState message={loadError} onRetry={() => window.location.reload()} />}
    {error && <div className="inline-error" role="alert"><strong>{t('Order request not completed.')}</strong><p>{t(error)}</p></div>}
    {loading ? <div className="skeleton" role="status">{t('Loading registered customers and live products...')}</div> : <>
      <section className="customer-account-card">
        <label htmlFor="registered-customer">{t('Registered customer')}</label>
        <select id="registered-customer" value={customerId} onChange={(event) => {
          setCustomerId(event.target.value)
          setProposal(null)
          setSavedOrder(null)
          setCart([])
          setConversation([])
          setError('')
          turnKey.current = null
          confirmKey.current = null
        }}>
          <option value="">{t('Choose your customer account')}</option>
          {customers.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.id})</option>)}
        </select>
        {customer && <p>{t('Account selected:')} <strong>{customer.name}</strong>. {t('Backend credit checks use this registered account.')}</p>}
        <small>{t('Account selection is for this local development workspace and is not authentication.')}</small>
      </section>
      {customer && <section className="customer-orders" aria-labelledby="customer-orders-heading"><div className="section-title-row"><div><p className="eyebrow">{t('Saved status')}</p><h2 id="customer-orders-heading">{t('Your recent orders')}</h2></div><small>{t('Refreshes every 30 seconds')}</small></div>{ordersError && <p role="alert">{t(ordersError)}</p>}{customerOrders.length ? <ul>{customerOrders.map((order) => <li key={order.id}><strong>{order.id}</strong><span>{formatStatusLabel(order.status)} · {formatMoney(order.total)}</span><small>{new Intl.DateTimeFormat(localeTag(), { dateStyle: 'medium' }).format(new Date(order.receivedAt))}</small>{order.hasPending && <small>{t('Some quantity is pending. No restock date is recorded.')}</small>}</li>)}</ul> : !ordersError && <p>{t('Saved orders for this account will appear here.')}</p>}</section>}
      <section className="customer-catalog" aria-labelledby="customer-catalog-heading">
        <div className="section-title-row"><div><p className="eyebrow">{t('Live MySQL catalog')}</p><h2 id="customer-catalog-heading">{t('Find products')}</h2></div><span>{products.length} {t('Products')}</span></div>
        <label htmlFor="catalog-search">{t('Search products or SKU')}</label>
        <input id="catalog-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('Try rice or a product code')} />
        {products.length === 0 ? <EmptyState title={t('No products available')} message={t('The shopkeeper needs to add products and inventory before you can order.')} /> : <div className="customer-product-grid">
          {visibleProducts.map((product) => <article className="customer-product-card" key={product.id}>
            <div><strong>{product.name}</strong><small>{product.sku} · {product.quantityAvailable} {product.unit} available</small></div>
            <p>{formatMoney(product.unitPrice)} / {product.unit}</p>
            <button type="button" disabled={busy || Boolean(proposal)} onClick={() => addProduct(product.id)}>{t('Add')}</button>
          </article>)}
          {visibleProducts.length === 0 && <p>{t('No products match that search.')}</p>}
        </div>}
      </section>
      <section className="customer-demo" aria-label={t('Order examples')}>
        <strong>{t('Try an order example')}</strong>
        <p>{t('Examples use registered customers and products loaded from MySQL. Backend rules perform stock and credit checks.')}</p>
        <div>
          <button type="button" className="button-secondary" onClick={() => fillExample('Kaveri Provision House', 'Please send 2 kg of India Gate Basmati Rice.')}>{t('Routine order')}</button>
          <button type="button" className="button-secondary" onClick={() => fillExample('Shree Balaji Kirana Supply', 'Please send 100 kg of India Gate Basmati Rice.')}>{t('Credit review')}</button>
          <button type="button" className="button-secondary" onClick={() => fillExample('Kaveri Provision House', 'Please send 8 kg of Cow Ghee.')}>{t('Stock review')}</button>
        </div>
      </section>
      {cartLines.length > 0 && <section className="customer-cart">
        <h2>{t('Order summary')}</h2>
        <ul>{cartLines.map((line) => <li key={line.productId}>
          <span>{line.product?.name} · {formatMoney(line.product?.unitPrice)} / {line.product?.unit}</span>
          <div>
            <label className="sr-only" htmlFor={`quantity-${line.productId}`}>{t('Quantity for')} {line.product?.name}</label>
            <input id={`quantity-${line.productId}`} type="number" min="0.001" step="0.001" value={line.quantity} disabled={busy || Boolean(proposal)} onChange={(event) => {
              turnKey.current = null
              setCart((current) => current.map((item) => item.productId === line.productId ? { ...item, quantity: event.target.value } : item))
            }} />
            <span>{line.product?.unit}</span>
            <button type="button" className="button-secondary" disabled={busy || Boolean(proposal)} onClick={() => {
              turnKey.current = null
              setCart((current) => current.filter((item) => item.productId !== line.productId))
            }}>{t('Remove')}</button>
          </div>
        </li>)}</ul>
        <p className="muted-note">{t('The backend calculates the final price, stock, and credit result. This selection is not an order.')}</p>
        <button type="button" className="button-primary" disabled={busy || Boolean(proposal) || !customer} onClick={() => void send()}>{t('Review order')}</button>
      </section>}
      <form className="assistant-form customer-chat-form" onSubmit={(event) => void send(event)}>
        <label htmlFor="customer-order-message">{t('Describe the order')}</label>
        <textarea id="customer-order-message" value={message} onChange={(event) => { setMessage(event.target.value); turnKey.current = null }} placeholder={t('For example: 2 kg India Gate Basmati Rice')} rows={4} disabled={busy || Boolean(proposal)} />
        <small>{t('For multiple products, put each exact catalog product on a separate line. Example:')}<br />10 kg India Gate Basmati Rice<br />2 kg Cow Ghee<br />3 kg Chana Dal<br />{t('If you dictate, review the transcript and add line breaks before sending.')}</small>
        <div className="assistant-form-footer">
          <small>{t('Use one quantity, unit, and exact product per line, or add products from the catalog. Nothing is ordered until you confirm.')}</small>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <SpeechLocaleSelector />
            {SpeechRecognitionAPI && (
              <button
                type="button"
                className="button-secondary"
                onClick={listening ? stopListening : startListening}
                disabled={busy || Boolean(proposal)}
                aria-label={listening ? t('Stop listening') : t('Dictate order with microphone')}
                title={listening ? t('Click to stop') : t('Click to dictate')}
              >
                {listening ? t('Stop') : t('Speak')}
              </button>
            )}
        <button type="submit" disabled={busy || Boolean(proposal) || !customer || (!message.trim() && cartLines.length === 0)}>{busy ? t('Checking rules...') : t('Review order')}</button>
          </div>
        </div>
        {listening && <p role="status" style={{ color: 'var(--color-accent, #2563eb)', fontSize: '0.875rem', marginTop: '0.25rem' }}>{t('Listening... speak your order clearly.')}</p>}
        {voiceError && <p role="alert" style={{ color: 'var(--color-danger, #dc2626)', fontSize: '0.875rem', marginTop: '0.25rem' }}>{voiceError}</p>}
        {!SpeechRecognitionAPI && <small style={{ color: '#6b7280' }}>{t('Voice input is not supported in this browser. Chrome or Edge recommended.')}</small>}
      </form>
    </>}
    {conversation.length > 0 && <section className="customer-conversation" aria-label="Rule-based order review" aria-live="polite">
      {conversation.map((item, index) => <article className={`chat-message chat-message-${item.role}`} key={`${item.role}-${index}`}><strong>{item.role === 'customer' ? t('You') : t('Vyapro rule checks')}</strong><p>{item.text}</p>{item.role === 'assistant' && <button className="button-secondary" type="button" onClick={() => speak(item.text)}>{t('Speak this answer')}</button>}</article>)}
      {busy && <p role="status">{t('Checking the live catalog, inventory, price, and credit...')}</p>}
    </section>}
      {savedOrder && <section className="success-panel" role="status">
      <p className="eyebrow">{t('Order confirmed')}</p>
      <h2>{t('Order saved')}: {savedOrder.id}</h2>
      <p>{savedOrder.customerName} · {formatMoney(savedOrder.total)} · {formatStatusLabel(savedOrder.status)}</p>
      <p>{t('The backend saved the order after your explicit confirmation and recorded its activity. Pending quantities are not promised for a date and will be checked against current stock and credit before fulfillment.')}</p>
      {savedOrder.items.map((item) => <p key={item.product.id}>{item.product.name}: {item.quantity} {item.unit} {t('accepted now')}{Number(item.remainingQuantity) > 0 ? `; ${item.remainingQuantity} ${item.unit} ${t('pending')}` : ''}.</p>)}
      <div className="section-actions" style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
        <button type="button" className="button-primary" onClick={startNewRequest}>Place another order</button>
        <a className="button-link" href="#customer-orders-heading">{t('View your order history')}</a>
      </div>
    </section>}
    {proposal && !savedOrder && <section className="customer-proposal" aria-labelledby="customer-proposal-heading">
      <div className="section-title-row"><div><p className="eyebrow">{t('Order request')}</p><h2 id="customer-proposal-heading">{t('Your order summary')}</h2></div><span className="status-badge">{formatStatusLabel(proposal.status)}</span></div>
      <p>{t('Customer')}: <strong>{proposal.matchedCustomer?.name ?? t('Not matched')}</strong> · {t('Estimated total')}: <strong>{formatMoney(proposal.total)}</strong></p>
      <div className="customer-lines">{proposal.items.map((item, index) => <article className="customer-line-card" key={`${item.requested.productText}-${index}`}>
        <strong>{item.requested.quantity} {item.requested.unit} {item.requested.productText}</strong>
        <p>{item.matchedProduct?.name ?? t('Product needs review')} · {item.availability ? `${item.availability.quantityAvailable} ${item.availability.unit} ${t('available')}` : formatStatusLabel(item.status)}</p>
      {Number(item.remainingQuantity) > 0 && <div className="substitution-card"><strong>{item.offeredQuantity} {item.requested.unit} {t('available now;')} {item.remainingQuantity} {item.requested.unit} {t('would remain pending.')}</strong><p>{t('No restock date is recorded. The pending quantity will be checked against current stock and credit before it is fulfilled.')}</p></div>}
      {item.substitution && <div className="substitution-card"><strong>{t('Suggested substitute:')} {item.substitution.product.name}</strong><p>{t(item.substitution.reason)}</p><small>{t('Vyapro will use this only if you accept it.')}</small></div>}
      </article>)}</div>
      {proposal.validation.warnings.length > 0 && <div className="warning-list"><strong>{t('Why this proposal was held')}</strong><ul>{proposal.validation.warnings.map((warning, index) => <li key={`${warning.code}-${index}`}>{t(warning.message)}</li>)}</ul></div>}
      {proposal.status === 'needs_review' ? <div className="approval-panel">
        {requiresSubstitutionAcceptance && <label className="check-label"><input type="checkbox" checked={acceptSubstitutions} onChange={(event) => { setAcceptSubstitutions(event.target.checked); confirmKey.current = null }} disabled={busy} /> {t('I accept the substitute shown above.')}</label>}
        {requiresPartialAcceptance && <label className="check-label"><input type="checkbox" checked={acceptPartial} onChange={(event) => { setAcceptPartial(event.target.checked); confirmKey.current = null }} disabled={busy} /> {t('I accept the available quantity now and the remaining quantity pending, with no confirmed restock date.')}</label>}
        <p><strong>{t('Awaiting your confirmation.')}</strong> {t('This is a proposal, not an order. Stock, price, and credit are checked again when you confirm.')}</p>
        <button type="button" disabled={busy || (requiresSubstitutionAcceptance && !acceptSubstitutions) || (requiresPartialAcceptance && !acceptPartial)} onClick={() => void confirmOrder()}>{busy ? t('Confirming with backend...') : t('Confirm order')}</button>
      </div> : proposal.status === 'committed' ? <div className="approval-panel">
        <p>{t('This proposal has already been confirmed and placed as an order.')}</p>
        <button type="button" className="button-secondary" onClick={startNewRequest} disabled={busy}>{t('Start another order')}</button>
      </div> : <div className="approval-panel">
        <p>{t('This request is held. Adjust the cart or order text and review it again; no order was submitted.')}</p>
        <button type="button" className="button-secondary" onClick={reviseRequest} disabled={busy}>{t('Revise order')}</button>
      </div>}
      <button type="button" className="button-secondary" onClick={startNewRequest} disabled={busy}>{t('Start another order')}</button>
    </section>}
  </AppLayout>
}
