const BASE = ''

export async function accConnect(payload: Record<string, string>) {
  const res = await fetch(`${BASE}/api/acc/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Connection failed')
  }
  return res.json()
}

export async function accDisconnect() {
  await fetch(`${BASE}/api/acc/disconnect`, { method: 'POST', credentials: 'include' })
}

export async function ajoConnect(orgId: string, clientId: string, clientSecret: string, sandboxName: string) {
  const res = await fetch(`${BASE}/api/ajo/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ org_id: orgId, client_id: clientId, client_secret: clientSecret, sandbox_name: sandboxName }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Connection failed')
  }
  return res.json()
}

export async function getSchemas(): Promise<{ schemas: Array<{ namespace: string; name: string; label: string }> }> {
  const res = await fetch(`${BASE}/api/acc/schemas`, { credentials: 'include' })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Failed to fetch schemas')
  }
  return res.json()
}

export async function getSchemaDetail(namespace: string, name: string): Promise<unknown> {
  const res = await fetch(`${BASE}/api/acc/schemas/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`, { credentials: 'include' })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || 'Failed to fetch schema detail')
  }
  return res.json()
}

export async function getAccStatus(): Promise<{ connected: boolean; login: string | null }> {
  const res = await fetch(`${BASE}/api/acc/status`, { credentials: 'include' })
  if (!res.ok) return { connected: false, login: null }
  return res.json()
}

export async function getAjoStatus(): Promise<{ connected: boolean; org_id: string | null; sandbox_name: string | null }> {
  const res = await fetch(`${BASE}/api/ajo/status`, { credentials: 'include' })
  if (!res.ok) return { connected: false, org_id: null, sandbox_name: null }
  return res.json()
}
