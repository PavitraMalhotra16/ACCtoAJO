import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSchemas, getSchemaDetail } from '../api/client'

interface SchemaEntry {
  namespace: string
  name: string
  label: string
}

interface SchemaAttr {
  name: string
  type: string
  label: string
  length: string
  required: string
  enum: string
  desc: string
}

interface SchemaElement {
  tag: string
  attrs: Record<string, string>
  children: SchemaElement[]
}

interface SchemaDetail {
  namespace: string
  name: string
  label: string
  labelSingular: string
  desc: string
  elements: SchemaElement[]
  attributes: SchemaAttr[]
}

export default function SchemasPage() {
  const navigate = useNavigate()
  const [schemas, setSchemas] = useState<SchemaEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [selectedNamespace, setSelectedNamespace] = useState<string>('')
  const [selectedSchema, setSelectedSchema] = useState<SchemaEntry | null>(null)
  const [detail, setDetail] = useState<SchemaDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)

  useEffect(() => {
    getSchemas()
      .then(data => setSchemas(data.schemas))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const namespaces = [...new Set(schemas.map(s => s.namespace))].sort()
  const schemasInNamespace = schemas.filter(s => s.namespace === selectedNamespace)

  function handleNamespaceChange(ns: string) {
    setSelectedNamespace(ns)
    setSelectedSchema(null)
    setDetail(null)
    setDetailError(null)
  }

  async function handleSchemaChange(schemaName: string) {
    const schema = schemasInNamespace.find(s => s.name === schemaName)
    if (!schema) return
    setSelectedSchema(schema)
    setDetail(null)
    setDetailError(null)
    setDetailLoading(true)
    try {
      const d = await getSchemaDetail(schema.namespace, schema.name)
      setDetail(d as SchemaDetail)
    } catch (e: unknown) {
      setDetailError(e instanceof Error ? e.message : 'Failed to load schema')
    } finally {
      setDetailLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/')} className="text-sm text-gray-500 hover:text-gray-800">← Back</button>
        <h1 className="text-xl font-bold text-gray-900">ACC Schemas</h1>
      </div>

      {loading && (
        <div className="flex items-center justify-center flex-1 py-20">
          <svg className="animate-spin w-8 h-8 text-red-600" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
        </div>
      )}

      {error && <div className="m-6 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700">{error}</div>}

      {!loading && !error && (
        <div className="flex flex-col flex-1 px-6 py-6 gap-6 max-w-6xl w-full mx-auto">

          {/* Dropdowns row */}
          <div className="flex gap-4 items-end">
            <div className="flex flex-col gap-1.5 w-56">
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Namespace</label>
              <select
                value={selectedNamespace}
                onChange={e => handleNamespaceChange(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-red-500 shadow-sm"
              >
                <option value="">— Select namespace —</option>
                {namespaces.map(ns => (
                  <option key={ns} value={ns}>{ns} ({schemas.filter(s => s.namespace === ns).length})</option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1.5 flex-1 max-w-sm">
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Schema / Table</label>
              <select
                value={selectedSchema?.name ?? ''}
                onChange={e => handleSchemaChange(e.target.value)}
                disabled={!selectedNamespace}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm disabled:bg-gray-100 disabled:text-gray-400"
              >
                <option value="">— Select schema —</option>
                {schemasInNamespace.map(s => (
                  <option key={s.name} value={s.name}>{s.label || s.name} ({s.name})</option>
                ))}
              </select>
            </div>

            {selectedSchema && (
              <div className="flex items-end pb-0.5">
                <span className="text-sm font-mono text-gray-500 bg-gray-100 px-2 py-1.5 rounded">
                  {selectedSchema.namespace}:{selectedSchema.name}
                </span>
              </div>
            )}
          </div>

          {/* Detail panel */}
          <div className="bg-white rounded-2xl border border-gray-200 flex-1 overflow-hidden">
            {!selectedSchema && (
              <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
                Select a namespace and schema above to view its details
              </div>
            )}

            {detailLoading && (
              <div className="flex items-center justify-center h-64">
                <svg className="animate-spin w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
              </div>
            )}

            {detailError && (
              <div className="m-4 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700 text-sm">{detailError}</div>
            )}

            {detail && !detailLoading && (
              <div className="flex flex-col">
                {/* Schema header */}
                <div className="px-6 py-4 border-b border-gray-100 flex items-center gap-4">
                  <div>
                    <h2 className="text-lg font-bold text-gray-900">{detail.label || detail.name}</h2>
                    <p className="text-xs font-mono text-gray-400">{detail.namespace}:{detail.name}</p>
                  </div>
                  {detail.desc && <p className="text-sm text-gray-500 ml-4">{detail.desc}</p>}
                  <div className="ml-auto flex gap-2 text-xs text-gray-400">
                    {detail.attributes.length > 0 && (
                      <span className="bg-purple-50 text-purple-600 px-2 py-1 rounded font-medium">{detail.attributes.length} attributes</span>
                    )}
                    {detail.elements.length > 0 && (
                      <span className="bg-blue-50 text-blue-600 px-2 py-1 rounded font-medium">{detail.elements.length} elements</span>
                    )}
                  </div>
                </div>

                <div className="p-6 flex flex-col gap-6 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 280px)' }}>
                  {/* Attributes table */}
                  {detail.attributes.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Attributes</h3>
                      <div className="border border-gray-200 rounded-lg overflow-hidden">
                        <table className="w-full text-sm">
                          <thead className="bg-gray-50 border-b border-gray-200">
                            <tr>
                              <th className="text-left px-4 py-2.5 font-medium text-gray-600 text-xs">Name</th>
                              <th className="text-left px-4 py-2.5 font-medium text-gray-600 text-xs">Type</th>
                              <th className="text-left px-4 py-2.5 font-medium text-gray-600 text-xs">Label</th>
                              <th className="text-left px-4 py-2.5 font-medium text-gray-600 text-xs">Length</th>
                              <th className="text-left px-4 py-2.5 font-medium text-gray-600 text-xs">Required</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100">
                            {detail.attributes.map((a, i) => (
                              <tr key={i} className="hover:bg-gray-50">
                                <td className="px-4 py-2.5 font-mono text-xs text-purple-700">@{a.name}</td>
                                <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{a.type || '—'}</td>
                                <td className="px-4 py-2.5 text-gray-800 text-xs">{a.label || '—'}</td>
                                <td className="px-4 py-2.5 text-gray-500 text-xs">{a.length || '—'}</td>
                                <td className="px-4 py-2.5 text-xs">
                                  {a.required === 'true'
                                    ? <span className="bg-red-100 text-red-700 px-1.5 py-0.5 rounded text-xs">yes</span>
                                    : <span className="text-gray-300">—</span>}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Elements */}
                  {detail.elements.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Elements</h3>
                      <div className="flex flex-col gap-2">
                        {detail.elements.map((el, i) => <ElementCard key={i} el={el} depth={0} />)}
                      </div>
                    </div>
                  )}

                  {detail.attributes.length === 0 && detail.elements.length === 0 && (
                    <p className="text-sm text-gray-400 py-8 text-center">No attributes or elements found in this schema.</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ElementCard({ el, depth }: { el: SchemaElement; depth: number }) {
  const [open, setOpen] = useState(depth === 0)
  const hasChildren = el.children.length > 0
  const { name, label, type, img: _img, md5: _md5, _cs, ...rest } = el.attrs

  return (
    <div className={`border border-gray-200 rounded-lg overflow-hidden ${depth > 0 ? 'ml-5 mt-1' : ''}`}>
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left transition-colors">
        {hasChildren
          ? <svg className={`w-3 h-3 text-gray-400 transition-transform flex-shrink-0 ${open ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          : <span className="w-3 flex-shrink-0" />
        }
        <span className="font-mono text-xs text-blue-700 font-semibold">{name || el.tag}</span>
        {type && <span className="text-xs text-gray-400 font-mono">: {type}</span>}
        {label && <span className="text-xs text-gray-500">— {label}</span>}
      </button>

      {open && (Object.keys(rest).length > 0 || el.children.length > 0) && (
        <div className="px-3 py-2 bg-white flex flex-col gap-1">
          {Object.entries(rest).map(([k, v]) => (
            <div key={k} className="flex gap-2 text-xs">
              <span className="text-gray-400 font-mono w-28 shrink-0">{k}</span>
              <span className="text-gray-700 break-all">{v}</span>
            </div>
          ))}
          {el.children.map((child, i) => <ElementCard key={i} el={child} depth={depth + 1} />)}
        </div>
      )}
    </div>
  )
}
