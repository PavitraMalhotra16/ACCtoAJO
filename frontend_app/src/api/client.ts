const BASE = ''

async function _safeError(res: Response, fallback: string): Promise<never> {
  if (res.status === 500 || res.status === 502 || res.status === 503 || res.status === 504) {
    throw new Error('Backend server is not running — please start it first')
  }
  try {
    const err = await res.json()
    throw new Error(err.detail || fallback)
  } catch {
    throw new Error(fallback)
  }
}

export async function accConnect(payload: Record<string, string>) {
  let res: Response
  try {
    res = await fetch(`${BASE}/api/acc/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
  } catch {
    throw new Error('Backend server is not running — please start it first')
  }
  if (!res.ok) await _safeError(res, 'Connection failed')
  return res.json()
}

export async function accDisconnect() {
  await fetch(`${BASE}/api/acc/disconnect`, { method: 'POST', credentials: 'include' })
}

export async function ajoConnect(orgId: string, clientId: string, clientSecret: string, sandboxName: string) {
  let res: Response
  try {
    res = await fetch(`${BASE}/api/ajo/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ org_id: orgId, client_id: clientId, client_secret: clientSecret, sandbox_name: sandboxName }),
    })
  } catch {
    throw new Error('Backend server is not running — please start it first')
  }
  if (!res.ok) await _safeError(res, 'Connection failed')
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
