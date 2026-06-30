import React, { Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ConfigPage from './pages/ConfigPage'
import MigrationTypePage from './pages/MigrationTypePage'
import MigrationSelectPage from './pages/MigrationSelectPage'
import MigrationRunPage from './pages/MigrationRunPage'
import TemplateMigrationPage from './pages/TemplateMigrationPage'
import DatasetIngestPage from './pages/DatasetIngestPage'
import { useConfigStore } from './store/configStore'

const TemplateAnalysisPage = React.lazy(() => import('./pages/TemplateAnalysisPage'))
const TemplateRunPage = React.lazy(() => import('./pages/TemplateRunPage'))

function ProtectedRoute({ children, condition }: { children: React.ReactNode; condition: boolean }) {
  return condition ? <>{children}</> : <Navigate to="/" replace />
}

export default function App() {
  const { accConnected, ajoConnected } = useConfigStore()
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ConfigPage />} />
        <Route path="/migration/type" element={
          <ProtectedRoute condition={accConnected && ajoConnected}>
            <MigrationTypePage />
          </ProtectedRoute>
        } />
        <Route path="/migration/select" element={
          <ProtectedRoute condition={accConnected && ajoConnected}>
            <MigrationSelectPage />
          </ProtectedRoute>
        } />
        <Route path="/migration/run" element={
          <ProtectedRoute condition={accConnected && ajoConnected}>
            <MigrationRunPage />
          </ProtectedRoute>
        } />
        <Route path="/migration/template" element={
          <ProtectedRoute condition={accConnected && ajoConnected}>
            <TemplateMigrationPage />
          </ProtectedRoute>
        } />
        <Route path="/migration/template/analysis" element={
          <ProtectedRoute condition={accConnected && ajoConnected}>
            <Suspense fallback={<div>Loading...</div>}>
              <TemplateAnalysisPage />
            </Suspense>
          </ProtectedRoute>
        } />
        <Route path="/migration/template/run/:runId" element={
          <ProtectedRoute condition={accConnected && ajoConnected}>
            <Suspense fallback={<div>Loading...</div>}>
              <TemplateRunPage />
            </Suspense>
          </ProtectedRoute>
        } />
        <Route path="/dataset/ingest" element={
          <ProtectedRoute condition={accConnected && ajoConnected}>
            <DatasetIngestPage />
          </ProtectedRoute>
        } />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
