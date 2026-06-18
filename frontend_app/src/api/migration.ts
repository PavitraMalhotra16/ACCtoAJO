export interface MigrationSchemaItem {
  id: string
  schema_name: string
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  current_step: string | null
  current_step_order: number
  identity_is_primary: boolean | null
  error_message: string | null
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
