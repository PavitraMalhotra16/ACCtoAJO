import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTemplateCount, getStoredCount, extractTemplates } from '../api/templates'

type Step = 'extracting' | 'setup'

interface FolderConfig {
  configured: boolean
  email_folder_name?: string
  sms_folder_name?: string
  email_folder_id?: string
  sms_folder_id?: string
}

export default function TemplateMigrationPage() {
  const navigate = useNavigate()

  // ── Step tracking ──────────────────────────────────────────────────────────
  const [step, setStep] = useState<Step>('extracting')

  // ── Extraction state ───────────────────────────────────────────────────────
  const [stored, setStored] = useState(0)
  const [extractError, setExtractError] = useState<string | null>(null)
  const stopRef = useRef(false)

  // ── AJO setup state ────────────────────────────────────────────────────────
  const [folderConfig, setFolderConfig] = useState<FolderConfig | null>(null)
  const [renaming, setRenaming] = useState(false)
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

  async function runExtraction(forceRefresh = false) {
    try {
      if (forceRefresh) {
        await fetch('/api/templates/stored', { method: 'DELETE', credentials: 'include' })
      } else {
        // Fast path: check DB only first — avoids a slow SOAP round-trip to ACC
        const quick = await getStoredCount()
        if (quick.stored > 0) {
          setStored(quick.stored)
          if (!stopRef.current) {
            await loadFolderConfig()
            setStep('setup')
          }
          return
        }
      }

      const counts = await getTemplateCount()
      setStored(counts.stored)

      // If everything is already stored, skip extraction
      if (counts.to_migrate === 0) {
        if (!stopRef.current) {
          await loadFolderConfig()
          setStep('setup')
        }
        return
      }

      while (!stopRef.current) {
        const result = await extractTemplates()
        if (result.total_found === 0) break
        if (result.total_found < 50) break
      }

      // Read the final count from DB once — avoids any race from double-invocations.
      const final = await getStoredCount()
      setStored(final.stored)
      if (!stopRef.current) {
        await loadFolderConfig()
        setStep('setup')
      }
    } catch (err: unknown) {
      setExtractError(err instanceof Error ? err.message : 'Extraction failed')
    }
  }

  async function loadFolderConfig() {
    try {
      const res = await fetch('/api/templates/folder-config', { credentials: 'include' })
      if (res.ok) {
        const cfg: FolderConfig = await res.json()
        setFolderConfig(cfg)
        if (cfg.configured) {
          setEmailSample(cfg.email_folder_name ?? '')
          setSmsSample(cfg.sms_folder_name ?? '')
        }
      }
    } catch {
      // non-fatal — just show the form
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
  const alreadyConfigured = folderConfig?.configured && !renaming

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
            <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded-lg p-3">{extractError}</div>
          ) : step === 'setup' ? (
            <div className="flex items-center justify-between">
              <p className="text-sm text-green-700">{stored} template{stored !== 1 ? 's' : ''} extracted and ready.</p>
              <button
                onClick={() => {
                  setStep('extracting')
                  setExtractError(null)
                  stopRef.current = false
                  runExtraction(true)
                }}
                className="text-xs text-gray-400 hover:text-gray-600 underline"
              >
                Re-extract
              </button>
            </div>
          ) : (
            <p className="text-sm text-gray-500 animate-pulse">Extraction in progress…</p>
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

          {/* Already configured — show summary + options */}
          {alreadyConfigured ? (
            <div>
              <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
                <p className="text-sm font-medium text-green-800 mb-2">✓ Folders already configured</p>
                <div className="text-sm text-green-700 space-y-1">
                  <div className="flex justify-between">
                    <span className="text-gray-500">Email folder</span>
                    <span className="font-medium">{folderConfig?.email_folder_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">SMS folder</span>
                    <span className="font-medium">{folderConfig?.sms_folder_name}</span>
                  </div>
                </div>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={() => navigate('/migration/template/analysis')}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-lg text-sm transition-colors"
                >
                  Continue →
                </button>
                <button
                  onClick={() => setRenaming(true)}
                  className="px-4 py-2 text-sm text-gray-600 border border-gray-300 hover:border-gray-400 rounded-lg transition-colors"
                >
                  Rename folders
                </button>
              </div>
            </div>
          ) : (
            /* Not configured or renaming — show the form */
            <>
              {renaming && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4 text-xs text-amber-800">
                  Entering new names will overwrite the existing folder configuration.
                </div>
              )}

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
                  <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded-lg p-3">{setupError}</div>
                )}

                <div className="flex gap-3">
                  <button
                    type="submit"
                    disabled={setupLoading || !emailSample.trim() || !smsSample.trim()}
                    className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-medium py-2 px-4 rounded-lg text-sm transition-colors flex items-center justify-center gap-2"
                  >
                    {setupLoading && (
                      <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                    )}
                    {setupLoading ? 'Verifying…' : 'Verify & Continue →'}
                  </button>
                  {renaming && (
                    <button
                      type="button"
                      onClick={() => { setRenaming(false); setSetupError(null) }}
                      className="px-4 py-2 text-sm text-gray-600 border border-gray-300 hover:border-gray-400 rounded-lg transition-colors"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
