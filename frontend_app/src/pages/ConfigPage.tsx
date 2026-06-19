import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import AccPanel from '../components/AccPanel'
import AjoPanel from '../components/AjoPanel'
import { useConfigStore } from '../store/configStore'
import { getAccStatus, getAjoStatus } from '../api/client'
import { listMigrationJobs, getMigrationStatus } from '../api/migration'

export default function ConfigPage() {
  const navigate = useNavigate()
  const { accConnected, ajoConnected, setAccConnected, setAccDisconnected, setAjoConnected } = useConfigStore()

  useEffect(() => {
    getAccStatus().then(s => {
      if (s.connected && s.login) setAccConnected(s.login)
      else setAccDisconnected()
    }).catch(() => setAccDisconnected())

    getAjoStatus().then(s => {
      if (s.connected && s.org_id && s.sandbox_name) setAjoConnected(s.org_id, s.sandbox_name)
    })

    // Resume active migration job if one is in progress
    listMigrationJobs().then(async ({ jobs }) => {
      if (!jobs.length) return
      const latest = jobs[0]
      const status = await getMigrationStatus(latest.job_id)
      if (status.running > 0 || status.queued > 0) {
        navigate(`/migration/run?migrate_job=${latest.job_id}`)
      }
    }).catch(() => {/* not authenticated yet, ignore */})
  }, [])

  function handleMigrate() {
    navigate('/migration/select')
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
            disabled={!accConnected || !ajoConnected}
            className="px-8 py-3 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-semibold text-base transition-colors"
          >
            Migrate →
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
        </div>
      </div>
    </div>
  )
}
