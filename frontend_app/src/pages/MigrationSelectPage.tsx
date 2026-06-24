import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSchemas, getSchemaDetail, getSchemaDependencies } from '../api/client'
import { startConversion, getExtractedSchemas, getIncompleteSchemas, getPushedSchemas, type IncompleteSchema } from '../api/migration'

interface SchemaEntry { namespace: string; name: string; label: string }

interface Attribute {
  name: string
  type: string
  label?: string
}

interface SchemaLink {
  name: string
  targetSchema: string
  sourceField: string
}

interface SchemaDetail {
  namespace: string
  name: string
  label?: string
  attributes?: Attribute[]
  keys?: {
    autoPk?: { enabled: boolean; field?: string }
    primaryKeys?: { fields: string[] }[]
    uniqueKeys?: { fields: string[] }[]
  }
  links?: SchemaLink[]
}

function getPrimaryKeyInfo(detail: SchemaDetail): { field: string | null; isAuto: boolean } {
  const keys = detail.keys || {}
  if (keys.autoPk?.enabled) return { field: keys.autoPk.field || 'id', isAuto: true }
  const pkFields = keys.primaryKeys?.[0]?.fields
  if (pkFields?.length) return { field: pkFields[0], isAuto: false }
  const ukFields = keys.uniqueKeys?.[0]?.fields
  if (ukFields?.length) return { field: ukFields[0], isAuto: false }
  return { field: null, isAuto: false }
}

