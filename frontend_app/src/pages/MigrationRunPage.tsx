import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getMigrationStatus, type MigrationJob, type MigrationSchemaItem } from '../api/migration'

const STEP_LABELS: Record<string, string> = {
  LOAD_JSON: 'Load schema',
  MAP_TYPES: 'Map types',
  RESOLVE_IDENTITY: 'Resolve identity',
  FETCH_TENANT_ID: 'Fetch tenant ID',
  BUILD_PAYLOAD: 'Build payload',
  CALL_SCHEMA_API: 'Create schema in AEP',
  CALL_IDENTITY_DESCRIPTOR_API: 'Register identity',
  VERIFY: 'Verify',
}

const TOTAL_STEPS = 8

function StatusBadge({ status }: { status: MigrationSchemaItem['status'] }) {
  const styles: Record<string, string> = {
    QUEUED: 'bg-gray-100 text-gray-500',
    RUNNING: 'bg-blue-100 text-blue-700',
    COMPLETED: 'bg-green-100 text-green-700',
    FAILED: 'bg-red-100 text-red-700',
  }
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${styles[status] ?? 'bg-gray-100 text-gray-500'}`}>
      {status}
    </span>
  )
}

function SchemaCard({ s }: { s: MigrationSchemaItem }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
      <div className="flex items-center gap-3">
        {s.status === 'RUNNING' && (
          <svg className="animate-spin w-4 h-4 text-blue-500 shrink-0" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
        )}
        {s.status === 'COMPLETED' && (
          <svg className="w-4 h-4 text-green-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
          </svg>
        )}
        {s.status === 'FAILED' && (
          <svg className="w-4 h-4 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
          </svg>
        )}
        {s.status === 'QUEUED' && (
          <div className="w-4 h-4 rounded-full border-2 border-gray-300 shrink-0" />
        )}

        <span className="font-mono text-sm text-gray-800 flex-1 truncate">{s.schema_name}</span>
        <StatusBadge status={s.status} />
      </div>

      {s.status === 'RUNNING' && s.current_step && (
        <div className="mt-2 ml-7">
          <p className="text-xs text-gray-500 mb-1.5">
            Step {s.current_step_order}/{TOTAL_STEPS}: {STEP_LABELS[s.current_step] ?? s.current_step}
          </p>
          <div className="flex gap-1">
            {Array.from({ length: TOTAL_STEPS }, (_, i) => (
              <div
                key={i}
                className={`h-1 flex-1 rounded-full transition-all duration-300 ${
                  i < s.current_step_order ? 'bg-blue-500' : 'bg-gray-200'
                }`}
              />
            ))}
          </div>
        </div>
      )}

      {s.status === 'FAILED' && s.error_message && (
        <p className="mt-1.5 ml-7 text-xs text-red-600 break-words">{s.error_message}</p>
      )}
    </div>
  )
}

export default function MigrationRunPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const jobId = params.get('job') ?? ''

  const [job, setJob] = useState<MigrationJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!jobId) { setError('No job ID provided'); return }

    async function poll() {
      try {
        const data = await getMigrationStatus(jobId)
        setJob(data)
        if (data.running === 0 && data.queued === 0) {
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch {
        setError('Failed to fetch job status')
        if (pollRef.current) clearInterval(pollRef.current)
      }
    }

    poll()
    pollRef.current = setInterval(poll, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [jobId])

  const allDone = job ? job.running === 0 && job.queued === 0 : false
  const progress = job && job.total > 0 ? Math.round((job.completed / job.total) * 100) : 0

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        {allDone && (
          <button onClick={() => navigate('/')} className="text-sm text-gray-500 hover:text-gray-800 shrink-0">
            ← Back
          </button>
        )}
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold text-gray-900">AJO Migration</h1>
          {job && (
            <p className="text-xs text-gray-400 mt-0.5">
              <span className="font-mono">{jobId.slice(0, 8)}…</span>
              {' · '}{job.completed} completed
              {job.running > 0 && <> · <span className="text-blue-600">{job.running} running</span></>}
              {job.queued > 0 && <> · {job.queued} queued</>}
              {job.failed > 0 && <> · <span className="text-red-500">{job.failed} failed</span></>}
            </p>
          )}
        </div>
      </div>

      <div className="flex-1 max-w-3xl mx-auto w-full px-6 py-6 flex flex-col gap-4">

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700 text-sm">{error}</div>
        )}

        {/* Progress bar */}
        {job && (
          <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-gray-700">Overall progress</span>
              <span className="text-gray-500">{job.completed} / {job.total} schemas</span>
            </div>
            <div className="w-full bg-gray-100 rounded-full h-2.5">
              <div
                className={`h-2.5 rounded-full transition-all duration-500 ${
                  allDone && job.failed === 0 ? 'bg-green-500' :
                  allDone ? 'bg-yellow-500' : 'bg-blue-500'
                }`}
                style={{ width: `${progress}%` }}
              />
            </div>
            {allDone && (
              <p className="text-sm text-center font-medium mt-1">
                {job.failed === 0
                  ? <span className="text-green-600">✓ All {job.completed} schemas migrated successfully</span>
                  : <span className="text-yellow-600">{job.completed} succeeded · {job.failed} failed</span>
                }
              </p>
            )}
          </div>
        )}

        {/* Schema list */}
        {job && (
          <div className="flex flex-col gap-2">
            {job.schemas.map(s => <SchemaCard key={s.id} s={s} />)}
          </div>
        )}

        {/* Initial loading */}
        {!job && !error && (
          <div className="flex items-center justify-center py-24">
            <svg className="animate-spin w-8 h-8 text-blue-500" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          </div>
        )}
      </div>
    </div>
  )
}
