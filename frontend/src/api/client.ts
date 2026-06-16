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

export async function accDisconnect() {
  await fetch(`${BASE}/api/acc/disconnect`, { method: 'POST' })
}

export async function ajoConnect(orgId: string, clientId: string, clientSecret: string, sandboxName: string, referenceToken?: string) {
  const res = await fetch(`${BASE}/api/ajo/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ org_id: orgId, client_id: clientId, client_secret: clientSecret, sandbox_name: sandboxName, reference_token: referenceToken || null }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Connection failed')
  }
  return res.json()
}

export async function getSchemas(): Promise<{ schemas: Array<{ namespace: string; name: string; label: string }> }> {
  const res = await fetch(`${BASE}/api/acc/schemas`)
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Failed to fetch schemas')
  }
  return res.json()
}

export async function getSchemaDetail(namespace: string, name: string): Promise<unknown> {
  const res = await fetch(`${BASE}/api/acc/schemas/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`)
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Failed to fetch schema detail')
  }
  return res.json()
}

export async function getAccStatus(): Promise<{ connected: boolean; login: string | null }> {
  const res = await fetch(`${BASE}/api/acc/status`)
  return res.json()
}

export async function getAjoStatus(): Promise<{ connected: boolean; org_id: string | null; sandbox_name: string | null }> {
  const res = await fetch(`${BASE}/api/ajo/status`)
  return res.json()
}
