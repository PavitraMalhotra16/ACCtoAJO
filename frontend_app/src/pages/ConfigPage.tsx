import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AccPanel from '../components/AccPanel'
import AjoPanel from '../components/AjoPanel'
import { useConfigStore } from '../store/configStore'
import { getAccStatus, getAjoStatus } from '../api/client'

export default function ConfigPage() {
  const navigate = useNavigate()
  const { accConnected, ajoConnected, setAccConnected, setAccDisconnected, setAjoConnected } = useConfigStore()
  const [migrating, setMigrating] = useState(false)
  const [migrateError, setMigrateError] = useState<string | null>(null)

  async function handleMigrate() {
    setMigrating(true); setMigrateError(null)
    try {
      const res = await fetch('/api/convert/start-all', {
        method: 'POST', credentials: 'include',
      })
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed') }
      const data = await res.json()
      if (data.message === 'all_done') {
        setMigrateError(`All ${data.total} schemas are already converted. Nothing left to migrate.`)
        setMigrating(false)
        return
      }
      navigate(`/migration/run?job=${data.job_id}`)
    } catch (e: unknown) {
      setMigrateError(e instanceof Error ? e.message : 'Failed to start migration')
      setMigrating(false)
    }
  }

  useEffect(() => {
    // Always verify against backend on mount.
    // Zustand persist handles the optimistic UI (instant render),
    // backend call corrects it if session expired or credentials changed.
    getAccStatus().then(s => {
      if (s.connected && s.login) {
        setAccConnected(s.login)
      } else {
        setAccDisconnected()
      }
    }).catch(() => setAccDisconnected())

    getAjoStatus().then(s => {
      if (s.connected && s.org_id && s.sandbox_name) setAjoConnected(s.org_id, s.sandbox_name)
    })
  }, [])

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-5xl flex flex-col gap-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900">ACC → AJO Migration Tool</h1>
          <p className="mt-2 text-gray-500">Configure your source and destination connections to get started</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <AccPanel />
          <AjoPanel />
        </div>

        <div className="flex gap-3 justify-center">
          {accConnected && (
            <button
              onClick={() => navigate('/schemas')}
              className="px-6 py-2.5 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100 font-medium transition-colors"
            >
              View ACC Schemas
            </button>
          )}
          {accConnected && (
            <button
              onClick={() => navigate('/inspect')}
              className="px-6 py-2.5 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100 font-medium transition-colors"
            >
              Schema Inspector
            </button>
          )}
          <button
            onClick={handleMigrate}
            disabled={!accConnected || !ajoConnected || migrating}
            className="px-6 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-medium transition-colors flex items-center gap-2"
          >
            {migrating ? (
              <>
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                Starting…
              </>
            ) : 'Migrate'}
          </button>
          {migrateError && (
            <p className={`text-sm ${migrateError.includes('already converted') ? 'text-green-600' : 'text-red-600'}`}>
              {migrateError}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
