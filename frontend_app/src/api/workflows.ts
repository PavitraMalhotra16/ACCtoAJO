export interface WorkflowMeta {
  internalName: string
  label: string
  folder: string
  status: string
  activityCount: number
  updatedAt: string | null
}

export interface WorkflowTransition {
  transitionType: string   // initial | result | done | remainder
  name: string
  target: string
  enabled: string
  attributes: Record<string, string>
}

export interface ActivityConfig {
  tag: string
  attributes: Record<string, string>
  text: string
  children: ActivityConfig[]
}

export interface WorkflowActivity {
  type: string             // start, query, fileImport, delivery, writer, end, etc.
  name: string
  label: string
  x: string
  y: string
  attributes: Record<string, string>
  transitions: WorkflowTransition[]
  config: ActivityConfig
  rawXml: string
}

export interface WorkflowEdge {
  fromActivity: string
  fromType: string
  transitionType: string
  transitionName: string
  toActivity: string
  enabled: string
}

export interface WorkflowDetail extends WorkflowMeta {
  description: string
  attributes: Record<string, string>
  activities: WorkflowActivity[]
  edges: WorkflowEdge[]
  variables_xml: string
}

export interface ExtractionStatus {
  batch_id: string
  status: 'queued' | 'running' | 'done' | 'error'
  done: number
  total: number
  errors: { internalName: string; error: string }[]
  stored: number
  started_at: string
  finished_at: string | null
}

async function _err(res: Response, fallback: string): Promise<string> {
  try { return (await res.json())?.detail || fallback } catch { return `${fallback} (HTTP ${res.status})` }
}

export async function getWorkflowCount(): Promise<{ total: number; stored: number; to_fetch: number }> {
  const res = await fetch('/api/workflows/count', { credentials: 'include' })
  if (!res.ok) throw new Error(await _err(res, 'Failed to get workflow count'))
  return res.json()
}

export async function getWorkflowStoredCount(): Promise<{ stored: number }> {
  const res = await fetch('/api/workflows/stored-count', { credentials: 'include' })
  if (!res.ok) throw new Error(await _err(res, 'Failed to get stored count'))
  return res.json()
}

export async function startWorkflowExtraction(): Promise<{ batch_id: string; status: string }> {
  const res = await fetch('/api/workflows/extract', { method: 'POST', credentials: 'include' })
  if (!res.ok) throw new Error(await _err(res, 'Failed to start extraction'))
  return res.json()
}

export async function getExtractionStatus(batchId: string): Promise<ExtractionStatus> {
  const res = await fetch(`/api/workflows/extract/status?batch_id=${encodeURIComponent(batchId)}`, { credentials: 'include' })
  if (!res.ok) throw new Error(await _err(res, 'Failed to get extraction status'))
  return res.json()
}

export async function listWorkflows(): Promise<{ workflows: WorkflowMeta[]; total: number }> {
  const res = await fetch('/api/workflows', { credentials: 'include' })
  if (!res.ok) throw new Error(await _err(res, 'Failed to list workflows'))
  return res.json()
}

export async function getWorkflowDetail(internalName: string): Promise<WorkflowDetail> {
  const res = await fetch(`/api/workflows/${encodeURIComponent(internalName)}`, { credentials: 'include' })
  if (!res.ok) throw new Error(await _err(res, 'Failed to load workflow'))
  return res.json()
}

// ── Migration ──────────────────────────────────────────────────────────────

export interface MigrationResult {
  internalName: string
  label: string
  status: 'SUCCESS' | 'FAILED' | 'SKIPPED'
  ajo_campaign_id?: string
  ajo_version_id?: string
  ajo_workflow_id?: string
  reason?: string   // for SKIPPED
  error?: string    // for FAILED
}

export interface MigrationStatus {
  batch_id: string
  status: 'queued' | 'running' | 'done' | 'error'
  done: number
  total: number
  results: MigrationResult[]
  error: string | null
  started_at: string
  finished_at: string | null
}

export async function startWorkflowMigration(
  internalNames?: string[],
  bearerToken?: string,
): Promise<{ batch_id: string; status: string }> {
  const res = await fetch('/api/workflows/migrate', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      internal_names: internalNames ?? null,
      bearer_token: bearerToken ?? null,
    }),
  })
  if (!res.ok) throw new Error(await _err(res, 'Failed to start migration'))
  return res.json()
}

export async function getMigrationStatus(batchId: string): Promise<MigrationStatus> {
  const res = await fetch(`/api/workflows/migrate/status?batch_id=${encodeURIComponent(batchId)}`, {
    credentials: 'include',
  })
  if (!res.ok) throw new Error(await _err(res, 'Failed to get migration status'))
  return res.json()
}
