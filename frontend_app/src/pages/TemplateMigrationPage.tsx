import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTemplateCount, extractTemplates } from '../api/templates'

type Step = 'extracting' | 'setup'

export default function TemplateMigrationPage() {
  const navigate = useNavigate()

  // ── Step tracking ──────────────────────────────────────────────────────────
  const [step, setStep] = useState<Step>('extracting')

  // ── Extraction state ───────────────────────────────────────────────────────
  const [total, setTotal] = useState(0)
  const [stored, setStored] = useState(0)
  const [extracting, setExtracting] = useState(true)
  const [extractError, setExtractError] = useState<string | null>(null)
  const stopRef = useRef(false)

  // ── AJO setup state ────────────────────────────────────────────────────────
  const [emailSample, setEmailSample] = useState('')
  const [smsSample, setSmsSample] = useState('')
  const [setupLoading, setSetupLoading] = useState(false)
  const [setupError, setSetupError] = useState<string | null>(null)

  // ── Extraction loop ────────────────────────────────────────────────────────
  useEffect(() => {
    stopRef.current = false
    runExtraction()
    return () => { stopRef.current = true }
  }, [])

  async function runExtraction() {
    try {
      // Get initial counts
      const counts = await getTemplateCount()
      setTotal(counts.total)
      setStored(counts.stored)

      if (counts.to_migrate === 0) {
        setExtracting(false)
        setStep('setup')
        return
      }

      // Batch loop until ACC returns nothing new
      let storedSoFar = counts.stored
      while (!stopRef.current) {
        const result = await extractTemplates()
        if (result.total_found === 0) break
        storedSoFar += result.extracted
        setStored(storedSoFar)
        if (result.total_found < 50) break // last page — done
      }

      setExtracting(false)
      if (!stopRef.current) setStep('setup')
    } catch (err: unknown) {
      setExtractError(err instanceof Error ? err.message : 'Extraction failed')
      setExtracting(false)
    }
  }

  // ── AJO setup submit ───────────────────────────────────────────────────────
  async function handleSetup(e: React.FormEvent) {
    e.preventDefault()
    setSetupError(null)
    setSetupLoading(true)
    try {
      const res = await fetch('/api/templates/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          email_sample_name: emailSample.trim(),
          sms_sample_name: smsSample.trim(),
        }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(d.detail || `Error ${res.status}`)
      }
      navigate('/migration/template/analysis')
    } catch (err: unknown) {
      setSetupError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setSetupLoading(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  const pct = total > 0 ? Math.round((stored / total) * 100) : 0

  return (
    <div className="min-h-screen bg-gray-50 px-6 py-8">
      <div className="max-w-2xl mx-auto">
        <button
          onClick={() => navigate('/migration/type')}
          className="text-sm text-gray-500 hover:text-gray-800 mb-6 transition-colors"
        >
          ← Back
        </button>

        <h1 className="text-2xl font-bold text-gray-900 mb-6">Migrate Delivery Templates</h1>

        {/* ── Step 1: Extraction ── */}
        <div className={`bg-white rounded-lg border p-6 mb-4 ${step === 'extracting' ? 'border-blue-300' : 'border-gray-200'}`}>
          <div className="flex items-center gap-3 mb-4">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold ${step === 'setup' ? 'bg-green-500 text-white' : 'bg-blue-600 text-white'}`}>
              {step === 'setup' ? '✓' : '1'}
            </div>
            <h2 className="font-semibold text-gray-800">Extract templates from ACC</h2>
          </div>

          {extractError ? (
            <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded-lg p-3">
              {extractError}
            </div>
          ) : step === 'setup' ? (
            <p className="text-sm text-green-700">{stored} template{stored !== 1 ? 's' : ''} extracted and ready.</p>
          ) : (
            <>
              <p className="text-sm text-gray-500 mb-3">
                {extracting
                  ? `Fetching templates from ACC… ${stored}${total > 0 ? ` / ${total}` : ''} stored`
                  : `${stored} template${stored !== 1 ? 's' : ''} extracted.`}
              </p>
              {total > 0 && (
                <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
                  <div
                    className="h-2 rounded-full bg-blue-500 transition-all duration-500"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              )}
              {extracting && (
                <p className="text-xs text-gray-400 mt-2 animate-pulse">This may take a moment for large sets…</p>
              )}
            </>
          )}
        </div>

        {/* ── Step 2: AJO folder setup ── */}
        <div className={`bg-white rounded-lg border p-6 transition-opacity ${step === 'setup' ? 'border-blue-300 opacity-100' : 'border-gray-200 opacity-40 pointer-events-none'}`}>
          <div className="flex items-center gap-3 mb-4">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold ${step === 'setup' ? 'bg-blue-600 text-white' : 'bg-gray-300 text-gray-600'}`}>
              2
            </div>
            <h2 className="font-semibold text-gray-800">Set up AJO destination folders</h2>
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 text-xs text-blue-900">
            <p className="font-semibold mb-1">Instructions:</p>
            <ol className="list-decimal list-inside space-y-0.5">
              <li>In AJO, open <strong>Content Templates</strong>.</li>
              <li>Create a folder for Email and one for SMS.</li>
              <li>Inside each, create one sample template with a name you'll remember.</li>
              <li>Enter those exact names below.</li>
            </ol>
          </div>

          <form onSubmit={handleSetup} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Email sample template name
              </label>
              <input
                type="text"
                value={emailSample}
                onChange={e => setEmailSample(e.target.value)}
                placeholder="e.g. email sample"
                required
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                SMS sample template name
              </label>
              <input
                type="text"
                value={smsSample}
                onChange={e => setSmsSample(e.target.value)}
                placeholder="e.g. sms sample"
                required
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {setupError && (
              <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded-lg p-3">
                {setupError}
              </div>
            )}

            <button
              type="submit"
              disabled={setupLoading || !emailSample.trim() || !smsSample.trim()}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-medium py-2 px-4 rounded-lg text-sm transition-colors flex items-center justify-center gap-2"
            >
              {setupLoading && (
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              {setupLoading ? 'Verifying…' : 'Verify & Continue →'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
