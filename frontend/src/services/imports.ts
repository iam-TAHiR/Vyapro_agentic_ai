import { createApiClient } from './api'

const api = createApiClient({ baseUrl: import.meta.env.VITE_API_BASE_URL || '/api/v1' })

export type ImportRow = {
  sheet: string
  row: number
  action: 'insert' | 'update' | 'skip' | 'blocked'
  before: Record<string, unknown> | null
  values: Record<string, unknown>
}
export type ImportError = {
  sheet: string
  row: number | null
  field: string | null
  code: string
  message: string
}
export type ImportResult = {
  importId: string
  source: { filename: string; format: string; sha256: string }
  status: string
  allowUpdates: boolean
  summary: Record<string, unknown>
  preview: { rows: ImportRow[]; errors: ImportError[] }
}

export async function previewShopData(file: File, updateExisting: boolean) {
  const body = new FormData()
  body.append('file', file)
  body.append('updateExisting', String(updateExisting))
  return api.requestJson<ImportResult>('/imports/preview', { method: 'POST', body })
}

export async function confirmShopData(importId: string, idempotencyKey: string) {
  return api.requestJson<ImportResult>(`/imports/${encodeURIComponent(importId)}/confirm`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ confirm: true }),
  })
}
