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

export async function startExtraction(): Promise<{ job_id: string | null; message: string; total: number; skipped: number }> {
  const res = await fetch('/api/convert/start-all', { method: 'POST', credentials: 'include' })
  if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to start extraction') }
  return res.json()
}

export async function getExtractionStatus(jobId: string): Promise<ExtractionJob> {
  const res = await fetch(`/api/convert/status/${jobId}`, { credentials: 'include' })
  if (!res.ok) throw new Error('Extraction job not found')
  return res.json()
}

export async function startMigration(): Promise<{ job_id: string; message: string; total: number; queued: number; skipped: number }> {
  const res = await fetch('/api/migrate/start', { method: 'POST', credentials: 'include' })
  if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to start migration') }
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
