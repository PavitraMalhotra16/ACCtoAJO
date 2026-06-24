import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

interface PlaceholderRow {
  acc: string;
  field: string;
  ajo: string;
}

interface AnalysisData {
  recipient: PlaceholderRow[];
  targetData: PlaceholderRow[];
}

export default function TemplateAnalysisPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<AnalysisData | null>(null);
  const [mappings, setMappings] = useState<Record<string, string>>({});
  const [editingField, setEditingField] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetch('/api/templates/analysis', { credentials: 'include' })
      .then(r => r.json())
      .then((d: AnalysisData) => {
        setData(d);
        // Initialize mappings from defaults
        const initial: Record<string, string> = {};
        [...d.recipient, ...d.targetData].forEach(row => {
          initial[row.field] = row.ajo;
        });
        setMappings(initial);
      })
      .catch(err => setError(String(err)))
      .finally(() => setLoading(false));
  }, []);

  function startEdit(field: string) {
    setEditingField(field);
    setEditValue(mappings[field] ?? '');
  }

  function saveEdit(field: string) {
    setMappings(prev => ({ ...prev, [field]: editValue }));
    setEditingField(null);
  }

  async function handleConfirm() {
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch('/api/templates/migrate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ placeholder_map: mappings }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Error ${res.status}`);
      }
      const { run_id } = await res.json();
      navigate(`/migration/template/run/${run_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  }

  function renderTable(rows: PlaceholderRow[], title: string) {
    return (
      <div className="mb-8">
        <h2 className="text-lg font-semibold mb-3">{title}</h2>
        {rows.length === 0 ? (
          <p className="text-gray-400 text-sm italic">No placeholders found.</p>
        ) : (
          <table className="w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600 w-2/5">ACC Placeholder</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">AJO Mapping</th>
                <th className="px-4 py-2 w-12" />
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.field} className="border-t border-gray-100">
                  <td className="px-4 py-2 font-mono text-xs text-gray-700">{row.acc}</td>
                  <td className="px-4 py-2">
                    {editingField === row.field ? (
                      <div className="flex gap-2">
                        <input
                          autoFocus
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') saveEdit(row.field); if (e.key === 'Escape') setEditingField(null); }}
                          className="flex-1 border border-blue-400 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                        <button onClick={() => saveEdit(row.field)} className="text-xs text-blue-600 font-medium hover:underline">Save</button>
                        <button onClick={() => setEditingField(null)} className="text-xs text-gray-400 hover:underline">Cancel</button>
                      </div>
                    ) : (
                      <span className="font-mono text-xs text-gray-800">{`{{${mappings[row.field] ?? row.ajo}}}`}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <button
                      onClick={() => startEdit(row.field)}
                      className="text-gray-400 hover:text-blue-600 transition-colors"
                      title="Edit mapping"
                    >
                      ✏️
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  if (loading) return <div className="p-8 text-gray-500">Loading placeholder analysis…</div>;

  return (
    <div className="max-w-3xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-1">Review Placeholder Mappings</h1>
      <p className="text-gray-500 text-sm mb-6">
        These are all unique ACC placeholders found in your templates. Edit any AJO mapping before starting migration.
      </p>

      {error && (
        <div className="text-red-600 text-sm bg-red-50 border border-red-200 rounded p-3 mb-6">{error}</div>
      )}

      {data && (
        <>
          {renderTable(data.recipient, 'recipient.* placeholders')}
          {renderTable(data.targetData, 'targetData.* placeholders')}
        </>
      )}

      <button
        onClick={handleConfirm}
        disabled={submitting || !data}
        className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 px-6 rounded-md text-sm transition-colors"
      >
        {submitting ? 'Starting migration…' : 'Confirm & Start Migration'}
      </button>
    </div>
  );
}
