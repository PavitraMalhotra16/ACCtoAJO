export async function getTemplateCount(): Promise<{ total: number; stored: number; to_migrate: number }> {
  const res = await fetch('/api/templates/count', { credentials: 'include' })
  if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to get count') }
  return res.json()
}

export async function getStoredCount(): Promise<{ stored: number }> {
  const res = await fetch('/api/templates/stored-count', { credentials: 'include' })
  if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to get stored count') }
  return res.json()
}

export async function extractTemplates(): Promise<{ extracted: number; total_found: number; skipped: number; errors: { id: string; error: string }[] }> {
  const res = await fetch('/api/templates/extract', { method: 'POST', credentials: 'include' })
  if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Extraction failed') }
  return res.json()
}
