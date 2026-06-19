export interface MigrationSchemaItem {
  id: string
  schema_name: string
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  current_step: string | null
  current_step_order: number
  identity_is_primary: boolean | null
  error_message: string | null
  created_at: string
  completed_at: string | null
}

export interface MigrationJob {
  job_id: string
  total: number
  completed: number
  running: number
  queued: number
  failed: number
  schemas: MigrationSchemaItem[]
}

export interface ExtractionStep {
  schemaName: string
  status: 'running' | 'success' | 'failed'
  error: string | null
}

export interface ExtractionJob {
  id: string
  status: 'pending' | 'running' | 'completed'
  schema_count: number
  skipped_count: number
  current_schema: string | null
  success_count: number
  failed_count: number
  steps: ExtractionStep[]
}

async function _safeError(res: Response, fallback: string): Promise<never> {
  try {
    const e = await res.json()
    throw new Error(e.detail || fallback)
  } catch {
    if (res.status === 502 || res.status === 503 || res.status === 504 || res.status === 500) {
      throw new Error('Backend server is not running — please start it first')
    }
    throw new Error(fallback)
  }
}

export async function startConversion(
  schemas: { namespace: string; name: string; label?: string }[]
): Promise<{ job_id: string | null; message: string; skipped?: string[] }> {
  let res: Response
  try {
    res = await fetch('/api/convert/start', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schemas }),
    })
  } catch {
    throw new Error('Backend server is not running — please start it first')
  }
  if (!res.ok) await _safeError(res, 'Failed to start conversion')
  return res.json()
}

export async function getExtractedSchemas(): Promise<{ extracted: string[] }> {
  try {
    const res = await fetch('/api/convert/extracted', { credentials: 'include' })
    if (!res.ok) return { extracted: [] }
    return res.json()
  } catch {
    return { extracted: [] }
  }
}

export async function startExtraction(): Promise<{ job_id: string | null; message: string; total: number; skipped: number }> {
  let res: Response
  try {
    res = await fetch('/api/convert/start-all', { method: 'POST', credentials: 'include' })
  } catch {
    throw new Error('Backend server is not running — please start it first')
  }
  if (!res.ok) await _safeError(res, 'Failed to start extraction')
  return res.json()
}

export async function getExtractionStatus(jobId: string): Promise<ExtractionJob> {
  const res = await fetch(`/api/convert/status/${jobId}`, { credentials: 'include' })
  if (!res.ok) throw new Error('Extraction job not found')
  return res.json()
}

export async function startMigration(extractJobId?: string): Promise<{ job_id: string; message: string; total: number; queued: number; skipped: number }> {
  let res: Response
  try {
    res = await fetch('/api/migrate/start', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ extract_job_id: extractJobId ?? null }),
    })
  } catch {
    throw new Error('Backend server is not running — please start it first')
  }
  if (!res.ok) await _safeError(res, 'Failed to start migration')
  return res.json()
}

export async function getMigrationStatus(jobId: string): Promise<MigrationJob> {
  const res = await fetch(`/api/migrate/status/${jobId}`, { credentials: 'include' })
  if (!res.ok) throw new Error('Job not found')
  return res.json()
}

export async function listMigrationJobs(): Promise<{ jobs: { job_id: string; created_at: string }[] }> {
  const res = await fetch('/api/migrate/jobs', { credentials: 'include' })
  if (!res.ok) return { jobs: [] }
  return res.json()
}
