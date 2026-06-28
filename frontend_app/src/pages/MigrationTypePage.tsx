import { useNavigate } from 'react-router-dom'

export default function MigrationTypePage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-2xl flex flex-col gap-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900">What would you like to migrate?</h1>
          <p className="mt-2 text-gray-500">Choose the type of migration to proceed</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Schema card */}
          <button
            onClick={() => navigate('/migration/select')}
            className="group flex flex-col items-start gap-4 rounded-xl border-2 border-gray-200 hover:border-blue-500 bg-white p-6 text-left transition-all hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-blue-50 group-hover:bg-blue-100 transition-colors">
              <svg className="h-6 w-6 text-blue-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 9.776c.112-.017.227-.026.344-.026h15.812c.117 0 .232.009.344.026m-16.5 0a2.25 2.25 0 0 0-1.883 2.542l.857 6a2.25 2.25 0 0 0 2.227 1.932H19.05a2.25 2.25 0 0 0 2.227-1.932l.857-6a2.25 2.25 0 0 0-1.883-2.542m-16.5 0V6A2.25 2.25 0 0 1 6 3.75h3.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 0 1.06.44H18A2.25 2.25 0 0 1 20.25 9v.776" />
              </svg>
            </div>
            <div>
              <p className="text-lg font-semibold text-gray-900 group-hover:text-blue-700 transition-colors">Schema</p>
              <p className="mt-1 text-sm text-gray-500">Migrate relational schemas from ACC into AEP / AJO</p>
            </div>
            <span className="mt-auto inline-flex items-center gap-1 text-sm font-medium text-blue-600 group-hover:gap-2 transition-all">
              Continue
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
              </svg>
            </span>
          </button>

          {/* Workflow card */}
          <button
            onClick={() => navigate('/migration/workflow')}
            className="group flex flex-col items-start gap-4 rounded-xl border-2 border-gray-200 hover:border-violet-500 bg-white p-6 text-left transition-all hover:shadow-md focus:outline-none focus:ring-2 focus:ring-violet-500"
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-violet-50 group-hover:bg-violet-100 transition-colors">
              <svg className="h-6 w-6 text-violet-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7 16V4m0 0L3 8m4-4l4 4M17 8v12m0 0l4-4m-4 4l-4-4" />
              </svg>
            </div>
            <div>
              <p className="text-lg font-semibold text-gray-900 group-hover:text-violet-700 transition-colors">Workflow</p>
              <p className="mt-1 text-sm text-gray-500">Extract and review ACC workflows — activities, transitions, and config</p>
            </div>
            <span className="mt-auto inline-flex items-center gap-1 text-sm font-medium text-violet-600 group-hover:gap-2 transition-all">
              Continue
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
              </svg>
            </span>
          </button>

          {/* Template card */}
          <button
            onClick={() => navigate('/migration/template')}
            className="group flex flex-col items-start gap-4 rounded-xl border-2 border-gray-200 hover:border-purple-500 bg-white p-6 text-left transition-all hover:shadow-md focus:outline-none focus:ring-2 focus:ring-purple-500"
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-purple-50 group-hover:bg-purple-100 transition-colors">
              <svg className="h-6 w-6 text-purple-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
              </svg>
            </div>
            <div>
              <p className="text-lg font-semibold text-gray-900 group-hover:text-purple-700 transition-colors">Template</p>
              <p className="mt-1 text-sm text-gray-500">Migrate delivery templates and campaign assets from ACC</p>
            </div>
            <span className="mt-auto inline-flex items-center gap-1 text-sm font-medium text-purple-600 group-hover:gap-2 transition-all">
              Continue
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
              </svg>
            </span>
          </button>
        </div>

        <div className="flex justify-center">
          <button
            onClick={() => navigate('/')}
            className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            ← Back
          </button>
        </div>
      </div>
    </div>
  )
}
