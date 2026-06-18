import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  getExtractionStatus,
  getMigrationStatus,
  startMigration,
  type ExtractionJob,
  type MigrationJob,
  type MigrationSchemaItem,
} from '../api/migration'

// Labels must match pipeline_steps.py
const STEP_LABELS: Record<string, string> = {
  LOAD_JSON: 'Loading schema',
  MAP_TYPES: 'Mapping types',
  RESOLVE_IDENTITY: 'Resolving identity',
  FETCH_TENANT_ID: 'Fetching tenant ID',
  BUILD_PAYLOAD: 'Building payload',
  CALL_SCHEMA_API: 'Creating schema in AEP',
  CALL_IDENTITY_DESCRIPTOR_API: 'Registering identity',
  VERIFY: 'Verifying',
}
const TOTAL_STEPS = 8

type Phase = 'extracting' | 'migrating' | 'done'

function timeAgo(iso: string): string {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}

function duration(startIso: string, endIso: string | null): string {
  if (!endIso) return ''
  const secs = Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000)
  return `${secs}s`
}

function StepProgressBar({ currentStepOrder, status }: { currentStepOrder: number; status: string }) {
  return (
    <div className="flex gap-1 mt-2">
      {Array.from({ length: TOTAL_STEPS }, (_, i) => {
        const stepNum = i + 1
        const done = stepNum < currentStepOrder
        const active = stepNum === currentStepOrder && status === 'RUNNING'
        return (
          <div
            key={i}
            className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${
              done ? 'bg-green-500' : active ? 'bg-blue-500' : 'bg-gray-200'
            }`}
          />
        )
      })}
    </div>
  )
}

function InProgressCard({ s }: { s: MigrationSchemaItem }) {
  const label = s.current_step ? STEP_LABELS[s.current_step] ?? s.current_step : '—'
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-5 py-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-medium text-gray-800">{s.schema_name}</span>
        <span className="text-xs px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 font-medium">
          Step {s.current_step_order} of {TOTAL_STEPS} — {label}
        </span>
      </div>
      <StepProgressBar currentStepOrder={s.current_step_order} status={s.status} />
    </div>
  )
}

function CompletedCard({ s }: { s: MigrationSchemaItem }) {
  // true = explicit business key, false = surrogate/auto key, null = no key at all
  const hasBusinessKey = s.identity_is_primary === true
  const hasSurrogateKey = s.identity_is_primary === false
  const noKeyAtAll = s.identity_is_primary === null
  const dur = duration(s.created_at!, s.completed_at)

  return (
    <div className={`bg-white border rounded-xl px-5 py-3.5 flex items-center gap-3 ${noKeyAtAll ? 'border-orange-300' : 'border-gray-200'}`}>
      <div className={`w-4 h-4 rounded border-2 shrink-0 ${hasBusinessKey ? 'border-teal-400' : hasSurrogateKey ? 'border-blue-300' : 'border-orange-300'}`} />
      <span className="font-mono text-sm text-gray-800 flex-1">{s.schema_name}</span>
      <div className="flex items-center gap-3 text-xs text-gray-400">
        <span className={hasBusinessKey ? 'text-gray-500' : hasSurrogateKey ? 'text-blue-500' : 'text-orange-500'}>
          Identity: {hasBusinessKey ? 'resolved' : hasSurrogateKey ? 'surrogate key' : 'unresolved'}
        </span>
        {dur && <span>· {dur}</span>}
        {noKeyAtAll && (
          <span className="px-2 py-0.5 rounded-full bg-orange-100 text-orange-600 font-medium">No business key</span>
        )}
      </div>
    </div>
  )
}

function FailedCard({ s }: { s: MigrationSchemaItem }) {
  const failedStep = s.current_step_order
  const label = s.current_step ? STEP_LABELS[s.current_step] ?? s.current_step : '—'

  return (
    <div className="bg-white border border-red-200 rounded-xl px-5 py-4">
      <div className="flex items-center gap-3">
        <svg className="w-4 h-4 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
        </svg>
        <span className="font-mono text-sm text-gray-800 flex-1">{s.schema_name}</span>
        <span className="text-xs px-2.5 py-1 rounded-full bg-red-100 text-red-600 font-medium">
          Failed at step {failedStep} of {TOTAL_STEPS} — {label}
        </span>
      </div>

      {/* Progress bar: green = completed, red = failed step, gray = remaining */}
      <div className="flex gap-1 mt-2">
        {Array.from({ length: TOTAL_STEPS }, (_, i) => {
          const stepNum = i + 1
          const done = stepNum < failedStep
          const failed = stepNum === failedStep
          return (
            <div
              key={i}
              className={`h-1.5 flex-1 rounded-full ${
                done ? 'bg-green-500' : failed ? 'bg-red-400' : 'bg-gray-200'
              }`}
            />
          )
        })}
      </div>

      {s.error_message && (
        <p className="mt-2 text-xs text-red-500 break-words">{s.error_message}</p>
      )}
    </div>
  )
}

function QueuedCard({ s }: { s: MigrationSchemaItem }) {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl px-5 py-3.5 flex items-center justify-between">
      <span className="font-mono text-sm text-gray-500">{s.schema_name}</span>
      <span className="text-xs px-2.5 py-1 rounded-full bg-gray-200 text-gray-500 font-medium">Queued</span>
    </div>
  )
}

function MigrationDashboard({ job, startedAt }: { job: MigrationJob; startedAt: string | null }) {
  const inProgress = job.schemas.filter(s => s.status === 'RUNNING')
  const completed = job.schemas.filter(s => s.status === 'COMPLETED')
  const failed = job.schemas.filter(s => s.status === 'FAILED')
  const queued = job.schemas.filter(s => s.status === 'QUEUED')
  const identityUnresolved = job.schemas.filter(
    s => s.status === 'COMPLETED' && s.identity_is_primary === null
  ).length
  const allDone = job.running === 0 && job.queued === 0
  const QUEUED_PREVIEW = 2

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Schema migration</h1>
        <p className="text-sm text-gray-400 mt-1">
          {startedAt && `Job started ${timeAgo(startedAt)} · `}
          {job.total} schemas
          {!allDone && ' · Runs in background — safe to close this window'}
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Total', value: job.total, color: 'text-gray-900' },
          { label: 'Completed', value: job.completed, color: 'text-green-600' },
          { label: 'In progress', value: job.running, color: 'text-blue-600' },
          { label: 'Identity unresolved', value: identityUnresolved, color: 'text-orange-600' },
        ].map(card => (
          <div key={card.label} className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3">
            <p className="text-xs text-gray-400 mb-1">{card.label}</p>
            <p className={`text-3xl font-bold ${card.color}`}>{card.value}</p>
          </div>
        ))}
      </div>

      {/* In Progress */}
      {inProgress.length > 0 && (
        <section>
          <p className="text-xs font-semibold text-gray-400 tracking-widest uppercase mb-3">In Progress</p>
          <div className="flex flex-col gap-2">
            {inProgress.map(s => <InProgressCard key={s.id} s={s} />)}
          </div>
        </section>
      )}

      {/* Completed */}
      {(completed.length > 0 || failed.length > 0) && (
        <section>
          <p className="text-xs font-semibold text-gray-400 tracking-widest uppercase mb-3">
            Completed — {completed.length + failed.length}
          </p>
          <div className="flex flex-col gap-2">
            {completed.map(s => <CompletedCard key={s.id} s={s} />)}
            {failed.map(s => <FailedCard key={s.id} s={s} />)}
          </div>
        </section>
      )}

      {/* Queued */}
      {queued.length > 0 && (
        <section>
          <p className="text-xs font-semibold text-gray-400 tracking-widest uppercase mb-3">
            Queued — {queued.length} remaining
          </p>
          <div className="flex flex-col gap-2">
            {queued.slice(0, QUEUED_PREVIEW).map(s => <QueuedCard key={s.id} s={s} />)}
            {queued.length > QUEUED_PREVIEW && (
              <p className="text-xs text-center text-gray-400 py-2">
                + {queued.length - QUEUED_PREVIEW} more waiting
              </p>
            )}
          </div>
        </section>
      )}

      {/* All done */}
      {allDone && failed.length === 0 && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center text-green-700 font-medium text-sm">
          All {job.completed} schemas migrated successfully
        </div>
      )}
    </div>
  )
}

function ExtractionLoadingView({ job }: { job: ExtractionJob | null }) {
  const progress = job && job.schema_count > 0
    ? Math.round(((job.success_count + job.failed_count) / job.schema_count) * 100)
    : 0

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Schema migration</h1>
        <p className="text-sm text-gray-400 mt-1">Extracting schemas from ACC…</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-xl p-5 flex flex-col gap-3">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium text-gray-700">Extracting schemas from ACC</span>
          {job && <span className="text-gray-400">{job.success_count + job.failed_count} / {job.schema_count}</span>}
        </div>
        <div className="w-full bg-gray-100 rounded-full h-2">
          <div className="h-2 rounded-full bg-blue-500 transition-all duration-500" style={{ width: `${progress}%` }} />
        </div>
        {job?.current_schema && (
          <p className="text-xs text-gray-400">Processing: <span className="font-mono">{job.current_schema}</span></p>
        )}
      </div>

      {job && job.steps.length > 0 && (
        <div className="flex flex-col gap-1.5 max-h-56 overflow-y-auto">
          {job.steps.map((s, i) => (
            <div key={i} className="bg-white border border-gray-100 rounded-lg px-3 py-2 flex items-center gap-2">
              {s.status === 'running' && <svg className="animate-spin w-3.5 h-3.5 text-blue-500 shrink-0" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>}
              {s.status === 'success' && <svg className="w-3.5 h-3.5 text-green-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/></svg>}
              {s.status === 'failed' && <svg className="w-3.5 h-3.5 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/></svg>}
              <span className="font-mono text-xs text-gray-600 flex-1 truncate">{s.schemaName}</span>
              {s.error && <span className="text-xs text-red-500 truncate max-w-xs">{s.error}</span>}
            </div>
          ))}
        </div>
      )}

      {!job && (
        <div className="flex justify-center py-12">
          <svg className="animate-spin w-7 h-7 text-blue-500" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
        </div>
      )}
    </div>
  )
}

export default function MigrationRunPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const extractJobId = searchParams.get('extract_job')
  const skipToMigrate = searchParams.get('phase') === 'migrate'

  const [phase, setPhase] = useState<Phase>('extracting')
  const [extractJob, setExtractJob] = useState<ExtractionJob | null>(null)
  const [migrateJob, setMigrateJob] = useState<MigrationJob | null>(null)
  const [startedAt, setStartedAt] = useState<string | null>(null)
  const [migrateJobId, setMigrateJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Phase 1: poll extraction → auto-start migration when done
  useEffect(() => {
    if (phase !== 'extracting' || !extractJobId) return

    async function pollExtraction() {
      try {
        const data = await getExtractionStatus(extractJobId!)
        setExtractJob(data)
        if (data.status === 'completed') {
          if (pollRef.current) clearInterval(pollRef.current)
          try {
            const migData = await startMigration()
            if (migData.message === 'all_done') {
              setPhase('done')
            } else {
              setMigrateJobId(migData.job_id)
              setPhase('migrating')
            }
          } catch (e: unknown) {
            setError(e instanceof Error ? e.message : 'Failed to start AJO migration')
          }
        }
      } catch {
        setError('Failed to check extraction status')
        if (pollRef.current) clearInterval(pollRef.current)
      }
    }

    pollExtraction()
    pollRef.current = setInterval(pollExtraction, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [phase, extractJobId])

  // Phase 2: poll migration status
  useEffect(() => {
    if (phase !== 'migrating' || !migrateJobId) return

    async function pollMigration() {
      try {
        const data = await getMigrationStatus(migrateJobId!)
        setMigrateJob(data)
        if (!startedAt && (data as any).started_at) setStartedAt((data as any).started_at)
        if (data.running === 0 && data.queued === 0) {
          if (pollRef.current) clearInterval(pollRef.current)
          setPhase('done')
        }
      } catch {
        setError('Failed to check migration status')
        if (pollRef.current) clearInterval(pollRef.current)
      }
    }

    pollMigration()
    pollRef.current = setInterval(pollMigration, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [phase, migrateJobId])

  // Skip-to-migrate path (schemas already extracted)
  useEffect(() => {
    if (!skipToMigrate) return
    startMigration()
      .then(data => {
        if (data.message === 'all_done') {
          setPhase('done')
        } else {
          setMigrateJobId(data.job_id)
          setPhase('migrating')
        }
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to start migration'))
  }, [skipToMigrate])

  const allDone = phase === 'done'

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top nav bar */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-3">
        {allDone && (
          <button onClick={() => navigate('/')} className="text-sm text-gray-400 hover:text-gray-700">← Back</button>
        )}
        <div className="flex gap-2 items-center ml-auto">
          {['extracting', 'migrating', 'done'].map((p, i) => {
            const phaseIdx = ['extracting', 'migrating', 'done'].indexOf(phase)
            const done = i < phaseIdx || phase === 'done'
            const active = p === phase && phase !== 'done'
            return (
              <div key={p} className="flex items-center gap-1.5">
                <div className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${
                  done ? 'bg-green-100 text-green-700' : active ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-400'
                }`}>
                  {done && <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/></svg>}
                  {active && <svg className="animate-spin w-3 h-3" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>}
                  {p === 'extracting' ? 'Extract' : p === 'migrating' ? 'Migrate' : 'Done'}
                </div>
                {i < 2 && <div className={`w-6 h-px ${i < phaseIdx ? 'bg-green-300' : 'bg-gray-200'}`} />}
              </div>
            )
          })}
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-6 py-8">
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-red-700 text-sm">{error}</div>
        )}

        {(phase === 'extracting') && <ExtractionLoadingView job={extractJob} />}

        {(phase === 'migrating' || phase === 'done') && migrateJob && (
          <MigrationDashboard job={migrateJob} startedAt={startedAt} />
        )}

        {(phase === 'migrating' || phase === 'done') && !migrateJob && !error && (
          <div className="flex justify-center py-24">
            <svg className="animate-spin w-8 h-8 text-blue-500" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          </div>
        )}

        {phase === 'done' && !migrateJob && (
          <div className="bg-green-50 border border-green-200 rounded-xl p-6 text-center">
            <p className="text-green-700 font-semibold">All schemas already up to date</p>
            <button onClick={() => navigate('/')} className="mt-3 text-sm text-green-600 underline">Back to home</button>
          </div>
        )}
      </div>
    </div>
  )
}
