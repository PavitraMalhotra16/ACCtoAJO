import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AccPanel from '../components/AccPanel'
import AjoPanel from '../components/AjoPanel'
import { useConfigStore } from '../store/configStore'
import { getAccStatus, getAjoStatus } from '../api/client'
import { startMigration } from '../api/migration'

export default function ConfigPage() {
  const navigate = useNavigate()
  const { accConnected, ajoConnected, setAccConnected, setAccDisconnected, setAjoConnected } = useConfigStore()
  const [migrating, setMigrating] = useState(false)
  const [migrateError, setMigrateError] = useState<string | null>(null)

  useEffect(() => {
    getAccStatus().then(s => {
      if (s.connected && s.login) setAccConnected(s.login)
      else setAccDisconnected()
    }).catch(() => setAccDisconnected())

    getAjoStatus().then(s => {
      if (s.connected && s.org_id && s.sandbox_name) setAjoConnected(s.org_id, s.sandbox_name)
    })
  }, [])

  async function handleMigrate() {
    setMigrating(true)
    setMigrateError(null)
    try {
      const data = await startMigration()
      if (data.message === 'all_done') {
        setMigrateError(`All ${data.total} schemas are already migrated.`)
        return
      }
      navigate(`/migration/run?job=${data.job_id}`)
    } catch (e: unknown) {
      setMigrateError(e instanceof Error ? e.message : 'Failed to start migration')
    } finally {
      setMigrating(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-5xl flex flex-col gap-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900">ACC → AJO Migration Tool</h1>
          <p className="mt-2 text-gray-500">Connect your source and destination, then migrate</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <AccPanel />
          <AjoPanel />
        </div>

        <div className="flex flex-col items-center gap-3">
          <button
            onClick={handleMigrate}
            disabled={!accConnected || !ajoConnected || migrating}
            className="px-8 py-3 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-semibold text-base transition-colors flex items-center gap-2"
          >
            {migrating ? (
              <>
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                Starting…
              </>
            ) : 'Migrate →'}
          </button>

          {!accConnected && !ajoConnected && (
            <p className="text-xs text-gray-400">Connect both ACC and AJO to enable migration</p>
          )}
          {accConnected && !ajoConnected && (
            <p className="text-xs text-gray-400">Connect AJO to enable migration</p>
          )}
          {!accConnected && ajoConnected && (
            <p className="text-xs text-gray-400">Connect ACC to enable migration</p>
          )}

          {migrateError && (
            <p className={`text-sm ${migrateError.includes('already migrated') ? 'text-green-600' : 'text-red-600'}`}>
              {migrateError}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
