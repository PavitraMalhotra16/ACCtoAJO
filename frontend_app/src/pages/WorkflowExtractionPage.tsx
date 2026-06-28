import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getWorkflowCount,
  getWorkflowStoredCount,
  startWorkflowExtraction,
  getExtractionStatus,
  listWorkflows,
  getWorkflowDetail,
  type WorkflowMeta,
  type WorkflowDetail,
  type ExtractionStatus,
} from '../api/workflows'

// ─── Activity type → colour pill ────────────────────────────────────────────
const ACTIVITY_COLORS: Record<string, string> = {
  start:        'bg-green-100 text-green-700',
  end:          'bg-red-100 text-red-600',
  delivery:     'bg-blue-100 text-blue-700',
  deliveryMgt:  'bg-blue-100 text-blue-700',
  query:        'bg-purple-100 text-purple-700',
  enrichment:   'bg-indigo-100 text-indigo-700',
  split:        'bg-amber-100 text-amber-700',
  test:         'bg-amber-100 text-amber-700',
  scheduler:    'bg-teal-100 text-teal-700',
  wait:         'bg-gray-100 text-gray-600',
  externalSignal: 'bg-orange-100 text-orange-700',
  fileImport:   'bg-cyan-100 text-cyan-700',
  extractFile:  'bg-cyan-100 text-cyan-700',
  transferFile: 'bg-cyan-100 text-cyan-700',
  writer:       'bg-pink-100 text-pink-700',
  dedup:        'bg-lime-100 text-lime-700',
  reconciliation: 'bg-violet-100 text-violet-700',
  js:           'bg-yellow-100 text-yellow-700',
  jstest:       'bg-yellow-100 text-yellow-700',
}
function activityColor(type: string) {
  return ACTIVITY_COLORS[type] || 'bg-gray-100 text-gray-500'
}