function SchemaDetailCard({
  entry,
  detail,
  loading,
  expanded,
  onToggle,
  isDependent,
}: {
  entry: SchemaEntry
  detail: SchemaDetail | null
  loading: boolean
  expanded: boolean
  onToggle: () => void
  isDependent?: boolean
}) {
  const pkInfo = detail ? getPrimaryKeyInfo(detail) : null
  const attrs = detail?.attributes ?? []

  // Build FK map: sourceField → link info
  const fkMap: Record<string, SchemaLink> = {}
  for (const link of detail?.links ?? []) {
    if (link.sourceField) fkMap[link.sourceField] = link
  }

  return (
    <div className={`border rounded-xl bg-white overflow-hidden ${isDependent ? 'border-orange-200' : 'border-gray-200'}`}>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
      >
        <svg
          className={`w-4 h-4 shrink-0 transition-transform ${expanded ? 'rotate-90' : ''} ${isDependent ? 'text-orange-300' : 'text-gray-400'}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <div className="flex-1 min-w-0">
          <div className={`text-sm font-mono font-semibold truncate ${isDependent ? 'text-orange-700' : 'text-blue-700'}`}>
            {entry.namespace}:{entry.name}
          </div>
          {entry.label && entry.label !== entry.name && (
            <div className="text-xs text-gray-500 truncate">{entry.label}</div>
          )}
        </div>
        {loading && (
          <svg className="animate-spin w-4 h-4 text-blue-400 shrink-0" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
        )}
        {!loading && detail && (
          <span className="text-xs text-gray-400 shrink-0">{attrs.length} fields</span>
        )}
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3">
          {loading && <p className="text-xs text-gray-400 py-2">Loading schema details…</p>}
          {!loading && !detail && <p className="text-xs text-red-400 py-2">Failed to load details</p>}
          {!loading && detail && (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {pkInfo?.field && (
                  <>
                    <span className="text-xs font-medium text-purple-700 bg-purple-50 border border-purple-200 rounded px-2 py-0.5">
                      {pkInfo.isAuto ? 'Auto PK' : 'Primary Key'}
                    </span>
                    <span className="text-xs font-mono text-gray-700">{pkInfo.field}</span>
                  </>
                )}
                {Object.keys(fkMap).length > 0 && (
                  <>
                    {pkInfo?.field && <span className="text-gray-200">|</span>}
                    <span className="text-xs font-medium text-orange-700 bg-orange-50 border border-orange-200 rounded px-2 py-0.5">
                      FK
                    </span>
                    {Object.entries(fkMap).map(([field, link]) => (
                      <span key={field} className="text-xs font-mono text-gray-700">
                        {field}
                        <span className="text-orange-400 mx-1">→</span>
                        <span className="text-orange-600">{link.targetSchema}</span>
                      </span>
                    ))}
                  </>
                )}
              </div>
              {attrs.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-gray-400 border-b border-gray-100">
                        <th className="text-left py-1 pr-3 font-medium">Field</th>
                        <th className="text-left py-1 pr-3 font-medium">Type</th>
                        <th className="text-left py-1 font-medium">Label</th>
                      </tr>
                    </thead>
                    <tbody>
                      {attrs.map(attr => {
                        const isPK = pkInfo?.field === attr.name
                        const fkLink = fkMap[attr.name]
                        const rowCls = isPK ? 'bg-purple-50' : fkLink ? 'bg-orange-50' : ''
                        return (
                          <tr
                            key={attr.name}
                            className={`border-b border-gray-50 last:border-0 ${rowCls}`}
                          >
                            <td className="py-1 pr-3 font-mono text-gray-800 whitespace-nowrap">
                              {isPK && (
                                <span className="inline-block w-2 h-2 rounded-full bg-purple-400 mr-1.5 align-middle" title="Primary key" />
                              )}
                              {fkLink && !isPK && (
                                <span className="inline-block w-2 h-2 rounded-full bg-orange-400 mr-1.5 align-middle" title={`FK → ${fkLink.targetSchema}`} />
                              )}
                              {attr.name}
                            </td>
                            <td className="py-1 pr-3 text-blue-600 whitespace-nowrap">{attr.type || 'string'}</td>
                            <td className="py-1 text-gray-500 truncate max-w-[160px]">
                              {fkLink ? (
                                <span className="text-orange-500">→ {fkLink.targetSchema}</span>
                              ) : (
                                attr.label || '—'
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-gray-400">No attributes found</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default function MigrationSelectPage() {
  const navigate = useNavigate()

  const [schemas, setSchemas]   = useState<SchemaEntry[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [nsFilter, setNsFilter] = useState('')
  const [search, setSearch]     = useState('')
  const [starting, setStarting] = useState(false)

  const [details, setDetails]             = useState<Record<string, SchemaDetail | null>>({})
  const [loadingDetail, setLoadingDetail] = useState<Set<string>>(new Set())
  const [expanded, setExpanded]           = useState<Set<string>>(new Set())
  const [depExpanded, setDepExpanded]     = useState<Set<string>>(new Set())
  const [extracted, setExtracted]         = useState<Set<string>>(new Set())
  const [pushed, setPushed]               = useState<Set<string>>(new Set())
  const [incomplete, setIncomplete]       = useState<Record<string, IncompleteSchema>>({})
  const [dependentsOf, setDependentsOf]   = useState<Record<string, string[]>>({})
  const [dependentSet, setDependentSet]   = useState<Set<string>>(new Set())

  useEffect(() => {
    Promise.all([
      getSchemas(),
      getExtractedSchemas(),
      getIncompleteSchemas(),
      getPushedSchemas(),
      getSchemaDependencies(),
    ])
      .then(([schemasData, extractedData, incompleteData, pushedData, depsData]) => {
        setSchemas(schemasData.schemas ?? [])
        setExtracted(new Set(extractedData.extracted))
        setPushed(new Set(pushedData.schemas))
        setDependentsOf(depsData.dependents_of)
        setDependentSet(new Set(depsData.dependent_set))

        const incompleteMap: Record<string, IncompleteSchema> = {}
        for (const s of incompleteData.schemas) incompleteMap[s.schema_name] = s
        setIncomplete(incompleteMap)

        // Pre-select FAILED independent schemas only
        const failedKeys = new Set(
          incompleteData.schemas
            .filter(s => s.status === 'FAILED' && !depsData.dependent_set.includes(s.schema_name))
            .map(s => s.schema_name)
        )
        if (failedKeys.size > 0) setSelected(failedKeys)
      })
      .catch(e => setError(`Failed to load schemas: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  const key = (s: SchemaEntry) => `${s.namespace}:${s.name}`
  const namespaces = [...new Set(schemas.map(s => s.namespace))].sort()

  // Build reverse map: depKey → list of independent schema keys it belongs to
  const belongsTo: Record<string, string[]> = {}
  for (const [parent, deps] of Object.entries(dependentsOf)) {
    for (const dep of deps) {
      belongsTo[dep] = [...(belongsTo[dep] ?? []), parent]
    }
  }

  const baseFiltered = schemas.filter(s =>
    (!nsFilter || s.namespace === nsFilter) &&
    (!search || s.name.toLowerCase().includes(search.toLowerCase()) ||
     (s.label || '').toLowerCase().includes(search.toLowerCase()))
  )

  // Reorder: each independent schema is followed immediately by its dependents
  const filtered: SchemaEntry[] = []
  const insertedKeys = new Set<string>()
  for (const s of baseFiltered) {
    const k = key(s)
    if (insertedKeys.has(k)) continue
    filtered.push(s)
    insertedKeys.add(k)
    if (!dependentSet.has(k)) {
      for (const depKey of (dependentsOf[k] ?? [])) {
        const depEntry = baseFiltered.find(s2 => key(s2) === depKey)
        if (depEntry && !insertedKeys.has(depKey)) {
          filtered.push(depEntry)
          insertedKeys.add(depKey)
        }
      }
    }
  }

  // Only count independently-selectable (non-dependent) schemas for "select all"
  const selectableFiltered = filtered.filter(s => !dependentSet.has(key(s)))
  const allSelected = selectableFiltered.length > 0 && selectableFiltered.every(s => selected.has(key(s)))

  // Total schemas that will migrate = selected + their dependents
  function expandWithDependents(keys: Set<string>): SchemaEntry[] {
    const allKeys = new Set(keys)
    for (const k of keys) {
      for (const dep of (dependentsOf[k] ?? [])) allKeys.add(dep)
    }
    return schemas.filter(s => allKeys.has(key(s)))
  }

  function fetchDetail(k: string, s: SchemaEntry) {
    if (details[k] !== undefined || loadingDetail.has(k)) return
    setLoadingDetail(prev => new Set(prev).add(k))
    getSchemaDetail(s.namespace, s.name)
      .then(d => setDetails(prev => ({ ...prev, [k]: d as SchemaDetail })))
      .catch(() => setDetails(prev => ({ ...prev, [k]: null })))
      .finally(() => setLoadingDetail(prev => { const n = new Set(prev); n.delete(k); return n }))
  }

  function fetchDependentsOf(k: string) {
    // When an independent schema is selected, pre-fetch details for all its dependents
    for (const depKey of (dependentsOf[k] ?? [])) {
      const depEntry = schemas.find(s => key(s) === depKey)
      if (depEntry) fetchDetail(depKey, depEntry)
    }
  }

  function toggle(s: SchemaEntry) {
    const k = key(s)
    if (dependentSet.has(k)) return  // dependent schemas cannot be toggled
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(k)) {
        next.delete(k)
        setExpanded(e => { const ne = new Set(e); ne.delete(k); return ne })
      } else {
        next.add(k)
        setExpanded(e => new Set(e).add(k))
        fetchDetail(k, s)
        fetchDependentsOf(k)
        // Auto-expand dependents in right panel
        setDepExpanded(e => {
          const ne = new Set(e)
          for (const dep of (dependentsOf[k] ?? [])) ne.add(dep)
          return ne
        })
      }
      return next
    })
  }

  function toggleExpand(s: SchemaEntry) {
    const k = key(s)
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(k)) { next.delete(k) } else {
        next.add(k)
        fetchDetail(k, s)
        fetchDependentsOf(k)
        setDepExpanded(e => {
          const ne = new Set(e)
          for (const dep of (dependentsOf[k] ?? [])) ne.add(dep)
          return ne
        })
      }
      return next
    })
  }

  function toggleAll() {
    setSelected(prev => {
      const next = new Set(prev)
      if (allSelected) {
        selectableFiltered.forEach(s => {
          next.delete(key(s))
          setExpanded(e => { const ne = new Set(e); ne.delete(key(s)); return ne })
        })
      } else {
        selectableFiltered.forEach(s => {
          const k = key(s)
          next.add(k)
          setExpanded(e => new Set(e).add(k))
          fetchDetail(k, s)
          fetchDependentsOf(k)
          setDepExpanded(e => {
            const ne = new Set(e)
            for (const dep of (dependentsOf[k] ?? [])) ne.add(dep)
            return ne
          })
        })
      }
      return next
    })
  }

  async function handleNext() {
    const chosen = expandWithDependents(selected)
    if (!chosen.length) return
    setStarting(true)
    setError(null)
    try {
      const data = await startConversion(chosen)
      if (!data.job_id) {
        setError('Could not start extraction — please try again.')
        setStarting(false)
        return
      }
      navigate(`/migration/run?extract_job=${data.job_id}`)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start')
      setStarting(false)
    }
  }

  const selectedSchemas = schemas.filter(s => selected.has(key(s)))

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">

      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <button onClick={() => navigate('/')} className="text-sm text-gray-500 hover:text-gray-800">← Back</button>
        <h1 className="text-xl font-bold text-gray-900 flex-1">Select Schemas to Migrate</h1>
        {selected.size > 0 && (
          <span className="text-sm font-medium text-blue-600 bg-blue-50 px-3 py-1 rounded-full">
            {expandWithDependents(selected).length} schema{expandWithDependents(selected).length !== 1 ? 's' : ''} will migrate
          </span>
        )}
        {Object.values(incomplete).some(s => s.status === 'FAILED') && (
          <span className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-3 py-1 rounded-full">
            Failed schemas will all be retried
          </span>
        )}
        <button
          onClick={handleNext}
          disabled={selected.size === 0 || starting || loading}
          className="px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors flex items-center gap-2"
        >
          {starting ? (
            <>
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              Starting…
            </>
          ) : 'Migrate →'}
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">

        {/* ── Sidebar ─────────────────────────────────────────────────── */}
        <div className="w-72 shrink-0 bg-white border-r border-gray-200 flex flex-col">
          <div className="p-3 border-b border-gray-100 flex flex-col gap-2">
            <input
              placeholder="Search schemas…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <select
              value={nsFilter}
              onChange={e => setNsFilter(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All namespaces</option>
              {namespaces.map(ns => (
                <option key={ns} value={ns}>{ns} ({schemas.filter(s => s.namespace === ns).length})</option>
              ))}
            </select>
            <div className="flex items-center justify-between px-1">
              <button onClick={toggleAll} className="text-xs text-blue-600 hover:text-blue-800 underline">
                {allSelected ? 'Deselect all' : 'Select all'}
                {nsFilter ? ` in "${nsFilter}"` : ' visible'}
              </button>
              <span className="text-xs text-gray-400">{filtered.length} shown</span>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loading && <p className="text-sm text-gray-400 p-4">Loading schemas…</p>}
            {error && <p className="text-sm text-red-500 p-4">{error}</p>}
            {filtered.map(s => {
              const k = key(s)
              const isDependent = dependentSet.has(k)
              const checked = selected.has(k)
              const incomp = incomplete[k]
              const isFailed = incomp?.status === 'FAILED'
              const isBusy = incomp?.status === 'RUNNING' || incomp?.status === 'QUEUED'
              const isPushed = pushed.has(k)
              const isExtracted = extracted.has(k)
              const isLocked = isBusy
              const depCount = (dependentsOf[k] ?? []).length
              const parents = belongsTo[k] ?? []

              let badge: { text: string; cls: string } | null = null
              if (isBusy) {
                badge = { text: 'In progress', cls: 'bg-amber-50 text-amber-600' }
              } else if (isFailed) {
                const err = incomp?.error_message
                badge = {
                  text: `Failed: ${incomp?.current_step ?? `step ${incomp?.current_step_order}`}${err ? ` — ${err.slice(0, 50)}${err.length > 50 ? '…' : ''}` : ''}`,
                  cls: 'bg-red-50 text-red-600',
                }
              } else if (isPushed) {
                badge = { text: 'Pushed to AJO — re-migrate to sync ACC changes', cls: 'bg-green-100 text-green-700' }
              } else if (isExtracted) {
                badge = { text: 'Ready to push', cls: 'bg-indigo-50 text-indigo-600' }
              }

              if (isDependent) {
                const isActivated = parents.some(p => selected.has(p))
                return (
                  <div
                    key={k}
                    className={`flex items-start gap-3 px-4 py-3 border-b border-gray-100 cursor-default transition-colors ${
                      isActivated ? 'bg-green-50 border-l-2 border-l-green-400' : 'bg-gray-50 opacity-70'
                    }`}
                    title={parents.length ? `Dependent on: ${parents.join(', ')}` : 'Dependent schema — migrates automatically'}
                  >
                    <svg
                      className={`mt-0.5 w-4 h-4 shrink-0 ${isActivated ? 'text-green-400' : 'text-gray-300'}`}
                      fill="none" stroke="currentColor" viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                    </svg>
                    <div className="min-w-0 flex-1">
                      <div className={`text-xs font-mono truncate ${isActivated ? 'text-green-700' : 'text-gray-500'}`}>
                        {s.namespace}:{s.name}
                      </div>
                      <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                        {s.label && (
                          <span className={`text-xs truncate ${isActivated ? 'text-green-500' : 'text-gray-400'}`}>
                            {s.label}
                          </span>
                        )}
                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium shrink-0 ${
                          isActivated ? 'bg-green-100 text-green-600' : 'bg-orange-50 text-orange-500'
                        }`}>
                          {isActivated ? 'will migrate' : 'dependent'}
                        </span>
                        {parents.length > 0 && (
                          <span className={`text-xs truncate ${isActivated ? 'text-green-400' : 'text-gray-400'}`}>
                            of {parents.map(p => p.split(':')[1]).join(', ')}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              }

              return (
                <div
                  key={k}
                  className={`flex items-start gap-3 px-4 py-3 border-b border-gray-100 transition-colors ${
                    isLocked
                      ? 'bg-gray-50 cursor-default'
                      : checked
                        ? `${isFailed ? 'bg-red-50 border-l-2 border-l-red-400' : 'bg-blue-50 border-l-2 border-l-blue-500'} cursor-pointer`
                        : 'hover:bg-gray-50 cursor-pointer'
                  }`}
                  onClick={() => { if (!isLocked) toggle(s) }}
                >
                  {isLocked ? (
                    <svg className="animate-spin mt-0.5 w-4 h-4 text-amber-400 shrink-0" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                  ) : (
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(s)}
                      onClick={e => e.stopPropagation()}
                      className={`mt-0.5 rounded ${isFailed ? 'accent-red-500' : ''}`}
                    />
                  )}

                  <div className="min-w-0 flex-1">
                    <div className={`text-xs font-mono truncate ${isFailed ? 'text-red-700' : isPushed ? 'text-green-700' : 'text-blue-700'}`}>
                      {s.namespace}:{s.name}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                      {s.label && <span className="text-xs text-gray-400 truncate">{s.label}</span>}
                      {depCount > 0 && (
                        <span className="text-xs px-1.5 py-0.5 rounded font-medium bg-blue-50 text-blue-500 shrink-0">
                          +{depCount} dependent{depCount !== 1 ? 's' : ''}
                        </span>
                      )}
                      {badge && (
                        <span
                          className={`text-xs px-1.5 py-0.5 rounded font-medium shrink-0 ${badge.cls}`}
                          title={incomp?.error_message ?? undefined}
                        >
                          {badge.text}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
            {!loading && filtered.length === 0 && (
              <p className="text-sm text-gray-400 p-4">No schemas found</p>
            )}
          </div>
        </div>

        {/* ── Right panel ─────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto p-6">
          {selectedSchemas.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center text-gray-400">
              <svg className="w-12 h-12 mx-auto mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
              </svg>
              <p className="text-sm">Select schemas from the list to preview their fields</p>
              <p className="text-xs mt-1">then click <strong>Migrate →</strong> to start</p>
            </div>
          ) : (
            <div className="max-w-2xl mx-auto flex flex-col gap-6">
              <p className="text-xs text-gray-400">
                {selectedSchemas.length} selected — click a row to expand
              </p>

              {selectedSchemas.map(s => {
                const k = key(s)
                const deps = dependentsOf[k] ?? []
                return (
                  <div key={k} className="flex flex-col gap-2">
                    {/* Independent schema card */}
                    <SchemaDetailCard
                      entry={s}
                      detail={details[k] ?? null}
                      loading={loadingDetail.has(k)}
                      expanded={expanded.has(k)}
                      onToggle={() => toggleExpand(s)}
                    />

                    {/* Dependent schema cards */}
                    {deps.length > 0 && (
                      <div className="ml-6 flex flex-col gap-2">
                        <p className="text-xs font-medium text-orange-500 px-1 flex items-center gap-1">
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                          </svg>
                          {deps.length} dependent schema{deps.length !== 1 ? 's' : ''} — will migrate automatically
                        </p>
                        {deps.map(depKey => {
                          const depEntry = schemas.find(s2 => key(s2) === depKey)
                          if (!depEntry) return null
                          return (
                            <SchemaDetailCard
                              key={depKey}
                              entry={depEntry}
                              detail={details[depKey] ?? null}
                              loading={loadingDetail.has(depKey)}
                              expanded={depExpanded.has(depKey)}
                              onToggle={() => {
                                setDepExpanded(prev => {
                                  const next = new Set(prev)
                                  if (next.has(depKey)) { next.delete(depKey) } else {
                                    next.add(depKey)
                                    fetchDetail(depKey, depEntry)
                                  }
                                  return next
                                })
                              }}
                              isDependent
                            />
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
