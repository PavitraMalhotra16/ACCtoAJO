import { useNavigate } from 'react-router-dom'

export default function TemplateMigrationPage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg flex flex-col items-center gap-6 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-purple-50">
          <svg className="h-8 w-8 text-purple-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
          </svg>
        </div>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Template Migration</h1>
          <p className="mt-2 text-gray-500">This section is coming soon. Template extraction and migration will be available here.</p>
        </div>
        <button
          onClick={() => navigate('/migration/type')}
          className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
        >
          ← Back to migration type
        </button>
      </div>
    </div>
  )
}
