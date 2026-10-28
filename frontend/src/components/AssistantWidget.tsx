import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../services/api'
import { sendAssistantMessage } from '../services/orders'
import type { AgentTurn } from '../services/orders'
import { getSpeechLocale, SpeechLocaleSelector, useI18n } from '../services/i18n'

export type PageContext = {
  page: string
  entityType?: 'order' | 'product' | 'customer' | 'proposal'
  entityId?: string
  entityLabel?: string
}

type ChatLine = { role: 'user' | 'assistant'; text: string }
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

const SpeechRecognitionAPI = typeof window === 'undefined'
  ? null
  : (window as SpeechRecognitionWindow).SpeechRecognition ?? (window as SpeechRecognitionWindow).webkitSpeechRecognition ?? null

const toolLabels: Record<string, string> = {
  explain_page: 'Explained this screen',
  get_my_order_history: 'Checked your recent orders',
  get_order_history: 'Checked customer order history',
  inspect_order: 'Checked the selected order',
  inspect_proposal: 'Checked the selected request',
  lookup_customer: 'Looked up a customer',
  match_product: 'Looked up a product',
  check_inventory: 'Checked available stock',
  get_customer_pricing: 'Checked the customer price',
  check_credit: 'Checked customer credit',
  get_substitution_options: 'Checked alternatives',
  prepare_order_proposal: 'Prepared an order for review',
  clarify_order: 'Rechecked the updated request',
  submit_order: 'Submitted the confirmed order',
}

function friendlyStatus(status: string) {
  if (status === 'completed' || status === 'ok') return 'Done'
  if (status === 'confirmation_required') return 'Waiting for your confirmation'
  if (status === 'TOOL_NOT_PERMITTED' || status === 'UNKNOWN_TOOL') return 'Unavailable in this workspace'
  if (status === 'INVALID_TOOL_ARGUMENTS') return 'Could not check this request'
  return status.toLowerCase().includes('failed') ? 'Could not complete' : status.replaceAll('_', ' ').toLowerCase()
}

function friendlyEscalation(reason: string) {
  const messages: Record<string, string> = {
    explicit_confirmation_required: 'This request needs your confirmation before an order can be placed.',
    tool_permission_denied: 'That action is not available in this workspace. No order was placed.',
    repeated_tool_call: 'I could not safely complete that check. Try asking in a different way.',
    tool_execution_failed: 'A business check could not be completed. No order was placed.',
    iteration_limit: 'I need one more detail to continue safely. No order was placed.',
    agent_timeout: 'The check took too long. No order was placed; please try again.',
  }
  return messages[reason] ?? 'I could not safely finish that request. No order was placed.'
}

function errorMessage(reason: unknown) {
  if (reason instanceof ApiError) return reason.message
  return 'Vyapro could not reach the backend. Check that Flask is running and try again.'
}

