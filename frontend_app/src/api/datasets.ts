// frontend_app/src/api/datasets.ts

const BASE = ''

export interface DatasetSchema {
  schema_name: string
  aep_dataset_id: string
}

export type IngestStepStatus = 'COMPLETED' | 'FAILED' | 'SKIPPED'

export interface IngestStep {
  name: 'CREATE_BATCH' | 'UPLOAD_FILE' | 'COMPLETE_BATCH'
  status: IngestStepStatus
  detail: string
}

export interface IngestResult {
  batch_id: string
  steps: IngestStep[]
  status: 'SUCCESS' | 'FAILED'
}

export async function getDatasetSchemas(): Promise<DatasetSchema[]> {
  const resp = await fetch(`${BASE}/api/datasets/schemas`, {
    credentials: 'include',
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(body.detail ?? `HTTP ${resp.status}`)
  }
  return resp.json() as Promise<DatasetSchema[]>
}

export async function ingestDataset(schemaName: string, file: File): Promise<IngestResult> {
  const form = new FormData()
  form.append('schema_name', schemaName)
  form.append('file', file)

  const resp = await fetch(`${BASE}/api/datasets/ingest`, {
    method: 'POST',
    credentials: 'include',
    body: form,
  })

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(body.detail ?? `HTTP ${resp.status}`)
  }

  return resp.json() as Promise<IngestResult>
}
