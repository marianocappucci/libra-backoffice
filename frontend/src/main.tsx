import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ErrorBoundary } from 'libra-ui/ErrorBoundary'
import { instalarReporteDeErrores } from 'libra-ui/errores-del-navegador'

import './index.css'
import App from './App.tsx'
import { AuthProvider } from './auth.ts'

// Los errores del navegador que nadie atrapa van al registro de errores del backend
// (`POST /api/errores-cliente`, ADR-045 de libracore / ADR-053 de libra-ui). Antes de montar la app.
instalarReporteDeErrores()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
)
