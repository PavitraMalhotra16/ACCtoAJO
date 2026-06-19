import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSchemas } from '../api/client'
import { startConversion } from '../api/migration'

interface SchemaEntry { namespace: string; name: string; label: string }

export default function MigrationSelectPage() {
  const navigate = useNavigate()

  const [schemas, setSchemas]   = useState<SchemaEntry[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [nsFilter, setNsFilter] = useState('')
  const [search, setSearch]     = useState('')
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    getSchemas()
      .then(d => setSchemas(d.schemas ?? []))
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

  function toggle(s: SchemaEntry) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(key(s))) next.delete(key(s)); else next.add(key(s))
      return next
    })
  }

  function toggleAll() {
    setSelected(prev => {
      const next = new Set(prev)
      if (allSelected) filtered.forEach(s => next.delete(key(s)))
      else filtered.forEach(s => next.add(key(s)))
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
      navigate(`/migration/run?extract_job=${data.job_id}`)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start conversion')
      setStarting(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">

      {/* Header */}
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

        {/* Left — filters */}
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
              return (
                <div
                  key={k}
                  onClick={() => toggle(s)}
                  className={`flex items-start gap-3 px-4 py-3 border-b border-gray-100 cursor-pointer transition-colors ${
                    checked ? 'bg-blue-50 border-l-2 border-l-blue-500' : 'hover:bg-gray-50'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(s)}
                    onClick={e => e.stopPropagation()}
                    className="mt-0.5 rounded"
                  />
                  <div className="min-w-0">
                    <div className="text-xs font-mono text-blue-700 truncate">{s.namespace}:{s.name}</div>
                    {s.label && <div className="text-xs text-gray-500 truncate mt-0.5">{s.label}</div>}
                  </div>
                </div>
              )
            })}
            {!loading && filtered.length === 0 && (
              <p className="text-sm text-gray-400 p-4">No schemas found</p>
            )}
          </div>
        </div>

        {/* Right — instructions */}
        <div className="flex-1 flex items-center justify-center text-center px-10">
          {selected.size === 0 ? (
            <div className="text-gray-400">
              <svg className="w-12 h-12 mx-auto mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
              </svg>
              <p className="text-sm">Select one or more schemas from the list</p>
              <p className="text-xs mt-1">then click <strong>Migrate →</strong> to start</p>
            </div>
          ) : (
            <div className="text-gray-600">
              <div className="text-4xl font-bold text-blue-600 mb-2">{selected.size}</div>
              <p className="text-sm">schema{selected.size !== 1 ? 's' : ''} selected</p>
              <p className="text-xs text-gray-400 mt-2">Click <strong>Migrate →</strong> in the header to start</p>
              <div className="mt-4 text-left bg-white border border-gray-200 rounded-xl p-4 max-h-64 overflow-y-auto">
                {[...selected].map(k => (
                  <div key={k} className="text-xs font-mono text-blue-700 py-0.5">{k}</div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
