import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';

interface ChannelCounts {
  total: number;
  completed: number;
  failed: number;
}

interface FailureItem {
  source_id: string;
  internal_name: string | null;
  channel: string;
  error_step: string | null;
  error_message: string | null;
}

interface RunStatus {
  status: string;
  email: ChannelCounts;
  sms: ChannelCounts;
  failures: FailureItem[];
}

function ProgressBar({ label, counts }: { label: string; counts: ChannelCounts }) {
  const { total, completed, failed } = counts;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
  return (
    <div className="mb-5">
      <div className="flex justify-between text-sm mb-1">
        <span className="font-medium text-gray-700">{label}</span>
        <span className="text-gray-500">
          {completed} / {total} done
          {failed > 0 && <span className="text-red-500 ml-2">({failed} failed)</span>}
        </span>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-3 overflow-hidden">
        <div
          className="h-3 rounded-full bg-blue-500 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function TemplateRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showFailures, setShowFailures] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function fetchStatus() {
    try {
      const res = await fetch(`/api/templates/runs/${runId}/status`, { credentials: 'include' });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Error ${res.status}`);
      }
      const data: RunStatus = await res.json();
      setStatus(data);
      if (data.status !== 'RUNNING') {
        stopPolling();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      stopPolling();
    }
  }

  useEffect(() => {
    fetchStatus();
    pollRef.current = setInterval(fetchStatus, 2500);
    return stopPolling;
  }, [runId]);

  if (error) {
    return (
      <div className="max-w-2xl mx-auto p-8">
        <div className="text-red-600 bg-red-50 border border-red-200 rounded p-4">{error}</div>
      </div>
    );
  }

  if (!status) {
    return <div className="p-8 text-gray-500">Connecting to migration run…</div>;
  }

  const emailTotal = status.email.total;
  const smsTotal = status.sms.total;
  const overallTotal = emailTotal + smsTotal;
  const overallCompleted = status.email.completed + status.sms.completed;
  const overallFailed = status.email.failed + status.sms.failed;
  const overallCounts: ChannelCounts = { total: overallTotal, completed: overallCompleted, failed: overallFailed };

  const isDone = status.status === 'COMPLETED';

  return (
    <div className="max-w-2xl mx-auto p-8">
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-2xl font-bold">Template Migration</h1>
        <span className={`text-xs font-semibold px-2 py-1 rounded-full ${isDone ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700'}`}>
          {isDone ? 'Completed' : 'Running…'}
        </span>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6">
        {emailTotal > 0 && <ProgressBar label="Email templates" counts={status.email} />}
        {smsTotal > 0 && <ProgressBar label="SMS templates" counts={status.sms} />}
        <div className="border-t border-gray-100 pt-4 mt-2">
          <ProgressBar label="Overall" counts={overallCounts} />
        </div>
      </div>

      {isDone && (
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h2 className="font-semibold text-gray-800 mb-3">Summary</h2>
          <div className="grid grid-cols-3 gap-4 text-center mb-4">
            <div>
              <div className="text-2xl font-bold text-blue-600">{status.email.completed}</div>
              <div className="text-xs text-gray-500">Email migrated</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-blue-600">{status.sms.completed}</div>
              <div className="text-xs text-gray-500">SMS migrated</div>
            </div>
            <div>
              <div className={`text-2xl font-bold ${overallFailed > 0 ? 'text-red-500' : 'text-green-600'}`}>{overallFailed}</div>
              <div className="text-xs text-gray-500">Failed</div>
            </div>
          </div>

          {status.failures.length > 0 && (
            <div>
              <button
                onClick={() => setShowFailures(f => !f)}
                className="text-sm text-red-600 hover:underline font-medium"
              >
                {showFailures ? 'Hide' : 'Show'} failed templates ({status.failures.length})
              </button>
              {showFailures && (
                <table className="w-full text-xs mt-3 border border-gray-200 rounded-lg overflow-hidden">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="text-left px-3 py-2 font-medium text-gray-600">Internal name</th>
                      <th className="text-left px-3 py-2 font-medium text-gray-600">Channel</th>
                      <th className="text-left px-3 py-2 font-medium text-gray-600">Failed at</th>
                      <th className="text-left px-3 py-2 font-medium text-gray-600">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.failures.map((f, i) => (
                      <tr key={i} className="border-t border-gray-100">
                        <td className="px-3 py-2 font-mono">{f.internal_name ?? f.source_id}</td>
                        <td className="px-3 py-2">{f.channel}</td>
                        <td className="px-3 py-2">{f.error_step ?? '—'}</td>
                        <td className="px-3 py-2 text-red-600">{f.error_message ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
