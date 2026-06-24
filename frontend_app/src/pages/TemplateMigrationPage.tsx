import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { extractTemplates, getStoredCount, getTemplateCount } from '../api/templates'

type Phase = 'counting' | 'extracting' | 'done' | 'nothing' | 'error'

export default function TemplateMigrationPage() {
  const navigate = useNavigate()
  const [phase, setPhase]             = useState<Phase>('counting')
  const [total, setTotal]             = useState(0)
  const [stored, setStored]           = useState(0)
  const [totalExtracted, setTotalExtracted] = useState(0)
  const [errorMsg, setErrorMsg]       = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const ranRef = useRef(false)

  useEffect(() => {
    if (ranRef.current) return
    ranRef.current = true

    async function run() {
      // Step 1 — get total count from ACC (minus already stored)
      let accTotal = 0
      try {
        const { to_migrate } = await getTemplateCount()
        accTotal = to_migrate
        setTotal(to_migrate)
      } catch (e: unknown) {
        setErrorMsg(e instanceof Error ? e.message : 'Failed to count templates')
        setPhase('error')
        return
      }

      // Step 2 — start polling stored count every 2s
      setPhase('extracting')
      pollRef.current = setInterval(async () => {
        try {
          const { stored: s } = await getStoredCount()
          setStored(s)
        } catch {
          // silent — extraction may still be running
        }
      }, 2000)

      // Step 3 — loop extraction batch by batch until ACC returns nothing
      let totalExtracted = 0
      try {
        while (true) {
          const result = await extractTemplates()

          if (result.total_found === 0) {
            // ACC returned empty — nothing left to fetch
            break
          }

          totalExtracted += result.extracted

          if (result.extracted < result.total_found) {
            // Partial batch (last page) — we're done
            break
          }
        }
      } catch (e: unknown) {
        setErrorMsg(e instanceof Error ? e.message : 'Extraction failed')
        setPhase('error')
        return
      } finally {
        if (pollRef.current) clearInterval(pollRef.current)
      }

      setTotalExtracted(totalExtracted)

      if (totalExtracted === 0 && accTotal === 0) {
        setPhase('nothing')
        return
      }

      setPhase('done')
    }

    run()
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const progress = total > 0 ? Math.min(Math.round((stored / total) * 100), 100) : 0

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 px-6">

      {/* Error */}
      {phase === 'error' && (
        <div className="flex flex-col items-center gap-4 max-w-sm text-center">
          <div className="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center">
            <svg className="w-8 h-8 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <p className="text-gray-800 font-semibold">Something went wrong</p>
          <p className="text-sm text-red-600">{errorMsg}</p>
          <button
            onClick={() => navigate('/migration/type')}
            className="text-sm text-gray-500 hover:text-gray-800 mt-2 transition-colors"
          >
            ← Back
          </button>
        </div>
      )}

      {/* Counting / Extracting */}
      {(phase === 'counting' || phase === 'extracting') && (
        <div className="flex flex-col items-center gap-6 w-full max-w-sm">
          <svg className="animate-spin w-14 h-14 text-purple-600" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>

          {phase === 'counting' && (
            <p className="text-gray-500 text-sm">Fetching template count from ACC…</p>
          )}

          {phase === 'extracting' && (
            <>
              <div className="text-center">
                <p className="text-4xl font-bold text-purple-700 tabular-nums">
                  {stored}
                  <span className="text-xl text-gray-400 font-normal"> / {total}</span>
                </p>
                <p className="text-sm text-gray-500 mt-1">templates stored in database</p>
              </div>

              <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                <div
                  className="bg-purple-500 h-2 rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="text-xs text-gray-400">{progress}% complete</p>
            </>
          )}
        </div>
      )}

      {/* Nothing to migrate */}
      {phase === 'nothing' && (
        <div className="flex flex-col items-center gap-5 max-w-sm text-center">
          <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center">
            <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div>
            <p className="text-xl font-bold text-gray-900">No templates to migrate</p>
            <p className="text-sm text-gray-500 mt-1">All templates are already stored in the database.</p>
          </div>
          <button
            onClick={() => navigate('/migration/type')}
            className="mt-2 px-5 py-2 border border-gray-300 text-gray-700 hover:bg-gray-100 text-sm font-medium rounded-lg transition-colors"
          >
            ← Back to Migration
          </button>
        </div>
      )}

      {/* Done */}
      {phase === 'done' && (
        <div className="flex flex-col items-center gap-5 max-w-sm text-center">
          <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center">
            <svg className="w-9 h-9 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div>
            <p className="text-2xl font-bold text-gray-900">Done</p>
            <p className="text-sm text-gray-500 mt-1">
              {totalExtracted} template{totalExtracted !== 1 ? 's' : ''} extracted and stored in database
            </p>
          </div>
          <button
            onClick={() => navigate('/migration/type')}
            className="mt-2 px-5 py-2 border border-gray-300 text-gray-700 hover:bg-gray-100 text-sm font-medium rounded-lg transition-colors"
          >
            ← Back to Migration
          </button>
        </div>
      )}
    </div>
  )
}
