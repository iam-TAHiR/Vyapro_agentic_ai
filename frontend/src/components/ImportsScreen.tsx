import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { AppLayout } from './AppLayout'
import { EmptyState } from './EmptyState'
import { ApiError } from '../services/api'
import { confirmShopData, previewShopData } from '../services/imports'
import type { ImportResult } from '../services/imports'
import { useI18n } from '../services/i18n'

function errorMessage(reason: unknown) {
  return reason instanceof ApiError ? reason.message : 'The import request could not reach the Flask backend.'
}

export function ImportsScreen() {
  const { t } = useI18n()
  const [file, setFile] = useState<File | null>(null)
  const [allowUpdates, setAllowUpdates] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [reviewed, setReviewed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const confirmationKey = useRef<string | null>(null)

  async function preview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    setBusy(true); setError(''); setResult(null); setReviewed(false); confirmationKey.current = null
    try {
      setResult(await previewShopData(file, allowUpdates))
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }

  async function confirm() {
    if (!result || result.status !== 'previewed' || !reviewed) return
    setBusy(true); setError(''); confirmationKey.current ??= crypto.randomUUID()
    try {
      setResult(await confirmShopData(result.importId, confirmationKey.current))
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }

  return <AppLayout>
    <div className="page-heading"><div><p className="eyebrow">{t('Shopkeeper tools')}</p><h1>{t('Import shop data')}</h1><p>{t('Upload records, review every row and proposed change, then explicitly confirm one transactional import.')}</p></div></div>
    <section className="import-policy" aria-label={t('Import safety rules')}><strong>{t('Preview first. No silent overwrites.')}</strong><p>{t('CSV, XLSX, and table-based PDF catalogues are supported. Invalid rows block the batch. Existing data changes only when you enable updates, review the before/after values, and confirm.')}</p><p>{t('Previous orders are stored as imported history. They do not appear as Vyapro-processed orders and do not change stock or credit.')}</p></section>
    <form className="assistant-form import-form" onSubmit={preview}>
      <label htmlFor="shop-data-file">{t('Choose CSV, Excel workbook, or PDF')}</label>
      <input id="shop-data-file" type="file" accept=".csv,.xlsx,.pdf,text/csv,application/pdf" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setResult(null); setReviewed(false); confirmationKey.current = null }} required />
      {file && <small>{t('Selected:')} {file.name} ({Math.ceil(file.size / 1024)} KB)</small>}
      <label className="check-label"><input type="checkbox" checked={allowUpdates} onChange={(event) => { setAllowUpdates(event.target.checked); setResult(null); setReviewed(false); confirmationKey.current = null }} /> {t('Allow updates to existing identifiers. The preview will show current and proposed values.')}</label>
      <div className="assistant-form-footer"><small>{t('Maximum upload size: 15 MB. Currency values use major units, for example 125.50.')}</small><button type="submit" disabled={busy || !file}>{busy ? t('Preparing preview…') : t('Preview import')}</button></div>
    </form>
    {error && <div className="inline-error" role="alert"><strong>{t('Import not completed.')}</strong><p>{t(error)}</p></div>}
    {result && <section className="import-preview" aria-live="polite">
      <div className="section-title-row"><div><p className="eyebrow">{t('Import preview')} · {t(result.status.replaceAll('_', ' '))}</p><h2>{result.source.filename}</h2></div><span className="status-badge">{String(result.summary.rows ?? 0)} {t('rows')}</span></div>
      <dl className="proposal-summary"><div><dt>{t('Creates')}</dt><dd>{String(result.summary.creates ?? 0)}</dd></div><div><dt>{t('Updates')}</dt><dd>{String(result.summary.updates ?? 0)}</dd></div><div><dt>{t('Skipped existing aliases')}</dt><dd>{String(result.summary.skipped ?? 0)}</dd></div><div><dt>{t('Row errors')}</dt><dd>{String(result.preview.errors.length)}</dd></div></dl>
      {result.preview.errors.length > 0 && <div className="warning-list" role="alert"><h3>{t('Fix these rows before importing')}</h3><ul>{result.preview.errors.map((rowError, index) => <li key={`${rowError.sheet}-${rowError.row}-${rowError.code}-${index}`}><strong>{rowError.sheet}{rowError.row ? ` ${t('row')} ${rowError.row}` : ''}{rowError.field ? ` · ${t(rowError.field)}` : ''}:</strong> {t(rowError.message)}</li>)}</ul></div>}
      {result.preview.rows.length > 0 ? <div className="import-rows">{result.preview.rows.map((row, index) => <article className="import-row" key={`${row.sheet}-${row.row}-${index}`}><div className="section-title-row"><strong>{row.sheet}, row {row.row}</strong><span>{row.action}</span></div><div className="import-diff"><div><small>{row.before ? 'Existing values' : 'Existing values'}</small><pre>{row.before ? JSON.stringify(row.before, null, 2) : 'No matching identifier; record will be inserted.'}</pre></div><div><small>Proposed values</small><pre>{JSON.stringify(row.values, null, 2)}</pre></div></div></article>)}</div> : <EmptyState title="No valid rows to preview" message="Correct the reported row errors and upload the file again." />}
      {result.status === 'imported' ? <p className="success-panel" role="status">{t('Import completed. Source and summary are recorded under import')} {result.importId}.</p> : <div className="approval-panel">
        {result.status === 'previewed' && <label className="check-label"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} disabled={busy} /> {t('I reviewed the rows and before/after changes above.')}</label>}
        <button type="button" onClick={confirm} disabled={busy || !reviewed || result.status !== 'previewed' || result.preview.errors.length > 0}>{busy ? t('Importing…') : t('Confirm and import')}</button>
        {result.status !== 'previewed' && <p className="muted-note">{t('This preview cannot be confirmed until its row errors are corrected. Upload a corrected file or adjust the update option and preview again.')}</p>}
      </div>}
    </section>}
  </AppLayout>
}
