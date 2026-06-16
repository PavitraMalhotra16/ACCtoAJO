import { useState } from 'react'
import { accConnect, accDisconnect } from '../api/client'
import { useConfigStore } from '../store/configStore'

type AuthMode = 'classic' | 'technical'

export default function AccPanel() {
  const [mode, setMode] = useState<AuthMode>('classic')

  // Classic fields
  const [instanceUrl, setInstanceUrl] = useState('http://localhost:8080')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')

  // Technical account fields
  const [techInstanceUrl, setTechInstanceUrl] = useState('')
  const [orgId, setOrgId] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [scope, setScope] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { accConnected, accLogin, setAccConnected, setAccDisconnected } = useConfigStore()

  async function handleConnect() {
    setLoading(true)
    setError(null)
    try {
      if (mode === 'classic') {
        await accConnect({ auth_type: 'classic', instance_url: instanceUrl, login, password })
        setAccConnected(login)
      } else {
        await accConnect({ auth_type: 'technical', instance_url: techInstanceUrl, org_id: orgId, client_id: clientId, client_secret: clientSecret, scope })
        setAccConnected(clientId)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Connection failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleDisconnect() {
    await accDisconnect()
    setAccDisconnected()
  }

  const classicValid = instanceUrl && login && password
  const technicalValid = techInstanceUrl && orgId && clientId && clientSecret && scope
  const canConnect = mode === 'classic' ? classicValid : technicalValid

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-red-600 flex items-center justify-center text-white font-bold text-sm">ACC</div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Adobe Campaign Classic</h2>
          <p className="text-sm text-gray-500">Connect via SOAP</p>
        </div>
      </div>

      {accConnected ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-green-600 bg-green-50 rounded-lg px-4 py-3">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <span className="font-medium">Connected as <strong>{accLogin}</strong></span>
          </div>
          <button onClick={handleDisconnect} className="text-sm text-gray-500 hover:text-red-600 underline text-center transition-colors">
            Disconnect &amp; reconnect
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-4">

          {/* Mode toggle */}
          <div className="flex bg-gray-100 rounded-lg p-1 gap-1">
            {(['classic', 'technical'] as AuthMode[]).map(m => (
              <button
                key={m}
                onClick={() => { setMode(m); setError(null) }}
                className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  mode === m ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {m === 'classic' ? 'Classic (Local)' : 'Technical Account (IMS)'}
              </button>
            ))}
          </div>

          {mode === 'classic' ? (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Instance URL</label>
                <input type="text" value={instanceUrl} onChange={e => setInstanceUrl(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                  placeholder="http://localhost:8080" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Login</label>
                <input type="text" value={login} onChange={e => setLogin(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                  placeholder="admin" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                  placeholder="••••••••" />
              </div>
            </>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Instance URL</label>
                <input type="text" value={techInstanceUrl} onChange={e => setTechInstanceUrl(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                  placeholder="https://your-instance.campaign.adobe.com" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Org ID</label>
                <input type="text" value={orgId} onChange={e => setOrgId(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                  placeholder="XXXXXXXX@AdobeOrg" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Client ID</label>
                <input type="text" value={clientId} onChange={e => setClientId(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                  placeholder="your-client-id" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Client Secret</label>
                <input type="password" value={clientSecret} onChange={e => setClientSecret(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                  placeholder="••••••••" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Scope</label>
                <input type="text" value={scope} onChange={e => setScope(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                  placeholder="openid,AdobeID,campaign" />
              </div>
            </>
          )}

          {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

          <button onClick={handleConnect} disabled={loading || !canConnect}
            className="w-full bg-red-600 hover:bg-red-700 disabled:bg-gray-300 text-white font-medium py-2 px-4 rounded-lg transition-colors flex items-center justify-center gap-2">
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
      )}
    </div>
  )
}
