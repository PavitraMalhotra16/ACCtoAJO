import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ConfigPage from './pages/ConfigPage'
import MigrationRunPage from './pages/MigrationRunPage'
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
        <Route path="/migration/run" element={
          <ProtectedRoute condition={accConnected && ajoConnected}>
            <MigrationRunPage />
          </ProtectedRoute>
        } />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
