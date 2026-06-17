// Types and API calls for the ACC → JSON conversion flow

export interface SchemaEntry {
  namespace: string
  name: string
  label: string
}

export interface ConversionStep {
  schemaName: string
  status: 'running' | 'success' | 'failed'
  error: string | null
}

export interface ConversionJob {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  schema_count: number
  skipped_count: number
  current_schema: string | null
  success_count: number
  failed_count: number
  steps: ConversionStep[]
}

export async function startConversionAll(): Promise<{ job_id: string | null; message: string; total: number; skipped: number }> {
  const res = await fetch('/api/convert/start-all', {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to start') }
  return res.json()
}

export async function startConversion(
  schemas: Array<{ namespace: string; name: string; label?: string }>
): Promise<{ job_id: string }> {
  const res = await fetch('/api/convert/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ schemas }),
  })
  if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to start') }
  return res.json()
}

export async function getConversionStatus(jobId: string): Promise<ConversionJob> {
  const res = await fetch(`/api/convert/status/${jobId}`, { credentials: 'include' })
  if (!res.ok) throw new Error('Job not found')
  return res.json()
}
