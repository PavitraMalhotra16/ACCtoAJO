import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getConversionStatus, type ConversionJob } from '../api/migration'

export default function MigrationRunPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const jobId = params.get('job') ?? ''

  const [job, setJob] = useState<ConversionJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!jobId) { setError('No job ID'); return }

    async function poll() {
      try {
        const data = await getConversionStatus(jobId)
        setJob(data)
        if (data.status === 'completed' || data.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch {
        setError('Failed to check status')
        if (pollRef.current) clearInterval(pollRef.current)
      }
    }

    poll()
    pollRef.current = setInterval(poll, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [jobId])

  const done = job?.status === 'completed'
  const progress = job ? Math.round((job.steps.length / job.schema_count) * 100) : 0

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 gap-8 px-6">

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-5 py-3 text-red-700 text-sm">{error}</div>
      )}

      {/* Loading / Running */}
      {!done && !error && (
        <div className="flex flex-col items-center gap-6 w-full max-w-md">
          <svg className="animate-spin w-12 h-12 text-blue-600" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>

          {job?.current_schema ? (
            <div className="text-center">
              <p className="text-xs text-gray-400 uppercase tracking-widest mb-1">Currently converting</p>
              <p className="text-xl font-mono font-semibold text-blue-700">{job.current_schema}</p>
            </div>
          ) : (
            <p className="text-gray-500 text-sm">Starting migration…</p>
          )}

          {job && (
            <>
              {/* Progress bar */}
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-blue-500 h-2 rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="text-sm text-gray-500">
                {job.steps.length} of {job.schema_count} schemas processed
                {job.failed_count > 0 && ` · ${job.failed_count} failed`}
              </p>
            </>
          )}
        </div>
      )}

      {/* Done */}
      {done && job && (
        <div className="flex flex-col items-center gap-4 w-full max-w-md">
          <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center">
            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
            </svg>
          </div>

          <div className="text-center">
            <p className="text-2xl font-bold text-gray-900">Done</p>
            <p className="text-sm text-gray-500 mt-1">
              {job.success_count} schema{job.success_count !== 1 ? 's' : ''} converted and saved
              {job.skipped_count > 0 && <span className="text-gray-400"> · {job.skipped_count} already existed</span>}
              {job.failed_count > 0 && <span className="text-red-500"> · {job.failed_count} failed</span>}
            </p>
          </div>

          {/* Failed list */}
          {job.failed_count > 0 && (
            <div className="w-full bg-red-50 border border-red-200 rounded-xl p-4">
              <p className="text-sm font-medium text-red-700 mb-2">Failed schemas:</p>
              {job.steps.filter(s => s.status === 'failed').map((s, i) => (
                <div key={i} className="text-xs mb-1">
                  <span className="font-mono text-red-800">{s.schemaName}</span>
                  {s.error && <span className="text-red-600"> — {s.error}</span>}
                </div>
              ))}
            </div>
          )}

          <button
            onClick={() => navigate('/')}
            className="px-5 py-2 border border-gray-300 text-gray-700 hover:bg-gray-100 text-sm font-medium rounded-lg"
          >
            Back to Home
          </button>
        </div>
      )}
    </div>
  )
}
