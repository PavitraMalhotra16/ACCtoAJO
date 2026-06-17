import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSchemas } from '../api/client'

interface SchemaEntry { namespace: string; name: string; label: string }

export default function SchemaInspectorPage() {
  const navigate = useNavigate()

  const [schemas, setSchemas]     = useState<SchemaEntry[]>([])
  const [nsFilter, setNsFilter]   = useState('')
  const [search, setSearch]       = useState('')
  const [selected, setSelected]   = useState<SchemaEntry | null>(null)
  const [detail, setDetail]       = useState<object | null>(null)
  const [loading, setLoading]     = useState(false)
  const [loadingList, setLoadingList] = useState(true)
  const [error, setError]         = useState<string | null>(null)

  useEffect(() => {
    getSchemas()
      .then(d => setSchemas(d.schemas ?? []))
      .catch(e => setError(`Failed to load schemas: ${e.message}`))
      .finally(() => setLoadingList(false))
  }, [])

  const namespaces = [...new Set(schemas.map(s => s.namespace))].sort()
  const filtered = schemas.filter(s =>
    (!nsFilter || s.namespace === nsFilter) &&
    (!search || s.name.toLowerCase().includes(search.toLowerCase()) ||
     s.label?.toLowerCase().includes(search.toLowerCase()))
  )

  async function inspect(s: SchemaEntry) {
    setSelected(s); setDetail(null); setError(null); setLoading(true)
    try {
      const res = await fetch(`/api/acc/schema/inspect/${s.namespace}/${s.name}`, { credentials: 'include' })
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed') }
      setDetail(await res.json())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch schema')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <button onClick={() => navigate('/')} className="text-sm text-gray-500 hover:text-gray-800">← Back</button>
        <h1 className="text-xl font-bold text-gray-900 flex-1">Schema Inspector</h1>
      </div>

      <div className="flex flex-1 overflow-hidden">

        {/* Left — Schema list */}
        <div className="w-80 shrink-0 bg-white border-r border-gray-200 flex flex-col">
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
              {namespaces.map(ns => <option key={ns} value={ns}>{ns}</option>)}
            </select>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loadingList && <p className="text-sm text-gray-400 p-4">Loading schemas…</p>}
            {error && !selected && <p className="text-sm text-red-500 p-4">{error}</p>}
            {filtered.map(s => (
              <button
                key={`${s.namespace}:${s.name}`}
                onClick={() => inspect(s)}
                className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-blue-50 transition-colors ${
                  selected?.namespace === s.namespace && selected?.name === s.name
                    ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''
                }`}
              >
                <div className="text-xs font-mono text-blue-700">{s.name}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{s.namespace}</span>
                  <span className="text-xs text-gray-500 truncate">{s.label}</span>
                </div>
              </button>
            ))}
            {!loadingList && filtered.length === 0 && (
              <p className="text-sm text-gray-400 p-4">No schemas found</p>
            )}
          </div>
        </div>

        {/* Right — Detail */}
        <div className="flex-1 overflow-y-auto p-6">
          {!selected && (
            <div className="flex items-center justify-center h-full text-gray-400 text-sm">
              Select a schema from the list to inspect it
            </div>
          )}

          {selected && loading && (
            <div className="flex items-center justify-center h-full gap-3">
              <svg className="animate-spin w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              <span className="text-sm text-gray-500">Fetching {selected.namespace}:{selected.name}…</span>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700 text-sm">{error}</div>
          )}

          {detail && !loading && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-bold text-gray-900 font-mono">
                  {selected?.namespace}:{selected?.name}
                </h2>
                <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                  {(detail as any).schema?.mappingType || 'sql'}
                </span>
              </div>

              <pre className="bg-gray-900 text-green-300 text-xs rounded-xl p-5 overflow-x-auto leading-relaxed">
                {JSON.stringify(detail, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
