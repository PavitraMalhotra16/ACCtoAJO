import { useState } from 'react'
import { ajoConnect, getAjoStatus } from '../api/client'
import { useConfigStore } from '../store/configStore'

export default function AjoPanel() {
  const [orgId, setOrgId] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [sandboxName, setSandboxName] = useState('')
  const [loading, setLoading] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { ajoConnected, ajoOrgId, ajoSandboxName, setAjoConnected, setAjoDisconnected } = useConfigStore()

  async function handleConnect() {
    setLoading(true)
    setError(null)
    try {
      await ajoConnect(orgId, clientId, clientSecret, sandboxName)
      setAjoConnected(orgId, sandboxName)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Connection failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleReconnect() {
    setReconnecting(true)
    setError(null)
    try {
      const status = await getAjoStatus()
      if (status.connected && status.org_id && status.sandbox_name) {
        setAjoConnected(status.org_id, status.sandbox_name)
      } else {
        setError('No saved credentials found')
      }
    } catch {
      setError('Reconnect failed')
    } finally {
      setReconnecting(false)
    }
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-sm">AJO</div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Adobe Journey Optimizer</h2>
          <p className="text-sm text-gray-500">Connect via IMS service credentials</p>
        </div>
      </div>

      {ajoConnected ? (
        <>
          <div className="flex items-center gap-2 text-green-600 bg-green-50 rounded-lg px-4 py-3">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <span className="font-medium">Connected · <strong>{ajoOrgId}</strong> / <strong>{ajoSandboxName}</strong></span>
          </div>
          <button
            onClick={setAjoDisconnected}
            className="w-full border border-red-300 text-red-600 hover:bg-red-50 font-medium py-2 px-4 rounded-lg transition-colors"
          >
            Disconnect
          </button>
        </>
      ) : (
        <>
          {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
          <button
            onClick={handleReconnect}
            disabled={reconnecting}
            className="w-full border border-blue-300 text-blue-600 hover:bg-blue-50 font-medium py-2 px-4 rounded-lg transition-colors"
          >
            {reconnecting ? 'Reconnecting...' : 'Reconnect with saved credentials'}
          </button>
          <div className="relative flex items-center gap-2">
            <div className="flex-1 border-t border-gray-200" />
            <span className="text-xs text-gray-400">or enter new credentials</span>
            <div className="flex-1 border-t border-gray-200" />
          </div>
          <div className="flex flex-col gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Org ID</label>
              <input
                type="text"
                value={orgId}
                onChange={e => setOrgId(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="XXXXXXXX@AdobeOrg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Client ID</label>
              <input
                type="text"
                value={clientId}
                onChange={e => setClientId(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="your-client-id"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Client Secret</label>
              <input
                type="password"
                value={clientSecret}
                onChange={e => setClientSecret(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="••••••••"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Sandbox Name</label>
              <input
                type="text"
                value={sandboxName}
                onChange={e => setSandboxName(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="prod"
              />
            </div>
            <button
              onClick={handleConnect}
              disabled={loading || !orgId || !clientId || !clientSecret || !sandboxName}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white font-medium py-2 px-4 rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  Connecting...
                </>
              ) : 'Connect'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