export function AssistantWidget({ actor, pageContext }: { actor: 'customer' | 'shopkeeper'; pageContext?: PageContext }) {
  const { t, locale } = useI18n()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [lines, setLines] = useState<ChatLine[]>([])
  const [lastTurn, setLastTurn] = useState<AgentTurn | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [listening, setListening] = useState(false)
  const [voiceError, setVoiceError] = useState('')
  const dialogRef = useRef<HTMLElement | null>(null)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)

  useEffect(() => {
    if (!open) return
    dialogRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        recognitionRef.current?.abort()
        setListening(false)
        setOpen(false)
      }
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open])

  useEffect(() => () => recognitionRef.current?.abort(), [])

  function toggleVoice() {
    if (listening) {
      recognitionRef.current?.stop()
      setListening(false)
      return
    }
    if (!SpeechRecognitionAPI) {
      setVoiceError(t('Microphone input is not supported in this browser. You can type instead.'))
      return
    }
    setVoiceError('')
    let recognition: SpeechRecognitionLike
    try {
      recognition = new SpeechRecognitionAPI()
      recognition.lang = getSpeechLocale()
      recognition.interimResults = false
      recognition.maxAlternatives = 1
      recognition.onresult = (event) => {
        const transcript = event.results[0]?.[0]?.transcript?.trim()
        if (transcript) setDraft((current) => `${current.trim()}${current.trim() ? ' ' : ''}${transcript}`)
      }
      recognition.onerror = (event) => {
        if (event.error !== 'no-speech' && event.error !== 'aborted') setVoiceError(t('Microphone input could not start. Check browser permission or type the order instead.'))
        setListening(false)
      }
      recognition.onend = () => { setListening(false); recognitionRef.current = null }
      recognitionRef.current = recognition
      recognition.start()
      setListening(true)
    } catch {
      recognitionRef.current = null
      setListening(false)
      setVoiceError(t('Microphone input could not start. Check browser permission or type the order instead.'))
    }
  }

  function clearConversation() {
    recognitionRef.current?.abort()
    recognitionRef.current = null
    setListening(false)
    setLines([])
    setLastTurn(null)
    setDraft('')
    setError('')
    setVoiceError('')
  }

  function speak(text: string) {
    if (!("speechSynthesis" in window)) {
      setVoiceError(t('Spoken playback is not supported in this browser.'))
      return
    }
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = getSpeechLocale()
    window.speechSynthesis.speak(utterance)
  }

  // Build a context-aware placeholder based on the current page
  function getPlaceholder() {
    if (pageContext?.page === 'orders' && pageContext.entityType === 'order') return t('Ask about this order, e.g. "What is its status?"')
    if (pageContext?.page === 'orders') return t('Ask about order statuses or open an order for details...')
    if (pageContext?.page === 'inventory') return t('Ask about stock, e.g. "Check rice stock"')
    if (pageContext?.page === 'review-queue') return t('Ask about pending approvals...')
    if (pageContext?.page === 'customers') return t('Ask about a customer credit or history...')
    return t('Ask Vyapro...')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || busy || listening) return
    setBusy(true)
    setError('')
    try {
      const result = await sendAssistantMessage(
        actor,
        text,
        crypto.randomUUID(),
        undefined,
        undefined,
        undefined,
        'deterministic',
        { page: pageContext?.page ?? 'workspace', ...pageContext, locale },
        'helper',
      )
      setLines((current) => [...current, { role: 'user', text }, { role: 'assistant', text: result.message }])
      setLastTurn(result)
      setDraft('')
    } catch (reason) {
      setError(t(errorMessage(reason)))
    } finally {
      setBusy(false)
    }
  }

  return <>
    {open && <section className={`assistant-widget-panel assistant-widget-${actor}`} role="dialog" aria-labelledby="assistant-widget-title" aria-modal="false" tabIndex={-1} ref={dialogRef}>
      <header className="assistant-widget-header"><div><span className="assistant-widget-avatar" aria-hidden="true">V</span><div><strong id="assistant-widget-title">{t('Vyapro App Guide')}</strong><small>{t('Explains screens and helps you navigate')}</small></div></div><button type="button" className="assistant-widget-close" onClick={() => { recognitionRef.current?.abort(); setListening(false); setOpen(false) }} aria-label={t('Close Vyapro Assistant')}>×</button></header>
      <div className="assistant-widget-content">
        {pageContext?.entityType && pageContext.entityId && <div className="assistant-widget-context-badge"><small>Looking at: {pageContext.entityLabel ?? `${pageContext.entityType} ${pageContext.entityId}`}</small></div>}
        {lines.length === 0 && <div className="assistant-widget-intro"><strong>{t('How can I help?')}</strong><p>{t('Ask what a card, button, warning, or step means. I can explain the page you are viewing and guide you through the next step.')}</p><small>{t('This guide does not create or change orders. Use the main order assistant for business actions.')}</small></div>}
        {lines.length > 0 && <div className="assistant-widget-messages" aria-live="polite">{lines.map((line, index) => <article className={`assistant-widget-message assistant-widget-message-${line.role}`} key={`${line.role}-${index}`}><strong>{line.role === 'user' ? t('You') : 'Vyapro'}</strong><p>{line.text}</p>{line.role === 'assistant' && <button type="button" className="assistant-widget-speak" onClick={() => speak(line.text)}>{t('Speak this answer')}</button>}</article>)}</div>}
        {lastTurn?.toolCalls.length ? <details className="assistant-widget-tools"><summary>{t('What I checked')}</summary><ol>{lastTurn.toolCalls.map((call, index) => <li key={`${call.name}-${index}`}><span>{t(toolLabels[call.name] ?? 'Checked Vyapro records')}</span><strong>{t(friendlyStatus(call.status))}</strong></li>)}</ol></details> : null}
        {lastTurn?.escalationReason && <p className="assistant-widget-hold">{t(friendlyEscalation(lastTurn.escalationReason))}</p>}
        {error && <p className="assistant-widget-error" role="alert">{t(error)}</p>}
        {busy && <p className="assistant-widget-loading" role="status">Vyapro is checking backend records...</p>}
      </div>
      <form className="assistant-widget-composer" onSubmit={(event) => void submit(event)}><label className="sr-only" htmlFor="assistant-widget-input">{t('Message Vyapro')}</label><textarea id="assistant-widget-input" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={getPlaceholder()} rows={2} disabled={busy} />{voiceError && <p className="assistant-widget-voice-error" role="status">{voiceError}</p>}{listening && <p className="assistant-widget-listening" role="status">{t('Listening… speak now. Your words will appear above so you can edit them.')}</p>}{!SpeechRecognitionAPI && <small className="assistant-widget-voice-hint">{t('Microphone input is not supported in this browser. You can type instead.')}</small>}<SpeechLocaleSelector /><div className="assistant-widget-composer-actions"><button className={`assistant-widget-mic${listening ? ' assistant-widget-mic-active' : ''}`} type="button" onClick={toggleVoice} disabled={!SpeechRecognitionAPI || busy} aria-label={listening ? t('Stop speaking') : SpeechRecognitionAPI ? t('Speak to Vyapro') : t('Microphone input unavailable')} title={SpeechRecognitionAPI ? (listening ? t('Stop microphone') : t('Speak; transcript will be added to the message')) : t('Microphone input is not supported in this browser') }><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3Z"/><path d="M19 11a7 7 0 0 1-14 0M12 18v3m-4 0h8"/></svg></button><button type="submit" disabled={busy || listening || !draft.trim()}>{busy ? t('Working...') : t('Send')}</button>{lines.length > 0 && <button type="button" className="assistant-widget-new" onClick={clearConversation} disabled={busy}>{t('New chat')}</button>}</div></form>
    </section>}
    <button type="button" className={`assistant-widget-launcher assistant-widget-launcher-${actor}`} aria-label={open ? 'Close Vyapro Assistant' : 'Open Vyapro Assistant'} aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      {open ? <span aria-hidden="true">×</span> : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.25a8.75 8.75 0 0 0-7.42 13.4L3.5 21l4.58-1.07A8.75 8.75 0 1 0 12 3.25Zm-3 7.5a1.1 1.1 0 1 1 0-2.2 1.1 1.1 0 0 1 0 2.2Zm6 0a1.1 1.1 0 1 1 0-2.2 1.1 1.1 0 0 1 0 2.2ZM8.5 13h7a3.5 3.5 0 0 1-7 0Z" /></svg>}
      {!open && <span className="assistant-widget-launcher-label">Vyapro Assistant</span>}
    </button>
  </>
}
