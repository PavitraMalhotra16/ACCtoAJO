import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSchemas } from '../api/client'

interface Schema {
  namespace: string
  name: string
  label: string
  labelSingular: string
}

export default function SchemasPage() {
  const navigate = useNavigate()
  const [schemas, setSchemas] = useState<Schema[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSchemas()
      .then(data => setSchemas(data.schemas))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen px-4 py-12">
      <div className="max-w-5xl mx-auto flex flex-col gap-6">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/')} className="text-sm text-gray-500 hover:text-gray-800 flex items-center gap-1">
            ← Back to Configuration
          </button>
        </div>
        <h1 className="text-2xl font-bold text-gray-900">ACC Schemas</h1>

        {loading && (
          <div className="flex items-center justify-center py-20">
            <svg className="animate-spin w-8 h-8 text-red-600" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700">{error}</div>
        )}

        {!loading && !error && (
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Namespace</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Name</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Label</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {schemas.map((s, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">{s.namespace}</td>
                    <td className="px-4 py-3 font-mono text-xs">{s.name}</td>
                    <td className="px-4 py-3 text-gray-800">{s.label || s.labelSingular || '—'}</td>
                  </tr>
                ))}
                {schemas.length === 0 && (
                  <tr><td colSpan={3} className="px-4 py-8 text-center text-gray-400">No schemas found</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
