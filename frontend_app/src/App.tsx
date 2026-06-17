import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ConfigPage from './pages/ConfigPage'
import SchemasPage from './pages/SchemasPage'
import MigrationSelectPage from './pages/MigrationSelectPage'
import MigrationRunPage from './pages/MigrationRunPage'
import SchemaInspectorPage from './pages/SchemaInspectorPage'
import { useConfigStore } from './store/configStore'

function ProtectedRoute({ children, condition }: { children: React.ReactNode; condition: boolean }) {
  return condition ? <>{children}</> : <Navigate to="/" replace />
}

export default function App() {
  const { accConnected, ajoConnected } = useConfigStore()
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ConfigPage />} />
        <Route path="/schemas" element={
          <ProtectedRoute condition={accConnected}>
            <SchemasPage />
          </ProtectedRoute>
        } />
        <Route path="/migration" element={
          <ProtectedRoute condition={accConnected && ajoConnected}>
            <MigrationSelectPage />
          </ProtectedRoute>
        } />
        <Route path="/migration/run" element={
          <ProtectedRoute condition={accConnected}>
            <MigrationRunPage />
          </ProtectedRoute>
        } />
        <Route path="/inspect" element={
          <ProtectedRoute condition={accConnected}>
            <SchemaInspectorPage />
          </ProtectedRoute>
        } />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
