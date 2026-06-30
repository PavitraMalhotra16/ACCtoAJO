// frontend_app/src/pages/DatasetIngestPage.tsx
import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { getDatasetSchemas, ingestDataset, DatasetSchema, IngestStep } from '../api/datasets'

const STEP_LABELS: Record<string, string> = {
  CREATE_BATCH: 'Create batch',
  UPLOAD_FILE: 'Upload file',
  COMPLETE_BATCH: 'Complete batch',
}

function StepIcon({ status }: { status: IngestStep['status'] }) {
  if (status === 'COMPLETED') return (
    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-green-100">
      <svg className="h-4 w-4 text-green-600" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
      </svg>
    </span>
  )
  if (status === 'FAILED') return (
    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-red-100">
      <svg className="h-4 w-4 text-red-600" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
      </svg>
    </span>
  )
  return (
    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gray-100">
      <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14" />
      </svg>
    </span>
  )
}

export default function DatasetIngestPage() {
  const navigate = useNavigate()
  const [schemas, setSchemas] = useState<DatasetSchema[]>([])
  const [schemasLoading, setSchemasLoading] = useState(true)
  const [schemasError, setSchemasError] = useState<string | null>(null)
  const [selectedSchema, setSelectedSchema] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [allSteps, setAllSteps] = useState<IngestStep[] | null>(null)
  const [visibleCount, setVisibleCount] = useState(0)
  const [finalStatus, setFinalStatus] = useState<'SUCCESS' | 'FAILED' | null>(null)
  const animTimers = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => {
    getDatasetSchemas()
      .then(data => {
        setSchemas(data.slice().sort((a, b) => a.schema_name.localeCompare(b.schema_name)))
      })
      .catch(err => setSchemasError(err.message))
      .finally(() => setSchemasLoading(false))
  }, [])

  useEffect(() => {
    if (!allSteps) return
    animTimers.current.forEach(clearTimeout)
    animTimers.current = []
    allSteps.forEach((_, i) => {
      const t = setTimeout(() => setVisibleCount(i + 1), i * 200)
      animTimers.current.push(t)
    })
    return () => animTimers.current.forEach(clearTimeout)
  }, [allSteps])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!file || !selectedSchema) return
    setLoading(true)
    setError(null)
    setAllSteps(null)
    setVisibleCount(0)
    setFinalStatus(null)
    try {
      const result = await ingestDataset(selectedSchema, file)
      setAllSteps(result.steps)
      setFinalStatus(result.status)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  function reset() {
    setSelectedSchema('')
    setFile(null)
    setAllSteps(null)
    setVisibleCount(0)
    setFinalStatus(null)
    setError(null)
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg flex flex-col gap-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Upload Dataset</h1>
          <p className="mt-1 text-sm text-gray-500">
            Ingest a CSV, JSON, or Parquet file into an AEP dataset
          </p>
        </div>

        {/* ── Form view ── */}
        {!allSteps && !loading && (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* Schema picker */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Schema</label>
              {schemasLoading ? (
                <p className="text-sm text-gray-400">Loading schemas…</p>
              ) : schemasError ? (
                <p className="text-sm text-red-600">{schemasError}</p>
              ) : schemas.length === 0 ? (
                <p className="text-sm text-amber-600">
                  No migrated schemas found — run a schema migration first.
                </p>
              ) : (
                <select
                  value={selectedSchema}
                  onChange={e => setSelectedSchema(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
                >
                  <option value="">Select a schema</option>
                  {schemas.map(s => (
                    <option key={s.schema_name} value={s.schema_name}>
                      {s.schema_name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* File picker */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                File{' '}
                <span className="text-gray-400 font-normal">(CSV, JSON, Parquet — max 256 MB)</span>
              </label>
              <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 hover:border-green-400 px-6 py-8 text-center transition-colors">
                <svg className="mb-2 h-8 w-8 text-gray-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
                </svg>
                {file ? (
                  <span className="text-sm font-medium text-gray-700">{file.name}</span>
                ) : (
                  <span className="text-sm text-gray-500">Click to select file</span>
                )}
                <input
                  type="file"
                  accept=".csv,.json,.parquet"
                  className="sr-only"
                  onChange={e => setFile(e.target.files?.[0] ?? null)}
                />
              </label>
            </div>

            {error && (
              <p className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={!file || !selectedSchema}
              className="w-full rounded-lg bg-green-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Upload
            </button>
          </form>
        )}

        {/* ── Loading spinner ── */}
        {loading && (
          <div className="flex flex-col items-center gap-3 py-8">
            <svg className="h-8 w-8 animate-spin text-green-600" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z" />
            </svg>
            <p className="text-sm text-gray-500">Uploading…</p>
          </div>
        )}

        {/* ── Step results ── */}
        {allSteps && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-3">
              {allSteps.slice(0, visibleCount).map(step => (
                <div
                  key={step.name}
                  className="flex items-start gap-3 rounded-lg border border-gray-100 bg-white p-3 shadow-sm"
                >
                  <StepIcon status={step.status} />
                  <div>
                    <p className="text-sm font-medium text-gray-800">
                      {STEP_LABELS[step.name] ?? step.name}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">{step.detail}</p>
                  </div>
                </div>
              ))}
            </div>

            {visibleCount === allSteps.length && finalStatus && (
              <div className={`rounded-lg px-4 py-3 text-sm font-medium ${
                finalStatus === 'SUCCESS'
                  ? 'bg-green-50 border border-green-200 text-green-800'
                  : 'bg-red-50 border border-red-200 text-red-800'
              }`}>
                {finalStatus === 'SUCCESS'
                  ? '✓ Upload complete — ingestion queued in AEP'
                  : '✗ Upload failed — see step details above'}
              </div>
            )}

            <button
              onClick={reset}
              className="text-sm text-gray-400 hover:text-gray-600 transition-colors text-center"
            >
              ← Upload another file
            </button>
          </div>
        )}

        {!allSteps && !loading && (
          <div className="flex justify-center">
            <button
              onClick={() => navigate('/migration/type')}
              className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
            >
              ← Back
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
