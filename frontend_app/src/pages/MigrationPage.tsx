import { useNavigate } from 'react-router-dom'

export default function MigrationPage() {
  const navigate = useNavigate()
  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4">
      <div className="text-center max-w-lg flex flex-col gap-4">
        <div className="w-16 h-16 rounded-2xl bg-green-100 flex items-center justify-center mx-auto">
          <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-gray-900">Both Systems Connected</h1>
        <p className="text-gray-500">ACC and AJO are configured. Migration functionality coming soon.</p>
        <button onClick={() => navigate('/')} className="mx-auto px-6 py-2.5 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100 font-medium transition-colors">
          ← Back to Configuration
        </button>
      </div>
    </div>
  )
}
