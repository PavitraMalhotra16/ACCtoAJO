import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import AccPanel from '../components/AccPanel'
import AjoPanel from '../components/AjoPanel'
import { useConfigStore } from '../store/configStore'
import { getAccStatus, getAjoStatus } from '../api/client'

export default function ConfigPage() {
  const navigate = useNavigate()
  const { accConnected, ajoConnected, setAccConnected, setAjoConnected } = useConfigStore()

  useEffect(() => {
    getAccStatus().then(s => { if (s.connected && s.login) setAccConnected(s.login) })
    getAjoStatus().then(s => { if (s.connected && s.org_id && s.sandbox_name) setAjoConnected(s.org_id, s.sandbox_name) })
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
          <button
            onClick={() => navigate('/migration')}
            disabled={!accConnected || !ajoConnected}
            className="px-6 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-medium transition-colors"
          >
            Proceed to Migration
          </button>
        </div>
      </div>
    </div>
  )
}