// ─── Workflow status badge ───────────────────────────────────────────────────
function statusBadge(status: string) {
  const map: Record<string, { label: string; cls: string }> = {
    '0': { label: 'Editing',  cls: 'bg-gray-100 text-gray-500' },
    '1': { label: 'Started',  cls: 'bg-green-100 text-green-700' },
    '2': { label: 'Paused',   cls: 'bg-amber-100 text-amber-700' },
    '3': { label: 'Stopped',  cls: 'bg-red-100 text-red-600' },
    '4': { label: 'Error',    cls: 'bg-red-100 text-red-600' },
    '5': { label: 'Finished', cls: 'bg-blue-100 text-blue-600' },
  }
  const s = map[status] || { label: status || 'Unknown', cls: 'bg-gray-100 text-gray-400' }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${s.cls}`}>
      {s.label}
    </span>
  )
}

// ─── Activity graph panel ────────────────────────────────────────────────────
function ActivityPanel({ detail }: { detail: WorkflowDetail }) {
  if (detail.activities.length === 0) {
    return <p className="text-xs text-gray-400 py-2">No activities found in this workflow.</p>
  }

  return (
    <div className="flex flex-col gap-1.5 pt-2">
      {detail.activities.map((act, i) => (
        <div key={i} className="flex items-start gap-2">
          {/* connector line */}
          <div className="flex flex-col items-center shrink-0 w-5">
            {i > 0 && <div className="w-px h-2 bg-gray-200" />}
            <div className={`w-2 h-2 rounded-full mt-0.5 ${activityColor(act.type).split(' ')[0]}`} />
          </div>

          <div className="flex-1 min-w-0 pb-1.5 border-b border-gray-50 last:border-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs px-2 py-0.5 rounded font-medium font-mono ${activityColor(act.type)}`}>
                {act.type}
              </span>
              <span className="text-xs text-gray-700 font-medium truncate">
                {act.label || act.name}
              </span>
              {act.name && act.name !== act.label && (
                <span className="text-xs text-gray-400 font-mono truncate">[{act.name}]</span>
              )}
            </div>

            {/* transitions */}
            {act.transitions.length > 0 && (
              <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                <span className="text-xs text-gray-300">→</span>
                {act.transitions.map((tr, j) => (
                  <span key={j} className="text-xs text-gray-400 font-mono">
                    {tr.target}{tr.label ? ` (${tr.label})` : ''}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Single workflow row ─────────────────────────────────────────────────────
function WorkflowRow({
  workflow,
  detail,
  loadingDetail,
  expanded,
  onToggle,
}: {
  workflow: WorkflowMeta
  detail: WorkflowDetail | null
  loadingDetail: boolean
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div className="border border-gray-200 rounded-xl bg-white overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
      >
        {/* chevron */}
        <svg
          className={`w-4 h-4 shrink-0 text-gray-400 transition-transform ${expanded ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>

        {/* workflow icon */}
        <div className="w-7 h-7 shrink-0 rounded-lg bg-violet-50 flex items-center justify-center">
          <svg className="w-4 h-4 text-violet-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M7 16V4m0 0L3 8m4-4l4 4M17 8v12m0 0l4-4m-4 4l-4-4" />
          </svg>
        </div>

        {/* label + meta */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-gray-800 truncate">
              {workflow.label}
            </span>
            {statusBadge(workflow.status)}
          </div>
          <div className="flex items-center gap-3 mt-0.5 flex-wrap">
            <span className="text-xs font-mono text-gray-400">{workflow.internalName}</span>
            {workflow.folder && (
              <span className="text-xs text-gray-400">{workflow.folder}</span>
            )}
          </div>
        </div>

        {/* activity count */}
        <div className="shrink-0 text-right">
          {loadingDetail ? (
            <svg className="animate-spin w-4 h-4 text-violet-400" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          ) : (
            <span className="text-xs text-gray-400">
              {workflow.activityCount} {workflow.activityCount === 1 ? 'activity' : 'activities'}
            </span>
          )}
        </div>
      </button>

      {/* expanded detail */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 pb-4">
          {loadingDetail && (
            <p className="text-xs text-gray-400 py-3 animate-pulse">Loading activity graph…</p>
          )}
          {!loadingDetail && !detail && (
            <p className="text-xs text-red-400 py-3">Failed to load workflow detail.</p>
          )}
          {!loadingDetail && detail && <ActivityPanel detail={detail} />}
        </div>
      )}
    </div>
  )
}

// ─── Main page ───────────────────────────────────────────────────────────────
export default function WorkflowExtractionPage() {
  const navigate = useNavigate()

  // extraction phase state
  const [phase, setPhase] = useState<'extracting' | 'review'>('extracting')
  const [batchId, setBatchId]   = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<ExtractionStatus | null>(null)
  const [extractError, setExtractError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const stopRef = useRef(false)

  // review phase state
  const [workflows, setWorkflows] = useState<WorkflowMeta[]>([])
  const [search, setSearch]       = useState('')
  const [expanded, setExpanded]   = useState<Set<string>>(new Set())
  const [details, setDetails]     = useState<Record<string, WorkflowDetail | null>>({})
  const [loadingDetail, setLoadingDetail] = useState<Set<string>>(new Set())

  // ── On mount: check if already extracted, otherwise start job ──────────────
  useEffect(() => {
    stopRef.current = false
    runExtraction()
    return () => {
      stopRef.current = true
      if (pollRef.current) clearTimeout(pollRef.current)
    }
  }, [])

  async function runExtraction(forceRefresh = false) {
    setExtractError(null)
    try {
      if (!forceRefresh) {
        // Fast path: if already in DB, skip straight to review
        const quick = await getWorkflowStoredCount()
        if (quick.stored > 0) {
          await loadWorkflows()
          setPhase('review')
          return
        }
      }

      // Start background extraction job
      const job = await startWorkflowExtraction()
      setBatchId(job.batch_id)

      // Poll until done
      const poll = async () => {
        if (stopRef.current) return
        try {
          const s = await getExtractionStatus(job.batch_id)
          setJobStatus(s)
          if (s.status === 'done' || s.status === 'error') {
            await loadWorkflows()
            setPhase('review')
          } else {
            pollRef.current = setTimeout(poll, 2000)
          }
        } catch {
          pollRef.current = setTimeout(poll, 3000)
        }
      }
      poll()

    } catch (err: unknown) {
      setExtractError(err instanceof Error ? err.message : 'Extraction failed')
    }
  }

  async function loadWorkflows() {
    const data = await listWorkflows()
    setWorkflows(data.workflows)
  }

  // ── Lazy-load activity detail when a row is expanded ──────────────────────
  function toggleExpand(internalName: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(internalName)) {
        next.delete(internalName)
      } else {
        next.add(internalName)
        if (details[internalName] === undefined && !loadingDetail.has(internalName)) {
          fetchDetail(internalName)
        }
      }
      return next
    })
  }

  async function fetchDetail(internalName: string) {
    setLoadingDetail(prev => new Set(prev).add(internalName))
    try {
      const d = await getWorkflowDetail(internalName)
      setDetails(prev => ({ ...prev, [internalName]: d }))
    } catch {
      setDetails(prev => ({ ...prev, [internalName]: null }))
    } finally {
      setLoadingDetail(prev => { const n = new Set(prev); n.delete(internalName); return n })
    }
  }

  // ── Derived ───────────────────────────────────────────────────────────────
  const pct = jobStatus && jobStatus.total > 0
    ? Math.round((jobStatus.done / jobStatus.total) * 100)
    : 0

  const filtered = workflows.filter(w =>
    !search ||
    w.label.toLowerCase().includes(search.toLowerCase()) ||
    w.internalName.toLowerCase().includes(search.toLowerCase()) ||
    w.folder.toLowerCase().includes(search.toLowerCase())
  )

  const folders = [...new Set(workflows.map(w => w.folder).filter(Boolean))].sort()

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50 px-6 py-8">
      <div className="max-w-3xl mx-auto">

        {/* Back */}
        <button
          onClick={() => navigate('/migration/type')}
          className="text-sm text-gray-500 hover:text-gray-800 mb-6 transition-colors"
        >
          ← Back
        </button>

        <h1 className="text-2xl font-bold text-gray-900 mb-6">Workflow Extraction</h1>

        {/* ── EXTRACTION CARD ────────────────────────────────────────────── */}
        <div className={`bg-white rounded-xl border p-6 mb-6 ${phase === 'extracting' ? 'border-violet-300' : 'border-gray-200'}`}>
          <div className="flex items-center gap-3 mb-4">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold ${phase === 'review' ? 'bg-green-500 text-white' : 'bg-violet-600 text-white'}`}>
              {phase === 'review' ? '✓' : '1'}
            </div>
            <h2 className="font-semibold text-gray-800">Extract workflows from ACC</h2>
          </div>

          {extractError ? (
            <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded-lg p-3 mb-3">
              {extractError}
            </div>
          ) : phase === 'review' ? (
            /* Extraction complete summary */
            <div className="flex items-center justify-between">
              <p className="text-sm text-green-700">
                {workflows.length} workflow{workflows.length !== 1 ? 's' : ''} extracted and ready.
                {jobStatus?.errors && jobStatus.errors.length > 0 && (
                  <span className="text-amber-600 ml-2">({jobStatus.errors.length} failed)</span>
                )}
              </p>
              <button
                onClick={() => {
                  setPhase('extracting')
                  setJobStatus(null)
                  setBatchId(null)
                  stopRef.current = false
                  runExtraction(true)
                }}
                className="text-xs text-gray-400 hover:text-gray-600 underline"
              >
                Re-extract
              </button>
            </div>
          ) : (
            /* Extraction in progress */
            <div className="space-y-3">
              <p className="text-sm text-gray-500">
                {!batchId
                  ? 'Starting extraction…'
                  : jobStatus?.status === 'queued'
                    ? 'Queued — connecting to ACC…'
                    : `Extracting ${jobStatus?.done ?? 0} of ${jobStatus?.total ?? '?'} workflows…`
                }
              </p>

              {/* Progress bar */}
              {batchId && (
                <div className="w-full bg-gray-100 rounded-full h-2">
                  <div
                    className="bg-violet-500 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${jobStatus?.total ? pct : 10}%` }}
                  />
                </div>
              )}

              {/* Spinning indicator */}
              {!batchId && (
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <svg className="animate-spin w-4 h-4 text-violet-400" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  Connecting…
                </div>
              )}

              {/* Per-workflow errors during extraction */}
              {jobStatus && jobStatus.errors.length > 0 && (
                <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2 max-h-24 overflow-y-auto">
                  {jobStatus.errors.map((e, i) => (
                    <p key={i}><span className="font-mono">{e.internalName}</span>: {e.error}</p>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── REVIEW CARD (only shown after extraction) ──────────────────── */}
        {phase === 'review' && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">

            {/* Header row */}
            <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
              <div className="w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold bg-violet-600 text-white">
                2
              </div>
              <h2 className="font-semibold text-gray-800 flex-1">Review extracted workflows</h2>
              <span className="text-sm text-gray-400">
                {filtered.length} of {workflows.length}
              </span>
            </div>

            {/* Search */}
            <div className="px-5 py-3 border-b border-gray-100">
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search by name, internal name, or folder…"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400"
              />
            </div>

            {/* Folder summary chips */}
            {folders.length > 0 && (
              <div className="px-5 py-2 border-b border-gray-100 flex flex-wrap gap-1.5">
                {folders.map(f => (
                  <button
                    key={f}
                    onClick={() => setSearch(f === search ? '' : f)}
                    className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                      search === f
                        ? 'bg-violet-600 text-white border-violet-600'
                        : 'text-gray-500 border-gray-200 hover:border-violet-300 hover:text-violet-600'
                    }`}
                  >
                    {f} ({workflows.filter(w => w.folder === f).length})
                  </button>
                ))}
              </div>
            )}

            {/* Workflow list */}
            <div className="p-4 flex flex-col gap-2 max-h-[600px] overflow-y-auto">
              {filtered.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-6">
                  {search ? 'No workflows match your search.' : 'No workflows found.'}
                </p>
              ) : (
                filtered.map(w => (
                  <WorkflowRow
                    key={w.internalName}
                    workflow={w}
                    detail={details[w.internalName] ?? null}
                    loadingDetail={loadingDetail.has(w.internalName)}
                    expanded={expanded.has(w.internalName)}
                    onToggle={() => toggleExpand(w.internalName)}
                  />
                ))
              )}
            </div>

            {/* Footer note — migration not yet available */}
            <div className="px-5 py-4 border-t border-gray-100 bg-gray-50">
              <p className="text-xs text-gray-400">
                Workflows have been extracted and stored. Migration to AJO will be available in a future step.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
