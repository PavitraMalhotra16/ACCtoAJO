import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSchemas, getSchemaDetail } from '../api/client'
import { startConversion, getExtractedSchemas } from '../api/migration'

interface SchemaEntry { namespace: string; name: string; label: string }

const EXCLUDED_NAMESPACES = new Set(['crm', 'ncm', 'nms', 'xtk', 'nl'])

interface Attribute {
  name: string
  type: string
  label?: string
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
}: {
  entry: SchemaEntry
  detail: SchemaDetail | null
  loading: boolean
  expanded: boolean
  onToggle: () => void
}) {
  const pkInfo = detail ? getPrimaryKeyInfo(detail) : null
  const attrs = detail?.attributes ?? []

  return (
    <div className="border border-gray-200 rounded-xl bg-white overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
      >
        <svg
          className={`w-4 h-4 text-gray-400 shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-mono font-semibold text-blue-700 truncate">
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
              {pkInfo && pkInfo.field && (
                <div className="mb-3 flex items-center gap-2">
                  <span className="text-xs font-medium text-purple-700 bg-purple-50 border border-purple-200 rounded px-2 py-0.5">
                    {pkInfo.isAuto ? 'Auto PK' : 'Primary Key'}
                  </span>
                  <span className="text-xs font-mono text-gray-700">{pkInfo.field}</span>
                </div>
              )}
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
                        return (
                          <tr
                            key={attr.name}
                            className={`border-b border-gray-50 last:border-0 ${isPK ? 'bg-purple-50' : ''}`}
                          >
                            <td className="py-1 pr-3 font-mono text-gray-800 whitespace-nowrap">
                              {isPK && (
                                <span className="inline-block w-2 h-2 rounded-full bg-purple-400 mr-1.5 align-middle" title="Primary key" />
                              )}
                              {attr.name}
                            </td>
                            <td className="py-1 pr-3 text-blue-600 whitespace-nowrap">{attr.type || 'string'}</td>
                            <td className="py-1 text-gray-500 truncate max-w-[160px]">{attr.label || '—'}</td>
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

  const [details, setDetails]   = useState<Record<string, SchemaDetail | null>>({})
  const [loadingDetail, setLoadingDetail] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [extracted, setExtracted] = useState<Set<string>>(new Set())

  useEffect(() => {
    Promise.all([
      getSchemas(),
      getExtractedSchemas(),
    ])
      .then(([schemasData, extractedData]) => {
        setSchemas(
          (schemasData.schemas ?? []).filter(s => !EXCLUDED_NAMESPACES.has(s.namespace.toLowerCase()))
        )
        setExtracted(new Set(extractedData.extracted))
      })
      .catch(e => setError(`Failed to load schemas: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  const key = (s: SchemaEntry) => `${s.namespace}:${s.name}`
  const namespaces = [...new Set(schemas.map(s => s.namespace))].sort()
  const filtered = schemas.filter(s =>
    (!nsFilter || s.namespace === nsFilter) &&
    (!search || s.name.toLowerCase().includes(search.toLowerCase()) ||
     (s.label || '').toLowerCase().includes(search.toLowerCase()))
  )

  const allSelected = filtered.length > 0 && filtered.every(s => selected.has(key(s)))

  function fetchDetail(s: SchemaEntry) {
    const k = key(s)
    if (details[k] !== undefined || loadingDetail.has(k)) return
    setLoadingDetail(prev => new Set(prev).add(k))
    getSchemaDetail(s.namespace, s.name)
      .then(d => setDetails(prev => ({ ...prev, [k]: d as SchemaDetail })))
      .catch(() => setDetails(prev => ({ ...prev, [k]: null })))
      .finally(() => setLoadingDetail(prev => { const n = new Set(prev); n.delete(k); return n }))
  }

  function toggle(s: SchemaEntry) {
    const k = key(s)
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(k)) {
        next.delete(k)
        setExpanded(e => { const ne = new Set(e); ne.delete(k); return ne })
      } else {
        next.add(k)
        setExpanded(e => new Set(e).add(k))
        fetchDetail(s)
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
        fetchDetail(s)
      }
      return next
    })
  }

  function toggleAll() {
    setSelected(prev => {
      const next = new Set(prev)
      if (allSelected) {
        filtered.forEach(s => {
          next.delete(key(s))
          setExpanded(e => { const ne = new Set(e); ne.delete(key(s)); return ne })
        })
      } else {
        filtered.forEach(s => {
          next.add(key(s))
          setExpanded(e => new Set(e).add(key(s)))
          fetchDetail(s)
        })
      }
      return next
    })
  }

  async function handleNext() {
    const chosen = schemas.filter(s => selected.has(key(s)))
    if (!chosen.length) return
    setStarting(true)
    setError(null)
    try {
      const data = await startConversion(chosen)
      if (data.message === 'all_done' || !data.job_id) {
        setError('All selected schemas are already migrated — nothing new to extract.')
        setStarting(false)
        return
      }
      navigate(`/migration/run?extract_job=${data.job_id}`)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start conversion')
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
            {selected.size} selected
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
              const checked = selected.has(k)
              const alreadyExtracted = extracted.has(k)
              return (
                <div
                  key={k}
                  className={`flex items-start gap-3 px-4 py-3 border-b border-gray-100 transition-colors ${
                    alreadyExtracted
                      ? 'bg-gray-50 cursor-default opacity-70'
                      : checked
                        ? 'bg-blue-50 border-l-2 border-l-blue-500 cursor-pointer'
                        : 'hover:bg-gray-50 cursor-pointer'
                  }`}
                  onClick={() => { if (!alreadyExtracted) toggle(s) }}
                >
                  {alreadyExtracted ? (
                    <svg className="mt-0.5 w-4 h-4 text-green-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
                    </svg>
                  ) : (
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(s)}
                      onClick={e => e.stopPropagation()}
                      className="mt-0.5 rounded"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className={`text-xs font-mono truncate ${alreadyExtracted ? 'text-gray-500' : 'text-blue-700'}`}>
                      {s.namespace}:{s.name}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      {s.label && <span className="text-xs text-gray-400 truncate">{s.label}</span>}
                      {alreadyExtracted && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700 font-medium shrink-0">
                          Extracted — enriched JSON ready
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
            <div className="max-w-2xl mx-auto flex flex-col gap-3">
              <p className="text-xs text-gray-400 mb-1">{selectedSchemas.length} schema{selectedSchemas.length !== 1 ? 's' : ''} selected — click a row to expand</p>
              {selectedSchemas.map(s => {
                const k = key(s)
                return (
                  <SchemaDetailCard
                    key={k}
                    entry={s}
                    detail={details[k] ?? null}
                    loading={loadingDetail.has(k)}
                    expanded={expanded.has(k)}
                    onToggle={() => toggleExpand(s)}
                  />
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
