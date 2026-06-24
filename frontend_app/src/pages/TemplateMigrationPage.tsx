import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function TemplateMigrationPage() {
  const navigate = useNavigate()
  const [emailSample, setEmailSample] = useState('')
  const [smsSample, setSmsSample] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
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
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `Error ${res.status}`)
      }
      navigate('/migration/template/analysis')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 px-6 py-8">
      <div className="max-w-2xl mx-auto">
        <button
          onClick={() => navigate('/migration/type')}
          className="text-sm text-gray-500 hover:text-gray-800 mb-6 transition-colors"
        >
          ← Back
        </button>

        <h1 className="text-2xl font-bold text-gray-900 mb-2">Migrate Delivery Templates</h1>
        <p className="text-gray-500 text-sm mb-6">
          Before migrating, you need to set up destination folders in AJO.
        </p>

        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6 text-sm text-blue-900">
          <p className="font-semibold mb-2">Setup instructions:</p>
          <ol className="list-decimal list-inside space-y-1">
            <li>In AJO, open <strong>Content Templates</strong>.</li>
            <li>Create a folder for email templates and one for SMS templates.</li>
            <li>Inside each folder, create one sample template with a name you'll remember.</li>
            <li>Enter those exact sample template names below.</li>
          </ol>
        </div>

        <form onSubmit={handleSubmit} className="bg-white rounded-lg border border-gray-200 p-6 space-y-4">
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
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
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
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
            />
          </div>

          {error && (
            <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded-lg p-3">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !emailSample.trim() || !smsSample.trim()}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-medium py-2 px-4 rounded-lg text-sm transition-colors flex items-center justify-center gap-2"
          >
            {loading && (
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {loading ? 'Verifying…' : 'Verify & Continue'}
          </button>
        </form>
      </div>
    </div>
  )
}
