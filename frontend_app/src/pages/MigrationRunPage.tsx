import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  getExtractionStatus,
  getIncompleteSchemas,
  getMigrationStatus,
  listMigrationJobs,
  startMigration,
  type ExtractionJob,
  type IncompleteSchema,
  type MigrationJob,
  type MigrationSchemaItem,
} from '../api/migration'

// Labels must match pipeline_steps.py — steps 1-5 enrich, 6-15 push to AJO
const STEP_LABELS: Record<string, string> = {
  LOAD_JSON: 'Loading schema',
  MAP_TYPES: 'Mapping types',
  RESOLVE_IDENTITY: 'Resolving identity',
  FETCH_TENANT_ID: 'Fetching tenant ID',
  BUILD_PAYLOAD: 'Building enriched JSON',
  NORMALIZE_INPUT: 'Reading enriched JSON',
  DUPLICATE_CHECK: 'Checking AEP registry',
  CREATE_SCHEMA: 'Creating schema in AEP',
  PRIMARY_KEY_DESCRIPTOR: 'Primary-key descriptor',
  VERSION_DESCRIPTOR: 'Version descriptor',
  TIMESTAMP_DESCRIPTOR: 'Timestamp descriptor',
  IDENTITY_DESCRIPTOR: 'Identity descriptor',
  RELATIONSHIP_DESCRIPTORS: 'Wiring relationships',
  CREATE_DATASET: 'Creating dataset in AEP',
  VERIFY: 'Verifying in AEP',
  VALIDATE_OC: 'Checking OC eligibility',
  ENABLE_OC: 'Enabling for Orchestrated Campaigns',
}
const TOTAL_STEPS = 17

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
  const dur = duration(s.created_at!, s.completed_at)
  const alreadyExisted = s.current_step === 'ALREADY_EXISTS'
  const wasUpdated = s.current_step === 'UPDATED'
  const warnings = s.warnings ?? []
  const fieldsAdded = s.fields_added ?? 0

  const borderColor = warnings.length
    ? 'border-amber-200'
    : alreadyExisted
    ? 'border-gray-200'
    : wasUpdated
    ? 'border-blue-200'
    : 'border-green-200'

  const iconColor = alreadyExisted ? 'text-gray-400' : wasUpdated ? 'text-blue-500' : 'text-green-500'

  const badgeClass = alreadyExisted
    ? 'bg-gray-100 text-gray-600'
    : wasUpdated
    ? 'bg-blue-100 text-blue-700'
    : 'bg-green-100 text-green-700'

  const badgeLabel = alreadyExisted
    ? 'Already in AJO — nothing to push'
    : wasUpdated
    ? fieldsAdded > 0
      ? `Updated in AJO — ${fieldsAdded} attribute${fieldsAdded !== 1 ? 's' : ''} changed`
      : 'Updated in AJO'
    : 'Pushed to AJO'

  return (
    <div className={`bg-white border rounded-xl px-5 py-3.5 ${borderColor}`}>
      <div className="flex items-center gap-3">
        <svg className={`w-4 h-4 shrink-0 ${iconColor}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
        </svg>
        <span className="font-mono text-sm text-gray-800 flex-1">{s.schema_name}</span>
        <div className="flex items-center gap-2 text-xs">
          {warnings.length > 0 && (
            <span className="px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700">
              {warnings.length} warning{warnings.length > 1 ? 's' : ''}
            </span>
          )}
          <span className={`px-2 py-0.5 rounded-full font-medium ${badgeClass}`}>
            {badgeLabel}
          </span>
          {dur && <span className="text-gray-400">· {dur}</span>}
        </div>
      </div>
      {warnings.length > 0 && (
        <ul className="mt-2 pl-7 flex flex-col gap-1">
          {warnings.map((w, i) => (
            <li key={i} className="text-xs text-amber-600 flex gap-1.5">
              <span className="shrink-0">⚠</span><span className="break-words">{w}</span>
            </li>
          ))}
        </ul>
      )}
      {s.oc_status && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          {s.oc_status === 'ENABLED' && (
            <div className="flex items-center gap-2 text-xs text-green-700">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" />
              <span className="font-medium">Enabled for Orchestrated Campaigns</span>
              {s.oc_job_id && (
                <span className="text-gray-400 font-mono ml-auto">job: {s.oc_job_id.slice(0, 8)}</span>
              )}
            </div>
          )}
          {s.oc_status === 'PENDING' && (
            <div className="flex items-center gap-2 text-xs text-blue-600">
              <svg className="w-3 h-3 animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
              <span>Enabling for Orchestrated Campaigns — may take up to 30s</span>
            </div>
          )}
          {s.oc_status === 'NOT_ELIGIBLE' && (
            <div className="flex flex-col gap-0.5 text-xs text-amber-700">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                <span className="font-medium">Not eligible for Orchestrated Campaigns</span>
              </div>
              {s.oc_not_supported_reason && (
                <p className="pl-3.5 text-amber-600">{s.oc_not_supported_reason}</p>
              )}
            </div>
          )}
          {s.oc_status === 'FAILED' && (
            <div className="flex items-center gap-2 text-xs text-red-600">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />
              <span>OC enablement failed — check logs for details</span>
            </div>
          )}
        </div>
      )}
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

function incompleteToItem(s: IncompleteSchema): MigrationSchemaItem {
  return {
    id: `inc-${s.schema_name}`,
    schema_name: s.schema_name,
    status: s.status,
    current_step: s.current_step,
    current_step_order: s.current_step_order,
    identity_is_primary: null,
    error_message: s.error_message,
    created_at: '',
    completed_at: null,
  }
}

function MigrationDashboard({
  job,
  startedAt,
  stuckSchemas,
}: {
  job: MigrationJob
  startedAt: string | null
  stuckSchemas: IncompleteSchema[]
}) {
  // Merge: current job schemas take priority; stuck schemas from other jobs fill in
  const currentNames = new Set(job.schemas.map(s => s.schema_name))
  const extraItems = stuckSchemas
    .filter(s => !currentNames.has(s.schema_name))
    .map(incompleteToItem)
  const allSchemas = [...job.schemas, ...extraItems]

  const inProgress = allSchemas.filter(s => s.status === 'RUNNING')
  const completed = allSchemas.filter(s => s.status === 'COMPLETED')
  const failed = allSchemas.filter(s => s.status === 'FAILED')
  const queued = allSchemas.filter(s => s.status === 'QUEUED')
  const identityUnresolved = allSchemas.filter(
    s => s.status === 'COMPLETED' && s.identity_is_primary === null
  ).length
  const allDone = inProgress.length === 0 && queued.length === 0
  const total = allSchemas.length
  const QUEUED_PREVIEW = 2

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Pushing schemas to AJO</h1>
        <p className="text-sm text-gray-400 mt-1">
          {startedAt && `Job started ${timeAgo(startedAt)} · `}
          {total} schemas
          {!allDone && ' · Runs in background — safe to close this window'}
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Total', value: total, color: 'text-gray-900' },
          { label: 'Pushed', value: completed.length, color: 'text-green-600' },
          { label: 'In progress', value: inProgress.length, color: 'text-blue-600' },
          { label: 'Failed', value: failed.length, color: 'text-red-600' },
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
          All {completed.length} schemas pushed to AJO
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
        <h1 className="text-2xl font-bold text-gray-900">Schema extraction</h1>
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
  const resumeJobId = searchParams.get('migrate_job')   // direct resume — skip extraction
  const skipToMigrate = searchParams.get('phase') === 'migrate'

  const initialPhase: Phase = (resumeJobId || skipToMigrate) ? 'migrating' : 'extracting'
  const [phase, setPhase] = useState<Phase>(initialPhase)
  const [extractJob, setExtractJob] = useState<ExtractionJob | null>(null)
  const [migrateJob, setMigrateJob] = useState<MigrationJob | null>(null)
  const [startedAt, setStartedAt] = useState<string | null>(null)
  const [migrateJobId, setMigrateJobId] = useState<string | null>(resumeJobId)
  const [stuckSchemas, setStuckSchemas] = useState<IncompleteSchema[]>([])
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Load the most recent completed job's stats (used when all_done)
  async function loadLastJobStats() {
    try {
      const { jobs } = await listMigrationJobs()
      if (jobs.length) {
        const data = await getMigrationStatus(jobs[0].job_id)
        setMigrateJob(data)
        if ((data as any).started_at) setStartedAt((data as any).started_at)
      }
    } catch { /* ignore */ }
    setPhase('done')
  }

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
            const migData = await startMigration(extractJobId!)
            if (migData.message === 'all_done') {
              await loadLastJobStats()
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
        const [data, incData] = await Promise.all([
          getMigrationStatus(migrateJobId!),
          getIncompleteSchemas(),
        ])
        setMigrateJob(data)
        if (!startedAt && (data as any).started_at) setStartedAt((data as any).started_at)
        // Stuck = incomplete schemas NOT in current job (they're from previous jobs)
        const currentNames = new Set(data.schemas.map((s: MigrationSchemaItem) => s.schema_name))
        setStuckSchemas(incData.schemas.filter(s => !currentNames.has(s.schema_name)))
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

  // Skip-to-migrate path (schemas already extracted, no known job ID yet)
  useEffect(() => {
    if (!skipToMigrate || resumeJobId) return
    startMigration()
      .then(data => {
        if (data.message === 'all_done') {
          loadLastJobStats()
        } else {
          setMigrateJobId(data.job_id)
          setPhase('migrating')
        }
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to start migration'))
  }, [skipToMigrate, resumeJobId])

  const allDone = phase === 'done'

  const phaseLabels = ['extracting', 'migrating', 'done']

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top nav bar */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-3">
        {allDone && (
          <button onClick={() => navigate('/')} className="text-sm text-gray-400 hover:text-gray-700">← Back to home</button>
        )}
        <div className="flex gap-2 items-center ml-auto">
          {phaseLabels.map((p, i) => {
            const phaseIdx = phaseLabels.indexOf(phase)
            const hasFailed = phase === 'done' && migrateJob && migrateJob.failed > 0
            const incomplete = p === 'done' && hasFailed
            const done = !incomplete && (i < phaseIdx || phase === 'done')
            const active = p === phase && phase !== 'done'
            return (
              <div key={p} className="flex items-center gap-1.5">
                <div className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${
                  incomplete ? 'bg-red-100 text-red-700' : done ? 'bg-green-100 text-green-700' : active ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-400'
                }`}>
                  {incomplete && <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/></svg>}
                  {done && <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/></svg>}
                  {active && <svg className="animate-spin w-3 h-3" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>}
                  {p === 'extracting' ? 'Extract' : p === 'migrating' ? 'Push to AJO' : incomplete ? 'Incomplete' : 'Done'}
                </div>
                {i < 2 && <div className={`w-6 h-px ${i < phaseLabels.indexOf(phase) ? 'bg-green-300' : 'bg-gray-200'}`} />}
              </div>
            )
          })}
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-6 py-8">
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-red-700 text-sm">{error}</div>
        )}

        {/* Final stats banner — shown when all done */}
        {allDone && migrateJob && (
          <div className={`mb-6 rounded-xl px-5 py-4 flex items-center justify-between ${
            migrateJob.failed === 0
              ? 'bg-green-50 border border-green-200'
              : 'bg-yellow-50 border border-yellow-200'
          }`}>
            <div>
              <p className={`font-semibold text-base ${migrateJob.failed === 0 ? 'text-green-700' : 'text-yellow-700'}`}>
                {migrateJob.failed === 0
                  ? `Migration complete — all ${migrateJob.completed} schemas pushed to AJO`
                  : `Migration finished — ${migrateJob.completed} pushed, ${migrateJob.failed} failed`}
              </p>
              <p className="text-xs text-gray-400 mt-0.5">Final results shown below</p>
            </div>
            <button
              onClick={() => navigate('/')}
              className="shrink-0 ml-4 px-4 py-2 rounded-lg bg-white border border-gray-200 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
            >
              Back to home
            </button>
          </div>
        )}

        {phase === 'extracting' && <ExtractionLoadingView job={extractJob} />}

        {(phase === 'migrating' || allDone) && migrateJob && (
          <MigrationDashboard job={migrateJob} startedAt={startedAt} stuckSchemas={stuckSchemas} />
        )}

        {(phase === 'migrating' || phase === 'done') && !migrateJob && !error && (
          <div className="flex justify-center py-24">
            <svg className="animate-spin w-8 h-8 text-blue-500" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          </div>
        )}

        {allDone && !migrateJob && (
          <div className="bg-green-50 border border-green-200 rounded-xl p-6 text-center">
            <p className="text-green-700 font-semibold">All schemas already up to date</p>
            <button onClick={() => navigate('/')} className="mt-3 text-sm text-green-600 underline">Back to home</button>
          </div>
        )}
      </div>
    </div>
  )
}
