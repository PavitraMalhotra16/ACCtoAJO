const BASE = ''  // proxied via vite

export async function accConnect(login: string, password: string) {
  const res = await fetch(`${BASE}/api/acc/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login, password }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Connection failed')
  }
  return res.json()
}

export async function ajoConnect(orgId: string, clientId: string, clientSecret: string, sandboxName: string) {
  const res = await fetch(`${BASE}/api/ajo/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ org_id: orgId, client_id: clientId, client_secret: clientSecret, sandbox_name: sandboxName }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Connection failed')
  }
  return res.json()
}

export async function getSchemas(): Promise<{ schemas: Array<{ namespace: string; name: string; label: string; labelSingular: string }> }> {
  const res = await fetch(`${BASE}/api/acc/schemas`)
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Failed to fetch schemas')
  }
  return res.json()
}

export async function getConnectionsStatus(): Promise<{
  sourceAuthenticated: boolean
  destinationAuthenticated: boolean
  sourceLoginId: string | null
  destinationOrgId: string | null
  destinationSandboxName: string | null
}> {
  const res = await fetch(`${BASE}/api/connections/status`)
  return res.json()
}
